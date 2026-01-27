"""
유목민 공부법 수집 서비스 v6.2
==============================

상한가/거래량천만 종목을 수집하여
nomad_candidates 테이블에 저장합니다.

v6.2 개선:
- 거래대금 상위 API + 주요 종목 보완 로직 제거
- 16:35 data_update에서 수집한 OHLCV CSV 기반 필터링
- 정확한 거래량/상한가 필터링 (실제 데이터 기반)

사용:
    from src.services.nomad_collector import run_nomad_collection
    run_nomad_collection()
"""

import logging
import os
from datetime import date
from pathlib import Path
from typing import Dict

import pandas as pd

from src.infrastructure.repository import get_nomad_candidates_repository

logger = logging.getLogger(__name__)

# 기준값
LIMIT_UP_THRESHOLD = 29.5  # 상한가 기준 (%)
VOLUME_EXPLOSION_THRESHOLD = 10_000_000  # 거래량천만 기준 (주)

# OHLCV 데이터 경로
OHLCV_DIR = Path(os.getenv('OHLCV_DIR', 'C:/Coding/data/ohlcv'))
STOCK_MAPPING_PATH = Path(os.getenv('STOCK_MAPPING', 'C:/Coding/data/stock_mapping.csv'))

# ETF 등 제외 패턴
EXCLUDE_PATTERNS = [
    'KODEX', 'TIGER', 'KBSTAR', 'ARIRANG', 'HANARO',
    'SOL', 'KOSEF', 'KINDEX', 'SMART', 'ACE', 'TIMEFOLIO',
    'ETF', 'ETN', '인버스', '레버리지', '선물', '스팩',
]


def load_stock_mapping() -> Dict[str, str]:
    """종목코드 → 종목명 매핑 로드"""
    mapping = {}
    
    if STOCK_MAPPING_PATH.exists():
        try:
            df = pd.read_csv(STOCK_MAPPING_PATH, dtype={'code': str})
            for _, row in df.iterrows():
                code = str(row['code']).zfill(6)
                mapping[code] = row['name']
        except Exception as e:
            logger.warning(f"stock_mapping.csv 로드 실패: {e}")
    
    return mapping


def collect_nomad_candidates(target_date: date = None) -> Dict:
    """
    유목민 공부 후보 수집 (CSV 기반)
    
    16:35에 수집된 OHLCV CSV 파일을 분석하여
    거래량 1천만 이상 OR 상한가(+29.5%) 종목을 추출합니다.
    
    Args:
        target_date: 수집 날짜 (기본: 오늘)
        
    Returns:
        {'limit_up': int, 'volume_explosion': int, 'total': int}
    """
    if target_date is None:
        target_date = date.today()
    
    target_date_str = target_date.isoformat()
    logger.info(f"📚 유목민 후보 수집 (CSV 기반): {target_date}")
    
    repo = get_nomad_candidates_repository()
    
    # 기존 데이터 확인
    existing = repo.get_by_date(target_date_str)
    if existing:
        logger.info(f"  이미 {len(existing)}개 후보가 있음 → 스킵")
        return {'limit_up': 0, 'volume_explosion': 0, 'total': len(existing), 'skipped': True}
    
    result = {'limit_up': 0, 'volume_explosion': 0, 'total': 0}
    candidates = []
    
    # 종목명 매핑 로드
    stock_mapping = load_stock_mapping()
    logger.info(f"  종목 매핑: {len(stock_mapping)}개")
    
    # OHLCV 폴더 확인
    if not OHLCV_DIR.exists():
        logger.error(f"  OHLCV 폴더 없음: {OHLCV_DIR}")
        return result
    
    csv_files = list(OHLCV_DIR.glob("*.csv"))
    logger.info(f"  CSV 파일: {len(csv_files)}개 스캔")
    
    for csv_file in csv_files:
        try:
            stock_code = csv_file.stem  # 파일명 = 종목코드
            
            # 종목명 조회
            stock_name = stock_mapping.get(stock_code, stock_code)
            
            # ETF 등 제외
            skip = False
            for pattern in EXCLUDE_PATTERNS:
                if pattern.lower() in stock_name.lower():
                    skip = True
                    break
            
            if skip:
                continue
            
            # CSV 읽기
            df = pd.read_csv(csv_file)
            
            # 컬럼명 소문자 통일
            df.columns = df.columns.str.lower()
            
            # date 컬럼 확인
            if 'date' not in df.columns:
                if 'unnamed: 0' in df.columns:
                    df = df.rename(columns={'unnamed: 0': 'date'})
                else:
                    continue
            
            # 오늘 데이터 찾기
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
            today_df = df[df['date'] == target_date_str]
            
            if today_df.empty:
                continue
            
            today_row = today_df.iloc[-1]
            
            # 데이터 추출
            volume = int(today_row.get('volume', 0))
            close = int(today_row.get('close', 0))
            
            # 전일 데이터로 등락률 계산
            prev_df = df[df['date'] < target_date_str]
            if prev_df.empty:
                continue
            
            prev_row = prev_df.iloc[-1]
            prev_close = int(prev_row.get('close', 0))
            
            if prev_close == 0:
                continue
            
            change_rate = ((close - prev_close) / prev_close) * 100
            
            # 거래대금 계산 (억원)
            trading_value = (close * volume) / 100_000_000
            
            # 상한가 확인 (등락률 >= 29.5%)
            is_limit_up = change_rate >= LIMIT_UP_THRESHOLD
            
            # 거래량천만 확인
            is_volume_explosion = volume >= VOLUME_EXPLOSION_THRESHOLD
            
            # 필터링: 상한가 OR 거래량천만
            if not (is_limit_up or is_volume_explosion):
                continue
            
            # 사유 결정
            if is_limit_up and is_volume_explosion:
                reason = '상한가+거래량'
            elif is_limit_up:
                reason = '상한가'
            else:
                reason = '거래량천만'
            
            candidate_data = {
                'study_date': target_date_str,
                'stock_code': stock_code,
                'stock_name': stock_name,
                'reason_flag': reason,
                'close_price': close,
                'change_rate': round(change_rate, 2),
                'volume': volume,
                'trading_value': round(trading_value, 2),
                'data_source': 'backfill',  # CSV에서 수집 = backfill
            }
            
            candidates.append(candidate_data)
            
            if is_limit_up:
                result['limit_up'] += 1
                logger.info(f"  상한가: {stock_name} ({stock_code}) +{change_rate:.1f}%")
            if is_volume_explosion:
                result['volume_explosion'] += 1
                logger.info(f"  거래량천만: {stock_name} ({stock_code}) +{change_rate:.1f}% 거래량:{volume:,}")
            
        except Exception as e:
            logger.debug(f"  {csv_file.name} 처리 실패: {e}")
            continue
    
    # DB 저장
    saved = 0
    for candidate in candidates:
        try:
            repo.insert(candidate)
            saved += 1
        except Exception as e:
            logger.debug(f"  저장 실패 ({candidate['stock_code']}): {e}")
    
    result['total'] = saved
    
    logger.info(f"📚 유목민 수집 완료: 상한가 {result['limit_up']}, 거래량천만 {result['volume_explosion']}, 총 {saved}개 저장")
    
    return result


def run_nomad_collection() -> Dict:
    """유목민 공부법 수집 실행 (스케줄러용)"""
    logger.info("=" * 50)
    logger.info("📚 유목민 공부법 수집 시작 (CSV 기반)")
    logger.info("=" * 50)
    
    result = collect_nomad_candidates()
    
    logger.info("=" * 50)
    logger.info(f"📚 유목민 공부법 완료: {result.get('total', 0)}개 종목")
    logger.info("=" * 50)
    
    return result


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    )
    
    print("=" * 60)
    print("📚 유목민 공부법 테스트 (CSV 기반)")
    print("=" * 60)
    
    result = run_nomad_collection()
    
    print()
    print(f"상한가: {result.get('limit_up', 0)}개")
    print(f"거래량천만: {result.get('volume_explosion', 0)}개")
    print(f"총: {result.get('total', 0)}개")
