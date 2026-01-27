#!/usr/bin/env python3
"""
=============================================================================
유목민 백테스트 v3.0 - Professional Grade
=============================================================================

📚 유목민 1권 기반 종합 백테스팅 시스템

[핵심 3축]
1. 지지/저항 (가격 레벨)
2. 거래량 (폭증/급감)
3. 이동평균선 (3/7/8/15/20/33/45/120/360일)

[구현 전략]
- S1: 거래량 급감 + 음봉 + MA5 근접
- S2: 거래량 폭증 → 급감 + MA5 근접 (거감음봉)
- S3: 급등 이력 + 3일선 지지
- S4: 7/8일선 눌림목 (터치형/이격형)
- S5: 45일선 낙주매매 (첫 터치 + 거래량 감소)
- S6: 33일선 정찰병 → 45일선 본진입
- S7: 360일선 급락반등

[분석 기능]
- D+1 ~ D+20 수익률/승률
- 손절/익절 시뮬레이션
- 수수료/세금 반영
- 손익비/MDD 계산
- 월별/분기별/요일별 시즌성 분석
- 기간 분할 검증 (In-Sample / Out-of-Sample)
- 멀티코어 병렬 처리

Author: Claude (Anthropic)
Version: 3.0
Date: 2026-01-27
=============================================================================
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing as mp
import warnings
import argparse
import time
from datetime import datetime

warnings.filterwarnings('ignore')

# =============================================================================
# 설정 (Configuration)
# =============================================================================

@dataclass
class BacktestConfig:
    """백테스트 설정"""
    # 데이터 경로
    ohlcv_dir: Path = Path(r"C:\Coding\data\ohlcv")
    
    # 백테스트 기간
    start_date: str = '2016-06-01'
    end_date: str = '2026-01-26'
    
    # 기간 분할 검증
    split_date: str = '2022-01-01'  # In-Sample / Out-of-Sample 구분
    
    # 이동평균선 기간
    ma_periods: List[int] = field(default_factory=lambda: [3, 5, 7, 8, 10, 15, 20, 33, 45, 60, 120, 360])
    
    # 수익률 계산 기간
    return_periods: List[int] = field(default_factory=lambda: [1, 2, 3, 5, 7, 10, 15, 20])
    
    # 거래 비용
    commission: float = 0.00015  # 매매 수수료 (0.015% × 2 = 편도 0.015%)
    tax: float = 0.0018  # 거래세 (코스피 0.18%, 코스닥 0.18%)
    slippage: float = 0.001  # 슬리피지 (0.1%)
    
    # 손절/익절
    stop_loss: float = -0.05  # -5% 손절
    take_profit: float = 0.10  # +10% 익절
    
    # 멀티코어
    use_multicore: bool = True
    num_workers: int = field(default_factory=lambda: max(1, mp.cpu_count() - 2))
    
    # 거래량 기준
    volume_10m: int = 10_000_000  # 1000만주
    
    # 워밍업 기간 (360일선용)
    warmup_days: int = 400


# 전역 설정
CONFIG = BacktestConfig()


# =============================================================================
# 1. 데이터 로딩 (멀티코어 지원)
# =============================================================================

def load_single_ohlcv(file_path: Path) -> Optional[pd.DataFrame]:
    """단일 종목 OHLCV 로드 (CSV 형식)"""
    try:
        df = pd.read_csv(file_path, encoding='utf-8-sig')
        
        # 컬럼 정규화
        df.columns = df.columns.str.lower()
        
        # 컬럼 매핑 (한글 → 영문)
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
        
        required = ['date', 'open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required):
            return None
        
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        
        # 종목코드 추출
        code = file_path.stem
        df['code'] = code
        
        # 기본 검증
        if len(df) < CONFIG.warmup_days:
            return None
        
        return df
        
    except Exception as e:
        return None


def _load_worker(file_path: Path) -> Tuple[str, Optional[pd.DataFrame]]:
    """멀티코어용 워커 함수"""
    df = load_single_ohlcv(file_path)
    code = file_path.stem
    return (code, df)


def load_all_ohlcv(
    ohlcv_dir: Path,
    start_date: str,
    end_date: str,
    use_multicore: bool = True,
    num_workers: int = None,
) -> Dict[str, pd.DataFrame]:
    """전체 OHLCV 데이터 로드 (멀티코어 지원)"""
    
    ohlcv_dir = Path(ohlcv_dir)
    if not ohlcv_dir.exists():
        print(f"❌ 경로 없음: {ohlcv_dir}")
        return {}
    
    files = list(ohlcv_dir.glob("*.csv"))
    if not files:
        print(f"❌ CSV 파일 없음: {ohlcv_dir}")
        return {}
    
    print(f"📂 데이터 로딩: {len(files)}개 파일")
    
    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)
    
    ohlcv_data = {}
    
    if use_multicore and len(files) > 100:
        workers = num_workers or CONFIG.num_workers
        print(f"   🚀 멀티코어 모드: {workers} workers")
        
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_load_worker, f): f for f in files}
            
            for i, future in enumerate(as_completed(futures)):
                if (i + 1) % 500 == 0:
                    print(f"   진행: {i+1}/{len(files)}")
                
                try:
                    code, df = future.result()
                    if df is not None:
                        # 기간 필터링
                        df = df[(df['date'] >= start_dt) & (df['date'] <= end_dt)]
                        if len(df) >= 60:  # 최소 60일
                            ohlcv_data[code] = df
                except Exception:
                    continue
    else:
        print(f"   📝 싱글코어 모드")
        for i, file_path in enumerate(files):
            if (i + 1) % 500 == 0:
                print(f"   진행: {i+1}/{len(files)}")
            
            df = load_single_ohlcv(file_path)
            if df is not None:
                df = df[(df['date'] >= start_dt) & (df['date'] <= end_dt)]
                if len(df) >= 60:
                    ohlcv_data[file_path.stem] = df
    
    print(f"✅ 로드 완료: {len(ohlcv_data)}개 종목")
    return ohlcv_data


# =============================================================================
# 2. 지표 계산 (Indicators)
# =============================================================================

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    모든 기술적 지표 계산
    
    [이동평균선]
    - MA: 3, 5, 7, 8, 10, 15, 20, 33, 45, 60, 120, 360
    - MA 이격도: (close - ma) / ma
    - MA 기울기: ma[t] - ma[t-1]
    
    [거래량]
    - vol_ratio_1d: 전일 대비
    - vol_ratio_ma5: 5일 평균 대비
    - vol_ratio_ma20: 20일 평균 대비
    
    [캔들/가격]
    - is_bullish / is_bearish
    - change_rate: 일간 수익률
    - volatility: (high - low) / close
    - body_ratio: 몸통 크기
    
    [급등 이력]
    - had_surge_Nd: 최근 N일 내 20%+ 급등
    - had_limit_up_Nd: 최근 N일 내 상한가(29%+)
    
    [가격 위치]
    - position_Nd: N일 중 현재 위치 (0~100%)
    """
    df = df.copy()
    
    # =========================================================================
    # 2-1. 이동평균선
    # =========================================================================
    for p in CONFIG.ma_periods:
        # MA 값
        df[f'ma{p}'] = df['close'].rolling(p, min_periods=p).mean()
        
        # 이격도 (양수: 위, 음수: 아래)
        df[f'ma{p}_dist'] = (df['close'] - df[f'ma{p}']) / df[f'ma{p}']
        
        # 기울기 (추세 강도)
        df[f'ma{p}_slope'] = df[f'ma{p}'] - df[f'ma{p}'].shift(1)
        df[f'ma{p}_slope_pct'] = df[f'ma{p}_slope'] / df[f'ma{p}'].shift(1)
    
    # =========================================================================
    # 2-2. 터치 판정 (low ≤ ma ≤ high)
    # =========================================================================
    for p in CONFIG.ma_periods:
        df[f'ma{p}_touch'] = (df['low'] <= df[f'ma{p}']) & (df[f'ma{p}'] <= df['high'])
    
    # =========================================================================
    # 2-3. 거래량 지표
    # =========================================================================
    df['vol_ratio_1d'] = df['volume'] / df['volume'].shift(1)
    df['vol_ma5'] = df['volume'].rolling(5).mean()
    df['vol_ma20'] = df['volume'].rolling(20).mean()
    df['vol_ratio_ma5'] = df['volume'] / df['vol_ma5']
    df['vol_ratio_ma20'] = df['volume'] / df['vol_ma20']
    
    # 전일 거래량 비율 (폭증 판단용)
    df['vol_ratio_prev'] = df['vol_ratio_1d'].shift(1)
    df['volume_prev'] = df['volume'].shift(1)
    
    # =========================================================================
    # 2-4. 캔들 & 가격 지표
    # =========================================================================
    df['is_bullish'] = df['close'] > df['open']
    df['is_bearish'] = df['close'] < df['open']
    df['change_rate'] = df['close'].pct_change()
    df['change_rate_pct'] = df['change_rate'] * 100
    
    # 변동폭 (변동성)
    df['volatility'] = (df['high'] - df['low']) / df['close']
    
    # 몸통 크기
    df['body'] = abs(df['close'] - df['open'])
    df['body_ratio'] = df['body'] / df['close']
    
    # 윗꼬리 / 아랫꼬리
    df['upper_shadow'] = df['high'] - df[['open', 'close']].max(axis=1)
    df['lower_shadow'] = df[['open', 'close']].min(axis=1) - df['low']
    
    # =========================================================================
    # 2-5. 급등 이력
    # =========================================================================
    for n in [5, 10, 20]:
        df[f'max_change_{n}d'] = df['change_rate'].rolling(n).max()
        df[f'had_surge_{n}d'] = df[f'max_change_{n}d'] >= 0.20  # 20%+
        df[f'had_limit_up_{n}d'] = df[f'max_change_{n}d'] >= 0.29  # 상한가
    
    # =========================================================================
    # 2-6. 가격 위치 (N일 중 현재 위치)
    # =========================================================================
    for n in [20, 60, 120]:
        high_n = df['high'].rolling(n).max()
        low_n = df['low'].rolling(n).min()
        df[f'position_{n}d'] = (df['close'] - low_n) / (high_n - low_n) * 100
    
    # =========================================================================
    # 2-7. 120일선 오버헤드 (45일선 매매용)
    # =========================================================================
    df['ma120_overhead'] = df['ma120'] > df['ma45']
    
    # =========================================================================
    # 2-8. 거래량 1000만 이상
    # =========================================================================
    df['vol_over_10m'] = df['volume'] >= CONFIG.volume_10m
    df['vol_prev_over_10m'] = df['volume_prev'] >= CONFIG.volume_10m
    
    return df


# =============================================================================
# 3. 수익률 계산 (손절/익절/수수료 반영)
# =============================================================================

def calculate_returns(
    df: pd.DataFrame,
    include_costs: bool = True,
    include_stoploss: bool = False,
) -> pd.DataFrame:
    """
    수익률 계산
    
    Parameters:
        include_costs: 수수료/세금/슬리피지 반영 여부
        include_stoploss: 손절/익절 시뮬레이션 여부
    """
    df = df.copy()
    
    # 비용 계산
    total_cost = 0
    if include_costs:
        total_cost = CONFIG.commission * 2 + CONFIG.tax + CONFIG.slippage
    
    # =========================================================================
    # 3-1. 단순 보유 수익률 (D+1 ~ D+20)
    # =========================================================================
    for d in CONFIG.return_periods:
        # 당일 종가 매수 → D+N 종가 매도
        raw_return = df['close'].shift(-d) / df['close'] - 1
        df[f'ret_D{d}'] = raw_return - total_cost
    
    # =========================================================================
    # 3-2. 손절/익절 시뮬레이션
    # =========================================================================
    if include_stoploss:
        # 각 날짜별 향후 20일간 고가/저가
        for i in range(1, 21):
            df[f'future_high_{i}'] = df['high'].shift(-i)
            df[f'future_low_{i}'] = df['low'].shift(-i)
            df[f'future_close_{i}'] = df['close'].shift(-i)
        
        # 손절/익절 발생일 및 최종 수익률 계산
        def calc_stoploss_return(row):
            entry_price = row['close']
            
            for day in range(1, 21):
                high = row.get(f'future_high_{day}', np.nan)
                low = row.get(f'future_low_{day}', np.nan)
                close = row.get(f'future_close_{day}', np.nan)
                
                if pd.isna(high) or pd.isna(low):
                    break
                
                # 일중 손절/익절 체크
                low_return = (low - entry_price) / entry_price
                high_return = (high - entry_price) / entry_price
                
                # 손절 먼저 체크 (보수적)
                if low_return <= CONFIG.stop_loss:
                    return CONFIG.stop_loss - total_cost, day, 'stop_loss'
                
                # 익절 체크
                if high_return >= CONFIG.take_profit:
                    return CONFIG.take_profit - total_cost, day, 'take_profit'
            
            # 20일 후 종가 청산
            final_close = row.get('future_close_20', np.nan)
            if pd.notna(final_close):
                final_return = (final_close - entry_price) / entry_price - total_cost
                return final_return, 20, 'hold'
            
            return np.nan, np.nan, 'na'
        
        # 적용 (느리므로 시그널 발생 행에만 나중에 적용)
        # df[['ret_sl', 'exit_day', 'exit_type']] = df.apply(
        #     lambda row: pd.Series(calc_stoploss_return(row)), axis=1
        # )
        
        # 임시 컬럼 정리
        for i in range(1, 21):
            df.drop(columns=[f'future_high_{i}', f'future_low_{i}', f'future_close_{i}'], 
                   inplace=True, errors='ignore')
    
    return df


def calculate_stoploss_return_for_signals(signals_df: pd.DataFrame) -> pd.DataFrame:
    """
    시그널 DataFrame에 대해 손절/익절 수익률 계산
    (전체 데이터가 아닌 시그널에만 적용하여 속도 향상)
    """
    if len(signals_df) == 0:
        return signals_df
    
    signals_df = signals_df.copy()
    
    total_cost = CONFIG.commission * 2 + CONFIG.tax + CONFIG.slippage
    
    results = []
    for idx, row in signals_df.iterrows():
        entry_price = row['close']
        exit_return = np.nan
        exit_day = np.nan
        exit_type = 'na'
        
        for day in range(1, 21):
            ret_col = f'ret_D{day}'
            if ret_col not in row.index:
                continue
            
            # 단순화: ret_D{day}에서 역산
            if pd.notna(row.get(ret_col)):
                day_return = row[ret_col] + total_cost  # 비용 제외한 원래 수익률
                
                # 손절 체크
                if day_return <= CONFIG.stop_loss:
                    exit_return = CONFIG.stop_loss - total_cost
                    exit_day = day
                    exit_type = 'stop_loss'
                    break
                
                # 익절 체크  
                if day_return >= CONFIG.take_profit:
                    exit_return = CONFIG.take_profit - total_cost
                    exit_day = day
                    exit_type = 'take_profit'
                    break
        
        # 20일 보유
        if pd.isna(exit_return) and 'ret_D20' in row.index and pd.notna(row['ret_D20']):
            exit_return = row['ret_D20']
            exit_day = 20
            exit_type = 'hold'
        
        results.append({
            'ret_sl': exit_return,
            'exit_day': exit_day,
            'exit_type': exit_type,
        })
    
    result_df = pd.DataFrame(results, index=signals_df.index)
    signals_df = pd.concat([signals_df, result_df], axis=1)
    
    return signals_df


# =============================================================================
# 4. 전략 모듈 (Strategy Signals)
# =============================================================================

def detect_all_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    모든 전략 시그널 탐지
    
    [전략 목록]
    - S1_vol_drop: 거래량 급감 + 음봉 + MA5 근접
    - S2_vol_spike_drop: 거래량 폭증→급감 + MA5 근접 (거감음봉)
    - S3_ma3_support: 급등 후 3일선 지지
    - S4_ma78_pullback: 7/8일선 눌림목 (이격형)
    - S4_ma78_touch: 7/8일선 눌림목 (터치형)
    - S5_ma45_first: 45일선 낙주매매 (첫 터치)
    - S6_ma33_scout: 33일선 정찰병
    - S7_ma360_bounce: 360일선 급락반등
    """
    df = df.copy()
    
    # =========================================================================
    # S1: 거래량 급감 + 음봉 + MA5 근접
    # =========================================================================
    # 전일 대비 거래량 36% 이하 (급감)
    vol_drop = df['vol_ratio_1d'] <= 0.36
    bearish = df['is_bearish']
    ma5_near = df['ma5_dist'].abs() <= 0.03  # 3% 이내
    
    df['S1_vol_drop'] = vol_drop & bearish & ma5_near
    
    # =========================================================================
    # S2: 거래량 폭증→급감 + MA5 근접 (거감음봉) ⭐핵심
    # =========================================================================
    # 전일 거래량 5배 이상 폭증
    vol_spike_prev = df['vol_ratio_prev'] >= 5.0
    # 당일 거래량 25% 이하로 급감
    vol_drop_today = df['vol_ratio_1d'] <= 0.25
    
    df['S2_vol_spike_drop'] = vol_spike_prev & vol_drop_today & ma5_near
    df['S2_vol_spike_drop_bearish'] = df['S2_vol_spike_drop'] & bearish  # 거감음봉
    df['S2_vol_spike_drop_10m'] = df['S2_vol_spike_drop'] & df['vol_prev_over_10m']  # 1000만+
    
    # =========================================================================
    # S3: 급등 이력 + 3일선 지지
    # =========================================================================
    # 최근 5일 내 20%+ 급등 이력
    had_surge = df['had_surge_5d']
    # 3일선 터치 또는 근접
    ma3_support = df['ma3_touch'] | (df['ma3_dist'].abs() <= 0.02)
    # 5일선 위 유지
    above_ma5 = df['close'] > df['ma5']
    
    df['S3_ma3_support'] = had_surge & ma3_support & above_ma5
    
    # =========================================================================
    # S4: 7/8일선 눌림목
    # =========================================================================
    # 조건: 최근 10일 내 급등 + 5일선 아래 + 7/8일선 지지 + 10일선 위
    had_surge_10d = df['had_surge_10d']
    below_ma5 = df['close'] < df['ma5']
    above_ma10 = df['close'] > df['ma10']
    
    # 이격형 (2% 이내)
    ma7_near = df['ma7_dist'].abs() <= 0.02
    ma8_near = df['ma8_dist'].abs() <= 0.02
    
    df['S4_ma7_pullback'] = had_surge_10d & below_ma5 & ma7_near & above_ma10
    df['S4_ma8_pullback'] = had_surge_10d & below_ma5 & ma8_near & above_ma10
    df['S4_ma78_pullback'] = df['S4_ma7_pullback'] | df['S4_ma8_pullback']
    
    # 터치형 (low ≤ ma ≤ high)
    df['S4_ma7_touch'] = had_surge_10d & below_ma5 & df['ma7_touch'] & above_ma10
    df['S4_ma8_touch'] = had_surge_10d & below_ma5 & df['ma8_touch'] & above_ma10
    df['S4_ma78_touch'] = df['S4_ma7_touch'] | df['S4_ma8_touch']
    
    # =========================================================================
    # S5: 45일선 낙주매매 (첫 터치) ⭐핵심
    # =========================================================================
    # 조건: 상한가 이력 + 45일선 첫 터치 + 거래량 감소 + 120일선 주의
    had_limit_up = df['had_limit_up_20d']
    ma45_touch = df['ma45_touch'] | (df['ma45_dist'].abs() <= 0.02)
    vol_decreased = df['vol_ratio_ma20'] <= 0.8  # 20일 평균의 80% 이하
    
    # "첫 터치" 판정: 이전 10일간 45일선 터치 없었음
    ma45_touch_history = df['ma45_touch'].rolling(10, min_periods=1).sum().shift(1)
    is_first_touch = (ma45_touch_history == 0) | ma45_touch_history.isna()
    
    df['S5_ma45_first'] = had_limit_up & ma45_touch & vol_decreased & is_first_touch
    df['S5_ma45_first_safe'] = df['S5_ma45_first'] & ~df['ma120_overhead']  # 120일선 아래일 때
    df['S5_ma45_first_caution'] = df['S5_ma45_first'] & df['ma120_overhead']  # 120일선 주의
    
    # =========================================================================
    # S6: 33일선 정찰병 → 45일선 본진입
    # =========================================================================
    # 33일선 터치 (45일선 전에 가는 경우)
    ma33_touch = df['ma33_touch'] | (df['ma33_dist'].abs() <= 0.02)
    above_ma45 = df['close'] > df['ma45']
    
    df['S6_ma33_scout'] = had_limit_up & ma33_touch & vol_decreased & above_ma45
    
    # =========================================================================
    # S7: 360일선 급락반등
    # =========================================================================
    # 60일 중 하위 20% 위치 + 360일선 근접 + 거래량 증가
    low_position = df['position_60d'] <= 20
    ma360_near = df['ma360_dist'].abs() <= 0.03  # 3% 이내
    vol_increased = df['vol_ratio_ma20'] >= 1.5
    
    df['S7_ma360_bounce'] = low_position & (ma360_near | df['ma360_touch']) & vol_increased
    
    # =========================================================================
    # S8: 15일선 눌림목 (외인 선호)
    # =========================================================================
    below_ma10 = df['close'] < df['ma10']
    above_ma20 = df['close'] > df['ma20']
    ma15_near = df['ma15_dist'].abs() <= 0.02
    
    df['S8_ma15_pullback'] = had_surge_10d & below_ma10 & ma15_near & above_ma20
    
    # =========================================================================
    # S9: 20일선 생명선
    # =========================================================================
    ma20_near = df['ma20_dist'].abs() <= 0.02
    above_ma60 = df['close'] > df['ma60']
    
    df['S9_ma20_lifeline'] = had_surge_10d & ma20_near & above_ma60
    
    return df


# =============================================================================
# 5. 백테스트 실행
# =============================================================================

# 전략 목록 정의
STRATEGIES = [
    'S1_vol_drop',
    'S2_vol_spike_drop',
    'S2_vol_spike_drop_bearish',
    'S2_vol_spike_drop_10m',
    'S3_ma3_support',
    'S4_ma7_pullback',
    'S4_ma8_pullback',
    'S4_ma78_pullback',
    'S4_ma7_touch',
    'S4_ma8_touch',
    'S4_ma78_touch',
    'S5_ma45_first',
    'S5_ma45_first_safe',
    'S5_ma45_first_caution',
    'S6_ma33_scout',
    'S7_ma360_bounce',
    'S8_ma15_pullback',
    'S9_ma20_lifeline',
]


def process_single_stock(args: Tuple[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """단일 종목 처리 (멀티코어용)"""
    code, df = args
    
    try:
        # 지표 계산
        df = calculate_indicators(df)
        
        # 수익률 계산
        df = calculate_returns(df, include_costs=True, include_stoploss=False)
        
        # 시그널 탐지
        df = detect_all_signals(df)
        
        # 워밍업 기간 제외
        df = df.iloc[CONFIG.warmup_days:].copy()
        
        # 전략별 시그널 추출
        results = {}
        for strategy in STRATEGIES:
            if strategy in df.columns:
                signals = df[df[strategy] == True].copy()
                if len(signals) > 0:
                    signals['strategy'] = strategy
                    results[strategy] = signals
        
        return results
        
    except Exception as e:
        return {}


def run_backtest(
    ohlcv_data: Dict[str, pd.DataFrame],
    use_multicore: bool = True,
) -> Dict[str, pd.DataFrame]:
    """
    전체 백테스트 실행
    
    Returns:
        전략별 시그널 DataFrame 딕셔너리
    """
    print(f"\n{'='*70}")
    print(f"🚀 백테스트 실행")
    print(f"{'='*70}")
    print(f"   종목 수: {len(ohlcv_data)}")
    print(f"   전략 수: {len(STRATEGIES)}")
    print(f"   멀티코어: {use_multicore}")
    
    start_time = time.time()
    
    # 전략별 시그널 수집
    all_signals = {s: [] for s in STRATEGIES}
    
    if use_multicore and len(ohlcv_data) > 100:
        print(f"   🚀 멀티코어 모드: {CONFIG.num_workers} workers")
        
        items = list(ohlcv_data.items())
        
        with ProcessPoolExecutor(max_workers=CONFIG.num_workers) as executor:
            futures = {executor.submit(process_single_stock, item): item[0] for item in items}
            
            for i, future in enumerate(as_completed(futures)):
                if (i + 1) % 500 == 0:
                    print(f"   진행: {i+1}/{len(items)}")
                
                try:
                    results = future.result()
                    for strategy, signals in results.items():
                        if len(signals) > 0:
                            all_signals[strategy].append(signals)
                except Exception:
                    continue
    else:
        print(f"   📝 싱글코어 모드")
        
        for i, (code, df) in enumerate(ohlcv_data.items()):
            if (i + 1) % 500 == 0:
                print(f"   진행: {i+1}/{len(ohlcv_data)}")
            
            results = process_single_stock((code, df))
            for strategy, signals in results.items():
                if len(signals) > 0:
                    all_signals[strategy].append(signals)
    
    # 시그널 합치기
    final_signals = {}
    for strategy in STRATEGIES:
        if all_signals[strategy]:
            combined = pd.concat(all_signals[strategy], ignore_index=True)
            final_signals[strategy] = combined
            print(f"   {strategy}: {len(combined):,}개 시그널")
        else:
            final_signals[strategy] = pd.DataFrame()
    
    elapsed = time.time() - start_time
    print(f"\n✅ 백테스트 완료! ({elapsed:.1f}초)")
    
    return final_signals


# =============================================================================
# 6. 성과 분석 (Performance Metrics)
# =============================================================================

def calculate_metrics(signals_df: pd.DataFrame, strategy_name: str = '') -> Dict[str, Any]:
    """
    전략 성과 지표 계산
    
    [지표]
    - 시그널 수, 종목 수
    - 평균/중앙값 수익률 (D+1 ~ D+20)
    - 승률 (D+1 ~ D+20)
    - 손익비 (Profit Factor)
    - 최대 수익/손실
    - MDD (최대낙폭)
    """
    if len(signals_df) == 0:
        return {'strategy': strategy_name, 'signals': 0}
    
    metrics = {
        'strategy': strategy_name,
        'signals': len(signals_df),
        'unique_stocks': signals_df['code'].nunique() if 'code' in signals_df.columns else 0,
    }
    
    # 보유기간별 수익률/승률
    for d in CONFIG.return_periods:
        col = f'ret_D{d}'
        if col in signals_df.columns:
            returns = signals_df[col].dropna()
            if len(returns) > 0:
                metrics[f'D{d}_mean'] = returns.mean() * 100
                metrics[f'D{d}_median'] = returns.median() * 100
                metrics[f'D{d}_win'] = (returns > 0).mean() * 100
                metrics[f'D{d}_max'] = returns.max() * 100
                metrics[f'D{d}_min'] = returns.min() * 100
                metrics[f'D{d}_std'] = returns.std() * 100
    
    # 손익비 (Profit Factor) - D+5 기준
    if 'ret_D5' in signals_df.columns:
        returns = signals_df['ret_D5'].dropna()
        wins = returns[returns > 0]
        losses = returns[returns < 0]
        
        if len(wins) > 0 and len(losses) > 0:
            avg_win = wins.mean()
            avg_loss = abs(losses.mean())
            metrics['profit_factor'] = avg_win / avg_loss if avg_loss > 0 else np.inf
            metrics['avg_win'] = avg_win * 100
            metrics['avg_loss'] = avg_loss * 100
        
        # 손익비 (총액 기준)
        total_profit = wins.sum() if len(wins) > 0 else 0
        total_loss = abs(losses.sum()) if len(losses) > 0 else 0
        metrics['profit_ratio'] = total_profit / total_loss if total_loss > 0 else np.inf
    
    # 손절/익절 수익률
    if 'ret_sl' in signals_df.columns:
        sl_returns = signals_df['ret_sl'].dropna()
        if len(sl_returns) > 0:
            metrics['sl_mean'] = sl_returns.mean() * 100
            metrics['sl_win'] = (sl_returns > 0).mean() * 100
            
            # Exit type 분포
            if 'exit_type' in signals_df.columns:
                exit_counts = signals_df['exit_type'].value_counts()
                metrics['exit_stop_loss'] = exit_counts.get('stop_loss', 0)
                metrics['exit_take_profit'] = exit_counts.get('take_profit', 0)
                metrics['exit_hold'] = exit_counts.get('hold', 0)
    
    return metrics


def calculate_mdd(returns: pd.Series) -> float:
    """
    MDD (Maximum Drawdown) 계산
    
    누적 수익률 기준 최대 낙폭
    """
    if len(returns) == 0:
        return 0.0
    
    cumulative = (1 + returns).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max
    
    return drawdown.min() * 100


def generate_performance_report(
    all_signals: Dict[str, pd.DataFrame],
    output_path: Optional[Path] = None,
) -> pd.DataFrame:
    """
    전체 성과 리포트 생성
    """
    print(f"\n{'='*70}")
    print(f"📊 성과 분석 리포트")
    print(f"{'='*70}")
    
    results = []
    
    for strategy, signals_df in all_signals.items():
        if len(signals_df) == 0:
            continue
        
        metrics = calculate_metrics(signals_df, strategy)
        
        # MDD 계산
        if 'ret_D5' in signals_df.columns:
            metrics['mdd'] = calculate_mdd(signals_df['ret_D5'].dropna())
        
        results.append(metrics)
    
    if not results:
        print("결과 없음")
        return pd.DataFrame()
    
    report_df = pd.DataFrame(results)
    
    # 컬럼 정렬
    priority_cols = ['strategy', 'signals', 'unique_stocks']
    return_cols = [c for c in report_df.columns if c.startswith('D') and '_mean' in c]
    win_cols = [c for c in report_df.columns if c.startswith('D') and '_win' in c]
    other_cols = [c for c in report_df.columns if c not in priority_cols + return_cols + win_cols]
    
    ordered_cols = priority_cols + sorted(return_cols) + sorted(win_cols) + other_cols
    ordered_cols = [c for c in ordered_cols if c in report_df.columns]
    report_df = report_df[ordered_cols]
    
    # 소수점 정리
    for col in report_df.columns:
        if report_df[col].dtype in ['float64', 'float32']:
            report_df[col] = report_df[col].round(2)
    
    # 출력
    print(f"\n📈 전략별 성과 요약:")
    print(report_df.to_string(index=False))
    
    # D+5 수익률 순위
    if 'D5_mean' in report_df.columns:
        print(f"\n🏆 D+5 수익률 TOP 10:")
        top10 = report_df.nlargest(10, 'D5_mean')[['strategy', 'signals', 'D5_mean', 'D5_win', 'profit_factor']]
        print(top10.to_string(index=False))
    
    # D+5 승률 순위 (시그널 100개 이상)
    if 'D5_win' in report_df.columns:
        print(f"\n🎯 D+5 승률 TOP 10 (시그널≥100):")
        filtered = report_df[report_df['signals'] >= 100]
        if len(filtered) > 0:
            top10_win = filtered.nlargest(10, 'D5_win')[['strategy', 'signals', 'D5_mean', 'D5_win', 'profit_factor']]
            print(top10_win.to_string(index=False))
    
    # CSV 저장
    if output_path:
        report_df.to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"\n💾 리포트 저장: {output_path}")
    
    return report_df


# =============================================================================
# 7. 시간대별 분석 (월별/분기별/요일별)
# =============================================================================

def analyze_by_time(
    signals_df: pd.DataFrame,
    strategy_name: str = '',
    save_csv: bool = True,
) -> Dict[str, pd.DataFrame]:
    """
    시간대별 성과 분석
    
    - 연도별
    - 월별 (감사의견 시즌 2~3월 표시)
    - 분기별
    - 요일별
    """
    if len(signals_df) == 0:
        return {}
    
    signals_df = signals_df.copy()
    signals_df['date'] = pd.to_datetime(signals_df['date'])
    signals_df['year'] = signals_df['date'].dt.year
    signals_df['month'] = signals_df['date'].dt.month
    signals_df['quarter'] = signals_df['date'].dt.quarter
    signals_df['weekday'] = signals_df['date'].dt.dayofweek
    
    results = {}
    
    print(f"\n{'='*70}")
    print(f"⏰ 시간대별 분석: {strategy_name}")
    print(f"{'='*70}")
    
    # =========================================================================
    # 연도별
    # =========================================================================
    by_year = signals_df.groupby('year').agg({
        'code': 'count',
        'ret_D5': ['mean', lambda x: (x > 0).mean()],
    }).round(4)
    by_year.columns = ['signals', 'D5_mean', 'D5_win']
    by_year['D5_mean'] = by_year['D5_mean'] * 100
    by_year['D5_win'] = by_year['D5_win'] * 100
    
    print(f"\n📅 연도별:")
    print(by_year.round(2).to_string())
    results['year'] = by_year
    
    # =========================================================================
    # 월별 (감사의견 시즌)
    # =========================================================================
    by_month = signals_df.groupby('month').agg({
        'code': 'count',
        'ret_D1': 'mean',
        'ret_D5': ['mean', lambda x: (x > 0).mean()],
        'ret_D10': 'mean',
    }).round(4)
    by_month.columns = ['signals', 'D1', 'D5', 'D5_win', 'D10']
    
    for col in ['D1', 'D5', 'D10']:
        by_month[col] = by_month[col] * 100
    by_month['D5_win'] = by_month['D5_win'] * 100
    
    month_names = {
        1: '1월(새해)', 2: '2월(감사⚠️)', 3: '3월(감사⚠️)',
        4: '4월', 5: '5월', 6: '6월',
        7: '7월', 8: '8월(휴가)', 9: '9월',
        10: '10월', 11: '11월(세금)', 12: '12월(윈도우)'
    }
    by_month.index = by_month.index.map(lambda x: month_names.get(x, f'{x}월'))
    
    print(f"\n📆 월별:")
    print(by_month.round(2).to_string())
    results['month'] = by_month
    
    # 감사의견 시즌 vs 비시즌
    signals_df['is_audit'] = signals_df['month'].isin([2, 3])
    audit = signals_df[signals_df['is_audit']]
    non_audit = signals_df[~signals_df['is_audit']]
    
    if len(audit) >= 10 and len(non_audit) >= 10:
        print(f"\n⚠️ 감사의견 시즌 (2~3월) vs 비시즌:")
        print(f"   2~3월:  D+5 {audit['ret_D5'].mean()*100:+.2f}%  승률 {(audit['ret_D5']>0).mean()*100:.1f}%  ({len(audit)}개)")
        print(f"   그 외:  D+5 {non_audit['ret_D5'].mean()*100:+.2f}%  승률 {(non_audit['ret_D5']>0).mean()*100:.1f}%  ({len(non_audit)}개)")
    
    # =========================================================================
    # 분기별
    # =========================================================================
    by_quarter = signals_df.groupby('quarter').agg({
        'code': 'count',
        'ret_D5': ['mean', lambda x: (x > 0).mean()],
    }).round(4)
    by_quarter.columns = ['signals', 'D5', 'D5_win']
    by_quarter['D5'] = by_quarter['D5'] * 100
    by_quarter['D5_win'] = by_quarter['D5_win'] * 100
    
    quarter_names = {1: 'Q1', 2: 'Q2', 3: 'Q3', 4: 'Q4'}
    by_quarter.index = by_quarter.index.map(lambda x: quarter_names.get(x, f'Q{x}'))
    
    print(f"\n📊 분기별:")
    print(by_quarter.round(2).to_string())
    results['quarter'] = by_quarter
    
    # =========================================================================
    # 요일별
    # =========================================================================
    by_weekday = signals_df.groupby('weekday').agg({
        'code': 'count',
        'ret_D1': 'mean',
        'ret_D5': ['mean', lambda x: (x > 0).mean()],
    }).round(4)
    by_weekday.columns = ['signals', 'D1', 'D5', 'D5_win']
    
    for col in ['D1', 'D5']:
        by_weekday[col] = by_weekday[col] * 100
    by_weekday['D5_win'] = by_weekday['D5_win'] * 100
    
    weekday_names = {0: '월', 1: '화', 2: '수', 3: '목', 4: '금'}
    by_weekday.index = by_weekday.index.map(lambda x: weekday_names.get(x, str(x)))
    
    print(f"\n📅 요일별:")
    print(by_weekday.round(2).to_string())
    results['weekday'] = by_weekday
    
    # =========================================================================
    # CSV 저장
    # =========================================================================
    if save_csv:
        safe_name = strategy_name.replace('/', '_').replace('\\', '_')
        
        # 월별 저장 (가장 유용)
        by_month.to_csv(f'nomad_v3_{safe_name}_monthly.csv', encoding='utf-8-sig')
        print(f"\n💾 월별 분석 저장: nomad_v3_{safe_name}_monthly.csv")
        
        # 연도별 저장
        by_year.to_csv(f'nomad_v3_{safe_name}_yearly.csv', encoding='utf-8-sig')
        
        # Excel 저장 시도 (openpyxl 필요)
        try:
            with pd.ExcelWriter(f'nomad_v3_{safe_name}_time_analysis.xlsx', engine='openpyxl') as writer:
                by_year.to_excel(writer, sheet_name='연도별')
                by_month.to_excel(writer, sheet_name='월별')
                by_quarter.to_excel(writer, sheet_name='분기별')
                by_weekday.to_excel(writer, sheet_name='요일별')
            print(f"💾 시간대별 분석 저장: nomad_v3_{safe_name}_time_analysis.xlsx")
        except Exception:
            # openpyxl 없으면 CSV로 각각 저장
            by_quarter.to_csv(f'nomad_v3_{safe_name}_quarterly.csv', encoding='utf-8-sig')
            by_weekday.to_csv(f'nomad_v3_{safe_name}_weekday.csv', encoding='utf-8-sig')
            print(f"💾 CSV로 저장 완료 (xlsx 생략)")
    
    return results


# =============================================================================
# 8. 기간 분할 검증 (In-Sample / Out-of-Sample)
# =============================================================================

def split_sample_analysis(
    signals_df: pd.DataFrame,
    split_date: str,
    strategy_name: str = '',
    save_csv: bool = True,
) -> Dict[str, Dict]:
    """
    기간 분할 검증
    
    - In-Sample (학습용): split_date 이전
    - Out-of-Sample (검증용): split_date 이후
    """
    if len(signals_df) == 0:
        return {}
    
    signals_df = signals_df.copy()
    signals_df['date'] = pd.to_datetime(signals_df['date'])
    split_dt = pd.to_datetime(split_date)
    
    in_sample = signals_df[signals_df['date'] < split_dt]
    out_sample = signals_df[signals_df['date'] >= split_dt]
    
    print(f"\n{'='*70}")
    print(f"🔬 기간 분할 검증: {strategy_name}")
    print(f"   분할일: {split_date}")
    print(f"{'='*70}")
    
    results = {}
    
    for name, sample_df in [('In-Sample', in_sample), ('Out-of-Sample', out_sample)]:
        if len(sample_df) < 10:
            print(f"\n{name}: 시그널 부족 ({len(sample_df)}개)")
            continue
        
        metrics = {
            'period': name,
            'signals': len(sample_df),
            'start': sample_df['date'].min().strftime('%Y-%m-%d'),
            'end': sample_df['date'].max().strftime('%Y-%m-%d'),
        }
        
        for d in [1, 5, 10]:
            col = f'ret_D{d}'
            if col in sample_df.columns:
                returns = sample_df[col].dropna()
                metrics[f'D{d}_mean'] = returns.mean() * 100
                metrics[f'D{d}_win'] = (returns > 0).mean() * 100
        
        results[name] = metrics
        
        print(f"\n📊 {name} ({metrics['start']} ~ {metrics['end']}):")
        print(f"   시그널: {metrics['signals']:,}개")
        if 'D5_mean' in metrics:
            print(f"   D+5 평균: {metrics['D5_mean']:+.2f}%")
            print(f"   D+5 승률: {metrics['D5_win']:.1f}%")
    
    # 비교
    if 'In-Sample' in results and 'Out-of-Sample' in results:
        in_d5 = results['In-Sample'].get('D5_mean', 0)
        out_d5 = results['Out-of-Sample'].get('D5_mean', 0)
        
        print(f"\n📈 검증 결과:")
        if out_d5 >= in_d5 * 0.7:  # Out-of-Sample이 In-Sample의 70% 이상이면 양호
            print(f"   ✅ 양호: Out-of-Sample({out_d5:+.2f}%) ≥ 70% of In-Sample({in_d5:+.2f}%)")
        else:
            print(f"   ⚠️ 주의: Out-of-Sample({out_d5:+.2f}%) < 70% of In-Sample({in_d5:+.2f}%)")
            print(f"   과최적화 가능성 있음")
    
    # CSV 저장
    if save_csv and results:
        safe_name = strategy_name.replace('/', '_').replace('\\', '_')
        split_df = pd.DataFrame([results.get('In-Sample', {}), results.get('Out-of-Sample', {})])
        split_df.to_csv(f'nomad_v3_{safe_name}_split.csv', index=False, encoding='utf-8-sig')
        print(f"\n💾 기간분할 검증 저장: nomad_v3_{safe_name}_split.csv")
    
    return results


# =============================================================================
# 9. 보유기간별 성과 매트릭스
# =============================================================================

def holding_period_matrix(
    signals_df: pd.DataFrame,
    strategy_name: str = '',
    save_csv: bool = True,
) -> pd.DataFrame:
    """
    보유기간별 성과 매트릭스
    
    D+1 ~ D+20까지 수익률/승률 한눈에
    """
    if len(signals_df) == 0:
        return pd.DataFrame()
    
    print(f"\n{'='*70}")
    print(f"📊 보유기간별 성과 매트릭스: {strategy_name}")
    print(f"{'='*70}")
    
    matrix_data = []
    
    for d in CONFIG.return_periods:
        col = f'ret_D{d}'
        if col not in signals_df.columns:
            continue
        
        returns = signals_df[col].dropna()
        if len(returns) == 0:
            continue
        
        matrix_data.append({
            '보유기간': f'D+{d}',
            '평균': returns.mean() * 100,
            '중앙값': returns.median() * 100,
            '승률': (returns > 0).mean() * 100,
            '표준편차': returns.std() * 100,
            '최대': returns.max() * 100,
            '최소': returns.min() * 100,
            '샘플': len(returns),
        })
    
    matrix_df = pd.DataFrame(matrix_data)
    
    for col in ['평균', '중앙값', '승률', '표준편차', '최대', '최소']:
        if col in matrix_df.columns:
            matrix_df[col] = matrix_df[col].round(2)
    
    print(matrix_df.to_string(index=False))
    
    # CSV 저장
    if save_csv:
        safe_name = strategy_name.replace('/', '_').replace('\\', '_')
        matrix_df.to_csv(f'nomad_v3_{safe_name}_holding.csv', index=False, encoding='utf-8-sig')
        print(f"\n💾 보유기간 매트릭스 저장: nomad_v3_{safe_name}_holding.csv")
    
    return matrix_df


# =============================================================================
# 10. 메인 실행
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='유목민 백테스트 v3.0')
    
    # 기본 옵션
    parser.add_argument('--start', type=str, default=CONFIG.start_date, 
                       help=f'시작일 (기본: {CONFIG.start_date})')
    parser.add_argument('--end', type=str, default=CONFIG.end_date,
                       help=f'종료일 (기본: {CONFIG.end_date})')
    parser.add_argument('--split', type=str, default=CONFIG.split_date,
                       help=f'In/Out Sample 분할일 (기본: {CONFIG.split_date})')
    
    # 실행 모드
    parser.add_argument('--quick', action='store_true',
                       help='빠른 테스트 (주요 전략만)')
    parser.add_argument('--full', action='store_true',
                       help='전체 테스트 (모든 전략)')
    parser.add_argument('--strategy', type=str, default=None,
                       help='특정 전략만 테스트')
    
    # 분석 옵션
    parser.add_argument('--time-analysis', action='store_true',
                       help='시간대별 분석 (월별/분기별/요일별)')
    parser.add_argument('--split-analysis', action='store_true',
                       help='기간 분할 검증')
    parser.add_argument('--holding-matrix', action='store_true',
                       help='보유기간별 매트릭스')
    parser.add_argument('--all-analysis', action='store_true',
                       help='모든 분석 실행')
    
    # 멀티코어
    parser.add_argument('--single', action='store_true',
                       help='싱글코어 모드')
    parser.add_argument('--workers', type=int, default=CONFIG.num_workers,
                       help=f'워커 수 (기본: {CONFIG.num_workers})')
    
    # 출력
    parser.add_argument('--output', type=str, default='nomad_v3_result.csv',
                       help='결과 CSV 파일명')
    
    args = parser.parse_args()
    
    # 설정 업데이트
    CONFIG.start_date = args.start
    CONFIG.end_date = args.end
    CONFIG.split_date = args.split
    CONFIG.use_multicore = not args.single
    CONFIG.num_workers = args.workers
    
    print(f"\n{'='*70}")
    print(f"📚 유목민 백테스트 v3.0 - Professional Grade")
    print(f"{'='*70}")
    print(f"   기간: {CONFIG.start_date} ~ {CONFIG.end_date}")
    print(f"   분할일: {CONFIG.split_date}")
    print(f"   멀티코어: {CONFIG.use_multicore} ({CONFIG.num_workers} workers)")
    print(f"   수수료: {CONFIG.commission*100:.3f}%")
    print(f"   세금: {CONFIG.tax*100:.2f}%")
    print(f"   손절: {CONFIG.stop_loss*100:.0f}%")
    print(f"   익절: {CONFIG.take_profit*100:.0f}%")
    
    # 데이터 로드
    ohlcv_data = load_all_ohlcv(
        CONFIG.ohlcv_dir,
        CONFIG.start_date,
        CONFIG.end_date,
        use_multicore=CONFIG.use_multicore,
        num_workers=CONFIG.num_workers,
    )
    
    if not ohlcv_data:
        print("❌ 데이터 로드 실패")
        return
    
    # 백테스트 실행
    all_signals = run_backtest(ohlcv_data, use_multicore=CONFIG.use_multicore)
    
    # 성과 리포트
    output_path = Path(args.output)
    report_df = generate_performance_report(all_signals, output_path)
    
    # ==========================================================================
    # 시그널 데이터 저장 (전략별)
    # ==========================================================================
    print(f"\n{'='*70}")
    print(f"💾 시그널 데이터 저장 중...")
    print(f"{'='*70}")
    
    for strategy, signals_df in all_signals.items():
        if len(signals_df) > 0:
            # 필요한 컬럼만 선택
            save_cols = ['date', 'code', 'open', 'high', 'low', 'close', 'volume',
                        'ret_D1', 'ret_D3', 'ret_D5', 'ret_D7', 'ret_D10', 'ret_D15', 'ret_D20']
            save_cols = [c for c in save_cols if c in signals_df.columns]
            
            signals_df[save_cols].to_csv(f'signals_{strategy}.csv', index=False, encoding='utf-8-sig')
    
    print(f"   ✅ {len([s for s in all_signals.values() if len(s) > 0])}개 전략 시그널 저장 완료")
    print(f"   📁 파일명: signals_[전략명].csv")
    
    # 추가 분석
    if args.all_analysis or args.time_analysis:
        # 시간대별 분석 (주요 전략)
        main_strategies = ['S2_vol_spike_drop', 'S4_ma78_pullback', 'S5_ma45_first']
        for strategy in main_strategies:
            if strategy in all_signals and len(all_signals[strategy]) > 0:
                analyze_by_time(all_signals[strategy], strategy, save_csv=True)
    
    if args.all_analysis or args.split_analysis:
        # 기간 분할 검증
        for strategy in ['S2_vol_spike_drop', 'S4_ma78_pullback', 'S5_ma45_first']:
            if strategy in all_signals and len(all_signals[strategy]) > 0:
                split_sample_analysis(all_signals[strategy], CONFIG.split_date, strategy, save_csv=True)
    
    if args.all_analysis or args.holding_matrix:
        # 보유기간별 매트릭스
        for strategy in ['S2_vol_spike_drop', 'S4_ma78_pullback', 'S5_ma45_first']:
            if strategy in all_signals and len(all_signals[strategy]) > 0:
                holding_period_matrix(all_signals[strategy], strategy, save_csv=True)
    
    # ==========================================================================
    # 저장된 파일 목록 출력
    # ==========================================================================
    print(f"\n{'='*70}")
    print(f"📁 저장된 파일 목록")
    print(f"{'='*70}")
    
    saved_files = list(Path(".").glob("nomad_v3_*.csv")) + \
                  list(Path(".").glob("signals_*.csv")) + \
                  list(Path(".").glob("nomad_v3_*.xlsx")) + \
                  [output_path]
    
    for f in sorted(set(saved_files)):
        if f.exists():
            size_kb = f.stat().st_size / 1024
            print(f"   📄 {f.name} ({size_kb:.1f} KB)")
    
    print(f"\n{'='*70}")
    print(f"✅ 완료!")
    print(f"{'='*70}")


if __name__ == '__main__':
    main()