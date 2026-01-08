"""
점수 산출기

책임:
- 5가지 지표별 점수 산출
- 가중치 적용
- 총점 계산
- TOP N 선정

의존성:
- domain.indicators
- domain.models
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
    CCI_OPTIMAL,
    CCI_SCORE_RANGES,
    CCI_EXTREME_HIGH,
    CCI_SLOPE_WARNING_LEVEL,
    TOP_N_COUNT,
    CCI_SLOPE_PERIOD,
)

logger = logging.getLogger(__name__)


def calculate_cci_value_score(cci: float) -> float:
    """CCI 값 점수 계산 (180 근접 시 최고점)
    
    Args:
        cci: CCI 값
        
    Returns:
        점수 (0~10)
    """
    # 극단값 처리
    if cci > CCI_EXTREME_HIGH:
        return 1.0  # 매우 과열
    if cci < 0:
        return 2.0  # 과매도
    
    # 범위 기반 점수
    for min_val, max_val, score in CCI_SCORE_RANGES:
        if min_val <= cci < max_val:
            return score
    
    # 정확히 맞는 범위가 없으면 180과의 거리로 계산
    distance = abs(cci - CCI_OPTIMAL)
    if distance <= 5:
        return 10.0
    elif distance <= 20:
        return 9.0 - (distance - 5) * 0.1
    elif distance <= 50:
        return 7.0 - (distance - 20) * 0.05
    else:
        return max(2.0, 5.0 - (distance - 50) * 0.02)


def calculate_cci_slope_score(
    cci_values: List[float],
    current_cci: float,
) -> float:
    """CCI 기울기 점수 계산 (2일 기준 상승세) - v2.2.1 패치
    
    핵심 조건:
    - 최근 2일 연속 상승 시 최고점 (어제→오늘)
    - CCI가 180을 향해 가는 방향성 중요
    
    Args:
        cci_values: CCI 값 리스트
        current_cci: 현재 CCI 값
        
    Returns:
        점수 (0~10)
    """
    if len(cci_values) < CCI_SLOPE_PERIOD:
        return 5.0  # 데이터 부족 시 중립 점수
    
    recent = cci_values[-CCI_SLOPE_PERIOD:]  # 최근 2일
    
    # 과열권 하락 감점
    if current_cci > CCI_SLOPE_WARNING_LEVEL and recent[-1] < recent[-2]:
        return 2.0
    
    # ★ 2일 연속 상승 = 만점
    is_rising = recent[-1] > recent[-2]
    
    if is_rising:
        if current_cci < 200:
            return 10.0
        else:
            return 8.5  # 과열권이지만 상승 중
    else:
        # 하락
        return 4.0


def calculate_ma20_slope_score(ma20_slope: float, ma20_values: List[float] = None) -> float:
    """MA20 기울기 점수 계산 (3일 기준 상승세) - v2.2.1 패치
    
    핵심 조건:
    - 최근 3일간 MA20이 상승 추세인지
    - 우상향 추세가 확실해야 높은 점수
    
    Args:
        ma20_slope: MA20 기울기 (%)
        ma20_values: MA20 값 리스트 (옵션, 연속 상승 체크용)
        
    Returns:
        점수 (0~10)
    """
    # 3일 연속 상승 체크 (ma20_values가 전달된 경우)
    if ma20_values and len(ma20_values) >= 3:
        recent = ma20_values[-3:]
        is_3day_rising = all(recent[i] > recent[i-1] for i in range(1, len(recent)))
        
        if is_3day_rising:
            return 10.0  # 3일 연속 상승 = 만점
    
    # 기울기 백분율 기반 점수
    if ma20_slope >= 2.0:
        return 9.5   # 강한 상승세
    elif ma20_slope >= 1.0:
        return 8.5   # 상승세
    elif ma20_slope >= 0.5:
        return 7.5   # 약한 상승세
    elif ma20_slope >= 0.2:
        return 6.5   # 미세 상승
    elif ma20_slope >= 0.0:
        return 5.5   # 횡보 (약간 상승)
    elif ma20_slope >= -0.5:
        return 4.0   # 약한 하락세
    elif ma20_slope >= -1.0:
        return 2.5   # 하락세
    else:
        return 1.0   # 강한 하락세


def calculate_candle_score(
    is_bullish: bool,
    upper_wick_ratio: float,
    is_above_ma20: bool,
    ma20_position: float,
) -> float:
    """양봉 품질 점수 계산 - v2.2 업데이트
    
    핵심 조건:
    - 양봉이 MA20 위에 안착했는가
    - 윗꼬리가 짧은가 (매물대 저항 없음)
    - MA20 대비 너무 위에 있으면 과열
    
    Args:
        is_bullish: 양봉 여부
        upper_wick_ratio: 윗꼬리 비율 (몸통 대비)
        is_above_ma20: MA20 위 안착 여부
        ma20_position: MA20 대비 위치 (%)
        
    Returns:
        점수 (0~10)
    """
    # 음봉인 경우 강한 감점
    if not is_bullish:
        return 2.0
    
    # ★ 윗꼬리 점수 (핵심)
    if upper_wick_ratio <= 0.1:
        wick_score = 10.0  # 윗꼬리 거의 없음 = 최고
    elif upper_wick_ratio <= 0.2:
        wick_score = 8.5   # 윗꼬리 짧음 = 양호
    elif upper_wick_ratio <= 0.3:
        wick_score = 6.5   # 윗꼬리 보통
    elif upper_wick_ratio <= 0.5:
        wick_score = 4.5   # 윗꼬리 김 = 매물대 저항
    else:
        wick_score = 2.5   # 윗꼬리 매우 김 = 위험
    
    # ★ MA20 안착 보정 (핵심)
    if is_above_ma20:
        if 0 <= ma20_position <= 2.0:
            # 최적 위치: MA20 바로 위에 안착
            position_bonus = 2.0
        elif ma20_position <= 5.0:
            # 적정 위치: 약간 위
            position_bonus = 1.0
        elif ma20_position <= 8.0:
            # 주의: 조금 과열
            position_bonus = 0.0
        else:
            # 과열: MA20 대비 너무 위
            position_bonus = -2.0
    else:
        # MA20 아래 = 추세 이탈
        if ma20_position >= -2.0:
            position_bonus = -1.0  # 살짝 아래
        else:
            position_bonus = -3.0  # 확실히 아래
    
    final_score = wick_score + position_bonus
    return max(SCORE_MIN, min(SCORE_MAX, final_score))


def calculate_change_score(change_rate: float) -> float:
    """당일 상승률 점수 - 비활성화 (가중치 0.0 권장) - v2.2 업데이트
    
    백테스트 결과: 등락률과 익일 수익률 역상관 (-0.040)
    따라서 점수에서 제외하거나 가중치 0으로 설정
    
    Args:
        change_rate: 등락률 (%)
        
    Returns:
        점수 (항상 중립 점수 5.0 반환)
    """
    return 5.0  # 항상 중립 점수 반환 (실질적 비활성화)


class ScoreCalculator:
    """점수 계산기"""
    
    def __init__(self, weights: Optional[Weights] = None):
        """
        Args:
            weights: 점수 가중치 (None이면 기본값 사용)
        """
        self.weights = weights or Weights()
    
    def calculate_single_score(
        self,
        stock: StockData,
    ) -> Optional[StockScore]:
        """단일 종목 점수 계산
        
        Args:
            stock: 종목 데이터
            
        Returns:
            종목 점수 또는 None (계산 불가 시)
        """
        # 지표 계산
        indicators = calculate_all_indicators(stock.daily_prices)
        if indicators is None:
            logger.warning(f"지표 계산 불가: {stock.code} ({stock.name})")
            return None
        
        # 당일 등락률
        change_rate = stock.today_change_rate
        
        # 5가지 점수 계산
        score_cci_value = calculate_cci_value_score(indicators.cci)
        score_cci_slope = calculate_cci_slope_score(
            indicators.cci_values,
            indicators.cci,
        )
        # MA20 기울기 점수 계산 시 ma20_values 전달 (v2.2)
        ma20_values = getattr(indicators, 'ma20_values', None)
        score_ma20_slope = calculate_ma20_slope_score(indicators.ma20_slope, ma20_values)
        score_candle = calculate_candle_score(
            indicators.candle.is_bullish,
            indicators.candle.upper_wick_ratio,
            indicators.candle.is_above_ma20,
            indicators.candle.ma20_position,
        )
        score_change = calculate_change_score(change_rate)
        
        # 점수 상세
        score_detail = ScoreDetail(
            cci_value=score_cci_value,
            cci_slope=score_cci_slope,
            ma20_slope=score_ma20_slope,
            candle=score_candle,
            change=score_change,
            raw_cci=indicators.cci,
            raw_ma20=indicators.ma20,
            raw_cci_slope=indicators.cci_slope,
            raw_ma20_slope=indicators.ma20_slope,
        )
        
        # 가중 합계
        score_total = score_detail.total(self.weights)
        
        return StockScore(
            stock_code=stock.code,
            stock_name=stock.name,
            current_price=stock.current_price,
            change_rate=change_rate,
            trading_value=stock.trading_value,
            score_detail=score_detail,
            score_total=score_total,
        )
    
    def calculate_scores(
        self,
        stocks: List[StockData],
    ) -> List[StockScore]:
        """여러 종목 점수 계산
        
        Args:
            stocks: 종목 데이터 리스트
            
        Returns:
            점수 계산된 종목 리스트 (점수 높은 순)
        """
        scores = []
        for stock in stocks:
            score = self.calculate_single_score(stock)
            if score:
                scores.append(score)
        
        # 점수 높은 순으로 정렬
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
        """TOP N 종목 선정
        
        Args:
            scores: 점수 리스트 (정렬됨)
            n: 선정 개수
            
        Returns:
            TOP N 종목 리스트
        """
        return scores[:n]


def calculate_scores(
    stocks: List[StockData],
    weights: Optional[Weights] = None,
) -> List[StockScore]:
    """점수 계산 유틸리티 함수
    
    Args:
        stocks: 종목 데이터 리스트
        weights: 가중치 (옵션)
        
    Returns:
        점수 계산된 종목 리스트
    """
    calculator = ScoreCalculator(weights)
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
    
    # 테스트용 더미 데이터 생성
    def create_dummy_stock(name: str, code: str, trend: str = "up") -> StockData:
        base_date = date.today()
        prices = []
        base_price = 50000
        
        for i in range(25):
            d = base_date - timedelta(days=24 - i)
            if trend == "up":
                close = base_price + (i * 500) + (i % 3 - 1) * 100
            elif trend == "down":
                close = base_price - (i * 300) + (i % 3 - 1) * 100
            else:
                close = base_price + (i % 5 - 2) * 200
            
            open_price = close - 200 + (i % 2) * 100
            high = max(close, open_price) + 150
            low = min(close, open_price) - 150
            
            prices.append(DailyPrice(
                date=d,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=1000000,
            ))
        
        return StockData(
            code=code,
            name=name,
            daily_prices=prices,
            current_price=prices[-1].close,
            trading_value=500.0,  # 억원
        )
    
    # 테스트 종목 생성
    stocks = [
        create_dummy_stock("상승주A", "001111", "up"),
        create_dummy_stock("상승주B", "002222", "up"),
        create_dummy_stock("횡보주", "003333", "flat"),
        create_dummy_stock("하락주", "004444", "down"),
    ]
    
    # 점수 계산
    calculator = ScoreCalculator()
    scores = calculator.calculate_scores(stocks)
    
    print("\n=== 점수 계산 결과 ===")
    for score in scores:
        print(f"\n{score.rank}위: {score.stock_name} ({score.stock_code})")
        print(f"  총점: {score.score_total:.2f}")
        print(f"  CCI값 점수: {score.score_cci_value:.1f} (CCI: {score.raw_cci:.1f})")
        print(f"  CCI기울기 점수: {score.score_cci_slope:.1f}")
        print(f"  MA20기울기 점수: {score.score_ma20_slope:.1f}")
        print(f"  양봉품질 점수: {score.score_candle:.1f}")
        print(f"  상승률 점수: {score.score_change:.1f} ({score.change_rate:.2f}%)")
    
    # TOP 3
    top3 = calculator.select_top_n(scores)
    print(f"\n=== TOP 3 ===")
    for s in top3:
        print(f"{s.rank}. {s.stock_name}: {s.score_total:.2f}점")
    
        print(f"  CCI값 점수: {score.score_cci_value:.1f} (CCI: {score.raw_cci:.1f})")
    
