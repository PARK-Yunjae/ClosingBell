"""
지지선/저항선 도메인 모델

매수 판단의 안전장치:
- 지지선 근접 = 반등 기대 (안전한 진입점)
- 저항선 근접 = 돌파 or 눌림 판단 필요
- 이동평균선 위치 = 추세 방향 확인
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PivotPoint:
    """피봇 포인트 (전일 고/저/종 기반)"""
    pp: float = 0.0       # 피봇 포인트
    r1: float = 0.0       # 저항선 1
    r2: float = 0.0       # 저항선 2
    r3: float = 0.0       # 저항선 3
    s1: float = 0.0       # 지지선 1
    s2: float = 0.0       # 지지선 2
    s3: float = 0.0       # 지지선 3


@dataclass
class MovingAverageSupport:
    """이동평균선 지지/저항"""
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    ma60: float = 0.0
    ma120: float = 0.0
    
    # 현재가 대비 위치 (True = 가격이 MA 위에 있음)
    above_ma5: bool = False
    above_ma10: bool = False
    above_ma20: bool = False
    above_ma60: bool = False
    above_ma120: bool = False
    
    @property
    def bullish_count(self) -> int:
        """가격이 위에 있는 이평선 개수 (0~5)"""
        return sum([
            self.above_ma5, self.above_ma10, self.above_ma20,
            self.above_ma60, self.above_ma120
        ])
    
    @property
    def nearest_support_ma(self) -> float:
        """현재가 아래 가장 가까운 이평선 (지지역할)"""
        below = []
        if not self.above_ma5 and self.ma5 > 0: below.append(self.ma5)
        if not self.above_ma10 and self.ma10 > 0: below.append(self.ma10)
        if not self.above_ma20 and self.ma20 > 0: below.append(self.ma20)
        if not self.above_ma60 and self.ma60 > 0: below.append(self.ma60)
        if not self.above_ma120 and self.ma120 > 0: below.append(self.ma120)
        # 현재가 아래 = MA가 현재가 아래 = above가 True인 것 중 가장 가까운
        # 아닙니다 - above=True인 MA들 중 가장 높은 것이 지지선
        return 0.0  # 아래 SupportResistance에서 계산


@dataclass
class HorizontalLevel:
    """수평 지지/저항 레벨"""
    price: float           # 가격대
    touch_count: int        # 터치 횟수
    level_type: str         # "support" or "resistance"
    strength: str           # "weak", "moderate", "strong"


@dataclass
class SupportResistance:
    """종합 지지/저항 분석 결과"""
    stock_code: str
    current_price: float = 0.0
    
    # 피봇 포인트
    pivot: Optional[PivotPoint] = None
    
    # 이동평균
    ma: Optional[MovingAverageSupport] = None
    
    # 수평 레벨 (N일 고저점 클러스터링)
    horizontal_levels: List[HorizontalLevel] = field(default_factory=list)
    
    # 종합 분석
    nearest_support: float = 0.0          # 가장 가까운 지지선
    nearest_resistance: float = 0.0       # 가장 가까운 저항선
    support_distance_pct: float = 0.0     # 지지선까지 거리 %
    resistance_distance_pct: float = 0.0  # 저항선까지 거리 %
    
    # 점수 (-5 ~ +5)
    score: float = 0.0
    
    # 요약 태그
    tags: List[str] = field(default_factory=list)
    # 가능한 태그:
    # "✅지지근접"    - 주요 지지선 1% 이내
    # "📍MA20지지"   - 20일선 지지
    # "📍MA60지지"   - 60일선 지지
    # "⚠️저항근접"   - 주요 저항선 1% 이내
    # "🔺이평정배열"  - 5>10>20>60선 정배열
    # "🔻이평역배열"  - 역배열
    
    # 요약 텍스트 (Discord용)
    summary: str = ""
    
    @property
    def near_support(self) -> bool:
        """지지선 근접 여부 (2% 이내)"""
        return 0 < self.support_distance_pct <= 2.0
    
    @property
    def near_resistance(self) -> bool:
        """저항선 근접 여부 (2% 이내)"""
        return 0 < self.resistance_distance_pct <= 2.0
