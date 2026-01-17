"""
익일 결과 수집 서비스 v5.4 (종가매매 전용)
==================================

종가매매 TOP5의 익일 시고저종을 수집하고
승률을 계산합니다.

v5.4: K값 전략 제거

사용:
    from src.services.result_collector import run_result_collection
    run_result_collection()
"""

import logging
import time
from datetime import date, timedelta
from typing import Dict, List, Optional

from src.infrastructure.repository import get_repository
from src.adapters.kis_client import get_kis_client

logger = logging.getLogger(__name__)


def collect_next_day_results(target_date: date = None) -> Dict:
    """
    익일 결과 수집 (종가매매 + K값)
    
    Args:
        target_date: 스크리닝 날짜 (기본: 어제)
        
    Returns:
        {'collected': int, 'failed': int, 'skipped': int}
    """
    if target_date is None:
        target_date = date.today() - timedelta(days=1)
    
    logger.info(f"📊 익일 결과 수집: {target_date}")
    
    repo = get_repository()
    kis = get_kis_client()
    
    # 해당 날짜의 스크리닝 종목 조회 (익일 결과 없는 것만)
    items = repo.screening.get_items_without_next_day_result(
        screen_date=target_date,
        top3_only=True,  # TOP5 (is_top3=1인 종목)
    )
    
    if not items:
        logger.info("  수집할 종목 없음")
        return {'collected': 0, 'failed': 0, 'skipped': 0}
    
    logger.info(f"  수집 대상: {len(items)}개 종목")
    
    results = {'collected': 0, 'failed': 0, 'skipped': 0}
    
    for item in items:
        try:
            code = item['stock_code']
            name = item['stock_name']
            yesterday_close = item['current_price']
            
            # 익일 시고저종 조회
            prices = kis.get_daily_prices(code, count=5)
            
            if not prices:
                logger.warning(f"  ⚠️ {code} {name}: 데이터 없음")
                results['failed'] += 1
                continue
            
            # 스크리닝 다음 거래일 찾기
            next_day_price = None
            for price in prices:
                if price.date > target_date:
                    next_day_price = price
                    break
            
            if next_day_price is None:
                logger.debug(f"  ⏭️ {code} {name}: 익일 데이터 없음")
                results['skipped'] += 1
                continue
            
            # 수익률 계산
            gap_rate = ((next_day_price.open - yesterday_close) / yesterday_close) * 100
            day_return = ((next_day_price.close - yesterday_close) / yesterday_close) * 100
            high_change = ((next_day_price.high - yesterday_close) / yesterday_close) * 100
            low_change = ((next_day_price.low - yesterday_close) / yesterday_close) * 100
            
            # DB 저장
            repo.save_next_day_result(
                stock_code=code,
                screen_date=target_date,
                gap_rate=gap_rate,
                day_return=day_return,
                volatility=0,
                next_open=next_day_price.open,
                next_close=next_day_price.close,
                next_high=next_day_price.high,
                next_low=next_day_price.low,
                high_change_rate=high_change,
            )
            
            # 로그
            win = "✅" if gap_rate > 0 else "❌"
            logger.info(f"  {win} {code} {name}: 갭 {gap_rate:+.1f}%, 고가 {high_change:+.1f}%")
            results['collected'] += 1
            
            time.sleep(0.3)
            
        except Exception as e:
            logger.error(f"  ✗ {item['stock_code']}: {e}")
            results['failed'] += 1
    
    logger.info(f"📊 수집 완료: 성공 {results['collected']}, 실패 {results['failed']}, 스킵 {results['skipped']}")
    return results


def get_win_rate_stats(days: int = 30) -> Dict:
    """
    최근 N일 승률 통계
    
    Args:
        days: 조회 기간
        
    Returns:
        {'total': int, 'wins': int, 'win_rate': float, 'avg_gap': float, 'avg_high': float}
    """
    repo = get_repository()
    
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    
    # DB에서 결과 조회
    results = repo.get_next_day_results(start_date, end_date)
    
    if not results:
        return {'total': 0, 'wins': 0, 'win_rate': 0, 'avg_gap': 0, 'avg_high': 0}
    
    total = len(results)
    wins = sum(1 for r in results if r.get('gap_rate', 0) > 0)
    
    avg_gap = sum(r.get('gap_rate', 0) for r in results) / total
    avg_high = sum(r.get('high_change_rate', 0) for r in results) / total
    
    return {
        'total': total,
        'wins': wins,
        'win_rate': (wins / total * 100) if total > 0 else 0,
        'avg_gap': avg_gap,
        'avg_high': avg_high,
    }


def run_result_collection() -> Dict:
    """
    익일 결과 수집 실행 (스케줄러용)
    
    최근 7일간 누락된 결과를 수집합니다.
    """
    logger.info("=" * 50)
    logger.info("📊 익일 결과 수집 시작")
    logger.info("=" * 50)
    
    total = {'collected': 0, 'failed': 0, 'skipped': 0}
    
    today = date.today()
    for i in range(1, 8):  # 최근 7일
        target_date = today - timedelta(days=i)
        
        # 주말 스킵
        if target_date.weekday() >= 5:
            continue
        
        result = collect_next_day_results(target_date)
        
        total['collected'] += result['collected']
        total['failed'] += result['failed']
        total['skipped'] += result['skipped']
    
    # 승률 통계 출력
    stats = get_win_rate_stats(30)
    
    logger.info("=" * 50)
    logger.info(f"📊 최근 30일 승률: {stats['win_rate']:.1f}% ({stats['wins']}/{stats['total']})")
    logger.info(f"   평균 갭: {stats['avg_gap']:+.2f}%")
    logger.info(f"   평균 고가: {stats['avg_high']:+.2f}%")
    logger.info("=" * 50)
    
    return total


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_result_collection()
