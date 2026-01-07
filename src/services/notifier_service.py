"""
알림 서비스 모듈

책임:
- 여러 알림 채널 통합 관리 (Discord + 카카오톡)
- 스크리닝 결과 알림
- 학습 결과 리포트
- 에러 알림
- 알림 실패 시 로그만 남기고 계속 진행 (fail-safe)

설계 원칙:
- 알림 실패가 스크리닝 프로세스를 중단시키지 않음
- 모든 채널에 병렬 발송 시도
- 개별 채널 실패는 다른 채널에 영향 없음
"""

import logging
import traceback
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

from src.adapters.discord_notifier import get_discord_notifier, DiscordNotifier
from src.adapters.kakao_notifier import get_kakao_notifier, KakaoNotifier
from src.domain.models import ScreeningResult, NotifyResult, NotifyChannel
from src.config.settings import settings

logger = logging.getLogger(__name__)


class NotificationChannel(Enum):
    """알림 채널"""
    DISCORD = "discord"
    KAKAO = "kakao"
    TELEGRAM = "telegram"  # 추후 구현


@dataclass
class NotificationConfig:
    """알림 설정"""
    enabled: bool = True
    discord_enabled: bool = True
    kakao_enabled: bool = True
    fail_silently: bool = True  # True면 알림 실패 시 예외를 던지지 않음
    
    def __post_init__(self):
        # 카카오 토큰이 없으면 비활성화
        if not settings.kakao.access_token:
            self.kakao_enabled = False


class NotifierService:
    """통합 알림 서비스
    
    모든 알림 발송은 fail-safe:
    - 개별 채널 실패는 로그만 남김
    - 스크리닝 프로세스는 계속 진행
    """
    
    def __init__(self, config: Optional[NotificationConfig] = None):
        self.config = config or NotificationConfig()
        
        # Discord 초기화 (실패해도 계속 진행)
        self.discord: Optional[DiscordNotifier] = None
        if self.config.discord_enabled:
            try:
                self.discord = get_discord_notifier()
                if not self.discord.webhook_url:
                    logger.warning("Discord 웹훅 URL이 설정되지 않음 - Discord 알림 비활성화")
                    self.discord = None
            except Exception as e:
                logger.warning(f"Discord 알림 초기화 실패: {e}")
                self.discord = None
        
        # 카카오톡 초기화 (실패해도 계속 진행)
        self.kakao: Optional[KakaoNotifier] = None
        if self.config.kakao_enabled:
            try:
                self.kakao = get_kakao_notifier()
                if not self.kakao.enabled:
                    logger.info("카카오톡 알림 비활성화 (토큰 없음)")
                    self.kakao = None
            except Exception as e:
                logger.warning(f"카카오톡 알림 초기화 실패: {e}")
                self.kakao = None
    
    def get_available_channels(self) -> List[NotificationChannel]:
        """활성화된 알림 채널 목록"""
        available = []
        
        if self.discord and self.discord.webhook_url:
            available.append(NotificationChannel.DISCORD)
        
        if self.kakao and self.kakao.enabled:
            available.append(NotificationChannel.KAKAO)
        
        return available
    
    def _safe_send(
        self,
        channel_name: str,
        send_func,
        *args,
        **kwargs
    ) -> Optional[NotifyResult]:
        """안전한 알림 발송 (예외를 잡아서 로그만 남김)
        
        Args:
            channel_name: 채널명 (로깅용)
            send_func: 발송 함수
            *args, **kwargs: 발송 함수 인자
            
        Returns:
            발송 결과 또는 None (실패 시)
        """
        try:
            result = send_func(*args, **kwargs)
            
            if result and result.success:
                logger.info(f"[{channel_name}] 알림 발송 성공")
            elif result:
                logger.warning(
                    f"[{channel_name}] 알림 발송 실패 "
                    f"(코드: {result.response_code}, 메시지: {result.error_message})"
                )
            
            return result
            
        except Exception as e:
            # 알림 실패는 로그만 남기고 계속 진행
            logger.error(
                f"[{channel_name}] 알림 발송 중 예외 발생: {e}\n"
                f"Traceback: {traceback.format_exc()}"
            )
            
            if not self.config.fail_silently:
                raise
            
            return NotifyResult(
                channel=NotifyChannel.DISCORD if channel_name == "Discord" else NotifyChannel.KAKAO,
                success=False,
                response_code=0,
                error_message=f"예외: {str(e)}",
            )
    
    def send_screening_result(
        self,
        result: ScreeningResult,
        is_preview: bool = False,
    ) -> Dict[str, NotifyResult]:
        """스크리닝 결과 알림 발송 (모든 활성 채널에 발송)
        
        Args:
            result: 스크리닝 결과
            is_preview: 프리뷰 여부
            
        Returns:
            채널별 발송 결과
        """
        if not self.config.enabled:
            logger.info("알림이 비활성화되어 있습니다")
            return {}
        
        results = {}
        
        # Discord 발송
        if self.discord:
            discord_result = self._safe_send(
                "Discord",
                self.discord.send_screening_result,
                result,
                is_preview,
            )
            if discord_result:
                results["discord"] = discord_result
        
        # 카카오톡 발송
        if self.kakao:
            kakao_result = self._safe_send(
                "KakaoTalk",
                self.kakao.send_screening_result,
                result,
                is_preview,
            )
            if kakao_result:
                results["kakao"] = kakao_result
        
        # 발송 결과 요약 로그
        success_count = sum(1 for r in results.values() if r.success)
        total_count = len(results)
        logger.info(f"알림 발송 완료: {success_count}/{total_count} 채널 성공")
        
        return results
    
    def send_learning_report(
        self,
        report,  # LearningReport 타입
    ) -> Dict[str, NotifyResult]:
        """학습 결과 리포트 발송
        
        Args:
            report: 학습 리포트
            
        Returns:
            채널별 발송 결과
        """
        if not self.config.enabled:
            return {}
        
        results = {}
        
        # Embed 메시지 구성
        embed = self._build_learning_embed(report)
        
        # Discord 발송
        if self.discord:
            def send_embed():
                payload = {"embeds": [embed]}
                return self.discord._send(payload)
            
            discord_result = self._safe_send("Discord", send_embed)
            if discord_result:
                results["discord"] = discord_result
        
        # 카카오톡 발송 (텍스트 변환)
        if self.kakao:
            text = self._build_learning_text(report)
            kakao_result = self._safe_send(
                "KakaoTalk",
                self.kakao.send_to_me,
                text,
            )
            if kakao_result:
                results["kakao"] = kakao_result
        
        return results
    
    def _build_learning_embed(self, report) -> Dict[str, Any]:
        """학습 리포트 Discord Embed 메시지 구성"""
        from datetime import datetime
        
        fields = [
            {
                "name": "📊 성과 분석 (30일)",
                "value": (
                    f"샘플: {report.sample_count}개\n"
                    f"승률: {report.performance.win_rate:.1f}%\n"
                    f"평균 갭: {report.performance.avg_gap_rate:+.2f}%"
                ),
                "inline": True,
            },
            {
                "name": "🏆 TOP1 성과",
                "value": (
                    f"승률: {report.performance.top1_win_rate:.1f}%\n"
                    f"평균 갭: {report.performance.top1_avg_gap_rate:+.2f}%"
                ),
                "inline": True,
            },
        ]
        
        # 상관관계 필드
        if report.correlations:
            corr_text = "\n".join([
                f"• {name}: {corr:+.4f}"
                for name, corr in sorted(
                    report.correlations.items(),
                    key=lambda x: abs(x[1]),
                    reverse=True
                )
            ])
            fields.append({
                "name": "📈 지표 상관관계",
                "value": corr_text,
                "inline": False,
            })
        
        # 가중치 변경 필드
        if report.weight_changed and report.optimization_result:
            changes = report.optimization_result.changes
            change_text = "\n".join([
                f"• {name}: {report.optimization_result.old_weights[name]:.2f} → "
                f"{report.optimization_result.new_weights[name]:.2f} ({change:+.3f})"
                for name, change in changes.items()
                if abs(change) > 0.001
            ])
            if change_text:
                fields.append({
                    "name": "⚖️ 가중치 변경",
                    "value": change_text,
                    "inline": False,
                })
        else:
            fields.append({
                "name": "⚖️ 가중치",
                "value": "변경 없음",
                "inline": False,
            })
        
        # 색상 결정
        if report.performance.win_rate >= 60:
            color = 3066993  # 녹색
        elif report.performance.win_rate >= 40:
            color = 16776960  # 노란색
        else:
            color = 15158332  # 빨간색
        
        return {
            "title": f"📚 일일 학습 리포트 ({report.learning_date})",
            "color": color,
            "fields": fields,
            "footer": {"text": "종가매매 스크리너 Learner v1.0"},
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
    
    def _build_learning_text(self, report) -> str:
        """학습 리포트 카카오톡 텍스트 구성"""
        lines = [
            f"📚 일일 학습 리포트 ({report.learning_date})",
            "",
            f"📊 성과 분석 (30일)",
            f"  샘플: {report.sample_count}개",
            f"  승률: {report.performance.win_rate:.1f}%",
            f"  평균 갭: {report.performance.avg_gap_rate:+.2f}%",
            "",
            f"🏆 TOP1 성과",
            f"  승률: {report.performance.top1_win_rate:.1f}%",
            f"  평균 갭: {report.performance.top1_avg_gap_rate:+.2f}%",
        ]
        
        if report.weight_changed:
            lines.append("")
            lines.append("⚖️ 가중치 변경됨")
        
        return "\n".join(lines)
    
    def send_error_alert(
        self,
        error: Exception,
        context: str = "",
    ) -> Dict[str, NotifyResult]:
        """에러 알림 발송
        
        Args:
            error: 에러 객체
            context: 에러 발생 컨텍스트
            
        Returns:
            채널별 발송 결과
        """
        if not self.config.enabled:
            return {}
        
        results = {}
        
        # Discord 발송
        if self.discord:
            discord_result = self._safe_send(
                "Discord",
                self.discord.send_error_alert,
                error,
                context,
            )
            if discord_result:
                results["discord"] = discord_result
        
        # 카카오톡 발송
        if self.kakao:
            kakao_result = self._safe_send(
                "KakaoTalk",
                self.kakao.send_error_alert,
                error,
                context,
            )
            if kakao_result:
                results["kakao"] = kakao_result
        
        return results
    
    def send_simple_message(
        self,
        message: str,
    ) -> Dict[str, NotifyResult]:
        """간단한 텍스트 메시지 발송"""
        if not self.config.enabled:
            return {}
        
        results = {}
        
        # Discord 발송
        if self.discord:
            discord_result = self._safe_send(
                "Discord",
                self.discord.send_simple_message,
                message,
            )
            if discord_result:
                results["discord"] = discord_result
        
        # 카카오톡 발송
        if self.kakao:
            kakao_result = self._safe_send(
                "KakaoTalk",
                self.kakao.send_to_me,
                message,
            )
            if kakao_result:
                results["kakao"] = kakao_result
        
        return results


# 싱글톤 인스턴스
_notifier_service: Optional[NotifierService] = None


def get_notifier_service() -> NotifierService:
    """알림 서비스 인스턴스 반환"""
    global _notifier_service
    if _notifier_service is None:
        _notifier_service = NotifierService()
    return _notifier_service


def reset_notifier_service():
    """알림 서비스 인스턴스 리셋 (테스트용)"""
    global _notifier_service
    _notifier_service = None


if __name__ == "__main__":
    # 테스트
    logging.basicConfig(level=logging.INFO)
    
    service = get_notifier_service()
    
    print("\n=== 알림 채널 확인 ===")
    channels = service.get_available_channels()
    print(f"활성 채널: {[c.value for c in channels]}")
    
    # 간단한 메시지 테스트
    if channels:
        print("\n=== 테스트 메시지 발송 ===")
        results = service.send_simple_message("🧪 NotifierService 테스트 메시지")
        for channel, result in results.items():
            status = "성공" if result.success else f"실패: {result.error_message}"
            print(f"  {channel}: {status}")
    else:
        print("\n⚠️ 활성화된 알림 채널이 없습니다.")
        print("   - Discord: DISCORD_WEBHOOK_URL 설정 확인")
        print("   - 카카오톡: KAKAO_ACCESS_TOKEN 설정 확인")
