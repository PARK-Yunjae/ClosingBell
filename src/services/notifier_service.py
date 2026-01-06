"""
알림 서비스 모듈

책임:
- 여러 알림 채널 통합 관리
- 스크리닝 결과 알림
- 학습 결과 리포트
- 에러 알림
"""

import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

from src.adapters.discord_notifier import get_discord_notifier, NotificationResult
from src.domain.models import ScreeningResult
from src.services.learner_service import LearningReport

logger = logging.getLogger(__name__)


class NotificationChannel(Enum):
    """알림 채널"""
    DISCORD = "discord"
    KAKAO = "kakao"
    TELEGRAM = "telegram"


@dataclass
class NotificationConfig:
    """알림 설정"""
    enabled: bool = True
    channels: List[NotificationChannel] = None
    
    def __post_init__(self):
        if self.channels is None:
            self.channels = [NotificationChannel.DISCORD]


class NotifierService:
    """통합 알림 서비스"""
    
    def __init__(self, config: Optional[NotificationConfig] = None):
        self.config = config or NotificationConfig()
        self.discord = get_discord_notifier()
        # 추후 다른 알림 채널 추가
        # self.kakao = get_kakao_notifier()
        # self.telegram = get_telegram_notifier()
    
    def get_available_channels(self) -> List[NotificationChannel]:
        """활성화된 알림 채널 목록"""
        available = []
        
        # Discord 활성화 확인
        if self.discord and self.discord.webhook_url:
            available.append(NotificationChannel.DISCORD)
        
        # 추후 다른 채널 추가
        # if self.kakao and self.kakao.is_configured():
        #     available.append(NotificationChannel.KAKAO)
        
        return available
    
    def send_screening_result(
        self,
        result: ScreeningResult,
        is_preview: bool = False,
        channels: Optional[List[NotificationChannel]] = None,
    ) -> Dict[str, NotificationResult]:
        """스크리닝 결과 알림 발송
        
        Args:
            result: 스크리닝 결과
            is_preview: 프리뷰 여부
            channels: 발송할 채널 (None이면 기본 채널)
            
        Returns:
            채널별 발송 결과
        """
        if not self.config.enabled:
            logger.info("알림이 비활성화되어 있습니다")
            return {}
        
        channels = channels or self.config.channels
        results = {}
        
        for channel in channels:
            try:
                if channel == NotificationChannel.DISCORD:
                    result_obj = self.discord.send_screening_result(result, is_preview)
                    results[channel.value] = result_obj
                    
                    if result_obj.success:
                        logger.info(f"[{channel.value}] 스크리닝 결과 발송 성공")
                    else:
                        logger.warning(f"[{channel.value}] 발송 실패: {result_obj.error_message}")
                
                # 추후 다른 채널 추가
                # elif channel == NotificationChannel.KAKAO:
                #     results[channel.value] = self.kakao.send_screening_result(result)
                
            except Exception as e:
                logger.error(f"[{channel.value}] 알림 발송 오류: {e}")
                results[channel.value] = NotificationResult(
                    success=False,
                    response_code=0,
                    error_message=str(e),
                )
        
        return results
    
    def send_learning_report(
        self,
        report: LearningReport,
        channels: Optional[List[NotificationChannel]] = None,
    ) -> Dict[str, NotificationResult]:
        """학습 결과 리포트 발송
        
        Args:
            report: 학습 리포트
            channels: 발송할 채널
            
        Returns:
            채널별 발송 결과
        """
        if not self.config.enabled:
            return {}
        
        channels = channels or self.config.channels
        results = {}
        
        # Embed 메시지 구성
        embed = self._build_learning_embed(report)
        
        for channel in channels:
            try:
                if channel == NotificationChannel.DISCORD:
                    result_obj = self.discord.send_embed(embed)
                    results[channel.value] = result_obj
                    
                    if result_obj.success:
                        logger.info(f"[{channel.value}] 학습 리포트 발송 성공")
                    else:
                        logger.warning(f"[{channel.value}] 발송 실패: {result_obj.error_message}")
                        
            except Exception as e:
                logger.error(f"[{channel.value}] 학습 리포트 발송 오류: {e}")
                results[channel.value] = NotificationResult(
                    success=False,
                    response_code=0,
                    error_message=str(e),
                )
        
        return results
    
    def _build_learning_embed(self, report: LearningReport) -> Dict[str, Any]:
        """학습 리포트 Embed 메시지 구성"""
        # 성과 필드
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
        
        # 색상 결정 (성과에 따라)
        if report.performance.win_rate >= 60:
            color = 3066993  # 녹색
        elif report.performance.win_rate >= 40:
            color = 16776960  # 노란색
        else:
            color = 15158332  # 빨간색
        
        embed = {
            "title": f"📚 일일 학습 리포트 ({report.learning_date})",
            "color": color,
            "fields": fields,
            "footer": {"text": "종가매매 스크리너 Learner v1.0"},
        }
        
        return embed
    
    def send_error_alert(
        self,
        error: Exception,
        context: str = "",
        channels: Optional[List[NotificationChannel]] = None,
    ) -> Dict[str, NotificationResult]:
        """에러 알림 발송
        
        Args:
            error: 에러 객체
            context: 에러 발생 컨텍스트
            channels: 발송할 채널
            
        Returns:
            채널별 발송 결과
        """
        if not self.config.enabled:
            return {}
        
        channels = channels or self.config.channels
        results = {}
        
        embed = {
            "title": "🚨 에러 발생",
            "color": 15158332,  # 빨간색
            "fields": [
                {"name": "컨텍스트", "value": context or "알 수 없음", "inline": False},
                {"name": "에러 타입", "value": type(error).__name__, "inline": True},
                {"name": "에러 메시지", "value": str(error)[:500], "inline": False},
            ],
            "footer": {"text": "종가매매 스크리너 Error Alert"},
        }
        
        for channel in channels:
            try:
                if channel == NotificationChannel.DISCORD:
                    result_obj = self.discord.send_embed(embed)
                    results[channel.value] = result_obj
                    
            except Exception as e:
                logger.error(f"[{channel.value}] 에러 알림 발송 실패: {e}")
                results[channel.value] = NotificationResult(
                    success=False,
                    response_code=0,
                    error_message=str(e),
                )
        
        return results
    
    def send_simple_message(
        self,
        message: str,
        channels: Optional[List[NotificationChannel]] = None,
    ) -> Dict[str, NotificationResult]:
        """간단한 텍스트 메시지 발송"""
        if not self.config.enabled:
            return {}
        
        channels = channels or self.config.channels
        results = {}
        
        for channel in channels:
            try:
                if channel == NotificationChannel.DISCORD:
                    result_obj = self.discord.send_message(message)
                    results[channel.value] = result_obj
                    
            except Exception as e:
                logger.error(f"[{channel.value}] 메시지 발송 실패: {e}")
        
        return results


# 싱글톤 인스턴스
_notifier_service: Optional[NotifierService] = None


def get_notifier_service() -> NotifierService:
    """알림 서비스 인스턴스 반환"""
    global _notifier_service
    if _notifier_service is None:
        _notifier_service = NotifierService()
    return _notifier_service


if __name__ == "__main__":
    # 테스트
    logging.basicConfig(level=logging.INFO)
    
    service = get_notifier_service()
    
    print("\n=== 알림 채널 확인 ===")
    channels = service.get_available_channels()
    print(f"활성 채널: {[c.value for c in channels]}")
    
    # 간단한 메시지 테스트
    print("\n=== 테스트 메시지 발송 ===")
    results = service.send_simple_message("🧪 NotifierService 테스트 메시지")
    for channel, result in results.items():
        print(f"  {channel}: {'성공' if result.success else '실패'}")
