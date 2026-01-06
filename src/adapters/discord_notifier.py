"""
디스코드 웹훅 알림

책임:
- 웹훅 메시지 포맷팅
- Embed 생성
- 발송 및 재시도
- Rate Limit 핸들링

의존성:
- requests
- config.settings
"""

import time
import logging
from datetime import datetime
from typing import List, Optional
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
    ScreenerError,
)

logger = logging.getLogger(__name__)


class DiscordNotifier:
    """디스코드 웹훅 알림 전송"""
    
    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or settings.discord.webhook_url
        self.max_retries = 2
        self.retry_delay = 2.0
    
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
        emojis = {1: "🥇", 2: "🥈", 3: "🥉"}
        return emojis.get(rank, f"{rank}위")
    
    def _build_stock_field(self, stock: StockScore) -> dict:
        """종목 필드 생성"""
        emoji = self._get_rank_emoji(stock.rank)
        
        name = f"{emoji} {stock.rank}위: {stock.stock_name} ({stock.stock_code})"
        
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
        """Embed 메시지 빌드"""
        # 타이틀
        label = MSG_PREVIEW_LABEL if is_preview else MSG_MAIN_LABEL
        title = f"🎯 종가매매 TOP 3 {label} ({result.screen_time})"
        
        # 설명
        description = f"📅 {result.screen_date.strftime('%Y-%m-%d')} 스크리닝 결과"
        if result.total_count > 0:
            description += f"\n📊 분석 종목: {result.total_count}개"
        
        # 색상
        if not result.top3:
            color = DISCORD_COLOR_WARNING
        else:
            color = DISCORD_COLOR_SUCCESS
        
        # 필드
        fields = []
        if result.top3:
            for stock in result.top3:
                fields.append(self._build_stock_field(stock))
        else:
            fields.append({
                "name": "❌ 결과",
                "value": MSG_NO_CANDIDATES,
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
                "text": "종가매매 스크리너 v1.0",
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
    
    def _send(
        self,
        payload: dict,
        retry_count: int = 0,
    ) -> NotifyResult:
        """웹훅 발송"""
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
