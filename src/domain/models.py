"""
데이터 모델 정의

책임:
- 도메인 객체 정의 (dataclass)
- 데이터 변환 유틸리티
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional, Dict
from enum import Enum


# ============================================================
# 기본 데이터 모델
# ============================================================

@dataclass
class DailyPrice:
    """일봉 데이터"""
    date: date
    open: int
    high: int
    low: int
    close: int
    volume: int
    trading_value: float = 0.0  # 거래대금 (원)
    
    @property
    def change_rate(self) -> float:
        """등락률 (전일 대비는 외부에서 계산)"""
        if self.open == 0:
            return 0.0
        return ((self.close - self.open) / self.open) * 100
    
    @property
    def is_bullish(self) -> bool:
        """양봉 여부"""
        return self.close > self.open
    
    @property
    def body_size(self) -> int:
        """몸통 크기"""
        return abs(self.close - self.open)
    
    @property
    def upper_wick(self) -> int:
        """윗꼬리 크기"""
        return self.high - max(self.open, self.close)
    
    @property
    def lower_wick(self) -> int:
        """아랫꼬리 크기"""
        return min(self.open, self.close) - self.low
    
    @property
    def upper_wick_ratio(self) -> float:
        """윗꼬리 비율 (몸통 대비)"""
        if self.body_size == 0:
            return 1.0 if self.upper_wick > 0 else 0.0
        return self.upper_wick / self.body_size


@dataclass
class StockInfo:
    """종목 기본 정보"""
    code: str
    name: str
    market: str = "KOSPI"  # KOSPI, KOSDAQ
    
    def __post_init__(self):
        # 종목코드 6자리 패딩
        self.code = self.code.zfill(6)


@dataclass
class CurrentPrice:
    """현재가 정보"""
    code: str
    price: int
    change: int  # 전일 대비 변동
    change_rate: float  # 등락률 (%)
    trading_value: float  # 당일 거래대금 (원)
    volume: int = 0  # 거래량 (주)
    market_cap: float = 0.0  # 시가총액 (억원)


@dataclass
class StockData:
    """종목 분석용 데이터"""
    code: str
    name: str
    daily_prices: List[DailyPrice]  # 최근 N일 일봉 (오래된 순)
    current_price: int
    trading_value: float  # 당일 거래대금 (억원)
    market_cap: float = 0.0  # 시가총액 (억원)
    
    @property
    def today_change_rate(self) -> float:
        """당일 등락률"""
        if not self.daily_prices:
            return 0.0
        today = self.daily_prices[-1]
        if len(self.daily_prices) >= 2:
            prev_close = self.daily_prices[-2].close
            if prev_close > 0:
                return ((today.close - prev_close) / prev_close) * 100
        return today.change_rate
    
    @property
    def today_candle(self) -> Optional[DailyPrice]:
        """오늘 캔들"""
        return self.daily_prices[-1] if self.daily_prices else None


# ============================================================
# 점수 관련 모델
# ============================================================

@dataclass
class Weights:
    """점수 가중치"""
    cci_value: float = 1.0
    cci_slope: float = 1.0
    ma20_slope: float = 1.0
    candle: float = 1.0
    change: float = 1.0
    
    def to_dict(self) -> Dict[str, float]:
        return {
            "cci_value": self.cci_value,
            "cci_slope": self.cci_slope,
            "ma20_slope": self.ma20_slope,
            "candle": self.candle,
            "change": self.change,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, float]) -> "Weights":
        return cls(
            cci_value=data.get("cci_value", 1.0),
            cci_slope=data.get("cci_slope", 1.0),
            ma20_slope=data.get("ma20_slope", 1.0),
            candle=data.get("candle", 1.0),
            change=data.get("change", 1.0),
        )


@dataclass
class ScoreDetail:
    """개별 점수 상세"""
    cci_value: float = 0.0      # CCI 값 점수
    cci_slope: float = 0.0      # CCI 기울기 점수
    ma20_slope: float = 0.0     # MA20 기울기 점수
    candle: float = 0.0         # 양봉 품질 점수
    change: float = 0.0         # 상승률 점수
    
    # 원시값 (디버깅/분석용)
    raw_cci: float = 0.0        # CCI 원시값
    raw_ma20: float = 0.0       # MA20 원시값
    raw_cci_slope: float = 0.0  # CCI 기울기 원시값
    raw_ma20_slope: float = 0.0 # MA20 기울기 원시값

    # v9.0: 매물대 표시용
    raw_vp_score: float = 6.0
    raw_vp_above_pct: float = 0.0
    raw_vp_below_pct: float = 0.0
    raw_vp_tag: str = "데이터부족"
    raw_vp_meta: str = ""
    
    def total(self, weights: Weights) -> float:
        """가중 합계 점수 (100점 만점으로 정규화)
        
        공식: (가중합 / (가중치합 × 10)) × 100
        """
        weighted_sum = (
            self.cci_value * weights.cci_value +
            self.cci_slope * weights.cci_slope +
            self.ma20_slope * weights.ma20_slope +
            self.candle * weights.candle +
            self.change * weights.change
        )
        
        weight_sum = (
            weights.cci_value +
            weights.cci_slope +
            weights.ma20_slope +
            weights.candle +
            weights.change
        )
        
        # 가중치 합이 0인 경우 방지
        if weight_sum == 0:
            return 0.0
        
        # 100점 만점으로 정규화
        # 각 지표 최대 10점 × 가중치 = 가중치합 × 10이 최대 가능 점수
        max_possible = weight_sum * 10
        normalized_score = (weighted_sum / max_possible) * 100
        
        return round(normalized_score, 1)


@dataclass
class StockScore:
    """종목 점수 결과"""
    stock_code: str
    stock_name: str
    current_price: int
    change_rate: float          # 당일 등락률
    trading_value: float        # 거래대금 (억원)
    
    score_detail: ScoreDetail
    score_total: float          # 가중 합계 점수
    
    rank: int = 0               # 순위
    
    @property
    def score_cci_value(self) -> float:
        return self.score_detail.cci_value
    
    @property
    def score_cci_slope(self) -> float:
        return self.score_detail.cci_slope
    
    @property
    def score_ma20_slope(self) -> float:
        return self.score_detail.ma20_slope
    
    @property
    def score_candle(self) -> float:
        return self.score_detail.candle
    
    @property
    def score_change(self) -> float:
        return self.score_detail.change
    
    @property
    def raw_cci(self) -> float:
        return self.score_detail.raw_cci
    
    @property
    def raw_ma20(self) -> float:
        return self.score_detail.raw_ma20


# ============================================================
# 스크리닝 결과 모델
# ============================================================

class ScreeningStatus(Enum):
    """스크리닝 상태"""
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"  # 일부 실패
    FAILED = "FAILED"


@dataclass
class ScreeningResult:
    """스크리닝 결과"""
    screen_date: date
    screen_time: str            # "15:00" or "12:30"
    
    total_count: int            # 필터링된 종목 수
    top3: List[StockScore]      # TOP N 종목 (DB 호환성 위해 top3 유지)
    all_items: List[StockScore] # 전체 종목 점수 (DB 저장용)
    
    execution_time_sec: float   # 실행 시간
    status: ScreeningStatus
    error_message: Optional[str] = None
    
    weights_used: Weights = field(default_factory=Weights)
    is_preview: bool = False    # 12:30 프리뷰 여부
    
    @property
    def top_n(self) -> List[StockScore]:
        """TOP N 종목 (top3의 alias, 실제로는 TOP_N_COUNT개)"""
        return self.top3
    
    @property
    def top_items(self) -> List[StockScore]:
        """TOP N 종목 (읽기 전용, top3의 명확한 alias)
        
        Note: top3는 DB 호환성을 위해 유지하지만, 실제로는 TOP5(또는 설정된 TOP_N_COUNT)를 담음
        """
        return self.top3


# ============================================================
# 알림 관련 모델
# ============================================================

class NotifyChannel(Enum):
    """알림 채널"""
    DISCORD = "discord"
    KAKAO = "kakao"
    EMAIL = "email"


@dataclass
class NotifyResult:
    """알림 발송 결과"""
    channel: NotifyChannel
    success: bool
    response_code: int = 0
    error_message: Optional[str] = None
    sent_at: datetime = field(default_factory=datetime.now)


# ============================================================
# 익일 결과 모델
# ============================================================

@dataclass
class NextDayResult:
    """익일 결과 데이터"""
    open_price: int             # 시초가
    close_price: int            # 종가
    high_price: int             # 고가
    low_price: int              # 저가
    volume: int                 # 거래량
    trading_value: float        # 거래대금
    
    prev_close: int             # 전일 종가 (스크리닝 당일 종가)
    
    @property
    def open_gap(self) -> float:
        """시초가 갭 (%)"""
        if self.prev_close == 0:
            return 0.0
        return ((self.open_price - self.prev_close) / self.prev_close) * 100
    
    @property
    def is_open_up(self) -> bool:
        """시초가 상승 여부"""
        return self.open_price > self.prev_close
    
    @property
    def close_change(self) -> float:
        """종가 등락률 (%)"""
        if self.prev_close == 0:
            return 0.0
        return ((self.close_price - self.prev_close) / self.prev_close) * 100
    
    @property
    def intraday_range(self) -> float:
        """장중 변동폭 (%)"""
        if self.low_price == 0:
            return 0.0
        return ((self.high_price - self.low_price) / self.low_price) * 100


# ============================================================
# 학습 관련 모델
# ============================================================

@dataclass
class OptimizeConfig:
    """가중치 최적화 설정"""
    min_samples: int = 30         # 최소 데이터 수
    max_weight_change: float = 0.2 # 1회 최대 변경폭
    target_metric: str = "is_open_up"  # 최적화 대상


@dataclass
class OptimizeResult:
    """최적화 결과"""
    old_weights: Weights
    new_weights: Weights
    correlations: Dict[str, float]  # 지표별 상관계수
    sample_size: int
    improved: bool
    reason: str = ""


# ============================================================
# 에러 모델
# ============================================================

class ScreenerError(Exception):
    """스크리너 에러"""
    def __init__(self, code: str, message: str, recoverable: bool = True):
        self.code = code
        self.message = message
        self.recoverable = recoverable
        super().__init__(f"[{code}] {message}")


if __name__ == "__main__":
    # 모델 테스트
    price = DailyPrice(
        date=date.today(),
        open=50000,
        high=52000,
        low=49500,
        close=51500,
        volume=1000000,
    )
    print(f"DailyPrice: {price}")
    print(f"Is Bullish: {price.is_bullish}")
    print(f"Upper Wick Ratio: {price.upper_wick_ratio:.2f}")
    
    weights = Weights()
    print(f"Weights: {weights.to_dict()}")
