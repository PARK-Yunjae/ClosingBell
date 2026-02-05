"""
장 운영일 판단 유틸리티 (market_calendar.py)

v8.0 - 중복 제거: scheduler.py, data_updater.py에서 공유

사용법:
    from src.utils.market_calendar import is_market_open
"""

from datetime import date
from typing import Optional


# 한국 공휴일 (2025~2026년)
HOLIDAYS_KR = {
    # 2025년
    date(2025, 1, 1),    # 신정
    date(2025, 1, 28),   # 설날 연휴
    date(2025, 1, 29),   # 설날
    date(2025, 1, 30),   # 설날 연휴
    date(2025, 3, 1),    # 삼일절
    date(2025, 5, 5),    # 어린이날
    date(2025, 5, 6),    # 대체공휴일
    date(2025, 6, 6),    # 현충일
    date(2025, 8, 15),   # 광복절
    date(2025, 10, 3),   # 개천절
    date(2025, 10, 5),   # 추석 연휴
    date(2025, 10, 6),   # 추석
    date(2025, 10, 7),   # 추석 연휴
    date(2025, 10, 8),   # 대체공휴일
    date(2025, 10, 9),   # 한글날
    date(2025, 12, 25),  # 크리스마스
    # 2026년
    date(2026, 1, 1),    # 신정
    date(2026, 2, 16),   # 설날 연휴
    date(2026, 2, 17),   # 설날
    date(2026, 2, 18),   # 설날 연휴
    date(2026, 3, 1),    # 삼일절
    date(2026, 3, 2),    # 대체공휴일
    date(2026, 5, 5),    # 어린이날
    date(2026, 5, 25),   # 부처님오신날
    date(2026, 6, 6),    # 현충일
    date(2026, 8, 15),   # 광복절
    date(2026, 8, 17),   # 대체공휴일
    date(2026, 9, 24),   # 추석 연휴
    date(2026, 9, 25),   # 추석
    date(2026, 9, 26),   # 추석 연휴
    date(2026, 10, 3),   # 개천절
    date(2026, 10, 5),   # 대체공휴일
    date(2026, 10, 9),   # 한글날
    date(2026, 12, 25),  # 크리스마스
}


def is_market_open(check_date: Optional[date] = None) -> bool:
    """장 운영일 체크
    
    Args:
        check_date: 확인할 날짜 (기본: 오늘)
        
    Returns:
        장 운영 여부
    """
    if check_date is None:
        check_date = date.today()
    
    # 주말 체크
    if check_date.weekday() >= 5:  # 토(5), 일(6)
        return False
    
    # 공휴일 체크
    if check_date in HOLIDAYS_KR:
        return False
    
    return True
