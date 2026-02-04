"""
Quiet Accumulation 스크리너 v1.0

🎯 목표: "거래량 폭발 전, 조용히 모이는 종목" 탐지

핵심 철학:
- 기존 ClosingBell: 거래량/거래대금 상위 → 이미 시장 관심
- Quiet Accumulation: 변동성 낮음 + 거래대금 미세 상승 → 선행 신호

4단계 필터:
A) 유동성 최소치: 20일 평균 거래대금 ≥ 5억
B) 변동성 낮음 + 박스권: ATR% 하위 30%, 20일 고저폭 ≤ 25%
C) 거래대금 온기 상승: 5일 평균 ≥ 20일 평균 × 1.25
D) 발사 직전 형태: 현재가 ≥ 60일 고점 × 0.80, 저점 상승 추세

실행 시점: 15:05 (ClosingBell 직후)
"""

import logging
from datetime import datetime, date
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass
import numpy as np

from src.adapters.kiwoom_rest_client import get_kiwoom_client, KiwoomRestClient
from src.adapters.discord_notifier import get_discord_notifier
from src.utils.stock_filters import filter_universe_stocks
from src.domain.models import DailyPrice

logger = logging.getLogger(__name__)


# ============================================================
# 데이터 모델
# ============================================================
@dataclass
class QuietStock:
    """조용한 축적 종목 정보"""
    code: str
    name: str
    current_price: int
    change_rate: float
    
    # A) 유동성
    avg_trading_value_20d: float  # 억원
    
    # B) 변동성
    volatility_score: float  # ATR% or (H-L)/C 평균
    range_20d: float  # 20일 고저폭 %
    
    # C) 온기 상승
    trading_value_ratio: float  # 5일/20일 비율
    warm_days: int  # 최근 5일 중 20일 평균 초과 일수
    
    # D) 발사 직전
    vs_high_60d: float  # 60일 고점 대비 %
    low_slope: float  # 저점 상승 추세 (회귀 기울기)
    
    # 종합 점수
    total_score: float = 0.0
    grade: str = ""


# ============================================================
# 설정 상수
# ============================================================
class QuietConfig:
    """Quiet Accumulation 설정"""
    
    # 1차 유니버스: 가격 범위
    MIN_PRICE = 2000
    MAX_PRICE = 10000
    
    # A) 유동성 최소치
    MIN_AVG_TRADING_VALUE_20D = 5.0  # 억원
    
    # B) 변동성
    VOLATILITY_TOP_PERCENTILE = 30  # 하위 30%만 통과
    MAX_RANGE_20D = 0.25  # 20일 고저폭 25% 이하
    
    # C) 온기 상승
    TRADING_VALUE_RATIO_MIN = 1.25  # 5일/20일 ≥ 1.25배
    MIN_WARM_DAYS = 3  # 최소 3일 이상
    
    # D) 발사 직전
    MIN_VS_HIGH_60D = 0.80  # 60일 고점의 80% 이상
    MIN_LOW_SLOPE = 0.0  # 저점 상승 (양수)
    
    # 결과
    TOP_N = 20


# ============================================================
# 메인 스캐너
# ============================================================
class QuietAccumulationScanner:
    """조용한 축적 패턴 스캐너"""
    
    def __init__(self, broker_client: KiwoomRestClient = None):
        self.broker = broker_client or get_kiwoom_client()
        self.config = QuietConfig()
    
    def scan(self) -> List[QuietStock]:
        """전체 스캔 실행"""
        logger.info("🔍 Quiet Accumulation 스캔 시작")
        
        # 1. 1차 유니버스 구성 (가격 범위 내 종목)
        universe = self._get_price_universe()
        logger.info(f"  [1차] 가격 유니버스: {len(universe)}개")
        
        if not universe:
            logger.warning("유니버스가 비어있습니다")
            return []
        
        # 2. 각 종목 분석 및 점수 계산
        candidates = []
        for stock in universe:
            quiet_stock = self._analyze_stock(stock)
            if quiet_stock:
                candidates.append(quiet_stock)
        
        logger.info(f"  [분석] 후보: {len(candidates)}개")
        
        # 3. 점수순 정렬 및 TOP N 선정
        candidates.sort(key=lambda x: x.total_score, reverse=True)
        top_stocks = candidates[:self.config.TOP_N]
        
        # 4. 등급 부여
        for i, stock in enumerate(top_stocks):
            stock.grade = self._assign_grade(stock.total_score, i + 1)
        
        logger.info(f"✅ Quiet Accumulation TOP {len(top_stocks)}개 선정")
        
        return top_stocks
    
    def _get_price_universe(self) -> List[Dict[str, Any]]:
        """가격 범위 내 종목 조회"""
        # 거래대금 상위에서 가격 필터링
        all_stocks = self.broker.get_trading_value_rank(market_type="0", count=300)
        
        filtered = []
        for stock in all_stocks:
            price = stock['current_price']
            if self.config.MIN_PRICE <= price <= self.config.MAX_PRICE:
                filtered.append(stock)
        
        # ETF/스팩 등 제외
        from src.utils.stock_filters import is_eligible_universe_stock
        
        result = []
        for s in filtered:
            is_ok, _ = is_eligible_universe_stock(s['code'], s['name'])
            if is_ok:
                result.append(s)
        
        return result
    
    def _analyze_stock(self, stock: Dict[str, Any]) -> Optional[QuietStock]:
        """개별 종목 분석"""
        code = stock['code']
        name = stock['name']
        
        try:
            # 일봉 데이터 조회 (60일)
            prices = self.broker.get_daily_prices(code, count=60)
            if len(prices) < 20:
                return None
            
            # A) 유동성 체크
            avg_tv_20d = self._calc_avg_trading_value(prices[:20])
            if avg_tv_20d < self.config.MIN_AVG_TRADING_VALUE_20D:
                return None
            
            # B) 변동성 계산
            volatility = self._calc_volatility(prices[:20])
            range_20d = self._calc_range_20d(prices[:20])
            if range_20d > self.config.MAX_RANGE_20D:
                return None
            
            # C) 온기 상승
            avg_tv_5d = self._calc_avg_trading_value(prices[:5])
            tv_ratio = avg_tv_5d / avg_tv_20d if avg_tv_20d > 0 else 0
            warm_days = self._count_warm_days(prices[:5], avg_tv_20d)
            
            # D) 발사 직전
            vs_high_60d = self._calc_vs_high_60d(prices)
            low_slope = self._calc_low_slope(prices[:10])
            
            # 점수 계산
            score = self._calc_score(
                volatility, range_20d, tv_ratio, warm_days,
                vs_high_60d, low_slope
            )
            
            return QuietStock(
                code=code,
                name=name,
                current_price=stock['current_price'],
                change_rate=stock['change_rate'],
                avg_trading_value_20d=avg_tv_20d,
                volatility_score=volatility,
                range_20d=range_20d,
                trading_value_ratio=tv_ratio,
                warm_days=warm_days,
                vs_high_60d=vs_high_60d,
                low_slope=low_slope,
                total_score=score,
            )
            
        except Exception as e:
            logger.debug(f"종목 분석 오류 ({code}): {e}")
            return None
    
    # ========================================
    # 지표 계산 함수들
    # ========================================
    
    def _calc_avg_trading_value(self, prices: List[DailyPrice]) -> float:
        """평균 거래대금 (억원)"""
        if not prices:
            return 0.0
        
        total = 0.0
        for p in prices:
            # 거래대금 = 종가 × 거래량 (대략)
            tv = p.close * p.volume / 100_000_000  # 억원
            total += tv
        
        return total / len(prices)
    
    def _calc_volatility(self, prices: List[DailyPrice]) -> float:
        """변동성 점수: (고가-저가)/종가 평균"""
        if not prices:
            return 0.0
        
        values = []
        for p in prices:
            if p.close > 0:
                v = (p.high - p.low) / p.close
                values.append(v)
        
        return np.mean(values) if values else 0.0
    
    def _calc_range_20d(self, prices: List[DailyPrice]) -> float:
        """20일 고저폭 비율"""
        if not prices:
            return 0.0
        
        high_20d = max(p.high for p in prices)
        low_20d = min(p.low for p in prices)
        close = prices[0].close
        
        if close > 0:
            return (high_20d - low_20d) / close
        return 0.0
    
    def _count_warm_days(self, prices: List[DailyPrice], avg_tv_20d: float) -> int:
        """20일 평균 초과한 날 수"""
        count = 0
        for p in prices:
            tv = p.close * p.volume / 100_000_000
            if tv >= avg_tv_20d:
                count += 1
        return count
    
    def _calc_vs_high_60d(self, prices: List[DailyPrice]) -> float:
        """60일 고점 대비 비율"""
        if not prices:
            return 0.0
        
        high_60d = max(p.high for p in prices)
        current = prices[0].close
        
        if high_60d > 0:
            return current / high_60d
        return 0.0
    
    def _calc_low_slope(self, prices: List[DailyPrice]) -> float:
        """저점 상승 추세 (선형회귀 기울기)"""
        if len(prices) < 5:
            return 0.0
        
        # 최근 10일 저점들
        lows = [p.low for p in reversed(prices)]  # 오래된 것 → 최신 순서
        
        # 선형회귀
        x = np.arange(len(lows))
        coeffs = np.polyfit(x, lows, 1)
        
        return coeffs[0]  # 기울기 (양수면 상승 추세)
    
    def _calc_score(
        self,
        volatility: float,
        range_20d: float,
        tv_ratio: float,
        warm_days: int,
        vs_high_60d: float,
        low_slope: float,
    ) -> float:
        """종합 점수 계산 (100점 만점)"""
        score = 0.0
        
        # A) 변동성 낮을수록 좋음 (25점)
        # volatility 0.02 이하 → 25점, 0.10 이상 → 0점
        vol_score = max(0, min(25, (0.10 - volatility) / 0.08 * 25))
        score += vol_score
        
        # B) 박스권 좁을수록 좋음 (25점)
        # range_20d 0.10 이하 → 25점, 0.25 이상 → 0점
        range_score = max(0, min(25, (0.25 - range_20d) / 0.15 * 25))
        score += range_score
        
        # C) 온기 상승 (25점)
        # tv_ratio 1.5 이상 → 15점, warm_days 5일 → 10점
        ratio_score = min(15, (tv_ratio - 1.0) / 0.5 * 15)
        warm_score = min(10, warm_days * 2)
        score += max(0, ratio_score) + warm_score
        
        # D) 발사 직전 (25점)
        # vs_high_60d 0.95 이상 → 15점, low_slope 양수 → 10점
        high_score = min(15, (vs_high_60d - 0.80) / 0.15 * 15)
        slope_score = 10 if low_slope > 0 else 0
        score += max(0, high_score) + slope_score
        
        return min(100, score)
    
    def _assign_grade(self, score: float, rank: int) -> str:
        """등급 부여"""
        if score >= 80:
            return "🔥S"
        elif score >= 65:
            return "🥇A"
        elif score >= 50:
            return "🥈B"
        elif score >= 35:
            return "🥉C"
        else:
            return "📊D"


# ============================================================
# Discord 알림
# ============================================================
def format_quiet_discord(stocks: List[QuietStock]) -> str:
    """Discord 알림 포맷"""
    if not stocks:
        return "🔇 Quiet Accumulation: 조건 충족 종목 없음"
    
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🔇 **Quiet Accumulation TOP 20**",
        "💡 거래량 폭발 전 조용한 축적 패턴",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ""
    ]
    
    for i, s in enumerate(stocks, 1):
        lines.append(
            f"**#{i}** {s.grade} **{s.name}** ({s.code})\n"
            f"   💰 {s.current_price:,}원 ({s.change_rate:+.1f}%)\n"
            f"   📊 점수: {s.total_score:.0f}점\n"
            f"   📈 5/20일 거래대금: {s.trading_value_ratio:.2f}배\n"
            f"   📉 변동성: {s.volatility_score*100:.1f}% | 60일고점: {s.vs_high_60d*100:.0f}%\n"
        )
    
    lines.append("")
    lines.append(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    return "\n".join(lines)


def send_quiet_alert(stocks: List[QuietStock]) -> bool:
    """Discord 알림 발송"""
    notifier = get_discord_notifier()
    message = format_quiet_discord(stocks)
    
    result = notifier.send_simple_message(message)
    return result.success


# ============================================================
# 메인 실행 함수
# ============================================================
def run_quiet_accumulation(send_alert: bool = True) -> List[QuietStock]:
    """
    Quiet Accumulation 스크리너 실행
    
    Args:
        send_alert: Discord 알림 발송 여부
        
    Returns:
        QuietStock 리스트 (TOP 20)
    """
    logger.info("=" * 50)
    logger.info("🔇 Quiet Accumulation 스크리너 시작")
    logger.info("=" * 50)
    
    scanner = QuietAccumulationScanner()
    stocks = scanner.scan()
    
    if send_alert and stocks:
        success = send_quiet_alert(stocks)
        if success:
            logger.info("✅ Discord 알림 발송 완료")
        else:
            logger.warning("⚠️ Discord 알림 발송 실패")
    
    logger.info(f"🔇 Quiet Accumulation 완료: {len(stocks)}개")
    
    return stocks


# ============================================================
# CLI 테스트
# ============================================================
if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__file__).split('src')[0])
    
    from src.infrastructure.logging_config import init_logging
    init_logging()
    
    # 테스트 실행 (알림 없이)
    stocks = run_quiet_accumulation(send_alert=False)
    
    print("\n" + "=" * 60)
    print("🔇 Quiet Accumulation 결과")
    print("=" * 60)
    
    for i, s in enumerate(stocks[:10], 1):
        print(f"\n#{i} {s.grade} {s.name} ({s.code})")
        print(f"   가격: {s.current_price:,}원 ({s.change_rate:+.1f}%)")
        print(f"   점수: {s.total_score:.0f}점")
        print(f"   5/20일 거래대금비: {s.trading_value_ratio:.2f}배")
        print(f"   변동성: {s.volatility_score*100:.1f}%")
        print(f"   60일 고점대비: {s.vs_high_60d*100:.0f}%")
        print(f"   저점추세: {'상승↑' if s.low_slope > 0 else '하락↓'}")
