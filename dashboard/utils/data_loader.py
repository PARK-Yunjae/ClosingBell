"""
데이터 로더 모듈

책임:
- DB에서 대시보드용 데이터 로드
- 캐싱 처리
"""

import sys
from pathlib import Path
from datetime import date, timedelta
from typing import List, Dict, Optional, Any
import pandas as pd

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.infrastructure.database import get_database, init_database
from src.infrastructure.repository import (
    get_screening_repository,
    get_weight_repository,
    get_next_day_repository,
    get_trade_journal_repository,
)


def load_today_screening() -> Optional[Dict]:
    """오늘 스크리닝 결과 로드"""
    repo = get_screening_repository()
    return repo.get_screening_by_date(date.today())


def load_screening_by_date(screen_date: date) -> Optional[Dict]:
    """특정 날짜 스크리닝 결과 로드"""
    repo = get_screening_repository()
    return repo.get_screening_by_date(screen_date)


def load_screening_items(screening_id: int, top3_only: bool = False) -> List[Dict]:
    """스크리닝 종목 로드"""
    repo = get_screening_repository()
    if top3_only:
        return repo.get_top3_items(screening_id)
    return repo.get_screening_items(screening_id)


def load_recent_screenings(days: int = 30) -> List[Dict]:
    """최근 스크리닝 목록 로드"""
    repo = get_screening_repository()
    return repo.get_recent_screenings(days)


def load_screening_items_by_date(screen_date: date, top3_only: bool = False) -> List[Dict]:
    """특정 날짜의 스크리닝 종목 로드"""
    screening = load_screening_by_date(screen_date)
    if not screening:
        return []
    return load_screening_items(screening['id'], top3_only)


def load_weights() -> Dict[str, float]:
    """현재 가중치 로드"""
    repo = get_weight_repository()
    weights = repo.get_weights()
    return weights.to_dict()


def load_weight_history(days: int = 30) -> List[Dict]:
    """가중치 변경 이력 로드"""
    repo = get_weight_repository()
    return repo.get_weight_history(days)


def load_hit_rate(days: int = 30, top3_only: bool = True) -> Dict:
    """적중률 로드"""
    repo = get_next_day_repository()
    return repo.get_hit_rate(days, top3_only)


def load_hit_rate_by_rank(days: int = 30) -> List[Dict]:
    """순위별 적중률 로드"""
    repo = get_next_day_repository()
    return repo.get_hit_rate_by_rank(days)


def load_all_results_with_screening(days: int = 30) -> pd.DataFrame:
    """스크리닝 정보와 익일 결과 로드 (DataFrame)"""
    repo = get_next_day_repository()
    results = repo.get_all_results_with_screening(days)
    if not results:
        return pd.DataFrame()
    return pd.DataFrame(results)


def load_screening_history_df(days: int = 30) -> pd.DataFrame:
    """스크리닝 히스토리 DataFrame으로 로드"""
    db = get_database()
    
    rows = db.fetch_all(
        """
        SELECT 
            s.screen_date,
            s.total_count,
            s.status,
            si.stock_code,
            si.stock_name,
            si.rank,
            si.is_top3,
            si.score_total,
            si.score_cci_value,
            si.score_cci_slope,
            si.score_ma20_slope,
            si.score_candle,
            si.score_change,
            si.raw_cci,
            si.change_rate,
            si.current_price,
            si.trading_value,
            ndr.gap_rate,
            ndr.day_change_rate,
            ndr.is_open_up,
            ndr.is_day_up
        FROM screenings s
        JOIN screening_items si ON s.id = si.screening_id
        LEFT JOIN next_day_results ndr ON si.id = ndr.screening_item_id
        WHERE s.screen_date >= DATE('now', ?)
        ORDER BY s.screen_date DESC, si.rank
        """,
        (f'-{days} days',)
    )
    
    if not rows:
        return pd.DataFrame()
    
    return pd.DataFrame([dict(row) for row in rows])


def load_stock_history(stock_code: str, days: int = 90) -> pd.DataFrame:
    """특정 종목의 스크리닝 이력 로드"""
    db = get_database()
    
    rows = db.fetch_all(
        """
        SELECT 
            s.screen_date,
            si.rank,
            si.is_top3,
            si.score_total,
            si.raw_cci,
            si.change_rate,
            ndr.gap_rate,
            ndr.day_change_rate,
            ndr.is_open_up
        FROM screenings s
        JOIN screening_items si ON s.id = si.screening_id
        LEFT JOIN next_day_results ndr ON si.id = ndr.screening_item_id
        WHERE si.stock_code = ? AND s.screen_date >= DATE('now', ?)
        ORDER BY s.screen_date DESC
        """,
        (stock_code, f'-{days} days')
    )
    
    if not rows:
        return pd.DataFrame()
    
    return pd.DataFrame([dict(row) for row in rows])


def load_daily_performance(days: int = 30) -> pd.DataFrame:
    """일별 성과 로드"""
    db = get_database()
    
    rows = db.fetch_all(
        """
        SELECT 
            s.screen_date,
            COUNT(si.id) as total_items,
            COUNT(ndr.id) as tracked_items,
            SUM(CASE WHEN ndr.is_open_up = 1 THEN 1 ELSE 0 END) as hit_count,
            AVG(ndr.gap_rate) as avg_gap_rate,
            MAX(ndr.gap_rate) as max_gap_rate,
            MIN(ndr.gap_rate) as min_gap_rate
        FROM screenings s
        JOIN screening_items si ON s.id = si.screening_id AND si.is_top3 = 1
        LEFT JOIN next_day_results ndr ON si.id = ndr.screening_item_id
        WHERE s.screen_date >= DATE('now', ?)
        GROUP BY s.screen_date
        ORDER BY s.screen_date DESC
        """,
        (f'-{days} days',)
    )
    
    if not rows:
        return pd.DataFrame()
    
    df = pd.DataFrame([dict(row) for row in rows])
    df['hit_rate'] = df.apply(
        lambda x: (x['hit_count'] / x['tracked_items'] * 100) if x['tracked_items'] > 0 else 0, 
        axis=1
    )
    return df


def load_unique_stocks(days: int = 30) -> List[Dict]:
    """스크리닝에 등장한 고유 종목 목록 로드"""
    db = get_database()
    
    rows = db.fetch_all(
        """
        SELECT 
            si.stock_code,
            si.stock_name,
            COUNT(*) as appearance_count,
            SUM(CASE WHEN si.is_top3 = 1 THEN 1 ELSE 0 END) as top3_count,
            AVG(si.score_total) as avg_score,
            AVG(ndr.gap_rate) as avg_gap_rate,
            SUM(CASE WHEN ndr.is_open_up = 1 THEN 1 ELSE 0 END) as win_count,
            COUNT(ndr.id) as tracked_count
        FROM screenings s
        JOIN screening_items si ON s.id = si.screening_id
        LEFT JOIN next_day_results ndr ON si.id = ndr.screening_item_id
        WHERE s.screen_date >= DATE('now', ?)
        GROUP BY si.stock_code, si.stock_name
        ORDER BY appearance_count DESC
        """,
        (f'-{days} days',)
    )
    
    results = []
    for row in rows:
        d = dict(row)
        d['win_rate'] = (d['win_count'] / d['tracked_count'] * 100) if d['tracked_count'] > 0 else 0
        results.append(d)
    
    return results


def load_trade_journal(days: int = 30) -> List[Dict]:
    """매매일지 로드"""
    repo = get_trade_journal_repository()
    return repo.get_trades(days)


def ensure_db_initialized():
    """DB 초기화 보장"""
    try:
        init_database()
    except Exception as e:
        print(f"DB 초기화 경고: {e}")


# 모듈 로드 시 DB 초기화
ensure_db_initialized()
