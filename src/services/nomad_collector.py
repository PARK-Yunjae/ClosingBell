"""
유목민 공부법 수집 서비스 v6.0
==============================

상한가/거래량천만 종목을 수집하여
nomad_candidates 테이블에 저장합니다.

사용:
    from src.services.nomad_collector import run_nomad_collection
    run_nomad_collection()
"""

import logging
import time
from datetime import date, timedelta
from typing import Dict, List, Optional

from src.adapters.kis_client import get_kis_client
from src.infrastructure.repository import get_nomad_candidates_repository

logger = logging.getLogger(__name__)

# 기준값
LIMIT_UP_THRESHOLD = 29.5  # 상한가 기준 (%)
VOLUME_EXPLOSION_THRESHOLD = 10_000_000  # 거래량천만 기준 (주)
MIN_TRADING_VALUE = 10  # 최소 거래대금 (억원)

# ETF 등 제외 패턴
EXCLUDE_PATTERNS = [
    'KODEX', 'TIGER', 'KBSTAR', 'ARIRANG', 'HANARO',
    'SOL', 'KOSEF', 'KINDEX', 'SMART', 'ACE', 'TIMEFOLIO',
    'ETF', 'ETN', '인버스', '레버리지', '선물', '스팩',
]


def collect_nomad_candidates(target_date: date = None) -> Dict:
    """
    유목민 공부 후보 수집
    
    상한가/거래량천만 종목을 수집합니다.
    
    Args:
        target_date: 수집 날짜 (기본: 오늘)
        
    Returns:
        {'limit_up': int, 'volume_explosion': int, 'total': int}
    """
    if target_date is None:
        target_date = date.today()
    
    logger.info(f"📚 유목민 후보 수집: {target_date}")
    
    kis = get_kis_client()
    repo = get_nomad_candidates_repository()
    
    # 기존 데이터 확인
    existing = repo.get_by_date(target_date.isoformat())
    if existing:
        logger.info(f"  이미 {len(existing)}개 후보가 있음")
        return {'limit_up': 0, 'volume_explosion': 0, 'total': len(existing), 'skipped': True}
    
    result = {'limit_up': 0, 'volume_explosion': 0, 'total': 0}
    candidates = []
    
    try:
        # 거래대금 상위 종목 조회 (상한가/거래량천만 종목 포함)
        stocks = kis.get_top_trading_value_stocks(
            min_trading_value=MIN_TRADING_VALUE,
            limit=500,
        )
        
        if not stocks:
            logger.warning("  종목 조회 실패")
            return result
        
        logger.info(f"  조회된 종목: {len(stocks)}개")
        
        for stock in stocks:
            # ETF 등 제외
            skip = False
            for pattern in EXCLUDE_PATTERNS:
                if pattern.lower() in stock.name.lower():
                    skip = True
                    break
            
            if skip:
                continue
            
            # 일봉 데이터 조회
            try:
                prices = kis.get_daily_prices(stock.code, count=5)
                
                if len(prices) < 2:
                    continue
                
                today_price = prices[-1]
                yesterday_price = prices[-2]
                
                # 날짜 확인
                if today_price.date != target_date:
                    continue
                
                # 등락률 계산
                change_rate = ((today_price.close - yesterday_price.close) / yesterday_price.close) * 100
                
                # 거래대금 계산
                trading_value = (today_price.close * today_price.volume) / 100_000_000
                
                # 상한가 확인
                is_limit_up = change_rate >= LIMIT_UP_THRESHOLD
                
                # 거래량천만 확인
                is_volume_explosion = today_price.volume >= VOLUME_EXPLOSION_THRESHOLD
                
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
                    'study_date': target_date.isoformat(),
                    'stock_code': stock.code,
                    'stock_name': stock.name,
                    'reason_flag': reason,
                    'close_price': today_price.close,
                    'change_rate': change_rate,
                    'volume': today_price.volume,
                    'trading_value': trading_value,
                    'data_source': 'realtime',
                }
                
                candidates.append(candidate_data)
                
                if is_limit_up:
                    result['limit_up'] += 1
                if is_volume_explosion:
                    result['volume_explosion'] += 1
                
                time.sleep(0.2)
                
            except Exception as e:
                logger.debug(f"  {stock.code} 처리 실패: {e}")
                continue
        
        # DB 저장
        for candidate in candidates:
            try:
                repo.upsert(candidate)
                logger.info(f"  {candidate['reason_flag']}: {candidate['stock_name']} ({candidate['stock_code']}) +{candidate['change_rate']:.1f}%")
            except Exception as e:
                logger.error(f"  저장 실패: {candidate['stock_code']} - {e}")
        
        result['total'] = len(candidates)
        
    except Exception as e:
        logger.error(f"유목민 수집 실패: {e}")
    
    logger.info(f"📚 유목민 수집 완료: 상한가 {result['limit_up']}, 거래량천만 {result['volume_explosion']}, 총 {result['total']}개")
    return result


def run_nomad_collection() -> Dict:
    """
    유목민 공부법 실행 (스케줄러용)
    
    오늘의 상한가/거래량천만 종목을 수집합니다.
    """
    logger.info("=" * 50)
    logger.info("📚 유목민 공부법 수집 시작")
    logger.info("=" * 50)
    
    result = collect_nomad_candidates()
    
    logger.info("=" * 50)
    logger.info(f"📚 유목민 공부법 완료: {result.get('total', 0)}개 종목")
    logger.info("=" * 50)
    
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_nomad_collection()
