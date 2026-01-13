"""
OHLCV 데이터 자동 갱신 스크립트 (data_updater.py)
"""

import logging
import time
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional, List
import pandas as pd

from src.adapters.kis_client import get_kis_client

logger = logging.getLogger(__name__)

# ============================================
# 설정
# ============================================
DATA_DIR = Path(r"C:\Coding\data\adjusted")
MAPPING_FILE = Path(r"C:\Coding\data\stock_mapping.csv")

API_DELAY = 0.3
MAX_STOCKS_PER_RUN = 100

# 공휴일
HOLIDAYS_2025_2026 = {
    date(2025, 1, 1), date(2025, 1, 28), date(2025, 1, 29), date(2025, 1, 30),
    date(2025, 3, 1), date(2025, 5, 5), date(2025, 5, 6), date(2025, 6, 6),
    date(2025, 8, 15), date(2025, 10, 3), date(2025, 10, 5), date(2025, 10, 6),
    date(2025, 10, 7), date(2025, 10, 8), date(2025, 10, 9), date(2025, 12, 25),
    date(2026, 1, 1),
}

def is_market_open(check_date: date = None) -> bool:
    """장 운영일 체크"""
    if check_date is None:
        check_date = date.today()
    if check_date.weekday() >= 5:
        return False
    if check_date in HOLIDAYS_2025_2026:
        return False
    return True


def get_last_date_in_csv(file_path: Path) -> Optional[date]:
    """CSV 파일의 마지막 거래일 반환"""
    try:
        df = pd.read_csv(file_path, index_col=0, parse_dates=True)
        if len(df) == 0:
            return None
        return df.index[-1].date()
    except Exception as e:
        logger.warning(f"CSV 읽기 실패 {file_path.name}: {e}")
        return None


def get_business_days_between(start: date, end: date) -> int:
    """두 날짜 사이의 영업일 수"""
    days = (end - start).days
    weeks = days // 7
    remainder = days % 7
    return weeks * 5 + min(remainder, 5)


def update_single_stock(code: str, last_date: date, today: date) -> bool:
    """단일 종목 데이터 갱신"""
    try:
        client = get_kis_client()
        days_needed = get_business_days_between(last_date, today) + 5
        prices = client.get_daily_prices(code, count=min(days_needed, 100))
        
        if not prices:
            logger.warning(f"  {code}: 데이터 없음")
            return False
        
        file_path = DATA_DIR / f"{code}.csv"
        df_existing = pd.read_csv(file_path, index_col=0, parse_dates=True)
        
        new_rows = []
        for price in prices:
            price_date = pd.Timestamp(price.date)
            if price_date not in df_existing.index and price.date > last_date:
                new_rows.append({
                    'Date': price_date,
                    'Open': price.open,
                    'High': price.high,
                    'Low': price.low,
                    'Close': price.close,
                    'Volume': price.volume,
                    'Change': (price.close / df_existing.iloc[-1]['Close'] - 1) if len(df_existing) > 0 else 0,
                    'TradingValue': price.trading_value,
                })
        
        if new_rows:
            df_new = pd.DataFrame(new_rows)
            df_new.set_index('Date', inplace=True)
            df_combined = pd.concat([df_existing, df_new])
            df_combined.sort_index(inplace=True)
            df_combined = df_combined[~df_combined.index.duplicated(keep='last')]
            df_combined.to_csv(file_path)
            logger.info(f"  ✓ {code}: {len(new_rows)}일 추가 (마지막: {df_combined.index[-1].date()})")
            return True
        else:
            logger.debug(f"  {code}: 추가할 데이터 없음")
            return True
            
    except Exception as e:
        logger.error(f"  ✗ {code}: 갱신 실패 - {e}")
        return False


def run_data_update(max_stocks: int = MAX_STOCKS_PER_RUN) -> dict:
    """OHLCV 데이터 자동 갱신"""
    print("=" * 50)
    print("📊 OHLCV 데이터 갱신 시작")
    print("=" * 50)
    
    today = date.today()
    
    if not is_market_open(today):
        print("휴장일 - 데이터 갱신 스킵")
        return {'updated': 0, 'failed': 0, 'skipped': 0}
    
    csv_files = list(DATA_DIR.glob("*.csv"))
    print(f"총 {len(csv_files)}개 종목 파일 발견")
    
    stocks_to_update = []
    for csv_file in csv_files:
        code = csv_file.stem
        if not code.replace('K', '').isdigit():
            continue
        last_date = get_last_date_in_csv(csv_file)
        if last_date is None:
            continue
        if last_date < today:
            stocks_to_update.append((code, last_date))
    
    print(f"갱신 필요: {len(stocks_to_update)}개 종목")
    
    stocks_to_update.sort(key=lambda x: x[1])
    stocks_to_update = stocks_to_update[:max_stocks]
    
    results = {'updated': 0, 'failed': 0, 'skipped': 0}
    
    for i, (code, last_date) in enumerate(stocks_to_update, 1):
        days_behind = (today - last_date).days
        print(f"[{i}/{len(stocks_to_update)}] {code} - 마지막: {last_date} ({days_behind}일 전)")
        
        success = update_single_stock(code, last_date, today)
        if success:
            results['updated'] += 1
        else:
            results['failed'] += 1
        
        time.sleep(API_DELAY)
    
    print("=" * 50)
    print(f"📊 데이터 갱신 완료: 성공 {results['updated']}, 실패 {results['failed']}")
    print("=" * 50)
    
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_data_update(max_stocks=10)