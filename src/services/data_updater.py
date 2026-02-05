"""
OHLCV + 글로벌 데이터 자동 갱신 (data_updater.py) v7.0
"""

import logging
import time
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional, List
import pandas as pd

from src.adapters.kiwoom_rest_client import get_kiwoom_client

logger = logging.getLogger(__name__)

# ============================================
# 설정
# ============================================
from src.config.app_config import OHLCV_FULL_DIR as DATA_DIR, GLOBAL_DIR, MAPPING_FILE

API_DELAY = 0.3
MAX_STOCKS_PER_RUN = 3000  # v5.2: API 제한 여유있으므로 전체 갱신

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
        df = pd.read_csv(file_path, encoding='utf-8-sig')
        
        # date 컬럼 찾기
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            return df['date'].max().date()
        
        # 첫 번째 컬럼이 날짜인 경우 (Unnamed: 0 또는 인덱스)
        first_col = df.columns[0]
        if first_col in ['', 'Unnamed: 0'] or 'date' in first_col.lower():
            df[first_col] = pd.to_datetime(df[first_col])
            return df[first_col].max().date()
        
        # 인덱스가 날짜인 경우
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


def load_csv_with_date(file_path: Path) -> Optional[pd.DataFrame]:
    """CSV 파일 로드 (date 컬럼/인덱스 모두 지원)
    
    Returns:
        DataFrame with date as index, lowercase columns
    """
    try:
        df = pd.read_csv(file_path, encoding='utf-8-sig')
        
        # 컬럼명 소문자 통일
        df.columns = df.columns.str.lower()
        
        # date 컬럼 찾기
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
        else:
            # 첫 번째 컬럼이 날짜인 경우
            first_col = df.columns[0]
            if first_col in ['', 'unnamed: 0']:
                df = df.rename(columns={first_col: 'date'})
                df['date'] = pd.to_datetime(df['date'])
                df = df.set_index('date')
            else:
                # 인덱스로 다시 읽기
                df = pd.read_csv(file_path, index_col=0, parse_dates=True, encoding='utf-8-sig')
                df.columns = df.columns.str.lower()
        
        df.index.name = 'date'
        return df
        
    except Exception as e:
        logger.warning(f"CSV 로드 실패 {file_path.name}: {e}")
        return None


def update_single_stock(code: str, last_date: date, today: date) -> bool:
    """단일 종목 데이터 갱신"""
    try:
        client = get_kiwoom_client()
        days_needed = get_business_days_between(last_date, today) + 5
        prices = client.get_daily_prices(code, count=min(days_needed, 100))
        
        if not prices:
            logger.warning(f"  {code}: 데이터 없음")
            return False
        
        file_path = DATA_DIR / f"{code}.csv"
        df_existing = load_csv_with_date(file_path)
        
        if df_existing is None:
            logger.warning(f"  {code}: 기존 파일 로드 실패")
            return False
        
        new_rows = []
        for price in prices:
            price_date = pd.Timestamp(price.date)
            if price_date not in df_existing.index and price.date > last_date:
                new_rows.append({
                    'date': price_date,
                    'open': price.open,
                    'high': price.high,
                    'low': price.low,
                    'close': price.close,
                    'volume': price.volume,
                    'trading_value': price.trading_value,
                })
        
        if new_rows:
            df_new = pd.DataFrame(new_rows)
            df_new.set_index('date', inplace=True)
            
            df_combined = pd.concat([df_existing, df_new])
            df_combined.sort_index(inplace=True)
            df_combined = df_combined[~df_combined.index.duplicated(keep='last')]
            
            # A안: OHLCV만 저장 (trading_value는 계산 가능)
            keep_cols = ['open', 'high', 'low', 'close', 'volume']
            save_cols = [c for c in keep_cols if c in df_combined.columns]
            df_combined = df_combined[save_cols]
            
            df_combined.to_csv(file_path, index_label='date')
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


# ============================================
# 글로벌 데이터 갱신 (v5.4)
# ============================================

# 글로벌 지표 심볼
GLOBAL_SYMBOLS = {
    'nasdaq': 'IXIC',      # 나스닥 종합
    'dow': 'DJI',          # 다우존스
    'sp500': 'US500',      # S&P 500
    'usdkrw': 'USD/KRW',   # 원/달러 환율
    'kospi': 'KS11',       # 코스피
    'kosdaq': 'KQ11',      # 코스닥
}


def update_global_data() -> dict:
    """글로벌 지표 데이터 갱신 (나스닥, 다우, S&P500, 환율, 코스피, 코스닥)
    
    Returns:
        갱신 결과 {'updated': int, 'failed': int}
    """
    try:
        import FinanceDataReader as fdr
    except ImportError:
        logger.error("FinanceDataReader 미설치. pip install finance-datareader")
        return {'updated': 0, 'failed': len(GLOBAL_SYMBOLS)}
    
    print("=" * 50)
    print("🌍 글로벌 데이터 갱신 시작")
    print("=" * 50)
    
    today = date.today()
    
    # 디렉토리 생성
    GLOBAL_DIR.mkdir(parents=True, exist_ok=True)
    
    results = {'updated': 0, 'failed': 0}
    
    for name, symbol in GLOBAL_SYMBOLS.items():
        file_path = GLOBAL_DIR / f"{name}.csv"
        
        try:
            # 기존 데이터 확인
            if file_path.exists():
                df_existing = load_csv_with_date(file_path)
                if df_existing is not None and len(df_existing) > 0:
                    last_date = df_existing.index[-1].date()
                    
                    # 이미 최신이면 스킵
                    if last_date >= today - timedelta(days=1):
                        logger.debug(f"  {name}: 이미 최신 ({last_date})")
                        results['updated'] += 1
                        continue
                    
                    # 부족한 기간만 조회
                    start_date = last_date + timedelta(days=1)
                else:
                    df_existing = None
                    start_date = date(2016, 6, 1)
            else:
                # 신규: 2016년부터
                df_existing = None
                start_date = date(2016, 6, 1)
            
            # 데이터 조회
            df_new = fdr.DataReader(symbol, start_date, today)
            
            if df_new is None or len(df_new) == 0:
                logger.warning(f"  {name}: 신규 데이터 없음")
                results['updated'] += 1
                continue
            
            # 컬럼 정리 (소문자 통일, date 컬럼 명시)
            df_new = df_new[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
            df_new.columns = ['open', 'high', 'low', 'close', 'volume']
            df_new.index.name = 'date'
            
            # 기존 데이터와 병합
            if df_existing is not None:
                # 기존 파일도 소문자로 정규화
                df_existing.columns = df_existing.columns.str.lower()
                df_existing.index.name = 'date'
                df_combined = pd.concat([df_existing, df_new])
                df_combined = df_combined[~df_combined.index.duplicated(keep='last')]
                df_combined.sort_index(inplace=True)
            else:
                df_combined = df_new
            
            # A안: 필요한 컬럼만 저장
            keep_cols = ['open', 'high', 'low', 'close', 'volume']
            save_cols = [c for c in keep_cols if c in df_combined.columns]
            df_combined = df_combined[save_cols]
            
            # 소수점 정리 (OHLC 2자리, volume 정수)
            for col in ['open', 'high', 'low', 'close']:
                if col in df_combined.columns:
                    df_combined[col] = df_combined[col].round(2)
            if 'volume' in df_combined.columns:
                df_combined['volume'] = df_combined['volume'].clip(lower=0).astype('int64')
            
            # 저장 (date 컬럼 명시)
            df_combined.to_csv(file_path, index_label='date')
            
            new_count = len(df_new)
            logger.info(f"  ✓ {name}: {new_count}일 추가 (마지막: {df_combined.index[-1].date()})")
            results['updated'] += 1
            
        except Exception as e:
            logger.error(f"  ✗ {name}: 갱신 실패 - {e}")
            results['failed'] += 1
    
    # global_merged.csv 갱신
    try:
        update_global_merged()
    except Exception as e:
        logger.warning(f"global_merged 갱신 실패: {e}")
    
    print("=" * 50)
    print(f"🌍 글로벌 데이터 갱신 완료: 성공 {results['updated']}, 실패 {results['failed']}")
    print("=" * 50)
    
    return results


def update_global_merged():
    """글로벌 통합 데이터 갱신 (global_merged.csv)"""
    
    # 코스피 기준 (한국 거래일)
    kospi_path = GLOBAL_DIR / "kospi.csv"
    if not kospi_path.exists():
        logger.warning("kospi.csv 없음 - global_merged 스킵")
        return
    
    kospi = pd.read_csv(kospi_path)
    
    # date 컬럼 처리
    if 'date' in kospi.columns:
        kospi['date'] = pd.to_datetime(kospi['date'])
        kospi = kospi.set_index('date')
    else:
        # 첫 번째 컬럼이 날짜
        first_col = kospi.columns[0]
        kospi[first_col] = pd.to_datetime(kospi[first_col])
        kospi = kospi.set_index(first_col)
    
    # 컬럼 소문자 통일
    kospi.columns = kospi.columns.str.lower()
    
    # 각 지표 로드 및 병합
    merged = pd.DataFrame(index=kospi.index)
    merged['date_kr'] = merged.index
    
    for name in GLOBAL_SYMBOLS.keys():
        file_path = GLOBAL_DIR / f"{name}.csv"
        if file_path.exists():
            df = pd.read_csv(file_path)
            
            # date 컬럼 처리
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
                df = df.set_index('date')
            else:
                first_col = df.columns[0]
                df[first_col] = pd.to_datetime(df[first_col])
                df = df.set_index(first_col)
            
            # 컬럼 소문자 통일
            df.columns = df.columns.str.lower()
            
            # 등락률 계산
            df['change_pct'] = ((df['close'] / df['close'].shift(1)) - 1) * 100
            
            # 한국 날짜에 맞춰 병합 (미국 데이터는 +1일 매핑)
            if name in ['nasdaq', 'dow', 'sp500', 'usdkrw']:
                # 미국 데이터: 다음 한국 영업일에 영향
                df.index = df.index + pd.Timedelta(days=1)
            
            merged[f'{name}_close'] = df['close']
            merged[f'{name}_change_pct'] = df['change_pct']
    
    # 나스닥 트렌드 분류
    if 'nasdaq_change_pct' in merged.columns:
        merged['nasdaq_trend'] = merged['nasdaq_change_pct'].apply(
            lambda x: '폭등' if x >= 2 else '급등' if x >= 1 else '상승' if x > 0 
            else '하락' if x > -1 else '급락' if x > -2 else '폭락' if pd.notna(x) else 'unknown'
        )
    
    # 환율 트렌드 분류
    if 'usdkrw_change_pct' in merged.columns:
        merged['fx_trend'] = merged['usdkrw_change_pct'].apply(
            lambda x: '원화강세' if x <= -0.5 else '약보합' if x < 0 
            else '강보합' if x < 0.5 else '원화약세' if pd.notna(x) else 'unknown'
        )
    
    # NaN 제거
    merged = merged.dropna(subset=['kospi_close'])
    
    # 저장 (date 컬럼 명시)
    merged_path = GLOBAL_DIR / "global_merged.csv"
    merged.to_csv(merged_path, index_label='date')
    
    logger.info(f"  ✓ global_merged.csv: {len(merged)}일 저장")


def run_full_data_update(max_stocks: int = MAX_STOCKS_PER_RUN) -> dict:
    """OHLCV + 글로벌 데이터 전체 갱신 (v5.4)
    
    Returns:
        {'ohlcv': dict, 'global': dict}
    """
    print("\n" + "=" * 60)
    print("📊 전체 데이터 갱신 시작 (OHLCV + 글로벌)")
    print("=" * 60 + "\n")
    
    # 1. OHLCV 갱신
    ohlcv_result = run_data_update(max_stocks=max_stocks)
    
    # 2. 글로벌 데이터 갱신
    global_result = update_global_data()
    
    print("\n" + "=" * 60)
    print("📊 전체 데이터 갱신 완료")
    print(f"   OHLCV: 성공 {ohlcv_result['updated']}, 실패 {ohlcv_result['failed']}")
    print(f"   글로벌: 성공 {global_result['updated']}, 실패 {global_result['failed']}")
    print("=" * 60)
    
    return {
        'ohlcv': ohlcv_result,
        'global': global_result,
    }


# ============================================
# KIS OHLCV 수집 (정규장 기준)
# ============================================

# run_kis_data_update 제거 - run_data_update로 통합 (v7.0)


def run_kis_data_update(days: int = 5) -> dict:
    """레거시 호환 래퍼 - v7.0에서 run_data_update로 통합"""
    logger.warning("run_kis_data_update는 deprecated입니다. run_data_update를 사용하세요.")
    return run_data_update(max_stocks=MAX_STOCKS_PER_RUN)