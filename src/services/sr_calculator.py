"""
지지선/저항선 계산 엔진

기존 일봉 데이터(DailyPrice)로 계산 — 추가 API 불필요.
TOP5/눌림목 스크리너에서 호출.
"""

import logging
from typing import List, Optional
from collections import defaultdict

from src.domain.models import DailyPrice
from src.domain.support_resistance import (
    PivotPoint, MovingAverageSupport, HorizontalLevel, SupportResistance
)

logger = logging.getLogger(__name__)


def calculate_pivot_point(high: float, low: float, close: float) -> PivotPoint:
    """피봇 포인트 계산 (전일 고/저/종가 기반)
    
    Classic Pivot Point:
    PP = (H + L + C) / 3
    R1 = 2*PP - L
    R2 = PP + (H - L)
    R3 = H + 2*(PP - L)
    S1 = 2*PP - H
    S2 = PP - (H - L)
    S3 = L - 2*(H - PP)
    """
    if high == 0 or low == 0 or close == 0:
        return PivotPoint()
    
    pp = (high + low + close) / 3
    r1 = 2 * pp - low
    r2 = pp + (high - low)
    r3 = high + 2 * (pp - low)
    s1 = 2 * pp - high
    s2 = pp - (high - low)
    s3 = low - 2 * (high - pp)
    
    return PivotPoint(
        pp=round(pp), r1=round(r1), r2=round(r2), r3=round(r3),
        s1=round(s1), s2=round(s2), s3=round(s3)
    )


def calculate_moving_averages(
    prices: List[DailyPrice], current_price: float
) -> MovingAverageSupport:
    """이동평균선 계산"""
    if not prices:
        return MovingAverageSupport()
    
    closes = [p.close for p in prices]
    
    def _ma(n: int) -> float:
        if len(closes) < n:
            return 0.0
        return round(sum(closes[-n:]) / n)
    
    ma5 = _ma(5)
    ma10 = _ma(10)
    ma20 = _ma(20)
    ma60 = _ma(60)
    ma120 = _ma(120)
    
    return MovingAverageSupport(
        ma5=ma5, ma10=ma10, ma20=ma20, ma60=ma60, ma120=ma120,
        above_ma5=current_price >= ma5 if ma5 > 0 else False,
        above_ma10=current_price >= ma10 if ma10 > 0 else False,
        above_ma20=current_price >= ma20 if ma20 > 0 else False,
        above_ma60=current_price >= ma60 if ma60 > 0 else False,
        above_ma120=current_price >= ma120 if ma120 > 0 else False,
    )


def find_horizontal_levels(
    prices: List[DailyPrice],
    current_price: float,
    lookback_days: int = 60,
    cluster_pct: float = 1.5
) -> List[HorizontalLevel]:
    """수평 지지/저항 레벨 탐색
    
    최근 N일 고가/저가를 클러스터링하여
    여러 번 터치된 가격대를 지지/저항으로 식별.
    
    Args:
        prices: 일봉 데이터 (시간순)
        current_price: 현재가
        lookback_days: 분석 기간
        cluster_pct: 클러스터링 기준 (% 이내면 같은 레벨)
    """
    if len(prices) < 10:
        return []
    
    recent = prices[-lookback_days:]
    
    # 고가/저가 수집
    price_points = []
    for p in recent:
        price_points.append(p.high)
        price_points.append(p.low)
    
    if not price_points:
        return []
    
    # 클러스터링: 가격을 정렬 후 인접한 것들 그룹핑
    price_points.sort()
    clusters = []
    current_cluster = [price_points[0]]
    
    for i in range(1, len(price_points)):
        # cluster_pct% 이내면 같은 클러스터
        if current_cluster and price_points[i] <= current_cluster[0] * (1 + cluster_pct / 100):
            current_cluster.append(price_points[i])
        else:
            clusters.append(current_cluster)
            current_cluster = [price_points[i]]
    clusters.append(current_cluster)
    
    # 2회 이상 터치된 클러스터만 레벨로
    levels = []
    for cluster in clusters:
        if len(cluster) >= 3:  # 고/저 합쳐서 3회 이상 = 의미있는 레벨
            avg_price = sum(cluster) / len(cluster)
            touch_count = len(cluster)
            
            # 현재가 기준 지지/저항 판별
            if avg_price < current_price:
                level_type = "support"
            else:
                level_type = "resistance"
            
            # 강도 판별
            if touch_count >= 6:
                strength = "strong"
            elif touch_count >= 4:
                strength = "moderate"
            else:
                strength = "weak"
            
            levels.append(HorizontalLevel(
                price=round(avg_price),
                touch_count=touch_count,
                level_type=level_type,
                strength=strength,
            ))
    
    # 현재가에 가까운 순으로 정렬
    levels.sort(key=lambda l: abs(l.price - current_price))
    
    return levels[:10]  # 상위 10개만


def calculate_support_resistance(
    stock_code: str,
    prices: List[DailyPrice],
    current_price: Optional[float] = None,
) -> SupportResistance:
    """종합 지지/저항 분석
    
    Args:
        stock_code: 종목코드
        prices: 일봉 데이터 (시간순, 오래된→최신)
        current_price: 현재가 (None이면 마지막 종가 사용)
    """
    if not prices or len(prices) < 5:
        return SupportResistance(stock_code=stock_code)
    
    if current_price is None:
        current_price = prices[-1].close
    
    # 1. 피봇 포인트 (전일 데이터 기준)
    prev = prices[-2] if len(prices) >= 2 else prices[-1]
    pivot = calculate_pivot_point(prev.high, prev.low, prev.close)
    
    # 2. 이동평균
    ma = calculate_moving_averages(prices, current_price)
    
    # 3. 수평 레벨
    h_levels = find_horizontal_levels(prices, current_price)
    
    # 4. 가장 가까운 지지/저항 결정
    support_candidates = []
    resistance_candidates = []
    
    # 피봇 기반
    for level in [pivot.s1, pivot.s2, pivot.s3]:
        if 0 < level < current_price:
            support_candidates.append(level)
    for level in [pivot.r1, pivot.r2, pivot.r3]:
        if level > current_price:
            resistance_candidates.append(level)
    
    # 이평 기반 (현재가 위의 MA = 저항, 아래 = 지지)
    for ma_val, above in [
        (ma.ma5, ma.above_ma5), (ma.ma10, ma.above_ma10),
        (ma.ma20, ma.above_ma20), (ma.ma60, ma.above_ma60),
        (ma.ma120, ma.above_ma120)
    ]:
        if ma_val > 0:
            if above:  # 가격이 MA 위 → MA가 지지
                support_candidates.append(ma_val)
            else:      # 가격이 MA 아래 → MA가 저항
                resistance_candidates.append(ma_val)
    
    # 수평 레벨 기반
    for level in h_levels:
        if level.level_type == "support":
            support_candidates.append(level.price)
        else:
            resistance_candidates.append(level.price)
    
    # 가장 가까운 지지/저항
    nearest_support = max(support_candidates) if support_candidates else 0
    nearest_resistance = min(resistance_candidates) if resistance_candidates else 0
    
    # 거리 % 계산
    support_dist_pct = 0.0
    if nearest_support > 0 and current_price > 0:
        support_dist_pct = round(
            (current_price - nearest_support) / current_price * 100, 2
        )
    
    resistance_dist_pct = 0.0
    if nearest_resistance > 0 and current_price > 0:
        resistance_dist_pct = round(
            (nearest_resistance - current_price) / current_price * 100, 2
        )
    
    # 5. 점수 계산 (-5 ~ +5)
    score = 0.0
    tags = []
    
    # 지지선 근접 (2% 이내) → 호의적
    if 0 < support_dist_pct <= 1.0:
        score += 2.0
        tags.append("✅지지근접")
    elif 0 < support_dist_pct <= 2.0:
        score += 1.0
    
    # 저항선 근접 (1% 이내) → 돌파 or 위험
    if 0 < resistance_dist_pct <= 1.0:
        tags.append("⚠️저항근접")
        # 저항 근접 자체는 감점하지 않음 (돌파 가능성도 있으므로)
    
    # 이동평균 정배열 (5>10>20>60)
    if (ma.ma5 > ma.ma10 > ma.ma20 > ma.ma60 > 0):
        score += 2.0
        tags.append("🔺이평정배열")
    # 역배열
    elif (0 < ma.ma5 < ma.ma10 < ma.ma20 < ma.ma60):
        score -= 2.0
        tags.append("🔻이평역배열")
    
    # MA20 위 → 단기 상승추세
    if ma.above_ma20:
        score += 0.5
        tags.append("📍MA20↑")
    else:
        score -= 0.5
    
    # MA60 위 → 중기 상승추세
    if ma.above_ma60:
        score += 0.5
        tags.append("📍MA60↑")
    else:
        score -= 0.5
    
    # 6. 요약 텍스트
    summary_parts = []
    if nearest_support > 0:
        summary_parts.append(f"S:{int(nearest_support):,}({support_dist_pct:.1f}%)")
    if nearest_resistance > 0:
        summary_parts.append(f"R:{int(nearest_resistance):,}({resistance_dist_pct:.1f}%)")
    
    ma_pos = f"MA{ma.bullish_count}/5"
    summary_parts.append(ma_pos)
    
    return SupportResistance(
        stock_code=stock_code,
        current_price=current_price,
        pivot=pivot,
        ma=ma,
        horizontal_levels=h_levels,
        nearest_support=nearest_support,
        nearest_resistance=nearest_resistance,
        support_distance_pct=support_dist_pct,
        resistance_distance_pct=resistance_dist_pct,
        score=round(score, 1),
        tags=tags,
        summary=" │ ".join(summary_parts),
    )
