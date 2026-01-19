"""
ClosingBell v6.0 백필 - 데이터 로더

OHLCV 파일 로드 (멀티프로세싱 지원)
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import date, datetime, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed
import logging

from src.config.backfill_config import BackfillConfig, get_backfill_config

logger = logging.getLogger(__name__)


def load_stock_mapping(config: Optional[BackfillConfig] = None) -> pd.DataFrame:
    """종목 매핑 로드
    
    Returns:
        DataFrame with columns: code, name, market
    """
    if config is None:
        config = get_backfill_config()
    
    if not config.stock_mapping_path.exists():
        logger.error(f"종목 매핑 파일 없음: {config.stock_mapping_path}")
        return pd.DataFrame()
    
    df = pd.read_csv(config.stock_mapping_path, encoding='utf-8-sig')
    
    # 컬럼명 정규화
    if 'stock_code' in df.columns:
        df = df.rename(columns={'stock_code': 'code', 'stock_name': 'name'})
    
    # 종목코드 6자리 패딩
    df['code'] = df['code'].astype(str).str.zfill(6)
    
    return df


def load_single_ohlcv(file_path: Path) -> Optional[pd.DataFrame]:
    """단일 OHLCV 파일 로드
    
    Args:
        file_path: CSV 파일 경로
        
    Returns:
        DataFrame with columns: date, open, high, low, close, volume
    """
    try:
        df = pd.read_csv(file_path, encoding='utf-8-sig')
        
        # 컬럼명 정규화
        column_map = {
            '날짜': 'date', '일자': 'date', 'Date': 'date',
            '시가': 'open', 'Open': 'open',
            '고가': 'high', 'High': 'high',
            '저가': 'low', 'Low': 'low',
            '종가': 'close', 'Close': 'close',
            '거래량': 'volume', 'Volume': 'volume',
        }
        df = df.rename(columns=column_map)
        
        # 필수 컬럼 확인
        required = ['date', 'open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required):
            logger.warning(f"필수 컬럼 누락: {file_path}")
            return None
        
        # 날짜 파싱
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        
        # 수치형 변환
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 종목코드 추출 (파일명에서)
        code = file_path.stem
        if len(code) == 6 and code.isdigit():
            df['code'] = code
        else:
            # A005930 형식일 수도 있음
            code = code.lstrip('A')
            if len(code) == 6 and code.isdigit():
                df['code'] = code
            else:
                df['code'] = file_path.stem
        
        return df[['date', 'code', 'open', 'high', 'low', 'close', 'volume']]
        
    except Exception as e:
        logger.error(f"파일 로드 실패 {file_path}: {e}")
        return None


def _load_file_worker(args: Tuple[Path, date, date]) -> Optional[pd.DataFrame]:
    """워커 함수 (멀티프로세싱용)"""
    file_path, start_date, end_date = args
    
    df = load_single_ohlcv(file_path)
    if df is None:
        return None
    
    # 날짜 필터
    mask = (df['date'].dt.date >= start_date) & (df['date'].dt.date <= end_date)
    return df[mask]


def load_all_ohlcv(
    config: Optional[BackfillConfig] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    codes: Optional[List[str]] = None,
    num_workers: int = 10,
) -> Dict[str, pd.DataFrame]:
    """전체 OHLCV 데이터 로드 (멀티프로세싱)
    
    Args:
        config: 백필 설정
        start_date: 시작 날짜
        end_date: 종료 날짜
        codes: 로드할 종목코드 (None이면 전체)
        num_workers: 워커 수
        
    Returns:
        {종목코드: DataFrame} 딕셔너리
    """
    if config is None:
        config = get_backfill_config()
    
    if end_date is None:
        end_date = date.today()
    
    if start_date is None:
        start_date = end_date - timedelta(days=365)  # 기본 1년
    
    # 파일 목록
    files = config.get_ohlcv_files()
    
    if codes:
        # 특정 종목만 필터
        codes_set = set(codes)
        files = [f for f in files if f.stem in codes_set or f.stem.lstrip('A') in codes_set]
    
    logger.info(f"OHLCV 파일 로드: {len(files)}개, {start_date} ~ {end_date}")
    
    # 멀티프로세싱
    result = {}
    args_list = [(f, start_date, end_date) for f in files]
    
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = {executor.submit(_load_file_worker, args): args[0] for args in args_list}
        
        for future in as_completed(futures):
            file_path = futures[future]
            try:
                df = future.result()
                if df is not None and len(df) > 0:
                    code = df['code'].iloc[0]
                    result[code] = df
            except Exception as e:
                logger.error(f"워커 오류 {file_path}: {e}")
    
    logger.info(f"로드 완료: {len(result)}개 종목")
    return result


def load_global_index(
    config: Optional[BackfillConfig] = None,
    index_name: str = 'KOSPI',
) -> Optional[pd.DataFrame]:
    """글로벌 지수 데이터 로드
    
    Args:
        config: 백필 설정
        index_name: 지수 이름 (KOSPI, KOSDAQ, NASDAQ, etc.)
        
    Returns:
        DataFrame with columns: date, close, change_rate
    """
    if config is None:
        config = get_backfill_config()
    
    # 지수 파일 찾기
    index_files = {
        'KOSPI': ['kospi.csv', 'KOSPI.csv', 'kospi_index.csv'],
        'KOSDAQ': ['kosdaq.csv', 'KOSDAQ.csv', 'kosdaq_index.csv'],
        'NASDAQ': ['nasdaq.csv', 'NASDAQ.csv', 'nasdaq_index.csv'],
        'SP500': ['sp500.csv', 'SP500.csv', 's&p500.csv'],
    }
    
    candidates = index_files.get(index_name, [f'{index_name}.csv'])
    
    for filename in candidates:
        file_path = config.global_data_dir / filename
        if file_path.exists():
            try:
                df = pd.read_csv(file_path, encoding='utf-8-sig')
                
                # 컬럼명 정규화
                column_map = {
                    '날짜': 'date', '일자': 'date', 'Date': 'date',
                    '종가': 'close', 'Close': 'close', '지수': 'close',
                }
                df = df.rename(columns=column_map)
                
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date')
                
                if 'close' in df.columns:
                    df['change_rate'] = df['close'].pct_change() * 100
                    return df[['date', 'close', 'change_rate']]
                    
            except Exception as e:
                logger.error(f"지수 파일 로드 실패 {file_path}: {e}")
    
    logger.warning(f"지수 파일 없음: {index_name}")
    return None


def get_trading_days(
    config: Optional[BackfillConfig] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> List[date]:
    """거래일 목록 반환
    
    KOSPI 지수 데이터 기준으로 거래일 판단
    """
    if config is None:
        config = get_backfill_config()
    
    # KOSPI 지수 로드
    kospi = load_global_index(config, 'KOSPI')
    
    if kospi is None or len(kospi) == 0:
        logger.warning("KOSPI 지수 데이터 없음 - 기본 거래일 사용")
        # 주말 제외한 날짜 반환
        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=60)
        
        dates = []
        current = start_date
        while current <= end_date:
            if current.weekday() < 5:  # 월~금
                dates.append(current)
            current += timedelta(days=1)
        return dates
    
    # KOSPI 데이터 기준 거래일
    kospi['trade_date'] = kospi['date'].dt.date
    trading_days = kospi['trade_date'].tolist()
    
    # 날짜 필터
    if start_date:
        trading_days = [d for d in trading_days if d >= start_date]
    if end_date:
        trading_days = [d for d in trading_days if d <= end_date]
    
    return sorted(trading_days)


def filter_stocks(
    df: pd.DataFrame,
    config: Optional[BackfillConfig] = None,
    stock_mapping: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """종목 필터링 (ETF, 저가주 등 제외)
    
    Args:
        df: OHLCV 데이터
        config: 백필 설정
        stock_mapping: 종목 매핑 (이름 조회용)
        
    Returns:
        필터링된 DataFrame
    """
    if config is None:
        config = get_backfill_config()
    
    result = df.copy()
    
    # 가격 필터
    result = result[result['close'] >= config.min_price]
    
    # 거래대금 필터
    if 'trading_value' in result.columns:
        result = result[result['trading_value'] >= config.min_trading_value]
    
    # ETF 등 제외 (종목명 기준)
    if stock_mapping is not None:
        # 종목명 조인
        if 'name' not in result.columns:
            result = result.merge(
                stock_mapping[['code', 'name']], 
                on='code', 
                how='left'
            )
        
        # 제외 패턴
        for pattern in config.exclude_patterns:
            mask = result['name'].str.contains(pattern, case=False, na=False)
            result = result[~mask]
    
    return result
