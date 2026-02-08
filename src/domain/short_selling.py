"""
공매도/대차거래 도메인 모델

공매도 데이터는 '위험 회피'를 위한 방어적 지표로 활용:
- 공매도 비중 높은 종목 → 하방 압력 경고
- 대차잔고 증가 → 숏 포지션 축적 경고
- 공매도 비중 급감 → 숏커버링 = 반등 가능 신호
"""

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional


@dataclass
class ShortSellingDaily:
    """공매도 일별 데이터 (ka10014)"""
    date: date
    close_price: int
    change_rate: float
    trade_volume: int          # 전체 거래량
    short_volume: int          # 공매도량
    short_ratio: float         # 매매비중 (%)
    cumulative_short: int      # 누적공매도량
    short_avg_price: int       # 공매도평균가
    short_trade_value: int     # 공매도거래대금


@dataclass
class StockLendingDaily:
    """대차거래 일별 데이터 (ka20068)"""
    date: date
    lending_volume: int        # 대차체결주수 (신규 대출)
    repayment_volume: int      # 대차상환주수 (상환)
    net_change: int            # 증감 (체결 - 상환)
    balance_shares: int        # 잔고주수
    balance_amount: int        # 잔고금액 (백만원)


@dataclass
class ShortSellingScore:
    """공매도 종합 분석 점수"""
    stock_code: str
    
    # 원시 데이터 요약
    latest_short_ratio: float = 0.0      # 최근일 공매도 비중 %
    avg_short_ratio_5d: float = 0.0      # 5일 평균 공매도 비중
    short_ratio_change: float = 0.0      # 비중 변화 (최근 vs 5일전)
    
    latest_lending_balance: int = 0      # 최근 대차잔고
    lending_trend_3d: int = 0            # 3일 잔고 변화 (양수=증가)
    lending_consecutive_decrease: int = 0 # 연속 감소 일수
    
    # 점수
    score: float = 0.0                   # 종합 점수 (-10 ~ +10)
    
    # 태그
    tags: List[str] = field(default_factory=list)
    # 가능한 태그:
    # "🔻숏과열"     - 공매도 비중 > 10%
    # "⚠️숏급증"     - 공매도 비중 전일비 +100% 이상
    # "✅숏비중낮음"  - 공매도 비중 < 3%
    # "✅숏커버링"    - 공매도 비중 3일 연속 감소
    # "📉대차증가"   - 대차잔고 3일 연속 증가
    # "✅대차감소"    - 대차잔고 3일 연속 감소
    
    # 요약 텍스트 (Discord용)
    summary: str = ""
    
    @property
    def is_dangerous(self) -> bool:
        """위험 종목 여부"""
        return self.score <= -3
    
    @property 
    def is_favorable(self) -> bool:
        """호의적 종목 여부"""
        return self.score >= 2
