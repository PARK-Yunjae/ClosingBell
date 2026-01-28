"""
점수 산출기 v6.5 - 구간 최적화 점수제

📊 9.5년 백테스트 최적 구간 기반 (2016-2025)
===========================================
🏆 구간 최적화로 역전 현상 해결:
   - CCI 160~180: 67.2% 승률 (최적)
   - 등락률 4~6%: 스윗스팟
   - 이격도 2~8%: 최적 구간
   - 연속양봉 1~3일: 최적, 5일+ 위험

🎯 점수 체계 (100점 만점):
  - 핵심 6개 지표: 각 15점 (총 90점) - 구간 최적화
  - 보너스 조건 3개: 각 3~4점 (총 10점)
  
📈 등급 및 매도 전략:
  - S등급 (85+): 시초가 30% + 목표 +4%
  - A등급 (75-84): 시초가 40% + 목표 +3%
  - B등급 (65-74): 시초가 50% + 목표 +2.5%
  - C등급 (55-64): 시초가 70% + 목표 +2%
  - D등급 (<55): 시초가 전량매도

🔧 v6.5 변경사항:
  - 단순 선형 → 구간 최적화 (역전 현상 해결)
  - CCI: 160~180 만점, 180+ 감점
  - 등락률: 4~6% 만점, 8%+ 추격매수 감점
  - 이격도: 2~8% 만점, 15%+ 과열 감점
  - 연속양봉: 1~3일 만점, 5일+ 급락위험 감점
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from enum import Enum

from src.domain.models import (
    DailyPrice,
    StockData,
    StockScore,
    ScoreDetail,
    Weights,
)
from src.domain.indicators import (
    calculate_all_indicators,
)
from src.config.constants import (
    SCORE_MAX,
    SCORE_MIN,
    TOP_N_COUNT,
)

logger = logging.getLogger(__name__)


# ============================================================
# v5 등급 시스템
# ============================================================

class StockGrade(Enum):
    """종목 등급"""
    S = "S"  # 85점 이상: 최상
    A = "A"  # 75-84점: 우수
    B = "B"  # 65-74점: 양호
    C = "C"  # 55-64점: 보통
    D = "D"  # 55점 미만: 주의


@dataclass
class SellStrategy:
    """매도 전략"""
    grade: StockGrade
    open_sell_ratio: int           # 시초가 매도 비율 (%)
    target_sell_ratio: int         # 목표가 매도 비율 (%)
    target_profit: float           # 목표 익절가 (%)
    stop_loss: float               # 손절가 (%)
    description: str               # 전략 설명
    confidence: str                # 신뢰도


# 등급별 매도 전략 정의
# 원칙: 확신 높을수록 오래 홀딩, 확신 낮을수록 빨리 익절/손절
SELL_STRATEGIES: Dict[StockGrade, SellStrategy] = {
    StockGrade.S: SellStrategy(
        grade=StockGrade.S,
        open_sell_ratio=30,           # 시초가 30%만 익절
        target_sell_ratio=70,         # 70%는 목표가까지 홀딩
        target_profit=4.0,            # 목표 +4% (높게)
        stop_loss=-3.0,               # 손절 -3% (넓게, 기다림)
        description="시초 30% 익절 + 70% 목표가 +4% 홀딩",
        confidence="매우 높음",
    ),
    StockGrade.A: SellStrategy(
        grade=StockGrade.A,
        open_sell_ratio=40,           # 시초가 40% 익절
        target_sell_ratio=60,         # 60%는 목표가까지
        target_profit=3.0,            # 목표 +3%
        stop_loss=-2.5,               # 손절 -2.5%
        description="시초 40% 익절 + 60% 목표가 +3% 홀딩",
        confidence="높음",
    ),
    StockGrade.B: SellStrategy(
        grade=StockGrade.B,
        open_sell_ratio=50,           # 시초가 50% 익절
        target_sell_ratio=50,         # 50%는 목표가까지
        target_profit=2.5,            # 목표 +2.5%
        stop_loss=-2.0,               # 손절 -2%
        description="시초 50% 익절 + 50% 목표가 +2.5% 홀딩",
        confidence="중상",
    ),
    StockGrade.C: SellStrategy(
        grade=StockGrade.C,
        open_sell_ratio=70,           # 시초가 70% 익절 (많이)
        target_sell_ratio=30,         # 30%만 목표가까지
        target_profit=2.0,            # 목표 +2% (낮게)
        stop_loss=-1.5,               # 손절 -1.5% (좁게)
        description="시초 70% 익절 + 30% 목표가 +2% (보수적)",
        confidence="중간",
    ),
    StockGrade.D: SellStrategy(
        grade=StockGrade.D,
        open_sell_ratio=100,          # 시초가 100% 전량 매도
        target_sell_ratio=0,          # 홀딩 없음
        target_profit=1.0,            # (참고용)
        stop_loss=-1.0,               # 손절 -1% (아주 좁게)
        description="시초가 전량 매도 권장 (리스크 높음)",
        confidence="낮음",
    ),
}


def get_grade(score: float) -> StockGrade:
    """점수에 따른 등급 반환"""
    if score >= 85:
        return StockGrade.S
    elif score >= 75:
        return StockGrade.A
    elif score >= 65:
        return StockGrade.B
    elif score >= 55:
        return StockGrade.C
    else:
        return StockGrade.D


def get_sell_strategy(score: float) -> SellStrategy:
    """점수에 따른 매도 전략 반환"""
    grade = get_grade(score)
    return SELL_STRATEGIES[grade]


# ============================================================
# v5 점수 상세 모델
# ============================================================

@dataclass
class ScoreDetailV5:
    """v5 점수 상세 (100점 만점)"""
    # 핵심 지표 (각 15점, 총 90점)
    cci_score: float = 0.0          # CCI 점수 (0~15)
    change_score: float = 0.0       # 등락률 점수 (0~15)
    distance_score: float = 0.0     # 이격도 점수 (0~15)
    consec_score: float = 0.0       # 연속양봉 점수 (0~15)
    volume_score: float = 0.0       # 거래량비율 점수 (0~15)
    candle_score: float = 0.0       # 캔들품질 점수 (0~15)
    
    # 보너스 조건 (총 10점)
    cci_rising_bonus: float = 0.0   # CCI 상승 보너스 (0~4)
    ma20_3day_bonus: float = 0.0    # MA20 3일상승 보너스 (0~3)
    not_high_eq_close_bonus: float = 0.0  # 고가≠종가 보너스 (0~3)
    
    # 원시값 (디버깅용 + Discord 표시용)
    raw_cci: float = 0.0
    raw_change_rate: float = 0.0
    raw_distance: float = 0.0
    raw_consec_days: int = 0
    raw_volume_ratio: float = 0.0
    raw_upper_wick_ratio: float = 0.0
    is_cci_rising: bool = False
    is_ma20_3day_up: bool = False
    is_high_eq_close: bool = False
    
    # v5.1 추가: MA20 값 (Discord 표시용)
    raw_ma20: float = 0.0
    is_above_ma20: bool = False
    is_bullish: bool = False
    
    # v6.5.1 추가: RSI
    raw_rsi: float = 0.0
    
    @property
    def total(self) -> float:
        """총점 (100점 만점)"""
        base = (
            self.cci_score +
            self.change_score +
            self.distance_score +
            self.consec_score +
            self.volume_score +
            self.candle_score
        )
        bonus = (
            self.cci_rising_bonus +
            self.ma20_3day_bonus +
            self.not_high_eq_close_bonus
        )
        return round(min(100.0, base + bonus), 1)
    
    @property
    def grade(self) -> StockGrade:
        """등급"""
        return get_grade(self.total)
    
    @property
    def sell_strategy(self) -> SellStrategy:
        """매도 전략"""
        return get_sell_strategy(self.total)


@dataclass
class StockScoreV5:
    """v5 종목 점수 결과"""
    stock_code: str
    stock_name: str
    current_price: int
    change_rate: float
    trading_value: float  # 거래대금 (억원)
    
    score_detail: ScoreDetailV5
    score_total: float
    
    rank: int = 0
    market_cap: float = 0.0  # 시가총액 (억원) - v6.5 추가
    volume: int = 0  # 거래량 (주) - v6.5 추가
    
    @property
    def grade(self) -> StockGrade:
        # score_total 기준 (글로벌 조정 반영)
        return get_grade(self.score_total)
    
    @property
    def sell_strategy(self) -> SellStrategy:
        # score_total 기준 (글로벌 조정 반영)
        return get_sell_strategy(self.score_total)
    
    def to_legacy_score(self) -> StockScore:
        """기존 StockScore 모델로 변환 (호환성)"""
        legacy_detail = ScoreDetail(
            cci_value=self.score_detail.cci_score / 1.5,  # 15점 -> 10점 스케일
            cci_slope=self.score_detail.distance_score / 1.5,
            ma20_slope=self.score_detail.ma20_3day_bonus * 3.33,
            candle=self.score_detail.candle_score / 1.5,
            change=self.score_detail.change_score / 1.5,
            raw_cci=self.score_detail.raw_cci,
            raw_ma20=0.0,
            raw_cci_slope=0.0,
            raw_ma20_slope=0.0,
        )
        return StockScore(
            stock_code=self.stock_code,
            stock_name=self.stock_name,
            current_price=self.current_price,
            change_rate=self.change_rate,
            trading_value=self.trading_value,
            score_detail=legacy_detail,
            score_total=self.score_total,
            rank=self.rank,
        )


# ============================================================
# v6.2.3 점수 계산 함수들 (각 15점 만점) - 단순 선형 정규화
# ============================================================

def calc_cci_score(cci: float) -> float:
    """CCI 점수 (15점 만점) - v6.5 단순화
    
    최적 구간: 160~180 (만점)
    멀어질수록 점진적 감점
    음수: 많이 감점
    """
    if cci is None:
        return 7.5
    
    # 음수: 많이 감점
    if cci < 0:
        return max(0, 5 + cci * 0.05)  # 0 → 5점, -100 → 0점
    
    # 최적 구간: 160~180 (만점)
    if 160 <= cci <= 180:
        return 15.0
    
    # 160 미만: 점진적 감점 (거리에 비례)
    if cci < 160:
        distance = 160 - cci
        return max(5, 15 - distance * 0.0625)  # 160pt 떨어지면 10점 감점
    
    # 180 초과: 점진적 감점 (과열)
    distance = cci - 180
    return max(3, 15 - distance * 0.1)  # 120pt 떨어지면 12점 감점


def calc_change_score(change_rate: float) -> float:
    """등락률 점수 (15점 만점) - v6.5 단순화
    
    최적 구간: 4~6% (만점)
    멀어질수록 점진적 감점
    음수: 많이 감점
    25%+: 많이 감점 (추격매수 위험)
    """
    if change_rate is None:
        return 7.5
    
    # 음수: 많이 감점
    if change_rate < 0:
        return max(0, 5 + change_rate * 0.5)  # 0% → 5점, -10% → 0점
    
    # 25%+: 많이 감점 (급등 추격 위험)
    if change_rate >= 25:
        return 2.0
    
    # 최적 구간: 4~6% (만점)
    if 4 <= change_rate <= 6:
        return 15.0
    
    # 4% 미만: 점진적 감점
    if change_rate < 4:
        distance = 4 - change_rate
        return max(7, 15 - distance * 2)  # 4pt 떨어지면 8점 감점
    
    # 6% 초과: 점진적 감점 (추격매수 위험 증가)
    distance = change_rate - 6
    return max(3, 15 - distance * 0.63)  # 19pt 떨어지면 12점 감점


def calc_distance_score(distance: float) -> float:
    """이격도 점수 (15점 만점) - v6.5 단순화
    
    최적 구간: 2~8% (만점)
    멀어질수록 점진적 감점
    음수: 많이 감점 (MA20 아래)
    """
    if distance is None:
        return 7.5
    
    # 음수: 많이 감점 (MA20 아래 = 약세)
    if distance < 0:
        return max(0, 5 + distance * 0.5)  # 0% → 5점, -10% → 0점
    
    # 최적 구간: 2~8% (만점)
    if 2 <= distance <= 8:
        return 15.0
    
    # 2% 미만: 점진적 감점 (아직 덜 올랐음)
    if distance < 2:
        return max(10, 15 - (2 - distance) * 2.5)  # 2pt 떨어지면 5점 감점
    
    # 8% 초과: 점진적 감점 (과열)
    return max(3, 15 - (distance - 8) * 0.6)  # 20pt 떨어지면 12점 감점


def calc_consec_score(consec_days: int) -> float:
    """연속양봉 점수 (15점 만점) - v6.5 단순화
    
    최적 구간: 2~3일 (만점)
    멀어질수록 점진적 감점
    """
    if consec_days is None:
        consec_days = 0
    
    # 최적 구간: 2~3일 (만점)
    if 2 <= consec_days <= 3:
        return 15.0
    
    # 0~1일: 점진적 감점 (모멘텀 부족)
    if consec_days < 2:
        return 7 + consec_days * 4  # 0일 → 7점, 1일 → 11점
    
    # 4일+: 점진적 감점 (과열/급락 위험)
    return max(2, 15 - (consec_days - 3) * 3)  # 4일 → 12점, 5일 → 9점, 6일 → 6점


def calc_volume_score(volume_ratio: float) -> float:
    """거래량비율 점수 (15점 만점) - 단순 선형
    
    v6.2.3: 단순 선형 정규화
    - 1배 → 0점
    - 5배 → 15점
    
    범위: (volume_ratio - 1) / 4 * 15
    """
    if volume_ratio is None:
        return 7.5
    
    # 1배 미만은 0점
    if volume_ratio < 1:
        return 0.0
    
    # 단순 선형: 1~5배를 0~15로 정규화
    normalized = (volume_ratio - 1) / 4
    normalized = max(0, min(1, normalized))  # 0~1 클램프
    return normalized * 15


def calc_candle_score(
    is_bullish: bool,
    upper_wick_ratio: float,
    lower_wick_ratio: float = 0.0,
) -> float:
    """캔들품질 점수 (15점 만점) - 단순 선형
    
    v6.2.3: 양봉 + 아래꼬리 기반 단순 계산
    - 양봉: 7.5점
    - 아래꼬리(0~3%): 0~7.5점
    
    범위: (is_bullish * 0.5 + lower_wick * 0.5) * 15
    """
    # 양봉 점수: 양봉이면 0.5, 음봉이면 0
    bullish_score = 1.0 if is_bullish else 0.0
    
    # 아래꼬리 점수: 0~3%를 0~1로 정규화
    if lower_wick_ratio is None:
        lower_wick_ratio = 0.0
    lower_score = min(lower_wick_ratio / 3, 1.0)
    
    # 합산
    total = bullish_score * 0.5 + lower_score * 0.5
    return total * 15


# ============================================================
# v5 보너스 점수 계산 함수들
# ============================================================

def calc_cci_rising_bonus(cci_values: List[float]) -> Tuple[float, bool]:
    """CCI 상승 보너스 (4점)"""
    if not cci_values or len(cci_values) < 2:
        return 0.0, False
    
    is_rising = cci_values[-1] > cci_values[-2]
    
    if is_rising:
        # 상승폭에 따라 보너스 차등
        rise_amount = cci_values[-1] - cci_values[-2]
        if rise_amount > 20:
            return 4.0, True
        elif rise_amount > 10:
            return 3.5, True
        elif rise_amount > 5:
            return 3.0, True
        else:
            return 2.5, True
    else:
        # CCI 하락 시 감점 (0점, 하락 표시)
        return 0.0, False


def calc_ma20_3day_bonus(ma20_values: List[float]) -> Tuple[float, bool]:
    """MA20 3일 연속 상승 보너스 (3점)"""
    if not ma20_values or len(ma20_values) < 3:
        return 0.0, False
    
    recent_3 = ma20_values[-3:]
    is_3day_up = recent_3[2] > recent_3[1] > recent_3[0]
    
    if is_3day_up:
        return 3.0, True
    elif recent_3[2] > recent_3[1]:
        # 2일 상승
        return 1.5, False
    else:
        return 0.0, False


def calc_not_high_eq_close_bonus(
    high: int,
    close: int,
    is_bullish: bool,
) -> Tuple[float, bool]:
    """고가≠종가 보너스 (3점)
    
    고가=종가 (상한가형)는 다음날 하락 가능성 높음
    """
    is_high_eq_close = (high == close) and is_bullish
    
    if is_high_eq_close:
        # 고가=종가: 보너스 없음 (오히려 리스크)
        return 0.0, True
    else:
        return 3.0, False


# ============================================================
# v5 유틸리티 함수
# ============================================================

def count_consecutive_bullish(prices: List[DailyPrice]) -> int:
    """연속 양봉일 수 계산"""
    if not prices:
        return 0
    
    count = 0
    for price in reversed(prices):
        if price.is_bullish:
            count += 1
        else:
            break
    return count


def calculate_volume_ratio(prices: List[DailyPrice]) -> float:
    """거래량 비율 계산 (20일 평균 대비)"""
    if len(prices) < 20:
        return 1.0
    
    recent_20_volume = [p.volume for p in prices[-20:]]
    avg_volume = sum(recent_20_volume[:-1]) / 19  # 오늘 제외
    today_volume = prices[-1].volume
    
    if avg_volume == 0:
        return 1.0
    
    return today_volume / avg_volume


# ============================================================
# v5 메인 점수 계산기
# ============================================================

class ScoreCalculatorV5:
    """점수 계산기 v6.2.3 - 단순 선형 점수제 (100점 만점)"""
    
    def __init__(self, weights: Optional[Weights] = None):
        """
        Args:
            weights: v5에서는 사용하지 않음 (고정 가중치)
        """
        self.weights = weights  # 레거시 호환
    
    def calculate_single_score(
        self,
        stock: StockData,
    ) -> Optional[StockScoreV5]:
        """단일 종목 점수 계산 - v6.2.3 단순 선형
        
        100점 만점 = 핵심 90점 + 보너스 10점
        """
        from src.domain.indicators import calculate_cci, calculate_ma, calculate_rsi
        
        prices = stock.daily_prices
        if len(prices) < 20:
            logger.warning(f"데이터 부족: {stock.code} ({stock.name})")
            return None
        
        today = prices[-1]
        
        # ============================================================
        # 원시값 계산
        # ============================================================
        
        # CCI
        cci_values = calculate_cci(prices, period=14)
        cci = cci_values[-1] if cci_values else None
        
        # RSI (v6.5.1 추가)
        rsi_values = calculate_rsi(prices, period=14)
        rsi = rsi_values[-1] if rsi_values else None
        
        # MA20
        ma20_values = calculate_ma(prices, period=20)
        ma20 = ma20_values[-1] if ma20_values else None
        
        # 이격도
        distance = None
        if ma20 and ma20 > 0:
            distance = ((today.close - ma20) / ma20) * 100
        
        # MA20 위 여부
        is_above_ma20 = today.close > ma20 if ma20 else False
        
        # 등락률
        change_rate = stock.today_change_rate
        
        # 연속양봉
        consec_days = count_consecutive_bullish(prices)
        
        # 거래량비율
        volume_ratio = calculate_volume_ratio(prices)
        
        # 캔들 정보
        is_bullish = today.is_bullish
        upper_wick_ratio = today.upper_wick_ratio
        # v6.2.3: lower_wick_ratio 추가 (아래꼬리 / 종가 * 100)
        lower_wick_ratio = (today.lower_wick / today.close * 100) if today.close > 0 else 0.0
        
        # ============================================================
        # 핵심 점수 계산 (각 15점, 총 90점)
        # ============================================================
        
        cci_score = calc_cci_score(cci)
        change_score = calc_change_score(change_rate)
        distance_score = calc_distance_score(distance)
        consec_score = calc_consec_score(consec_days)
        volume_score = calc_volume_score(volume_ratio)
        candle_score = calc_candle_score(is_bullish, upper_wick_ratio, lower_wick_ratio)
        
        # ============================================================
        # 보너스 점수 계산 (총 10점)
        # ============================================================
        
        cci_rising_bonus, is_cci_rising = calc_cci_rising_bonus(cci_values)
        ma20_3day_bonus, is_ma20_3day_up = calc_ma20_3day_bonus(ma20_values)
        not_high_eq_close_bonus, is_high_eq_close = calc_not_high_eq_close_bonus(
            today.high, today.close, is_bullish
        )
        
        # ============================================================
        # 점수 상세 생성
        # ============================================================
        
        score_detail = ScoreDetailV5(
            # 핵심 점수
            cci_score=cci_score,
            change_score=change_score,
            distance_score=distance_score,
            consec_score=consec_score,
            volume_score=volume_score,
            candle_score=candle_score,
            # 보너스 점수
            cci_rising_bonus=cci_rising_bonus,
            ma20_3day_bonus=ma20_3day_bonus,
            not_high_eq_close_bonus=not_high_eq_close_bonus,
            # 원시값 (v5.1: 추가 필드)
            raw_cci=cci or 0.0,
            raw_change_rate=change_rate,
            raw_distance=distance or 0.0,
            raw_consec_days=consec_days,
            raw_volume_ratio=volume_ratio,
            raw_upper_wick_ratio=upper_wick_ratio,
            is_cci_rising=is_cci_rising,
            is_ma20_3day_up=is_ma20_3day_up,
            is_high_eq_close=is_high_eq_close,
            # v5.1 추가
            raw_ma20=ma20 or 0.0,
            is_above_ma20=is_above_ma20,
            is_bullish=is_bullish,
            # v6.5.1 추가
            raw_rsi=rsi or 0.0,
        )
        
        return StockScoreV5(
            stock_code=stock.code,
            stock_name=stock.name,
            current_price=stock.current_price,
            change_rate=change_rate,
            trading_value=stock.trading_value,
            score_detail=score_detail,
            score_total=score_detail.total,
            market_cap=getattr(stock, 'market_cap', 0.0),  # v6.5: 시총 전달
            volume=today.volume if today else 0,  # v6.5: 거래량 전달
        )
    
    def calculate_scores(
        self,
        stocks: List[StockData],
    ) -> List[StockScoreV5]:
        """여러 종목 점수 계산"""
        scores = []
        for stock in stocks:
            score = self.calculate_single_score(stock)
            if score:
                scores.append(score)
        
        # 점수 높은 순 정렬
        scores.sort(key=lambda x: (-x.score_total, -x.trading_value))
        
        # 순위 부여
        for i, score in enumerate(scores, 1):
            score.rank = i
        
        logger.info(f"점수 계산 완료: {len(scores)}개 종목")
        return scores
    
    def select_top_n(
        self,
        scores: List[StockScoreV5],
        n: int = TOP_N_COUNT,
    ) -> List[StockScoreV5]:
        """TOP N 종목 선정"""
        return scores[:n]
    
    def _determine_grade(self, score: float) -> StockGrade:
        """점수에 따른 등급 결정"""
        return get_grade(score)
    
    def _get_sell_strategy(self, grade: StockGrade) -> SellStrategy:
        """등급에 따른 매도 전략 반환"""
        return SELL_STRATEGIES[grade]


# ============================================================
# 디스플레이 포매터 (v6.2.3)
# ============================================================

def format_score_display(score: StockScoreV5, rank: int = None) -> str:
    """점수 디스플레이 포맷팅 (Discord/터미널용) - v6.2.3"""
    d = score.score_detail
    s = score.sell_strategy
    
    rank_str = f"#{rank} " if rank else ""
    
    # 등급 이모지
    grade_emoji = {
        StockGrade.S: "🏆",
        StockGrade.A: "🥇",
        StockGrade.B: "🥈",
        StockGrade.C: "🥉",
        StockGrade.D: "⚠️",
    }
    
    # 보너스 체크마크
    cci_check = "✅" if d.is_cci_rising else "❌"
    ma20_check = "✅" if d.is_ma20_3day_up else "❌"
    candle_check = "❌" if d.is_high_eq_close else "✅"
    
    lines = [
        f"{rank_str}**{score.stock_name}** ({score.stock_code})",
        f"├ 현재가: {score.current_price:,}원 ({score.change_rate:+.2f}%)",
        f"├ 거래대금: {score.trading_value:.0f}억",
        f"├ 총점: **{score.score_total:.1f}점** {grade_emoji[score.grade]} {score.grade.value}등급",
        f"│",
        f"├ 📊 핵심지표 (90점)",
        f"│  ├ CCI({d.raw_cci:.0f}): {d.cci_score:.1f}/15",
        f"│  ├ 등락률({d.raw_change_rate:.1f}%): {d.change_score:.1f}/15",
        f"│  ├ 이격도({d.raw_distance:.1f}%): {d.distance_score:.1f}/15",
        f"│  ├ 연속양봉({d.raw_consec_days}일): {d.consec_score:.1f}/15",
        f"│  ├ 거래량비({d.raw_volume_ratio:.1f}x): {d.volume_score:.1f}/15",
        f"│  └ 캔들품질: {d.candle_score:.1f}/15",
        f"│",
        f"├ 🎁 보너스 (10점)",
        f"│  ├ CCI상승 {cci_check}: {d.cci_rising_bonus:.1f}/4",
        f"│  ├ MA20 3일↑ {ma20_check}: {d.ma20_3day_bonus:.1f}/3",
        f"│  └ 고가≠종가 {candle_check}: {d.not_high_eq_close_bonus:.1f}/3",
        f"│",
        f"└ 📈 매도전략 ({s.confidence})",
        f"   ├ 시초가 {s.open_sell_ratio}% 매도",
        f"   ├ 목표가 +{s.target_profit}% ({s.target_sell_ratio}%)",
        f"   └ 손절가 {s.stop_loss}%",
    ]
    
    return "\n".join(lines)


def format_simple_display(score: StockScoreV5, rank: int = None) -> str:
    """간단한 디스플레이 포맷팅"""
    d = score.score_detail
    s = score.sell_strategy
    
    rank_str = f"#{rank} " if rank else ""
    
    grade_emoji = {
        StockGrade.S: "🏆S",
        StockGrade.A: "🥇A",
        StockGrade.B: "🥈B",
        StockGrade.C: "🥉C",
        StockGrade.D: "⚠️D",
    }
    
    return (
        f"{rank_str}{score.stock_name} ({score.stock_code}) | "
        f"{score.score_total:.1f}점 {grade_emoji[score.grade]} | "
        f"{score.current_price:,}원 ({score.change_rate:+.1f}%) | "
        f"시초{s.open_sell_ratio}% 목표+{s.target_profit}%"
    )


def format_discord_embed(
    scores: List[StockScoreV5], 
    title: str = "종가매매 TOP5",
    leading_sectors_text: str = None,
) -> dict:
    """Discord Embed 포맷 - v6.3 주도섹터 표시"""
    
    grade_emoji = {
        StockGrade.S: "🏆",
        StockGrade.A: "🥇",
        StockGrade.B: "🥈",
        StockGrade.C: "🥉",
        StockGrade.D: "⚠️",
    }
    
    fields = []
    
    # v6.3: 주도섹터 정보 (맨 위에 표시)
    if leading_sectors_text:
        fields.append({
            "name": "📈 오늘의 주도섹터",
            "value": leading_sectors_text,
            "inline": False,
        })
    
    for i, score in enumerate(scores[:5], 1):
        d = score.score_detail
        s = score.sell_strategy
        
        # v6.3: 섹터 정보
        sector = getattr(score, '_sector', '')
        is_leading = getattr(score, '_is_leading_sector', False)
        sector_rank = getattr(score, '_sector_rank', 99)
        
        sector_badge = ""
        if sector:
            if is_leading:
                sector_badge = f"🔥 {sector} (#{sector_rank})"
            else:
                sector_badge = f"📁 {sector}"
        
        # 보너스 상태
        bonus_icons = []
        if d.is_cci_rising:
            bonus_icons.append("CCI↑")
        if d.is_ma20_3day_up:
            bonus_icons.append("MA20↑")
        if not d.is_high_eq_close:
            bonus_icons.append("캔들✓")
        bonus_str = " ".join(bonus_icons) if bonus_icons else "-"
        
        # v6.3: 섹터 정보 추가
        field_value = (
            f"**{score.score_total:.1f}점** {grade_emoji[score.grade]}{score.grade.value}"
        )
        if sector_badge:
            field_value += f" | {sector_badge}"
        field_value += (
            f"\n현재가: {score.current_price:,}원 ({score.change_rate:+.1f}%)\n"
            f"거래대금: {score.trading_value:.0f}억\n"
            f"━━━━━━━━━━\n"
            f"📊 **핵심지표**\n"
            f"CCI: **{d.raw_cci:.0f}** | 이격도: {d.raw_distance:.1f}%\n"
            f"거래량: {d.raw_volume_ratio:.1f}배 | 연속: {d.raw_consec_days}일\n"
            f"━━━━━━━━━━\n"
            f"🎁 보너스: {bonus_str}\n"
            f"📈 **매도전략**\n"
            f"시초가 {s.open_sell_ratio}% / 목표 +{s.target_profit}%\n"
            f"손절 {s.stop_loss}%"
        )
        
        fields.append({
            "name": f"#{i} {score.stock_name} ({score.stock_code})",
            "value": field_value,
            "inline": False,
        })
    
    # 등급 설명
    legend = (
        "```\n"
        "🏆S(85+): 시초30% + 목표+4% (손절-3%)\n"
        "🥇A(75-84): 시초40% + 목표+3% (손절-2.5%)\n"
        "🥈B(65-74): 시초50% + 목표+2.5% (손절-2%)\n"
        "🥉C(55-64): 시초70% + 목표+2% (손절-1.5%)\n"
        "⚠️D(<55): 시초 전량매도 권장 (손절-1%)\n"
        "```"
    )
    
    fields.append({
        "name": "📋 등급별 매도전략",
        "value": legend,
        "inline": False,
    })
    
    return {
        "title": f"🔔 {title}",
        "color": 3066993,  # 녹색
        "fields": fields,
        "footer": {
            "text": "v6.3 | 단순 선형 점수제 + 주도섹터 | 100점 만점"
        }
    }


# ============================================================
# 호환성을 위한 별칭
# ============================================================

ScoreCalculator = ScoreCalculatorV5


def calculate_scores(
    stocks: List[StockData],
    weights: Optional[Weights] = None,
) -> List[StockScore]:
    """레거시 호환 함수 - StockScore 반환"""
    calculator = ScoreCalculatorV5(weights)
    v5_scores = calculator.calculate_scores(stocks)
    return [s.to_legacy_score() for s in v5_scores]


def calculate_scores_v5(
    stocks: List[StockData],
) -> List[StockScoreV5]:
    """v5 점수 계산 함수"""
    calculator = ScoreCalculatorV5()
    return calculator.calculate_scores(stocks)


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 60)
    print("v6.2.3 점수 계산기 테스트")
    print("=" * 60)
    
    print("\n[CCI 점수 테스트] (15점 만점) - v6.2.3 단순 선형")
    for cci in [50, 100, 140, 160, 170, 180, 200, 250, 300]:
        score = calc_cci_score(cci)
        bar = "█" * int(score)
        opt = " ★최적" if 160 <= cci <= 180 else ""
        print(f"  CCI {cci:3d}: {score:5.1f}점 {bar}{opt}")
    
    print("\n[등락률 점수 테스트] (15점 만점)")
    for change in [-3, 0, 1, 2, 5, 8, 10, 15, 20]:
        score = calc_change_score(change)
        bar = "█" * int(score)
        print(f"  등락률 {change:3d}%: {score:5.1f}점 {bar}")
    
    print("\n[이격도 점수 테스트] (15점 만점)")
    for dist in [-5, -2, 0, 2, 5, 8, 10, 15, 20]:
        score = calc_distance_score(dist)
        bar = "█" * int(score)
        print(f"  이격도 {dist:3d}%: {score:5.1f}점 {bar}")
    
    print("\n[연속양봉 점수 테스트] (15점 만점) - v6.2.3 단순 선형")
    for days in [0, 1, 2, 3, 4, 5, 6, 7, 10]:
        score = calc_consec_score(days)
        bar = "█" * int(score)
        warn = " ⚠️위험" if days >= 5 else ""
        print(f"  연속 {days:2d}일: {score:5.1f}점 {bar}{warn}")
    
    print("\n[거래량비율 점수 테스트] (15점 만점)")
    for ratio in [0.3, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 8.0, 12.0]:
        score = calc_volume_score(ratio)
        bar = "█" * int(score)
        print(f"  거래량 {ratio:4.1f}x: {score:5.1f}점 {bar}")
    
    print("\n[등급별 매도전략]")
    for grade, strategy in SELL_STRATEGIES.items():
        print(f"\n  {grade.value}등급: {strategy.description}")
        print(f"    - 시초가 매도: {strategy.open_sell_ratio}%")
        print(f"    - 목표가 매도: {strategy.target_sell_ratio}% (목표 +{strategy.target_profit}%)")
        print(f"    - 손절가: {strategy.stop_loss}%")
        print(f"    - 신뢰도: {strategy.confidence}")
