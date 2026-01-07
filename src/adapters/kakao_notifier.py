"""
카카오톡 나에게 보내기 알림

책임:
- 카카오톡 메시지 포맷팅
- 나에게 보내기 API 호출
- 발송 및 재시도
- 토큰 만료 처리

의존성:
- requests
- config.settings

참고:
- 카카오 REST API: https://developers.kakao.com/docs/latest/ko/message/rest-api
"""

import time
import logging
from datetime import datetime
from typing import Optional
import requests

from src.config.settings import settings
from src.domain.models import (
    StockScore,
    ScreeningResult,
    NotifyResult,
    NotifyChannel,
)

logger = logging.getLogger(__name__)


class KakaoNotifier:
    """카카오톡 나에게 보내기 알림 전송"""
    
    # 카카오 API 엔드포인트
    SEND_ME_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    
    def __init__(self, access_token: Optional[str] = None):
        self.access_token = access_token or settings.kakao.access_token
        self.enabled = bool(self.access_token and self.access_token.strip())
        self.max_retries = 2
        self.retry_delay = 2.0
        
        if not self.enabled:
            logger.info("카카오톡 알림 비활성화 (액세스 토큰 없음)")
    
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
    
    def _build_stock_text(self, stock: StockScore) -> str:
        """종목 텍스트 생성"""
        emoji = self._get_rank_emoji(stock.rank)
        
        lines = [
            f"{emoji} {stock.rank}위: {stock.stock_name} ({stock.stock_code})",
            f"  💰 {self._format_price(stock.current_price)} ({self._format_change_rate(stock.change_rate)})",
            f"  📊 총점: {self._format_score(stock.score_total)}",
            f"  📈 CCI: {stock.raw_cci:.1f} | 거래대금: {stock.trading_value:.0f}억",
        ]
        
        return "\n".join(lines)
    
    def _build_message_text(
        self,
        result: ScreeningResult,
        is_preview: bool = False,
    ) -> str:
        """메시지 텍스트 빌드"""
        # 타이틀
        label = "[프리뷰]" if is_preview else "[최종]"
        title = f"🎯 종가매매 TOP 3 {label}"
        
        # 날짜/시간
        date_str = result.screen_date.strftime('%Y-%m-%d')
        header = f"{title}\n📅 {date_str} {result.screen_time}"
        
        if result.total_count > 0:
            header += f"\n📊 분석 종목: {result.total_count}개"
        
        # 종목 정보
        stock_texts = []
        if result.top3:
            stock_texts.append("\n" + "=" * 30)
            for stock in result.top3:
                stock_texts.append(self._build_stock_text(stock))
            stock_texts.append("=" * 30)
        else:
            stock_texts.append("\n❌ 적합한 종목이 없습니다.")
        
        # 실행 시간
        footer = ""
        if result.execution_time_sec:
            footer = f"\n⏱️ 실행시간: {result.execution_time_sec:.1f}초"
        
        return header + "\n".join(stock_texts) + footer
    
    def send_to_me(self, text: str) -> NotifyResult:
        """텍스트 메시지 나에게 보내기
        
        Args:
            text: 발송할 텍스트
            
        Returns:
            발송 결과
        """
        if not self.enabled:
            logger.debug("카카오톡 알림 스킵 (비활성화)")
            return NotifyResult(
                channel=NotifyChannel.KAKAO,
                success=False,
                response_code=0,
                error_message="카카오톡 알림 비활성화 (토큰 없음)",
            )
        
        # 텍스트 메시지 템플릿
        template_object = {
            "object_type": "text",
            "text": text[:1000],  # 최대 1000자
            "link": {
                "web_url": "https://github.com",
                "mobile_web_url": "https://github.com",
            },
        }
        
        return self._send(template_object)
    
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
        if not self.enabled:
            logger.debug("카카오톡 알림 스킵 (비활성화)")
            return NotifyResult(
                channel=NotifyChannel.KAKAO,
                success=False,
                response_code=0,
                error_message="카카오톡 알림 비활성화 (토큰 없음)",
            )
        
        text = self._build_message_text(result, is_preview)
        return self.send_to_me(text)
    
    def send_error_alert(
        self,
        error: Exception,
        context: str = "",
    ) -> NotifyResult:
        """에러 알림 발송"""
        if not self.enabled:
            return NotifyResult(
                channel=NotifyChannel.KAKAO,
                success=False,
                response_code=0,
                error_message="카카오톡 알림 비활성화 (토큰 없음)",
            )
        
        text = f"⚠️ 스크리너 에러 발생\n\n{context}\n\n에러: {str(error)[:300]}"
        return self.send_to_me(text)
    
    def _send(
        self,
        template_object: dict,
        retry_count: int = 0,
    ) -> NotifyResult:
        """카카오 API 발송"""
        import json
        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        
        data = {
            "template_object": json.dumps(template_object),
        }
        
        try:
            response = requests.post(
                self.SEND_ME_URL,
                headers=headers,
                data=data,
                timeout=10,
            )
            
            # 성공
            if response.status_code == 200:
                result_json = response.json()
                if result_json.get("result_code") == 0:
                    logger.info("카카오톡 알림 발송 성공")
                    return NotifyResult(
                        channel=NotifyChannel.KAKAO,
                        success=True,
                        response_code=200,
                    )
            
            # 토큰 만료 (401)
            if response.status_code == 401:
                error_msg = "액세스 토큰 만료 - 토큰 재발급 필요"
                logger.warning(f"카카오톡 알림 실패: {error_msg}")
                
                return NotifyResult(
                    channel=NotifyChannel.KAKAO,
                    success=False,
                    response_code=401,
                    error_message=error_msg,
                )
            
            # Rate Limit (429)
            if response.status_code == 429:
                if retry_count < self.max_retries:
                    logger.warning(f"카카오톡 Rate Limit, {self.retry_delay}초 대기")
                    time.sleep(self.retry_delay)
                    return self._send(template_object, retry_count + 1)
                
                return NotifyResult(
                    channel=NotifyChannel.KAKAO,
                    success=False,
                    response_code=429,
                    error_message="Rate Limit 초과",
                )
            
            # 기타 에러
            error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
            logger.error(f"카카오톡 알림 실패: {error_msg}")
            
            return NotifyResult(
                channel=NotifyChannel.KAKAO,
                success=False,
                response_code=response.status_code,
                error_message=error_msg,
            )
            
        except requests.exceptions.RequestException as e:
            logger.error(f"카카오톡 요청 에러: {e}")
            
            if retry_count < self.max_retries:
                time.sleep(self.retry_delay)
                return self._send(template_object, retry_count + 1)
            
            return NotifyResult(
                channel=NotifyChannel.KAKAO,
                success=False,
                response_code=0,
                error_message=str(e),
            )


# 싱글톤 인스턴스
_notifier: Optional[KakaoNotifier] = None


def get_kakao_notifier() -> KakaoNotifier:
    """Kakao 알림 인스턴스 반환"""
    global _notifier
    if _notifier is None:
        _notifier = KakaoNotifier()
    return _notifier


if __name__ == "__main__":
    # 테스트
    from datetime import date
    from src.domain.models import ScoreDetail, ScreeningStatus
    
    logging.basicConfig(level=logging.INFO)
    
    # 설정 확인
    print(f"카카오 REST API Key: {settings.kakao.rest_api_key[:10]}..." if settings.kakao.rest_api_key else "없음")
    print(f"카카오 Access Token: {'설정됨' if settings.kakao.access_token else '없음'}")
    print(f"카카오 알림 활성화: {settings.kakao.enabled}")
    
    if not settings.kakao.enabled:
        print("\n⚠️ 카카오톡 알림이 비활성화 상태입니다.")
        print("   액세스 토큰을 발급받아 .env의 KAKAO_ACCESS_TOKEN에 설정해주세요.")
    else:
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
        notifier = get_kakao_notifier()
        
        print("\n카카오톡 알림 테스트 발송...")
        result = notifier.send_screening_result(test_result, is_preview=False)
        
        print(f"\n발송 결과:")
        print(f"  성공: {result.success}")
        print(f"  응답코드: {result.response_code}")
        if result.error_message:
            print(f"  에러: {result.error_message}")
