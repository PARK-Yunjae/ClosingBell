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
        
        # 컬럼명 정규화 (소문자 통일)
        df.columns = df.columns.str.lower()
        
        column_map = {
            '날짜': 'date', '일자': 'date',
            '시가': 'open',
            '고가': 'high',
            '저가': 'low',
            '종가': 'close',
            '거래량': 'volume',
            '거래대금': 'trading_value',
            'tradingvalue': 'trading_value',
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
        
        # 거래대금 (있으면 사용, 없으면 계산)
        if 'trading_value' in df.columns:
            df['trading_value'] = pd.to_numeric(df['trading_value'], errors='coerce')
            # v6.3.4: 거래대금 단위 통일 (항상 억원)
            # KIS API/FDR 데이터는 원 단위로 저장됨
            # 첫 행이 아닌 평균/중간값으로 판단하여 안정성 확보
            median_val = df['trading_value'].median()
            if median_val > 1_000_000:  # 중간값이 100만 이상이면 원 단위로 판단
                df['trading_value'] = df['trading_value'] / 100_000_000  # 원 → 억원
                logger.debug(f"거래대금 변환: 원 → 억원 (median: {median_val:.0f})")
        else:
            # 거래대금 = 종가 × 거래량 → 억원 단위로 변환
            df['trading_value'] = df['close'] * df['volume'] / 100_000_000
        
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
        
        return df[['date', 'code', 'open', 'high', 'low', 'close', 'volume', 'trading_value']]
        
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
        'USDKRW': ['usdkrw.csv', 'USDKRW.csv', 'USD_KRW.csv', 'usd_krw.csv', 'fx.csv'],
        'USD_KRW': ['usdkrw.csv', 'USDKRW.csv', 'USD_KRW.csv', 'usd_krw.csv'],
    }
    
    candidates = index_files.get(index_name, [f'{index_name}.csv'])
    
    for filename in candidates:
        file_path = config.global_data_dir / filename
        if file_path.exists():
            try:
                df = pd.read_csv(file_path, encoding='utf-8-sig')
                
                # 첫 번째 컬럼이 인덱스(날짜)인 경우 처리
                first_col = df.columns[0]
                if first_col == '' or first_col == 'Unnamed: 0':
                    df = df.rename(columns={first_col: 'date'})
                
                # 컬럼명 정규화
                column_map = {
                    '날짜': 'date', '일자': 'date', 'Date': 'date',
                    '종가': 'close', 'Close': 'close', '지수': 'close',
                }
                df = df.rename(columns=column_map)
                
                # date 컬럼이 없으면 인덱스 사용
                if 'date' not in df.columns:
                    df = df.reset_index()
                    df = df.rename(columns={'index': 'date'})
                
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date')
                
                if 'close' in df.columns:
                    df['change_rate'] = df['close'].pct_change() * 100
                    logger.info(f"지수 로드 성공: {index_name} ({len(df)}일)")
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
    """종목 필터링 (v6.4 거래량 TOP 방식)
    
    필터 조건:
    1. 거래대금 150억 이상
    2. 거래량 상위 150위
    3. 등락률 1% ~ 29%
    
    CCI/ETF/스팩 필터는 제거됨 (점수제에서 자연 반영)
    
    Args:
        df: OHLCV 데이터 (해당 날짜의 모든 종목)
        config: 백필 설정
        stock_mapping: 종목 매핑 (이름 조회용)
        
    Returns:
        필터링된 DataFrame
    """
    if config is None:
        config = get_backfill_config()
    
    result = df.copy()
    initial_count = len(result)
    
    # 1. 가격 필터 (min_price=0이면 실질적으로 비활성화)
    if config.min_price > 0:
        result = result[result['close'] >= config.min_price]
    
    # 2. 거래대금 필터 (150억 이상)
    if 'trading_value' in result.columns:
        result = result[result['trading_value'] >= config.min_trading_value]
    
    # 3. 등락률 필터 (1% ~ 29%)
    if 'change_rate' in result.columns:
        result = result[
            (result['change_rate'] >= config.min_change_rate) &
            (result['change_rate'] < config.max_change_rate)
        ]
    
    # 4. 거래량 상위 N위 필터 (v6.4 핵심!)
    if 'volume' in result.columns and config.volume_top_n > 0:
        # 거래량 기준 내림차순 정렬 후 상위 N개만
        result = result.nlargest(config.volume_top_n, 'volume')
    
    # 5. CCI 필터 (v6.4: 비활성화)
    if config.use_cci_filter and 'cci' in result.columns:
        result = result[
            (result['cci'] >= config.min_cci) &
            (result['cci'] < config.max_cci)
        ]
    
    # 6. ETF/스팩 제외 (v6.4: 비활성화 - exclude_patterns가 빈 리스트)
    if stock_mapping is not None and config.exclude_patterns:
        # 종목명 조인
        if 'name' not in result.columns:
            result = result.merge(
                stock_mapping[['code', 'name']], 
                on='code', 
                how='left'
            )
        
        # 제외 패턴 적용
        for pattern in config.exclude_patterns:
            mask = result['name'].str.contains(pattern, case=False, na=False)
            result = result[~mask]
    
    logger.debug(f"필터링: {initial_count} → {len(result)}개 "
                 f"(거래대금≥{config.min_trading_value}억, "
                 f"거래량TOP{config.volume_top_n}, "
                 f"등락률{config.min_change_rate}~{config.max_change_rate}%)")
    
    return result