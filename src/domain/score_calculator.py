"""
점수 산출기 v4.0 - 그리드 서치 최적화 반영

📊 그리드 서치 결과 (2024년 백테스트 기반)
===========================================
🏆 최고 승률 조합 (60.15%):
  - CCI: 160~180
  - 등락률: 2~8%
  - 연속양봉: ≤4일
  - 거래대금: ≥200억
  - 이격도: 2~8%
  - 거래량: ≥1.0배
  - CCI 상승중
  - MA20 3일 연속 상승
  - 고가≠종가

🛡️ 안정적 조합 (56.55%, 9054건):
  - CCI: 100~200
  - 연속양봉: ≤5일
  - 거래대금: ≥200억
  - 이격도: 2~8%
  - 거래량: ≥1.0배
  - CCI 상승중
  - MA20 3일 상승
  - 고가≠종가

위험 신호 (대화 분석):
- 이격도 8% 이상: 위험
- CCI 180 이상: 과열 시작
- 연속 5일+ 양봉: 급락 위험
- 등락률 15% 이상: 추격 위험
- 거래량 500%+ 폭발: 고점 가능성
"""

import logging
from typing import List, Optional

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
# v4 최적 상수 (그리드 서치 결과)
# ============================================================

# CCI 최적 구간
CCI_OPTIMAL_MIN = 160
CCI_OPTIMAL_MAX = 180
CCI_GOOD_MIN = 100
CCI_GOOD_MAX = 200
CCI_DANGER = 180  # 이 이상은 과열 시작

# 이격도 최적 구간 (MA20 대비 %)
DISTANCE_OPTIMAL_MIN = 2.0
DISTANCE_OPTIMAL_MAX = 8.0
DISTANCE_DANGER = 8.0  # 이 이상은 위험

# 등락률 최적 구간
CHANGE_OPTIMAL_MIN = 2.0
CHANGE_OPTIMAL_MAX = 8.0
CHANGE_DANGER = 15.0  # 이 이상은 추격 위험

# 연속 양봉
CONSEC_OPTIMAL_MAX = 4
CONSEC_DANGER = 5  # 5일 이상은 급락 위험

# 거래량 비율 (전일 대비)
VOLUME_RATIO_MIN = 1.0
VOLUME_RATIO_DANGER = 5.0  # 500% 이상은 고점 가능성


def calculate_cci_score(cci: float, cci_rising: bool = False) -> float:
    """CCI 점수 계산 - v4
    
    최적: 160~180 (10점)
    양호: 100~200 (6~9점)
    위험: 180+ (감점 시작)
    
    Args:
        cci: CCI 값
        cci_rising: CCI 상승 중 여부
        
    Returns:
        점수 (0~10)
    """
    # 기본 점수 (CCI 값 기반)
    if CCI_OPTIMAL_MIN <= cci <= CCI_OPTIMAL_MAX:
        # 160~180: 최적 구간
        # 170에 가까울수록 높은 점수
        distance_to_170 = abs(cci - 170)
        base_score = 10.0 - (distance_to_170 / 10) * 0.5
    elif CCI_GOOD_MIN <= cci < CCI_OPTIMAL_MIN:
        # 100~160: 양호하지만 최적 아님
        base_score = 6.0 + ((cci - CCI_GOOD_MIN) / (CCI_OPTIMAL_MIN - CCI_GOOD_MIN)) * 2.5
    elif CCI_OPTIMAL_MAX < cci <= CCI_GOOD_MAX:
        # 180~200: 과열 시작
        overheat = (cci - CCI_OPTIMAL_MAX) / (CCI_GOOD_MAX - CCI_OPTIMAL_MAX)
        base_score = 8.5 - overheat * 2.5
    elif cci > CCI_GOOD_MAX:
        # 200+: 과열 위험
        if cci > 300:
            base_score = 1.0
        elif cci > 250:
            base_score = 2.0
        else:
            base_score = 4.0 - ((cci - 200) / 50) * 2
    else:
        # 100 미만: 모멘텀 부족
        if cci < 0:
            base_score = 2.0
        else:
            base_score = 3.0 + (cci / 100) * 2
    
    # CCI 상승 중 보너스 (+1점, 최대 10점)
    if cci_rising and base_score < 10:
        base_score = min(10.0, base_score + 1.0)
    
    return max(SCORE_MIN, min(SCORE_MAX, base_score))


def calculate_distance_score(ma20_position: float) -> float:
    """MA20 이격도 점수 - v4
    
    최적: 2~8% (10점)
    위험: 8%+ (급감점)
    
    Args:
        ma20_position: MA20 대비 위치 (%)
        
    Returns:
        점수 (0~10)
    """
    if ma20_position < 0:
        # MA20 아래: 추세 이탈
        if ma20_position < -5:
            return 1.0
        elif ma20_position < -2:
            return 3.0
        else:
            return 5.0
    
    if DISTANCE_OPTIMAL_MIN <= ma20_position <= DISTANCE_OPTIMAL_MAX:
        # 2~8%: 최적 구간
        # 5%에 가까울수록 높은 점수 (중앙값)
        distance_to_optimal = abs(ma20_position - 5)
        return 10.0 - (distance_to_optimal / 3) * 0.5
    elif ma20_position < DISTANCE_OPTIMAL_MIN:
        # 0~2%: MA20 바로 위 (괜찮지만 최적 아님)
        return 7.0 + ma20_position
    else:
        # 8%+: 위험 구간 (급감점!)
        overheat = ma20_position - DISTANCE_DANGER
        if overheat > 10:
            return 1.0
        elif overheat > 5:
            return 2.0
        else:
            return max(1.0, 6.0 - overheat * 1.0)


def calculate_change_score(change_rate: float) -> float:
    """등락률 점수 - v4
    
    최적: 2~8% (10점)
    위험: 15%+ (추격 위험)
    
    Args:
        change_rate: 당일 등락률 (%)
        
    Returns:
        점수 (0~10)
    """
    if change_rate < 0:
        # 하락: 모멘텀 부족
        if change_rate < -5:
            return 2.0
        else:
            return 4.0
    
    if CHANGE_OPTIMAL_MIN <= change_rate <= CHANGE_OPTIMAL_MAX:
        # 2~8%: 최적 구간
        # 5%에 가까울수록 높은 점수
        distance_to_optimal = abs(change_rate - 5)
        return 10.0 - (distance_to_optimal / 3) * 0.5
    elif change_rate < CHANGE_OPTIMAL_MIN:
        # 0~2%: 약한 상승 (괜찮음)
        return 7.0 + change_rate * 1.5
    elif change_rate <= 10:
        # 8~10%: 조금 높음
        return 8.0 - (change_rate - 8) * 0.5
    elif change_rate <= CHANGE_DANGER:
        # 10~15%: 주의
        return 6.0 - (change_rate - 10) * 0.4
    else:
        # 15%+: 추격 위험!
        if change_rate >= 25:
            return 1.0
        else:
            return max(1.0, 4.0 - (change_rate - 15) * 0.3)


def calculate_consec_score(consec_days: int) -> float:
    """연속 양봉일 점수 - v4
    
    최적: 1~4일 (8~10점)
    위험: 5일+ (급락 위험)
    
    Args:
        consec_days: 연속 양봉일 수
        
    Returns:
        점수 (0~10)
    """
    if consec_days == 0:
        # 오늘 음봉: 감점
        return 4.0
    elif consec_days == 1:
        return 9.0
    elif consec_days == 2:
        return 10.0  # 2일 연속이 최적
    elif consec_days == 3:
        return 9.5
    elif consec_days == 4:
        return 8.0
    elif consec_days == 5:
        # 5일차: 위험 시작
        return 5.0
    elif consec_days == 6:
        return 3.0
    elif consec_days == 7:
        return 2.0
    else:
        # 7일+: 고점 확률 높음
        return 1.0


def calculate_candle_quality_score(
    is_bullish: bool,
    upper_wick_ratio: float,
    high_eq_close: bool,
) -> float:
    """캔들 품질 점수 - v4
    
    양봉 + 윗꼬리 짧음 + 고가≠종가 = 최적
    
    Args:
        is_bullish: 양봉 여부
        upper_wick_ratio: 윗꼬리 비율
        high_eq_close: 고가=종가 여부 (상한가형)
        
    Returns:
        점수 (0~10)
    """
    if not is_bullish:
        return 3.0
    
    # 윗꼬리 점수
    if upper_wick_ratio <= 0.1:
        wick_score = 10.0
    elif upper_wick_ratio <= 0.2:
        wick_score = 9.0
    elif upper_wick_ratio <= 0.3:
        wick_score = 7.5
    elif upper_wick_ratio <= 0.5:
        wick_score = 5.0
    else:
        wick_score = 3.0
    
    # 고가=종가 감점 (그리드 서치에서 고가≠종가가 더 좋음)
    if high_eq_close:
        wick_score = max(1.0, wick_score - 2.0)
    
    return wick_score


def calculate_volume_ratio_score(volume_ratio: float) -> float:
    """거래량 비율 점수 - v4
    
    최적: 1.5~3배 (10점)
    위험: 5배+ (고점 가능성)
    
    Args:
        volume_ratio: 전일 대비 거래량 비율
        
    Returns:
        점수 (0~10)
    """
    if volume_ratio < 1.0:
        # 거래량 감소: 관심 부족
        return 5.0 + volume_ratio * 2
    elif 1.0 <= volume_ratio < 1.5:
        return 8.0
    elif 1.5 <= volume_ratio < 2.0:
        return 10.0  # 최적
    elif 2.0 <= volume_ratio < 3.0:
        return 9.5
    elif 3.0 <= volume_ratio < 5.0:
        return 8.0
    else:
        # 5배+: 고점 가능성
        if volume_ratio >= 10:
            return 3.0
        else:
            return max(3.0, 7.0 - (volume_ratio - 5) * 0.8)


def calculate_ma20_trend_score(ma20_values: List[float]) -> float:
    """MA20 추세 점수 - v4
    
    3일 연속 상승 = 만점
    
    Args:
        ma20_values: MA20 값 리스트
        
    Returns:
        점수 (0~10)
    """
    if not ma20_values or len(ma20_values) < 3:
        return 5.0
    
    recent = ma20_values[-3:]
    
    # 3일 연속 상승 체크
    is_3day_rising = all(recent[i] > recent[i-1] for i in range(1, len(recent)))
    
    if is_3day_rising:
        return 10.0
    
    # 2일 상승
    if recent[-1] > recent[-2]:
        if recent[-2] > recent[-3]:
            return 10.0  # 3일 연속
        else:
            return 8.0  # 최근 2일 상승
    else:
        # 하락
        if recent[-2] > recent[-3]:
            return 5.0  # 어제까지 상승, 오늘 꺾임
        else:
            return 3.0  # 연속 하락


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


class ScoreCalculatorV4:
    """점수 계산기 v4 - 그리드 서치 최적화"""
    
    def __init__(self, weights: Optional[Weights] = None):
        """
        Args:
            weights: 점수 가중치 (v4에서는 기본 1.0 사용)
        """
        # v4 기본 가중치 (균등 배분)
        self.weights = weights or Weights(
            cci_value=1.0,
            cci_slope=1.0,  # CCI 추세 대신 이격도 사용
            ma20_slope=1.0,
            candle=1.0,
            change=1.0,
        )
    
    def calculate_single_score(
        self,
        stock: StockData,
    ) -> Optional[StockScore]:
        """단일 종목 점수 계산 - v4
        
        6가지 핵심 지표:
        1. CCI 값 + 상승 여부
        2. 이격도 (MA20 대비)
        3. 등락률
        4. 연속 양봉일
        5. 캔들 품질
        6. MA20 추세
        
        Args:
            stock: 종목 데이터
            
        Returns:
            종목 점수 또는 None
        """
        indicators = calculate_all_indicators(stock.daily_prices)
        if indicators is None:
            logger.warning(f"지표 계산 불가: {stock.code} ({stock.name})")
            return None
        
        # 추가 계산
        consec_days = count_consecutive_bullish(stock.daily_prices)
        volume_ratio = calculate_volume_ratio(stock.daily_prices)
        
        # CCI 상승 여부
        cci_rising = False
        if len(indicators.cci_values) >= 2:
            cci_rising = indicators.cci_values[-1] > indicators.cci_values[-2]
        
        # 고가=종가 여부
        today = stock.daily_prices[-1]
        high_eq_close = (today.high == today.close) and today.is_bullish
        
        # 6가지 점수 계산
        score_cci = calculate_cci_score(indicators.cci, cci_rising)
        score_distance = calculate_distance_score(indicators.candle.ma20_position)
        score_change = calculate_change_score(stock.today_change_rate)
        score_consec = calculate_consec_score(consec_days)
        score_candle = calculate_candle_quality_score(
            indicators.candle.is_bullish,
            indicators.candle.upper_wick_ratio,
            high_eq_close,
        )
        score_ma20_trend = calculate_ma20_trend_score(indicators.ma20_values)
        
        # 점수 상세 (기존 모델과 호환)
        score_detail = ScoreDetail(
            cci_value=score_cci,
            cci_slope=score_distance,  # v4: 이격도 점수
            ma20_slope=score_ma20_trend,
            candle=score_candle,
            change=score_change,
            raw_cci=indicators.cci,
            raw_ma20=indicators.ma20,
            raw_cci_slope=indicators.cci_slope,
            raw_ma20_slope=indicators.ma20_slope,
        )
        
        # 총점 계산 (6가지 평균)
        total_score = (
            score_cci + score_distance + score_change + 
            score_consec + score_candle + score_ma20_trend
        ) / 6 * 10  # 100점 만점으로 환산
        
        return StockScore(
            stock_code=stock.code,
            stock_name=stock.name,
            current_price=stock.current_price,
            change_rate=stock.today_change_rate,
            trading_value=stock.trading_value,
            score_detail=score_detail,
            score_total=round(total_score, 1),
        )
    
    def calculate_scores(
        self,
        stocks: List[StockData],
    ) -> List[StockScore]:
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
        scores: List[StockScore],
        n: int = TOP_N_COUNT,
    ) -> List[StockScore]:
        """TOP N 종목 선정"""
        return scores[:n]
    
    def get_sell_recommendation(self, stock: StockScore) -> dict:
        """매도 추천 방식 - v4
        
        점수 기반 매도 전략:
        - 80점+: 시초가 매도 (익절)
        - 70~80점: 2~3% 익절 또는 손절 -2%
        - 60~70점: 1~2% 익절 또는 손절 -1.5%
        - 60점 미만: 보수적 (손절 -1%)
        
        Returns:
            매도 추천 딕셔너리
        """
        score = stock.score_total
        
        if score >= 80:
            return {
                "strategy": "시초가 매도",
                "target_profit": "+1% ~ +3%",
                "stop_loss": "-2%",
                "confidence": "높음",
                "reason": "고점수 종목, 시초가 갭 기대"
            }
        elif score >= 70:
            return {
                "strategy": "목표가 매도",
                "target_profit": "+2% ~ +3%",
                "stop_loss": "-2%",
                "confidence": "중상",
                "reason": "양호한 점수, 익절 후 정리"
            }
        elif score >= 60:
            return {
                "strategy": "보수적 익절",
                "target_profit": "+1% ~ +2%",
                "stop_loss": "-1.5%",
                "confidence": "중간",
                "reason": "평균 점수, 욕심 금물"
            }
        else:
            return {
                "strategy": "조기 손절",
                "target_profit": "+1%",
                "stop_loss": "-1%",
                "confidence": "낮음",
                "reason": "낮은 점수, 리스크 관리 우선"
            }


# 호환성을 위한 별칭
ScoreCalculator = ScoreCalculatorV4


def calculate_scores(
    stocks: List[StockData],
    weights: Optional[Weights] = None,
) -> List[StockScore]:
    """점수 계산 유틸리티 함수"""
    calculator = ScoreCalculatorV4(weights)
    return calculator.calculate_scores(stocks)


def select_top_n(
    scores: List[StockScore],
    n: int = TOP_N_COUNT,
) -> List[StockScore]:
    """TOP N 선정 유틸리티 함수"""
    return scores[:n]


if __name__ == "__main__":
    # 테스트
    from datetime import date, timedelta
    
    logging.basicConfig(level=logging.INFO)
    
    print("=== v4 점수 계산기 테스트 ===")
    print("\n[CCI 점수 테스트]")
    for cci in [50, 100, 150, 165, 170, 175, 180, 190, 200, 250, 300]:
        score = calculate_cci_score(cci, cci_rising=True)
        print(f"  CCI {cci:3d}: {score:.1f}점")
    
    print("\n[이격도 점수 테스트]")
    for dist in [-5, -2, 0, 2, 5, 8, 10, 15, 20]:
        score = calculate_distance_score(dist)
        print(f"  이격도 {dist:3d}%: {score:.1f}점")
    
    print("\n[등락률 점수 테스트]")
    for change in [-3, 0, 2, 5, 8, 10, 15, 20, 25]:
        score = calculate_change_score(change)
        print(f"  등락률 {change:3d}%: {score:.1f}점")
    
    print("\n[연속양봉 점수 테스트]")
    for days in [0, 1, 2, 3, 4, 5, 6, 7, 10]:
        score = calculate_consec_score(days)
        print(f"  연속 {days:2d}일: {score:.1f}점")
