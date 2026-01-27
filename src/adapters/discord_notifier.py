"""
디스코드 웹훅 알림

책임:
- 웹훅 메시지 포맷팅
- Embed 생성
- 발송 및 재시도
- Rate Limit 핸들링
- Dry-run 모드 지원 (DISCORD_DRY_RUN=true)

의존성:
- requests
- config.settings
"""

import os
import time
import logging
from datetime import datetime
from typing import Optional
import requests

from src.config.settings import settings
from src.config.constants import (
    DISCORD_COLOR_SUCCESS,
    DISCORD_COLOR_WARNING,
    DISCORD_COLOR_ERROR,
    MSG_NO_CANDIDATES,
    MSG_PREVIEW_LABEL,
    MSG_MAIN_LABEL,
)
from src.domain.models import (
    StockScore,
    ScreeningResult,
    NotifyResult,
    NotifyChannel,
)

logger = logging.getLogger(__name__)

# Dry-run 모드 (환경변수로 제어)
DISCORD_DRY_RUN = os.getenv('DISCORD_DRY_RUN', 'false').lower() == 'true'


class DiscordNotifier:
    """디스코드 웹훅 알림 전송"""
    
    def __init__(self, webhook_url: Optional[str] = None, dry_run: bool = None):
        self.webhook_url = webhook_url or settings.discord.webhook_url
        self.max_retries = 2
        self.retry_delay = 2.0
        # dry_run 파라미터가 None이면 환경변수 사용
        self.dry_run = dry_run if dry_run is not None else DISCORD_DRY_RUN
    
    def _format_price(self, price: int) -> str:
        """가격 포맷팅"""
        return f"{price:,}원"
    
    def _format_change_rate(self, rate: float) -> str:
        """등락률 포맷팅"""
        sign = "+" if rate >= 0 else ""
        return f"{sign}{rate:.2f}%"
    
    def _format_score(self, score: float) -> str:
        """점수 포맷팅"""
        return f"{score:.1f}점"
    
    def _get_rank_emoji(self, rank: int) -> str:
        """순위 이모지"""
        emojis = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4️⃣", 5: "5️⃣"}
        return emojis.get(rank, f"{rank}위")
    
    def _build_stock_field(self, stock: StockScore, is_recommended: bool = False) -> dict:
        """종목 필드 생성
        
        Args:
            stock: 종목 점수 정보
            is_recommended: CCI 기준 추천 종목 여부 (⭐ 표시)
        """
        emoji = self._get_rank_emoji(stock.rank)
        recommend_mark = " ⭐추천" if is_recommended else ""
        
        name = f"{emoji} {stock.rank}위: {stock.stock_name} ({stock.stock_code}){recommend_mark}"
        
        value_lines = [
            f"💰 현재가: {self._format_price(stock.current_price)} ({self._format_change_rate(stock.change_rate)})",
            f"📊 총점: **{self._format_score(stock.score_total)}**",
            f"├ CCI값: {stock.score_cci_value:.1f} | CCI기울기: {stock.score_cci_slope:.1f}",
            f"├ MA20기울기: {stock.score_ma20_slope:.1f} | 양봉품질: {stock.score_candle:.1f}",
            f"└ 상승률: {stock.score_change:.1f}",
            f"📈 CCI: {stock.raw_cci:.1f} | 거래대금: {stock.trading_value:.0f}억",
        ]
        
        return {
            "name": name,
            "value": "\n".join(value_lines),
            "inline": False,
        }
    
    def _build_embed(
        self,
        result: ScreeningResult,
        is_preview: bool = False,
    ) -> dict:
        """Embed 메시지 빌드 (v4.0: TOP5 + CCI 추천 + 점수별 매도전략)"""
        # 타이틀
        label = MSG_PREVIEW_LABEL if is_preview else MSG_MAIN_LABEL
        title = f"🎯 종가매매 TOP 5 {label} ({result.screen_time})"
        
        # 설명
        description = f"📅 {result.screen_date.strftime('%Y-%m-%d')} 스크리닝 결과"
        if result.total_count > 0:
            description += f"\n📊 분석 종목: {result.total_count}개"
        description += "\n💡 ⭐추천: CCI가 가장 낮은 종목 (백테스트 최적)"
        
        # 색상
        if not result.top3:
            color = DISCORD_COLOR_WARNING
        else:
            color = DISCORD_COLOR_SUCCESS
        
        # 필드 - CCI 가장 낮은 종목 찾기
        fields = []
        if result.top3:
            # CCI 가장 낮은 종목 찾기
            min_cci_stock = min(result.top3, key=lambda s: s.raw_cci)
            
            for stock in result.top3:
                is_recommended = (stock.stock_code == min_cci_stock.stock_code)
                fields.append(self._build_stock_field(stock, is_recommended))
        else:
            fields.append({
                "name": "❌ 결과",
                "value": MSG_NO_CANDIDATES,
                "inline": False,
            })
        
        # 매도 전략 안내 (v4.0)
        fields.append({
            "name": "📌 매도 전략 (그리드 서치 최적)",
            "value": "• 80점+: 시초가 매도 (+1%~+3%)\n• 70점+: 목표가 +2%~+3% / 손절 -2%\n• 60점+: 익절 +1%~+2% / 손절 -1.5%\n• 60점-: 손절 -1% 우선",
            "inline": False,
        })
        
        # 실행 시간 필드
        if result.execution_time_sec:
            fields.append({
                "name": "⏱️ 실행 시간",
                "value": f"{result.execution_time_sec:.1f}초",
                "inline": True,
            })
        
        return {
            "title": title,
            "description": description,
            "color": color,
            "fields": fields,
            "footer": {
                "text": "종가매매 스크리너 v4.0 (그리드 서치 최적화)",
            },
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
    
    def send_screening_result(
        self,
        result: ScreeningResult,
        is_preview: bool = False,
    ) -> NotifyResult:
        """스크리닝 결과 발송
        
        Args:
            result: 스크리닝 결과
            is_preview: 12:30 프리뷰 여부
            
        Returns:
            발송 결과
        """
        embed = self._build_embed(result, is_preview)
        payload = {
            "embeds": [embed],
        }
        
        return self._send(payload)
    
    def send_error_alert(
        self,
        error: Exception,
        context: str = "",
    ) -> NotifyResult:
        """에러 알림 발송"""
        embed = {
            "title": "⚠️ 스크리너 에러 발생",
            "description": context or "스크리닝 중 에러가 발생했습니다.",
            "color": DISCORD_COLOR_ERROR,
            "fields": [
                {
                    "name": "에러 메시지",
                    "value": f"```{str(error)[:500]}```",
                    "inline": False,
                }
            ],
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        
        payload = {"embeds": [embed]}
        return self._send(payload)
    
    def send_simple_message(self, content: str) -> NotifyResult:
        """단순 텍스트 메시지 발송"""
        payload = {"content": content}
        return self._send(payload)
    
    def send_message(self, content: str) -> NotifyResult:
        """텍스트 메시지 발송 (v5 호환용 별칭)"""
        return self.send_simple_message(content)
    
    def send_embed(self, embed: dict) -> bool:
        """Embed 메시지 발송 (v5용)
        
        Args:
            embed: Discord Embed 딕셔너리
            
        Returns:
            발송 성공 여부
        """
        payload = {"embeds": [embed]}
        result = self._send(payload)
        return result.success
    
    def send_top5(
        self, 
        stocks: list, 
        ai_results: dict = None,
        title: str = "종가매매 TOP5",
        run_type: str = "main",
        leading_sectors_text: str = None,
    ) -> bool:
        """★ P0-C: TOP5 전용 웹훅 발송 (DiscordEmbedBuilder 사용)
        
        Args:
            stocks: StockScoreV5 또는 EnrichedStock 리스트
            ai_results: AI 분석 결과 {stock_code: {...}}
            title: Embed 제목
            run_type: main/preview
            leading_sectors_text: 주도섹터 텍스트
            
        Returns:
            발송 성공 여부
        """
        try:
            from src.services.discord_embed_builder import DiscordEmbedBuilder
            
            builder = DiscordEmbedBuilder()
            embed = builder.build_top5_embed(
                stocks=stocks,
                title=title,
                ai_results=ai_results,
                run_type=run_type,
                leading_sectors_text=leading_sectors_text,
            )
            
            return self.send_embed(embed)
        except ImportError:
            logger.warning("DiscordEmbedBuilder 로드 실패, 기본 메시지로 대체")
            # Fallback: 간단한 텍스트 메시지
            stock_names = [getattr(s, 'stock_name', '?') for s in stocks[:5]]
            self.send_message(f"TOP5: {', '.join(stock_names)}")
            return True
        except Exception as e:
            logger.error(f"TOP5 웹훅 발송 실패: {e}")
            return False
    
    def send_learning_report(self, report) -> NotifyResult:
        """학습 리포트 발송"""
        # report object expected to have learning_date and message
        title = f"📚 학습 리포트 ({report.learning_date})"
        description = report.message
        
        # Split message if too long (Discord limit 4096)
        if len(description) > 4000:
            description = description[:4000] + "..."
            
        embed = {
            "title": title,
            "description": description,
            "color": DISCORD_COLOR_SUCCESS,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        
        payload = {"embeds": [embed]}
        return self._send(payload)

    def _send(
        self,
        payload: dict,
        retry_count: int = 0,
    ) -> NotifyResult:
        """웹훅 발송"""
        # Dry-run 모드: 실제 발송하지 않고 콘솔에 출력
        if self.dry_run:
            import json
            logger.info("🔵 [DRY-RUN] 웹훅 발송 대신 콘솔 출력:")
            
            # Embed 요약 출력
            if 'embeds' in payload:
                for embed in payload['embeds']:
                    title = embed.get('title', 'No Title')
                    fields_count = len(embed.get('fields', []))
                    logger.info(f"  📋 Embed: {title} ({fields_count} fields)")
                    
                    # 첫 3개 필드만 출력
                    for field in embed.get('fields', [])[:3]:
                        name = field.get('name', '')
                        value = field.get('value', '')[:100] + "..." if len(field.get('value', '')) > 100 else field.get('value', '')
                        logger.info(f"    - {name}: {value}")
            
            if 'content' in payload:
                logger.info(f"  📝 Content: {payload['content'][:200]}")
            
            return NotifyResult(
                channel=NotifyChannel.DISCORD,
                success=True,
                response_code=200,
                error_message="[DRY-RUN] 실제 발송하지 않음"
            )
        
        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=10,
            )
            
            # Rate Limit 처리
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", self.retry_delay))
                logger.warning(f"Discord Rate Limit, {retry_after}초 대기")
                
                if retry_count < self.max_retries:
                    time.sleep(retry_after)
                    return self._send(payload, retry_count + 1)
                
                return NotifyResult(
                    channel=NotifyChannel.DISCORD,
                    success=False,
                    response_code=429,
                    error_message="Rate Limit 초과",
                )
            
            # 성공 (204 No Content)
            if response.status_code in (200, 204):
                logger.info("Discord 알림 발송 성공")
                return NotifyResult(
                    channel=NotifyChannel.DISCORD,
                    success=True,
                    response_code=response.status_code,
                )
            
            # 기타 에러
            error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
            logger.error(f"Discord 알림 실패: {error_msg}")
            
            return NotifyResult(
                channel=NotifyChannel.DISCORD,
                success=False,
                response_code=response.status_code,
                error_message=error_msg,
            )
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Discord 요청 에러: {e}")
            
            if retry_count < self.max_retries:
                time.sleep(self.retry_delay)
                return self._send(payload, retry_count + 1)
            
            return NotifyResult(
                channel=NotifyChannel.DISCORD,
                success=False,
                response_code=0,
                error_message=str(e),
            )


# 싱글톤 인스턴스
_notifier: Optional[DiscordNotifier] = None


def get_discord_notifier() -> DiscordNotifier:
    """Discord 알림 인스턴스 반환"""
    global _notifier
    if _notifier is None:
        _notifier = DiscordNotifier()
    return _notifier


if __name__ == "__main__":
    # 테스트
    from datetime import date
    from src.domain.models import ScoreDetail, ScreeningStatus
    
    logging.basicConfig(level=logging.INFO)
    
    # 테스트 데이터
    test_stocks = [
        StockScore(
            stock_code="005930",
            stock_name="삼성전자",
            current_price=71500,
            change_rate=3.25,
            trading_value=850.5,
            score_detail=ScoreDetail(
                cci_value=8.5,
                cci_slope=7.0,
                ma20_slope=8.0,
                candle=9.0,
                change=8.5,
                raw_cci=175.3,
                raw_ma20=70000,
            ),
            score_total=41.0,
            rank=1,
        ),
        StockScore(
            stock_code="000660",
            stock_name="SK하이닉스",
            current_price=185000,
            change_rate=5.12,
            trading_value=620.3,
            score_detail=ScoreDetail(
                cci_value=7.5,
                cci_slope=8.0,
                ma20_slope=7.5,
                candle=8.0,
                change=9.0,
                raw_cci=182.1,
                raw_ma20=175000,
            ),
            score_total=40.0,
            rank=2,
        ),
        StockScore(
            stock_code="373220",
            stock_name="LG에너지솔루션",
            current_price=420000,
            change_rate=2.45,
            trading_value=550.8,
            score_detail=ScoreDetail(
                cci_value=7.0,
                cci_slope=7.5,
                ma20_slope=8.5,
                candle=7.5,
                change=7.0,
                raw_cci=168.5,
                raw_ma20=410000,
            ),
            score_total=37.5,
            rank=3,
        ),
    ]
    
    test_result = ScreeningResult(
        screen_date=date.today(),
        screen_time="15:00",
        total_count=85,
        top3=test_stocks,
        all_items=test_stocks,
        execution_time_sec=125.3,
        status=ScreeningStatus.SUCCESS,
    )
    
    # 알림 발송 테스트
    notifier = get_discord_notifier()
    
    print("Discord 알림 테스트 발송...")
    result = notifier.send_screening_result(test_result, is_preview=False)
    
    print(f"\n발송 결과:")
    print(f"  성공: {result.success}")
    print(f"  응답코드: {result.response_code}")
    if result.error_message:
        print(f"  에러: {result.error_message}")
