"""
점수 산출기 v5.0 - 소프트 필터 방식 (점수제)

📊 그리드 서치 최적 조건 = 100점 만점 기준
===========================================
🏆 최고 승률 조합 (60.15%):
  - CCI: 160~180 → 최적 구간 만점
  - 등락률: 2~8% → 최적 구간 만점
  - 연속양봉: ≤4일 → 최적 구간 만점
  - 이격도: 2~8% → 최적 구간 만점
  - 거래량비율: ≥1.0배 → 최적 구간 만점
  - CCI 상승중 → 보너스 점수
  - MA20 3일 상승 → 보너스 점수
  - 고가≠종가 → 보너스 점수

🎯 점수 체계 (100점 만점):
  - 핵심 6개 지표: 각 15점 (총 90점)
  - 보너스 조건 3개: 각 3~4점 (총 10점)
  
📈 등급 및 매도 전략:
  - S등급 (85+): 시초가 100% 매도 or 목표가 +3%
  - A등급 (75-84): 시초가 50% + 목표가 +2.5% 50%
  - B등급 (65-74): 시초가 30% + 목표가 +2% 70%
  - C등급 (55-64): 목표가 +1.5% 100%
  - D등급 (55미만): 시초가 손절 고려
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
    
    # 원시값 (디버깅용)
    raw_cci: float = 0.0
    raw_change_rate: float = 0.0
    raw_distance: float = 0.0
    raw_consec_days: int = 0
    raw_volume_ratio: float = 0.0
    raw_upper_wick_ratio: float = 0.0
    is_cci_rising: bool = False
    is_ma20_3day_up: bool = False
    is_high_eq_close: bool = False
    
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
    
    @property
    def grade(self) -> StockGrade:
        return self.score_detail.grade
    
    @property
    def sell_strategy(self) -> SellStrategy:
        return self.score_detail.sell_strategy
    
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
# v5 점수 계산 함수들 (각 15점 만점)
# ============================================================

def calc_cci_score(cci: float) -> float:
    """CCI 점수 (15점 만점)
    
    최적: 160~180 → 15점
    양호: 140~200 → 10~14점
    보통: 100~140, 200~250 → 5~10점
    위험: 그 외 → 0~5점
    """
    if cci is None:
        return 7.5  # 중간값
    
    # 최적 구간 (160~180)
    if 160 <= cci <= 180:
        # 170에 가까울수록 높은 점수
        distance_to_170 = abs(cci - 170)
        return 15.0 - (distance_to_170 / 10) * 1.0  # 15~14점
    
    # 양호 구간 (140~160, 180~200)
    elif 140 <= cci < 160:
        return 10.0 + ((cci - 140) / 20) * 4.0  # 10~14점
    elif 180 < cci <= 200:
        return 14.0 - ((cci - 180) / 20) * 4.0  # 14~10점
    
    # 보통 구간 (100~140, 200~250)
    elif 100 <= cci < 140:
        return 5.0 + ((cci - 100) / 40) * 5.0  # 5~10점
    elif 200 < cci <= 250:
        return 10.0 - ((cci - 200) / 50) * 5.0  # 10~5점
    
    # 위험 구간
    elif cci > 250:
        # 과열: 250 이상은 급격히 감점
        if cci > 350:
            return 0.0
        return 5.0 - ((cci - 250) / 100) * 5.0  # 5~0점
    else:
        # 모멘텀 부족: 100 미만
        if cci < 0:
            return 2.0
        return 2.0 + (cci / 100) * 3.0  # 2~5점


def calc_change_score(change_rate: float) -> float:
    """등락률 점수 (15점 만점)
    
    최적: 2~8% → 15점
    양호: 1~2%, 8~10% → 10~14점
    보통: 0~1%, 10~15% → 5~10점
    위험: 15%+ 또는 음수 → 0~5점
    """
    if change_rate is None:
        return 7.5
    
    # 음수 (하락)
    if change_rate < 0:
        if change_rate < -5:
            return 0.0
        return 3.0 + (change_rate + 5) * 0.6  # 0~3점
    
    # 최적 구간 (2~8%)
    if 2.0 <= change_rate <= 8.0:
        # 5%에 가까울수록 높은 점수
        distance_to_5 = abs(change_rate - 5)
        return 15.0 - (distance_to_5 / 3) * 1.0  # 15~14점
    
    # 양호 구간
    elif 1.0 <= change_rate < 2.0:
        return 10.0 + (change_rate - 1.0) * 4.0  # 10~14점
    elif 8.0 < change_rate <= 10.0:
        return 14.0 - ((change_rate - 8.0) / 2) * 4.0  # 14~10점
    
    # 보통 구간
    elif 0 <= change_rate < 1.0:
        return 5.0 + change_rate * 5.0  # 5~10점
    elif 10.0 < change_rate <= 15.0:
        return 10.0 - ((change_rate - 10.0) / 5) * 5.0  # 10~5점
    
    # 위험 구간 (15%+)
    else:
        if change_rate >= 25:
            return 0.0
        return 5.0 - ((change_rate - 15) / 10) * 5.0  # 5~0점


def calc_distance_score(distance: float) -> float:
    """이격도 점수 (15점 만점)
    
    최적: 2~8% → 15점
    양호: 0~2%, 8~10% → 10~14점
    보통: -2~0%, 10~15% → 5~10점
    위험: -2% 미만, 15%+ → 0~5점
    """
    if distance is None:
        return 7.5
    
    # 최적 구간 (2~8%)
    if 2.0 <= distance <= 8.0:
        distance_to_5 = abs(distance - 5)
        return 15.0 - (distance_to_5 / 3) * 1.0  # 15~14점
    
    # 양호 구간
    elif 0 <= distance < 2.0:
        return 10.0 + (distance / 2) * 4.0  # 10~14점
    elif 8.0 < distance <= 10.0:
        return 14.0 - ((distance - 8.0) / 2) * 4.0  # 14~10점
    
    # 보통 구간
    elif -2.0 <= distance < 0:
        return 5.0 + ((distance + 2) / 2) * 5.0  # 5~10점
    elif 10.0 < distance <= 15.0:
        return 10.0 - ((distance - 10) / 5) * 5.0  # 10~5점
    
    # 위험 구간
    elif distance < -2.0:
        if distance < -10:
            return 0.0
        return 5.0 + ((distance + 10) / 8) * 5.0  # 0~5점
    else:  # 15%+
        if distance >= 25:
            return 0.0
        return 5.0 - ((distance - 15) / 10) * 5.0  # 5~0점


def calc_consec_score(consec_days: int) -> float:
    """연속양봉 점수 (15점 만점)
    
    최적: 2~3일 → 15점
    양호: 1일, 4일 → 12~14점
    보통: 0일(음봉), 5일 → 8~11점
    위험: 6일+ → 0~7점
    """
    score_map = {
        0: 8.0,   # 오늘 음봉
        1: 12.0,  # 1일차
        2: 15.0,  # 2일차 (최적!)
        3: 15.0,  # 3일차 (최적!)
        4: 12.0,  # 4일차
        5: 8.0,   # 5일차 (주의)
        6: 5.0,   # 6일차
        7: 3.0,   # 7일차
    }
    
    if consec_days in score_map:
        return score_map[consec_days]
    elif consec_days > 7:
        return max(0.0, 3.0 - (consec_days - 7))  # 7일 이후 급감
    else:
        return 8.0  # 기본값


def calc_volume_score(volume_ratio: float) -> float:
    """거래량비율 점수 (15점 만점)
    
    최적: 1.5~3.0배 → 15점
    양호: 1.0~1.5배, 3.0~5.0배 → 10~14점
    보통: 0.5~1.0배, 5.0~8.0배 → 5~10점
    위험: 0.5배 미만, 8배+ → 0~5점
    """
    if volume_ratio is None:
        return 7.5
    
    # 최적 구간 (1.5~3.0배)
    if 1.5 <= volume_ratio <= 3.0:
        # 2.0배에 가까울수록 높은 점수
        distance_to_2 = abs(volume_ratio - 2.0)
        return 15.0 - (distance_to_2 / 1.0) * 1.0  # 15~14점
    
    # 양호 구간
    elif 1.0 <= volume_ratio < 1.5:
        return 10.0 + ((volume_ratio - 1.0) / 0.5) * 4.0  # 10~14점
    elif 3.0 < volume_ratio <= 5.0:
        return 14.0 - ((volume_ratio - 3.0) / 2.0) * 4.0  # 14~10점
    
    # 보통 구간
    elif 0.5 <= volume_ratio < 1.0:
        return 5.0 + ((volume_ratio - 0.5) / 0.5) * 5.0  # 5~10점
    elif 5.0 < volume_ratio <= 8.0:
        return 10.0 - ((volume_ratio - 5.0) / 3.0) * 5.0  # 10~5점
    
    # 위험 구간
    elif volume_ratio < 0.5:
        return volume_ratio * 10.0  # 0~5점
    else:  # 8배+
        if volume_ratio >= 15:
            return 0.0
        return 5.0 - ((volume_ratio - 8) / 7) * 5.0  # 5~0점


def calc_candle_score(
    is_bullish: bool,
    upper_wick_ratio: float,
) -> float:
    """캔들품질 점수 (15점 만점)
    
    양봉 + 윗꼬리 짧음 → 15점
    음봉은 최대 7점
    """
    if not is_bullish:
        # 음봉: 윗꼬리 비율에 따라 차등
        if upper_wick_ratio <= 0.3:
            return 7.0
        elif upper_wick_ratio <= 0.5:
            return 5.0
        else:
            return 3.0
    
    # 양봉: 윗꼬리 비율에 따라
    if upper_wick_ratio <= 0.1:
        return 15.0  # 최상
    elif upper_wick_ratio <= 0.2:
        return 14.0
    elif upper_wick_ratio <= 0.3:
        return 12.0
    elif upper_wick_ratio <= 0.5:
        return 10.0
    elif upper_wick_ratio <= 0.7:
        return 8.0
    else:
        return 6.0


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
    """점수 계산기 v5 - 소프트 필터 방식 (100점 만점)"""
    
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
        """단일 종목 점수 계산 - v5
        
        100점 만점 = 핵심 90점 + 보너스 10점
        """
        from src.domain.indicators import calculate_cci, calculate_ma
        
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
        
        # MA20
        ma20_values = calculate_ma(prices, period=20)
        ma20 = ma20_values[-1] if ma20_values else None
        
        # 이격도
        distance = None
        if ma20 and ma20 > 0:
            distance = ((today.close - ma20) / ma20) * 100
        
        # 등락률
        change_rate = stock.today_change_rate
        
        # 연속양봉
        consec_days = count_consecutive_bullish(prices)
        
        # 거래량비율
        volume_ratio = calculate_volume_ratio(prices)
        
        # 캔들 정보
        is_bullish = today.is_bullish
        upper_wick_ratio = today.upper_wick_ratio
        
        # ============================================================
        # 핵심 점수 계산 (각 15점, 총 90점)
        # ============================================================
        
        cci_score = calc_cci_score(cci)
        change_score = calc_change_score(change_rate)
        distance_score = calc_distance_score(distance)
        consec_score = calc_consec_score(consec_days)
        volume_score = calc_volume_score(volume_ratio)
        candle_score = calc_candle_score(is_bullish, upper_wick_ratio)
        
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
            # 원시값
            raw_cci=cci or 0.0,
            raw_change_rate=change_rate,
            raw_distance=distance or 0.0,
            raw_consec_days=consec_days,
            raw_volume_ratio=volume_ratio,
            raw_upper_wick_ratio=upper_wick_ratio,
            is_cci_rising=is_cci_rising,
            is_ma20_3day_up=is_ma20_3day_up,
            is_high_eq_close=is_high_eq_close,
        )
        
        return StockScoreV5(
            stock_code=stock.code,
            stock_name=stock.name,
            current_price=stock.current_price,
            change_rate=change_rate,
            trading_value=stock.trading_value,
            score_detail=score_detail,
            score_total=score_detail.total,
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


# ============================================================
# 디스플레이 포매터
# ============================================================

def format_score_display(score: StockScoreV5, rank: int = None) -> str:
    """점수 디스플레이 포맷팅 (Discord/터미널용)"""
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


def format_discord_embed(scores: List[StockScoreV5], title: str = "종가매매 TOP5") -> dict:
    """Discord Embed 포맷"""
    
    grade_emoji = {
        StockGrade.S: "🏆",
        StockGrade.A: "🥇",
        StockGrade.B: "🥈",
        StockGrade.C: "🥉",
        StockGrade.D: "⚠️",
    }
    
    fields = []
    for i, score in enumerate(scores[:5], 1):
        d = score.score_detail
        s = score.sell_strategy
        
        # 보너스 상태
        bonus_icons = []
        if d.is_cci_rising:
            bonus_icons.append("CCI↑")
        if d.is_ma20_3day_up:
            bonus_icons.append("MA20↑")
        if not d.is_high_eq_close:
            bonus_icons.append("캔들✓")
        bonus_str = " ".join(bonus_icons) if bonus_icons else "-"
        
        field_value = (
            f"**{score.score_total:.1f}점** {grade_emoji[score.grade]}{score.grade.value}\n"
            f"현재가: {score.current_price:,}원 ({score.change_rate:+.1f}%)\n"
            f"거래대금: {score.trading_value:.0f}억\n"
            f"보너스: {bonus_str}\n"
            f"━━━━━━━━━━\n"
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
            "text": "v5.0 | 그리드서치 최적 조건 기반 | 100점 만점"
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
    print("v5 점수 계산기 테스트")
    print("=" * 60)
    
    print("\n[CCI 점수 테스트] (15점 만점)")
    for cci in [50, 100, 140, 160, 170, 180, 200, 250, 300]:
        score = calc_cci_score(cci)
        bar = "█" * int(score)
        print(f"  CCI {cci:3d}: {score:5.1f}점 {bar}")
    
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
    
    print("\n[연속양봉 점수 테스트] (15점 만점)")
    for days in [0, 1, 2, 3, 4, 5, 6, 7, 10]:
        score = calc_consec_score(days)
        bar = "█" * int(score)
        print(f"  연속 {days:2d}일: {score:5.1f}점 {bar}")
    
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
