"""
ClosingBell v6.5 백테스팅 시뮬레이션 (고성능 버전)

전략:
- 필터: 거래대금 150억+, 거래량 TOP 150, 등락률 1~29%
- 점수: v6.5 구간 최적화 (100점 만점)

v6.5 점수 체계 (구간 최적화):
- CCI: 160~180 만점, 180+ 감점
- 등락률: 4~6% 만점, 8%+ 감점  
- 이격도: 2~8% 만점, 15%+ 감점
- 연속양봉: 1~3일 만점, 5일+ 급감점

성능 최적화:
- CPU 90% 활용 (자동 감지)
- 멀티스레딩 데이터 로드
- 병렬 날짜별 처리

Usage:
    python backtest_v64.py --start 2020-01-01 --end 2025-12-31 --top 5
    python backtest_v64.py --start 2016-01-01 --end 2025-12-31 --top 10 --cpu 90
"""

import argparse
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from multiprocessing import cpu_count
import warnings
import logging
import os
import time

warnings.filterwarnings('ignore')

# ============================================================
# 설정
# ============================================================

def get_optimal_workers(cpu_percent: int = 90) -> int:
    """CPU 사용률에 따른 최적 워커 수 계산
    
    Args:
        cpu_percent: CPU 사용률 (0-100)
    
    Returns:
        워커 수
    """
    total_cores = cpu_count()
    workers = max(1, int(total_cores * cpu_percent / 100))
    return workers


@dataclass
class BacktestConfig:
    """백테스트 설정"""
    # 데이터 경로
    ohlcv_dir: Path = Path(r"C:\Coding\data\ohlcv")          # FDR (백테스팅용)
    ohlcv_kis_dir: Path = Path(r"C:\Coding\data\ohlcv_kis")  # KIS (운영용)
    stock_mapping_path: Path = Path(r"C:\Coding\data\stock_mapping.csv")
    global_data_dir: Path = Path(r"C:\Coding\data\global")
    output_dir: Path = Path(r"C:\Coding\ClosingBell\backtest_results")
    
    # 데이터 소스
    data_source: str = 'fdr'  # 백테스팅은 FDR 권장 (장기 데이터)
    
    # 필터 조건 (v6.4)
    min_trading_value: float = 150  # 최소 거래대금 (억원)
    volume_top_n: int = 150         # 거래량 상위 N위
    min_change_rate: float = 1.0    # 최소 등락률 (%)
    max_change_rate: float = 29.0   # 최대 등락률 (%)
    
    # TOP N
    top_n: int = 5                  # 선정 종목 수
    
    # 추적 일수
    tracking_days: int = 20         # 보유 기간 분석
    
    # 성능 설정 (CPU 90% 기본)
    cpu_percent: int = 90           # CPU 사용률 (%)
    num_workers: int = None         # None이면 자동 계산
    chunk_size: int = 50            # 날짜 청크 크기 (병렬 처리용)
    
    def __post_init__(self):
        if self.num_workers is None:
            self.num_workers = get_optimal_workers(self.cpu_percent)
    
    def get_active_ohlcv_dir(self) -> Path:
        if self.data_source == 'kis':
            return self.ohlcv_kis_dir
        return self.ohlcv_dir


# ============================================================
# 데이터 로더
# ============================================================

def load_single_ohlcv(file_path: Path) -> Optional[pd.DataFrame]:
    """단일 OHLCV 파일 로드"""
    try:
        df = pd.read_csv(file_path, encoding='utf-8-sig')
        df.columns = df.columns.str.lower()
        
        column_map = {
            '날짜': 'date', '일자': 'date',
            '시가': 'open', '고가': 'high', '저가': 'low',
            '종가': 'close', '거래량': 'volume', '거래대금': 'trading_value',
        }
        df = df.rename(columns=column_map)
        
        required = ['date', 'open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required):
            return None
        
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 거래대금 (억원)
        if 'trading_value' in df.columns:
            df['trading_value'] = pd.to_numeric(df['trading_value'], errors='coerce')
            median_val = df['trading_value'].median()
            if median_val > 1_000_000:
                df['trading_value'] = df['trading_value'] / 100_000_000
        else:
            df['trading_value'] = df['close'] * df['volume'] / 100_000_000
        
        # 종목코드
        code = file_path.stem.lstrip('A')
        if len(code) == 6 and code.isdigit():
            df['code'] = code
        else:
            df['code'] = file_path.stem
        
        return df[['date', 'code', 'open', 'high', 'low', 'close', 'volume', 'trading_value']]
        
    except Exception as e:
        return None


def load_all_ohlcv(config: BacktestConfig, start_date: date, end_date: date) -> Dict[str, pd.DataFrame]:
    """전체 OHLCV 데이터 로드 (멀티스레딩)"""
    ohlcv_dir = config.get_active_ohlcv_dir()
    if not ohlcv_dir.exists():
        print(f"OHLCV 디렉토리 없음: {ohlcv_dir}")
        return {}
    
    files = list(ohlcv_dir.glob("*.csv"))
    print(f"OHLCV 파일: {len(files)}개")
    print(f"멀티스레딩 워커: {config.num_workers}개 (CPU {config.cpu_percent}%)")
    
    result = {}
    loaded = 0
    start_time = time.time()
    
    def load_worker(file_path: Path) -> Tuple[str, Optional[pd.DataFrame]]:
        """워커 함수"""
        df = load_single_ohlcv(file_path)
        if df is not None and len(df) > 0:
            mask = (df['date'].dt.date >= start_date) & (df['date'].dt.date <= end_date)
            df_filtered = df[mask]
            if len(df_filtered) > 0:
                code = df_filtered['code'].iloc[0]
                return (code, df_filtered)
        return (None, None)
    
    # ThreadPoolExecutor 사용 (Windows 호환 + I/O 작업에 적합)
    with ThreadPoolExecutor(max_workers=config.num_workers) as executor:
        futures = {executor.submit(load_worker, f): f for f in files}
        
        for future in as_completed(futures):
            try:
                code, df = future.result()
                if code is not None:
                    result[code] = df
                loaded += 1
                
                if loaded % 500 == 0:
                    elapsed = time.time() - start_time
                    rate = loaded / elapsed if elapsed > 0 else 0
                    remaining = (len(files) - loaded) / rate if rate > 0 else 0
                    print(f"  로드 중... {loaded}/{len(files)} ({rate:.0f}개/초, 남은시간: {remaining:.0f}초)")
            except Exception as e:
                pass
    
    elapsed = time.time() - start_time
    print(f"로드 완료: {len(result)}개 종목 ({elapsed:.1f}초, {len(result)/elapsed:.0f}개/초)")
    return result


def load_stock_mapping(config: BacktestConfig) -> pd.DataFrame:
    """종목 매핑 로드"""
    if not config.stock_mapping_path.exists():
        return pd.DataFrame()
    
    df = pd.read_csv(config.stock_mapping_path, encoding='utf-8-sig')
    if 'stock_code' in df.columns:
        df = df.rename(columns={'stock_code': 'code', 'stock_name': 'name'})
    df['code'] = df['code'].astype(str).str.zfill(6)
    return df


def load_global_index(config: BacktestConfig, index_name: str) -> Optional[pd.DataFrame]:
    """글로벌 지수 로드"""
    index_files = {
        'NASDAQ': ['nasdaq.csv', 'NASDAQ.csv'],
        'USDKRW': ['usdkrw.csv', 'USDKRW.csv', 'USD_KRW.csv'],
    }
    
    for filename in index_files.get(index_name, []):
        file_path = config.global_data_dir / filename
        if file_path.exists():
            try:
                df = pd.read_csv(file_path, encoding='utf-8-sig')
                first_col = df.columns[0]
                if first_col == '' or first_col == 'Unnamed: 0':
                    df = df.rename(columns={first_col: 'date'})
                
                column_map = {'날짜': 'date', 'Date': 'date', '종가': 'close', 'Close': 'close'}
                df = df.rename(columns=column_map)
                
                if 'date' not in df.columns:
                    df = df.reset_index().rename(columns={'index': 'date'})
                
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date')
                
                if 'close' in df.columns:
                    df['change_rate'] = df['close'].pct_change() * 100
                    return df[['date', 'close', 'change_rate']]
            except:
                pass
    return None


# ============================================================
# 지표 계산
# ============================================================

def calculate_cci(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """CCI 계산"""
    tp = (df['high'] + df['low'] + df['close']) / 3
    sma = tp.rolling(window=period).mean()
    mad = tp.rolling(window=period).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    cci = (tp - sma) / (0.015 * mad)
    return cci


def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """모든 지표 계산"""
    result = df.copy()
    
    # 등락률
    result['change_rate'] = result['close'].pct_change() * 100
    
    # CCI
    result['cci'] = calculate_cci(result)
    result['prev_cci'] = result['cci'].shift(1)
    
    # 이동평균
    result['ma5'] = result['close'].rolling(5).mean()
    result['ma20'] = result['close'].rolling(20).mean()
    
    # MA20 상승 여부
    ma20_diff = result['ma20'].diff()
    result['ma20_3day_up'] = ((ma20_diff > 0) & (ma20_diff.shift(1) > 0) & (ma20_diff.shift(2) > 0)).astype(int)
    result['ma20_2day_up'] = ((ma20_diff > 0) & (ma20_diff.shift(1) > 0)).astype(int)
    
    # 이격도
    result['disparity_20'] = (result['close'] / result['ma20'] - 1) * 100
    
    # 거래량 비율 (당일 제외 평균)
    result['volume_ratio_19'] = result['volume'] / result['volume'].shift(1).rolling(19).mean()
    
    # 연속 양봉
    is_up = result['close'] > result['open']
    groups = (~is_up).cumsum()
    result['consecutive_up'] = is_up.groupby(groups).cumsum()
    
    # 캔들 지표
    result['is_bullish'] = (result['close'] > result['open']).astype(int)
    lower_shadow = result['open'].where(result['close'] > result['open'], result['close']) - result['low']
    result['lower_shadow_pct'] = lower_shadow / result['close'] * 100
    
    # 고가=종가 여부
    result['high_eq_close'] = ((result['high'] == result['close']) & (result['is_bullish'] == 1)).astype(int)
    
    return result


# ============================================================
# 점수 계산 (v6.4)
# ============================================================

def calc_cci_score(cci: float) -> float:
    """CCI 점수 (15점 만점) - v6.5 단순화
    
    최적 구간: 160~180 (만점)
    멀어질수록 점진적 감점
    음수: 많이 감점
    """
    if pd.isna(cci): return 7.5
    
    # 음수: 많이 감점
    if cci < 0:
        return max(0, 5 + cci * 0.05)  # 0 → 5점, -100 → 0점
    
    # 최적 구간: 160~180 (만점)
    if 160 <= cci <= 180:
        return 15.0
    
    # 160 미만: 점진적 감점 (거리에 비례)
    if cci < 160:
        distance = 160 - cci
        return max(5, 15 - distance * 0.0625)  # 160pt 떨어지면 10점 감점
    
    # 180 초과: 점진적 감점 (과열)
    distance = cci - 180
    return max(3, 15 - distance * 0.1)  # 120pt 떨어지면 12점 감점

def calc_change_score(change_rate: float) -> float:
    """등락률 점수 (15점 만점) - v6.5 단순화
    
    최적 구간: 4~6% (만점)
    멀어질수록 점진적 감점
    음수: 많이 감점
    25%+: 많이 감점 (추격매수 위험)
    """
    if pd.isna(change_rate): return 7.5
    
    # 음수: 많이 감점
    if change_rate < 0:
        return max(0, 5 + change_rate * 0.5)  # 0% → 5점, -10% → 0점
    
    # 25%+: 많이 감점 (급등 추격 위험)
    if change_rate >= 25:
        return 2.0
    
    # 최적 구간: 4~6% (만점)
    if 4 <= change_rate <= 6:
        return 15.0
    
    # 4% 미만: 점진적 감점
    if change_rate < 4:
        distance = 4 - change_rate
        return max(7, 15 - distance * 2)  # 4pt 떨어지면 8점 감점
    
    # 6% 초과: 점진적 감점 (추격매수 위험 증가)
    distance = change_rate - 6
    return max(3, 15 - distance * 0.63)  # 19pt 떨어지면 12점 감점

def calc_distance_score(distance: float) -> float:
    """이격도 점수 (15점 만점) - v6.5 단순화
    
    최적 구간: 2~8% (만점)
    멀어질수록 점진적 감점
    음수: 많이 감점 (MA20 아래)
    """
    if pd.isna(distance): return 7.5
    
    # 음수: 많이 감점 (MA20 아래 = 약세)
    if distance < 0:
        return max(0, 5 + distance * 0.5)  # 0% → 5점, -10% → 0점
    
    # 최적 구간: 2~8% (만점)
    if 2 <= distance <= 8:
        return 15.0
    
    # 2% 미만: 점진적 감점 (아직 덜 올랐음)
    if distance < 2:
        return max(10, 15 - (2 - distance) * 2.5)  # 2pt 떨어지면 5점 감점
    
    # 8% 초과: 점진적 감점 (과열)
    return max(3, 15 - (distance - 8) * 0.6)  # 20pt 떨어지면 12점 감점

def calc_consec_score(consec_days: int) -> float:
    """연속양봉 점수 (15점 만점) - v6.5 단순화
    
    최적 구간: 2~3일 (만점)
    멀어질수록 점진적 감점
    """
    if pd.isna(consec_days): consec_days = 0
    consec_days = int(consec_days)
    
    # 최적 구간: 2~3일 (만점)
    if 2 <= consec_days <= 3:
        return 15.0
    
    # 0~1일: 점진적 감점 (모멘텀 부족)
    if consec_days < 2:
        return 7 + consec_days * 4  # 0일 → 7점, 1일 → 11점
    
    # 4일+: 점진적 감점 (과열/급락 위험)
    return max(2, 15 - (consec_days - 3) * 3)  # 4일 → 12점, 5일 → 9점, 6일 → 6점

def calc_volume_score(volume_ratio: float) -> float:
    if pd.isna(volume_ratio) or volume_ratio < 1: return 0.0
    return max(0, min(1, (volume_ratio - 1) / 4)) * 15

def calc_candle_score(is_bullish: int, lower_shadow_pct: float) -> float:
    if pd.isna(is_bullish): is_bullish = 0
    if pd.isna(lower_shadow_pct): lower_shadow_pct = 0.0
    bullish_score = 1.0 if is_bullish else 0.0
    lower_score = min(lower_shadow_pct / 3, 1.0)
    return (bullish_score * 0.5 + lower_score * 0.5) * 15


def calculate_score(row: pd.Series) -> float:
    """종목 점수 계산 (100점 만점)"""
    # 기본 점수 (90점)
    cci_score = calc_cci_score(row.get('cci'))
    change_score = calc_change_score(row.get('change_rate'))
    distance_score = calc_distance_score(row.get('disparity_20'))
    consec_score = calc_consec_score(row.get('consecutive_up'))
    volume_score = calc_volume_score(row.get('volume_ratio_19'))
    candle_score = calc_candle_score(row.get('is_bullish', 0), row.get('lower_shadow_pct', 0))
    
    base_score = cci_score + change_score + distance_score + consec_score + volume_score + candle_score
    
    # 보너스 (10점)
    bonus = 0.0
    
    # CCI 상승 보너스 (4점)
    cci = row.get('cci')
    prev_cci = row.get('prev_cci')
    if not pd.isna(cci) and not pd.isna(prev_cci) and cci > prev_cci:
        rise = cci - prev_cci
        if rise > 20: bonus += 4.0
        elif rise > 10: bonus += 3.5
        elif rise > 5: bonus += 3.0
        else: bonus += 2.5
    
    # MA20 3일 상승 보너스 (3점)
    if row.get('ma20_3day_up', 0) == 1:
        bonus += 3.0
    elif row.get('ma20_2day_up', 0) == 1:
        bonus += 1.5
    
    # 고가≠종가 보너스 (3점)
    if row.get('high_eq_close', 0) == 0:
        bonus += 3.0
    
    return min(100.0, base_score + bonus)


def score_to_grade(score: float) -> str:
    if score >= 85: return 'S'
    elif score >= 75: return 'A'
    elif score >= 65: return 'B'
    elif score >= 55: return 'C'
    else: return 'D'


# ============================================================
# 백테스팅 엔진 (병렬 처리)
# ============================================================

@dataclass
class TradeResult:
    """거래 결과"""
    trade_date: date           # 매수일
    code: str                  # 종목코드
    name: str                  # 종목명
    rank: int                  # 순위 (1~5)
    score: float               # 점수
    grade: str                 # 등급
    buy_price: float           # 매수가 (당일 종가)
    
    # 수익률
    next_open_return: float = 0.0    # 익일 시가 수익률
    next_close_return: float = 0.0   # 익일 종가 수익률
    day3_return: float = 0.0         # 3일 후 종가 수익률
    day5_return: float = 0.0         # 5일 후 종가 수익률
    day10_return: float = 0.0        # 10일 후 종가 수익률
    day20_return: float = 0.0        # 20일 후 종가 수익률
    max_return: float = 0.0          # 20일 내 최대 수익률
    min_return: float = 0.0          # 20일 내 최소 수익률 (MDD)


def process_single_date(args) -> List[dict]:
    """단일 날짜 처리 (워커 함수)"""
    trade_date, day_data, all_data, name_map, config = args
    
    results = []
    
    if len(day_data) == 0:
        return results
    
    # 1. 필터링: 거래대금 150억+
    filtered = day_data[day_data['trading_value'] >= config['min_trading_value']]
    
    # 2. 필터링: 등락률 1~29%
    filtered = filtered[
        (filtered['change_rate'] >= config['min_change_rate']) &
        (filtered['change_rate'] < config['max_change_rate'])
    ]
    
    # 3. 필터링: 거래량 TOP 150
    if len(filtered) > config['volume_top_n']:
        filtered = filtered.nlargest(config['volume_top_n'], 'volume')
    
    if len(filtered) == 0:
        return results
    
    # 4. 점수 계산
    filtered = filtered.copy()
    filtered['score'] = filtered.apply(calculate_score, axis=1)
    filtered['grade'] = filtered['score'].apply(score_to_grade)
    
    # 5. TOP N 선정
    top_stocks = filtered.nlargest(config['top_n'], 'score')
    
    # 6. 수익률 계산
    for rank, (idx, row) in enumerate(top_stocks.iterrows(), 1):
        code = row['code']
        buy_price = row['close']
        
        # 해당 종목의 미래 데이터
        stock_future = all_data.get(code)
        if stock_future is None:
            continue
        
        future_data = stock_future[stock_future['date'].dt.date > trade_date].sort_values('date')
        
        if len(future_data) == 0:
            continue
        
        # 익일 시가/종가
        next_day = future_data.iloc[0] if len(future_data) > 0 else None
        next_open_return = (next_day['open'] / buy_price - 1) * 100 if next_day is not None else 0
        next_close_return = (next_day['close'] / buy_price - 1) * 100 if next_day is not None else 0
        
        # N일 후 수익률
        day3_return = (future_data.iloc[2]['close'] / buy_price - 1) * 100 if len(future_data) > 2 else 0
        day5_return = (future_data.iloc[4]['close'] / buy_price - 1) * 100 if len(future_data) > 4 else 0
        day10_return = (future_data.iloc[9]['close'] / buy_price - 1) * 100 if len(future_data) > 9 else 0
        day20_return = (future_data.iloc[19]['close'] / buy_price - 1) * 100 if len(future_data) > 19 else 0
        
        # 20일 내 최대/최소 수익률
        future_20 = future_data.head(20)
        if len(future_20) > 0:
            max_price = future_20['high'].max()
            min_price = future_20['low'].min()
            max_return = (max_price / buy_price - 1) * 100
            min_return = (min_price / buy_price - 1) * 100
        else:
            max_return = 0
            min_return = 0
        
        results.append({
            'trade_date': trade_date,
            'code': code,
            'name': name_map.get(code, code),
            'rank': rank,
            'score': row['score'],
            'grade': row['grade'],
            'buy_price': buy_price,
            'next_open_return': next_open_return,
            'next_close_return': next_close_return,
            'day3_return': day3_return,
            'day5_return': day5_return,
            'day10_return': day10_return,
            'day20_return': day20_return,
            'max_return': max_return,
            'min_return': min_return,
        })
    
    return results


def run_backtest(
    config: BacktestConfig,
    all_data: Dict[str, pd.DataFrame],
    stock_mapping: pd.DataFrame,
    start_date: date,
    end_date: date,
) -> List[TradeResult]:
    """백테스팅 실행 (병렬 처리)"""
    
    start_time = time.time()
    
    # 종목명 딕셔너리
    name_map = dict(zip(stock_mapping['code'], stock_mapping['name'])) if len(stock_mapping) > 0 else {}
    
    # 모든 날짜의 데이터를 합침 + 지표 계산
    print("데이터 병합 및 지표 계산 중...")
    indicator_start = time.time()
    
    all_rows = []
    processed = 0
    
    # 지표 계산도 병렬로
    def calc_indicators(item):
        code, df = item
        df_ind = calculate_all_indicators(df)
        df_ind['code'] = code
        return df_ind
    
    with ThreadPoolExecutor(max_workers=config.num_workers) as executor:
        futures = [executor.submit(calc_indicators, item) for item in all_data.items()]
        
        for future in as_completed(futures):
            try:
                df_ind = future.result()
                all_rows.append(df_ind)
                processed += 1
                
                if processed % 500 == 0:
                    print(f"  지표 계산 중... {processed}/{len(all_data)}")
            except:
                pass
    
    combined = pd.concat(all_rows, ignore_index=True)
    combined['trade_date'] = combined['date'].dt.date
    
    print(f"지표 계산 완료: {time.time() - indicator_start:.1f}초")
    
    # 거래일 목록
    trading_days = sorted(combined['trade_date'].unique())
    trading_days = [d for d in trading_days if start_date <= d <= end_date]
    
    print(f"거래일: {len(trading_days)}일 ({trading_days[0]} ~ {trading_days[-1]})")
    print(f"병렬 처리: {config.num_workers}개 워커 (CPU {config.cpu_percent}%)")
    
    # 날짜별 데이터 미리 분리
    date_groups = {d: combined[combined['trade_date'] == d].copy() for d in trading_days}
    
    # config를 dict로 변환 (pickle 가능하게)
    config_dict = {
        'min_trading_value': config.min_trading_value,
        'min_change_rate': config.min_change_rate,
        'max_change_rate': config.max_change_rate,
        'volume_top_n': config.volume_top_n,
        'top_n': config.top_n,
    }
    
    # 병렬 처리
    all_results = []
    backtest_start = time.time()
    
    # 청크 단위로 처리 (메모리 효율)
    chunk_size = config.chunk_size
    total_chunks = (len(trading_days) + chunk_size - 1) // chunk_size
    
    for chunk_idx in range(total_chunks):
        chunk_start = chunk_idx * chunk_size
        chunk_end = min(chunk_start + chunk_size, len(trading_days))
        chunk_dates = trading_days[chunk_start:chunk_end]
        
        # 이 청크의 날짜들에 대해 병렬 처리
        args_list = [
            (d, date_groups[d], all_data, name_map, config_dict)
            for d in chunk_dates
        ]
        
        with ThreadPoolExecutor(max_workers=config.num_workers) as executor:
            futures = [executor.submit(process_single_date, args) for args in args_list]
            
            for future in as_completed(futures):
                try:
                    results = future.result()
                    all_results.extend(results)
                except Exception as e:
                    pass
        
        # 진행률 표시
        processed_days = chunk_end
        elapsed = time.time() - backtest_start
        rate = processed_days / elapsed if elapsed > 0 else 0
        remaining = (len(trading_days) - processed_days) / rate if rate > 0 else 0
        print(f"  백테스트 진행: {processed_days}/{len(trading_days)}일 "
              f"({rate:.1f}일/초, 남은시간: {remaining:.0f}초)")
    
    # TradeResult 객체로 변환
    results = [TradeResult(**r) for r in all_results]
    
    total_time = time.time() - start_time
    print(f"\n총 소요시간: {total_time:.1f}초 ({len(results)}건 처리)")
    
    return results


# ============================================================
# 분석 및 리포트
# ============================================================

def analyze_results(results: List[TradeResult], config: BacktestConfig) -> pd.DataFrame:
    """결과 분석"""
    df = pd.DataFrame([vars(r) for r in results])
    
    if len(df) == 0:
        print("결과 없음")
        return df
    
    print("\n" + "=" * 70)
    print(f"📊 ClosingBell v6.4 백테스팅 결과")
    print("=" * 70)
    
    # 기본 통계
    print(f"\n📈 기본 통계")
    print(f"  - 총 거래일: {df['trade_date'].nunique()}일")
    print(f"  - 총 거래: {len(df)}건 (일평균 {len(df) / df['trade_date'].nunique():.1f}건)")
    print(f"  - 분석 기간: {df['trade_date'].min()} ~ {df['trade_date'].max()}")
    
    # 수익률 분석
    print(f"\n💰 수익률 분석 (종가 매수 기준)")
    print(f"  {'구분':12} {'평균':>8} {'승률':>8} {'최대':>8} {'최소':>8}")
    print(f"  {'-'*48}")
    
    metrics = [
        ('익일 시가', 'next_open_return'),
        ('익일 종가', 'next_close_return'),
        ('3일 후', 'day3_return'),
        ('5일 후', 'day5_return'),
        ('10일 후', 'day10_return'),
        ('20일 후', 'day20_return'),
        ('20일 최대', 'max_return'),
    ]
    
    for name, col in metrics:
        avg = df[col].mean()
        win_rate = (df[col] > 0).mean() * 100
        max_val = df[col].max()
        min_val = df[col].min()
        print(f"  {name:12} {avg:+7.2f}% {win_rate:6.1f}% {max_val:+7.1f}% {min_val:+7.1f}%")
    
    # 등급별 분석
    print(f"\n🏆 등급별 분석 (익일 시가 기준)")
    print(f"  {'등급':6} {'건수':>8} {'평균':>8} {'승률':>8}")
    print(f"  {'-'*36}")
    
    for grade in ['S', 'A', 'B', 'C', 'D']:
        grade_df = df[df['grade'] == grade]
        if len(grade_df) > 0:
            count = len(grade_df)
            avg = grade_df['next_open_return'].mean()
            win_rate = (grade_df['next_open_return'] > 0).mean() * 100
            print(f"  {grade:6} {count:8} {avg:+7.2f}% {win_rate:6.1f}%")
    
    # 순위별 분석
    print(f"\n📊 순위별 분석 (익일 시가 기준)")
    print(f"  {'순위':6} {'건수':>8} {'평균':>8} {'승률':>8}")
    print(f"  {'-'*36}")
    
    for rank in range(1, config.top_n + 1):
        rank_df = df[df['rank'] == rank]
        if len(rank_df) > 0:
            count = len(rank_df)
            avg = rank_df['next_open_return'].mean()
            win_rate = (rank_df['next_open_return'] > 0).mean() * 100
            print(f"  #{rank:5} {count:8} {avg:+7.2f}% {win_rate:6.1f}%")
    
    # 연도별 분석
    df['year'] = pd.to_datetime(df['trade_date']).dt.year
    
    print(f"\n📅 연도별 분석 (익일 시가 기준)")
    print(f"  {'연도':6} {'거래':>8} {'평균':>8} {'승률':>8}")
    print(f"  {'-'*36}")
    
    for year in sorted(df['year'].unique()):
        year_df = df[df['year'] == year]
        count = len(year_df)
        avg = year_df['next_open_return'].mean()
        win_rate = (year_df['next_open_return'] > 0).mean() * 100
        print(f"  {year:6} {count:8} {avg:+7.2f}% {win_rate:6.1f}%")
    
    # 월별 분석
    df['month'] = pd.to_datetime(df['trade_date']).dt.month
    
    print(f"\n📆 월별 분석 (익일 시가 기준)")
    print(f"  {'월':6} {'거래':>8} {'평균':>8} {'승률':>8}")
    print(f"  {'-'*36}")
    
    for month in range(1, 13):
        month_df = df[df['month'] == month]
        if len(month_df) > 0:
            count = len(month_df)
            avg = month_df['next_open_return'].mean()
            win_rate = (month_df['next_open_return'] > 0).mean() * 100
            print(f"  {month:2}월    {count:8} {avg:+7.2f}% {win_rate:6.1f}%")
    
    print("\n" + "=" * 70)
    
    return df


def main():
    parser = argparse.ArgumentParser(description='ClosingBell v6.4 백테스팅 (고성능)')
    parser.add_argument('--start', type=str, default='2020-01-01', help='시작일 (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, default='2025-12-31', help='종료일 (YYYY-MM-DD)')
    parser.add_argument('--top', type=int, default=5, help='TOP N')
    parser.add_argument('--source', type=str, default='fdr', choices=['fdr', 'kis'], help='데이터 소스')
    parser.add_argument('--cpu', type=int, default=90, help='CPU 사용률 (%%)')
    parser.add_argument('--chunk', type=int, default=50, help='청크 크기')
    parser.add_argument('--output', type=str, default=None, help='결과 CSV 경로')
    
    args = parser.parse_args()
    
    # 설정
    config = BacktestConfig()
    config.data_source = args.source
    config.top_n = args.top
    config.cpu_percent = args.cpu
    config.chunk_size = args.chunk
    config.num_workers = get_optimal_workers(config.cpu_percent)
    
    start_date = datetime.strptime(args.start, '%Y-%m-%d').date()
    end_date = datetime.strptime(args.end, '%Y-%m-%d').date()
    
    print(f"\n{'='*70}")
    print(f"📊 ClosingBell v6.4 백테스팅 (고성능 버전)")
    print(f"{'='*70}")
    print(f"  기간: {start_date} ~ {end_date}")
    print(f"  TOP N: {config.top_n}")
    print(f"  데이터: {config.data_source} ({config.get_active_ohlcv_dir()})")
    print(f"  필터: 거래대금≥{config.min_trading_value}억, 거래량TOP{config.volume_top_n}, 등락률{config.min_change_rate}~{config.max_change_rate}%")
    print(f"  ")
    print(f"  🚀 성능 설정:")
    print(f"     CPU 사용률: {config.cpu_percent}%")
    print(f"     워커 수: {config.num_workers}개 (총 {cpu_count()}코어)")
    print(f"     청크 크기: {config.chunk_size}일")
    print(f"{'='*70}\n")
    
    # 데이터 로드
    print("📂 데이터 로드 중...")
    all_data = load_all_ohlcv(config, start_date - timedelta(days=60), end_date + timedelta(days=30))
    
    if len(all_data) == 0:
        print("❌ OHLCV 데이터 없음")
        return
    
    stock_mapping = load_stock_mapping(config)
    print(f"종목 매핑: {len(stock_mapping)}개")
    
    # 백테스팅 실행
    print("\n🔄 백테스팅 실행 중...")
    results = run_backtest(config, all_data, stock_mapping, start_date, end_date)
    
    # 분석
    df = analyze_results(results, config)
    
    # 결과 저장
    if args.output:
        output_path = Path(args.output)
    else:
        config.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = config.output_dir / f"backtest_v64_{args.start}_{args.end}.csv"
    
    df.to_csv(output_path, index=False, encoding='utf-8-sig')
    print(f"\n💾 결과 저장: {output_path}")


if __name__ == '__main__':
    main()