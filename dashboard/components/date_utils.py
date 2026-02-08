"""대시보드 공용 유틸리티 (v10.1)

- 휴장일 자동 보정 날짜 선택
- 시장 달력 연동
"""

import streamlit as st
from datetime import date, timedelta
from typing import Optional

try:
    from src.utils.market_calendar import is_market_open, HOLIDAYS_KR
except ImportError:
    HOLIDAYS_KR = set()
    def is_market_open(check_date=None):
        d = check_date or date.today()
        return d.weekday() < 5


def get_prev_market_day(d: date) -> date:
    """가장 최근 거래일 반환 (d 포함)"""
    for _ in range(10):
        if is_market_open(d):
            return d
        d -= timedelta(days=1)
    return d


def get_next_market_day(d: date) -> date:
    """다음 거래일 반환 (d 포함)"""
    for _ in range(10):
        if is_market_open(d):
            return d
        d += timedelta(days=1)
    return d


def market_date_input(
    label: str = "📅 날짜 선택",
    default: Optional[date] = None,
    key: Optional[str] = None,
    sidebar: bool = True,
    help_text: str = "휴장일 선택 시 직전 거래일로 자동 보정됩니다",
) -> date:
    """휴장일 자동 보정 날짜 선택 위젯
    
    Args:
        label: 위젯 라벨
        default: 기본 날짜 (None이면 최근 거래일)
        key: Streamlit 위젯 키
        sidebar: 사이드바에 표시할지
        help_text: 도움말 텍스트
    
    Returns:
        거래일로 보정된 날짜
    """
    # 기본값: 최근 거래일
    if default is None:
        default = get_prev_market_day(date.today())
    else:
        default = get_prev_market_day(default)
    
    container = st.sidebar if sidebar else st
    
    selected = container.date_input(
        label,
        value=default,
        max_value=date.today(),
        key=key,
        help=help_text,
    )
    
    # 휴장일 선택 시 자동 보정
    if not is_market_open(selected):
        corrected = get_prev_market_day(selected)
        
        # 왜 보정되었는지 표시
        if selected.weekday() >= 5:
            reason = "주말"
        elif selected in HOLIDAYS_KR:
            reason = "공휴일"
        else:
            reason = "휴장일"
        
        container.caption(
            f"⚠️ {selected.strftime('%m/%d')}은 {reason} → "
            f"**{corrected.strftime('%m/%d')}** (직전 거래일)"
        )
        return corrected
    
    return selected
