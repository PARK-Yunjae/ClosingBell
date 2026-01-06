"""pytest 설정 및 공통 fixture"""

import pytest
import sys
from pathlib import Path
from datetime import date
from typing import List

# 프로젝트 루트를 path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.domain.models import DailyPrice, StockInfo, ScoreDetail


@pytest.fixture
def sample_daily_prices() -> List[DailyPrice]:
    """테스트용 일봉 데이터 (30일)"""
    base_date = date(2026, 1, 1)
    prices = []
    
    # 상승 추세 시뮬레이션
    base_price = 10000
    for i in range(30):
        day_date = date(2026, 1, i + 1)
        
        # 약간의 변동성 추가
        variation = (i % 5 - 2) * 50  # -100 ~ +100
        trend = i * 30  # 상승 추세
        
        open_price = base_price + trend + variation
        close_price = open_price + 50 + (i % 3) * 30  # 양봉 위주
        high_price = max(open_price, close_price) + 30
        low_price = min(open_price, close_price) - 20
        
        prices.append(DailyPrice(
            date=day_date,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=1000000 + i * 50000,
            trading_value=float(close_price * (1000000 + i * 50000)),
        ))
    
    return prices


@pytest.fixture
def sample_stock_info() -> StockInfo:
    """테스트용 종목 정보"""
    return StockInfo(
        code="005930",
        name="삼성전자",
        market="KOSPI",
    )


@pytest.fixture
def sample_score_detail() -> ScoreDetail:
    """테스트용 점수 상세"""
    return ScoreDetail(
        cci_value=8.0,
        cci_slope=7.5,
        ma20_slope=6.0,
        candle=9.0,
        change=7.0,
        raw_cci=175.5,
        raw_ma20=55000,
    )


@pytest.fixture
def sample_cci_optimal_prices() -> List[DailyPrice]:
    """CCI가 180 근처인 테스트용 데이터"""
    prices = []
    base_date = date(2026, 1, 1)
    
    # CCI 180 근처가 되도록 설계된 가격 데이터
    # Typical Price가 MA보다 약간 높고, Mean Deviation이 적절한 값
    price_sequence = [
        (10000, 10100, 9900, 10050),  # open, high, low, close
        (10050, 10150, 10000, 10100),
        (10100, 10200, 10050, 10150),
        (10150, 10250, 10100, 10200),
        (10200, 10300, 10150, 10250),
        (10250, 10350, 10200, 10300),
        (10300, 10400, 10250, 10350),
        (10350, 10450, 10300, 10400),
        (10400, 10500, 10350, 10450),
        (10450, 10550, 10400, 10500),
        (10500, 10600, 10450, 10550),
        (10550, 10650, 10500, 10600),
        (10600, 10700, 10550, 10650),
        (10650, 10750, 10600, 10700),
        (10700, 10850, 10650, 10800),  # 마지막 날 상승
    ]
    
    for i, (o, h, l, c) in enumerate(price_sequence):
        prices.append(DailyPrice(
            date=date(2026, 1, i + 1),
            open=o,
            high=h,
            low=l,
            close=c,
            volume=1000000,
            trading_value=float(c * 1000000),
        ))
    
    return prices


@pytest.fixture
def sample_downtrend_prices() -> List[DailyPrice]:
    """하락 추세 테스트용 데이터"""
    prices = []
    base_price = 20000
    
    for i in range(30):
        trend = -i * 50  # 하락 추세
        variation = (i % 3 - 1) * 30
        
        close_price = base_price + trend + variation
        open_price = close_price + 30  # 음봉 위주
        high_price = max(open_price, close_price) + 20
        low_price = min(open_price, close_price) - 30
        
        prices.append(DailyPrice(
            date=date(2026, 1, i + 1),
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=800000,
            trading_value=float(close_price * 800000),
        ))
    
    return prices
