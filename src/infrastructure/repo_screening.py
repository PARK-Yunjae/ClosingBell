"""
repo_screening: ScreeningRepository, NextDayResultRepository
"""

import json
import logging
from datetime import date
from typing import List, Optional, Dict

from src.infrastructure.database import get_database, Database

logger = logging.getLogger(__name__)

from src.domain.models import (
    StockScore,
    Weights,
    ScreeningResult,
    NextDayResult,
)

class ScreeningRepository:
    """스크리닝 데이터 저장소"""
    
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()
    
    def save_screening(self, result: ScreeningResult) -> int:
        """스크리닝 결과 저장
        
        Args:
            result: 스크리닝 결과
            
        Returns:
            생성된 screening ID
        """
        # TOP3 종목 코드 JSON
        top3_codes = json.dumps([s.stock_code for s in result.top3])
        
        # 기존 데이터 확인 (같은 날짜)
        existing = self.db.fetch_one(
            "SELECT id FROM screenings WHERE screen_date = ?",
            (result.screen_date.isoformat(),)
        )
        
        if existing:
            # 기존 데이터 업데이트 (upsert)
            screening_id = existing['id']
            self.db.execute(
                """
                UPDATE screenings SET
                    screen_time = ?,
                    total_count = ?,
                    top3_codes = ?,
                    execution_time_sec = ?,
                    status = ?,
                    error_message = ?
                WHERE id = ?
                """,
                (
                    result.screen_time,
                    result.total_count,
                    top3_codes,
                    result.execution_time_sec,
                    result.status.value,
                    result.error_message,
                    screening_id,
                )
            )
            
            # 기존 items 삭제
            self.db.execute(
                "DELETE FROM screening_items WHERE screening_id = ?",
                (screening_id,)
            )
            logger.info(f"기존 스크리닝 업데이트: {result.screen_date}")
        else:
            # 새 스크리닝 생성
            cursor = self.db.execute(
                """
                INSERT INTO screenings 
                (screen_date, screen_time, total_count, top3_codes, execution_time_sec, status, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.screen_date.isoformat(),
                    result.screen_time,
                    result.total_count,
                    top3_codes,
                    result.execution_time_sec,
                    result.status.value,
                    result.error_message,
                )
            )
            screening_id = cursor.lastrowid
            logger.info(f"새 스크리닝 저장: {result.screen_date}, ID={screening_id}")
        
        # 종목 상세 저장
        self._save_screening_items(screening_id, result.all_items, result.top3)
        
        return screening_id
    
    def _save_screening_items(
        self,
        screening_id: int,
        all_items: List[StockScore],
        top3: List[StockScore],
    ):
        """스크리닝 종목 상세 저장"""
        top3_codes = {s.stock_code for s in top3}
        
        items_data = []
        for score in all_items:
            items_data.append((
                screening_id,
                score.stock_code,
                score.stock_name,
                score.current_price,
                score.change_rate,
                score.trading_value,
                score.score_total,
                score.score_cci_value,
                score.score_cci_slope,
                score.score_ma20_slope,
                score.score_candle,
                score.score_change,
                score.raw_cci,
                score.raw_ma20,
                score.rank,
                1 if score.stock_code in top3_codes else 0,
            ))
        
        self.db.execute_many(
            """
            INSERT INTO screening_items 
            (screening_id, stock_code, stock_name, current_price, change_rate, 
             trading_value, score_total, score_cci_value, score_cci_slope, 
             score_ma20_slope, score_candle, score_change, raw_cci, raw_ma20, 
             rank, is_top3)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            items_data
        )
        logger.info(f"종목 상세 저장: {len(items_data)}개")
    
    def get_screening_by_date(self, screen_date: date) -> Optional[Dict]:
        """날짜별 스크리닝 조회"""
        row = self.db.fetch_one(
            "SELECT * FROM screenings WHERE screen_date = ?",
            (screen_date.isoformat(),)
        )
        if row:
            return dict(row)
        return None
    
    def get_screening_items(self, screening_id: int) -> List[Dict]:
        """스크리닝 종목 조회"""
        rows = self.db.fetch_all(
            """
            SELECT * FROM screening_items 
            WHERE screening_id = ? 
            ORDER BY rank
            """,
            (screening_id,)
        )
        return [dict(row) for row in rows]
    
    def get_top3_items(self, screening_id: int) -> List[Dict]:
        """TOP3 종목 조회"""
        rows = self.db.fetch_all(
            """
            SELECT * FROM screening_items 
            WHERE screening_id = ? AND is_top3 = 1
            ORDER BY rank
            """,
            (screening_id,)
        )
        return [dict(row) for row in rows]
    
    def get_recent_screenings(self, days: int = 30) -> List[Dict]:
        """최근 N일 스크리닝 조회"""
        rows = self.db.fetch_all(
            """
            SELECT * FROM screenings 
            WHERE screen_date >= DATE('now', ?)
            ORDER BY screen_date DESC
            """,
            (f'-{days} days',)
        )
        return [dict(row) for row in rows]
    
    def get_items_without_next_day_result(
        self, 
        screen_date: date,
        top3_only: bool = False,
    ) -> List[Dict]:
        """익일 결과가 없는 종목 조회 (특정 날짜)
        
        Args:
            screen_date: 스크리닝 날짜
            top3_only: True면 TOP3만, False면 전체 종목
            
        Returns:
            익일 결과가 없는 종목 리스트
        """
        if top3_only:
            rows = self.db.fetch_all(
                """
                SELECT si.* FROM screening_items si
                JOIN screenings s ON si.screening_id = s.id
                LEFT JOIN next_day_results ndr ON si.id = ndr.screening_item_id
                WHERE s.screen_date = ? AND ndr.id IS NULL AND si.is_top3 = 1
                """,
                (screen_date.isoformat(),)
            )
        else:
            # 전체 종목 조회 (TOP3 + 나머지 모두)
            rows = self.db.fetch_all(
                """
                SELECT si.* FROM screening_items si
                JOIN screenings s ON si.screening_id = s.id
                LEFT JOIN next_day_results ndr ON si.id = ndr.screening_item_id
                WHERE s.screen_date = ? AND ndr.id IS NULL
                ORDER BY si.rank
                """,
                (screen_date.isoformat(),)
            )
        return [dict(row) for row in rows]
    
    def get_all_items_by_date(self, screen_date: date) -> List[Dict]:
        """특정 날짜의 전체 스크리닝 종목 조회"""
        screening = self.get_screening_by_date(screen_date)
        if not screening:
            return []
        return self.get_screening_items(screening['id'])
    
    def get_screening_items_with_results(self, screening_id: int) -> List[Dict]:
        """스크리닝 종목 + 익일 결과 조인 조회
        
        Args:
            screening_id: 스크리닝 ID
            
        Returns:
            종목 리스트 (익일 결과 포함)
        """
        rows = self.db.fetch_all(
            """
            SELECT 
                si.*,
                ndr.gap_rate,
                ndr.day_change_rate,
                ndr.high_change_rate,
                ndr.next_open,
                ndr.next_high,
                ndr.next_low,
                ndr.next_close
            FROM screening_items si
            LEFT JOIN next_day_results ndr ON si.id = ndr.screening_item_id
            WHERE si.screening_id = ? AND si.is_top3 = 1
            ORDER BY si.rank
            """,
            (screening_id,)
        )
        return [dict(row) for row in rows]


class NextDayResultRepository:
    """익일 결과 저장소"""
    
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()
    
    def save_next_day_result(
        self,
        item_id: int,
        next_date: date,
        result: NextDayResult,
    ):
        """익일 결과 저장"""
        # 중복 체크
        existing = self.db.fetch_one(
            "SELECT id FROM next_day_results WHERE screening_item_id = ?",
            (item_id,)
        )
        
        if existing:
            logger.warning(f"익일 결과 이미 존재: item_id={item_id}")
            return
        
        self.db.execute(
            """
            INSERT INTO next_day_results 
            (screening_item_id, next_date, open_price, close_price, high_price, 
             low_price, volume, trading_value, open_change_rate, day_change_rate, 
             high_change_rate, gap_rate, volatility, is_open_up, is_day_up)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                next_date.isoformat(),
                result.open_price,
                result.close_price,
                result.high_price,
                result.low_price,
                result.volume,
                result.trading_value,
                result.open_gap,
                result.close_change,
                ((result.high_price - result.prev_close) / result.prev_close * 100) 
                    if result.prev_close > 0 else 0,
                result.open_gap,
                result.intraday_range,
                1 if result.is_open_up else 0,
                1 if result.close_change > 0 else 0,
            )
        )
        logger.info(f"익일 결과 저장: item_id={item_id}")
    
    def get_hit_rate(self, days: int = 30, top3_only: bool = True) -> Dict[str, float]:
        """적중률 조회
        
        Args:
            days: 조회 기간 (일)
            top3_only: True면 TOP3만, False면 전체 종목
            
        Returns:
            적중률 정보 딕셔너리
        """
        if top3_only:
            row = self.db.fetch_one(
                """
                SELECT 
                    COUNT(CASE WHEN ndr.is_open_up = 1 THEN 1 END) as hit_count,
                    COUNT(ndr.id) as total_count,
                    AVG(ndr.gap_rate) as avg_gap_rate
                FROM screenings s
                JOIN screening_items si ON s.id = si.screening_id AND si.is_top3 = 1
                JOIN next_day_results ndr ON si.id = ndr.screening_item_id
                WHERE s.screen_date >= DATE('now', ?)
                """,
                (f'-{days} days',)
            )
        else:
            row = self.db.fetch_one(
                """
                SELECT 
                    COUNT(CASE WHEN ndr.is_open_up = 1 THEN 1 END) as hit_count,
                    COUNT(ndr.id) as total_count,
                    AVG(ndr.gap_rate) as avg_gap_rate
                FROM screenings s
                JOIN screening_items si ON s.id = si.screening_id
                JOIN next_day_results ndr ON si.id = ndr.screening_item_id
                WHERE s.screen_date >= DATE('now', ?)
                """,
                (f'-{days} days',)
            )
        
        if row and row['total_count'] > 0:
            return {
                'hit_count': row['hit_count'],
                'total_count': row['total_count'],
                'hit_rate': row['hit_count'] / row['total_count'] * 100,
                'avg_gap_rate': row['avg_gap_rate'] or 0.0,
            }
        return {'hit_count': 0, 'total_count': 0, 'hit_rate': 0.0, 'avg_gap_rate': 0.0}
    
    def get_hit_rate_by_rank(self, days: int = 30) -> List[Dict]:
        """순위별 적중률 조회
        
        Returns:
            순위별 적중률 리스트
        """
        rows = self.db.fetch_all(
            """
            SELECT 
                si.rank,
                COUNT(*) as total_count,
                COUNT(CASE WHEN ndr.is_open_up = 1 THEN 1 END) as hit_count,
                AVG(ndr.gap_rate) as avg_gap_rate,
                AVG(ndr.day_change_rate) as avg_day_change
            FROM screenings s
            JOIN screening_items si ON s.id = si.screening_id
            JOIN next_day_results ndr ON si.id = ndr.screening_item_id
            WHERE s.screen_date >= DATE('now', ?)
            GROUP BY si.rank
            ORDER BY si.rank
            """,
            (f'-{days} days',)
        )
        
        results = []
        for row in rows:
            results.append({
                'rank': row['rank'],
                'total_count': row['total_count'],
                'hit_count': row['hit_count'],
                'hit_rate': (row['hit_count'] / row['total_count'] * 100) if row['total_count'] > 0 else 0,
                'avg_gap_rate': row['avg_gap_rate'] or 0.0,
                'avg_day_change': row['avg_day_change'] or 0.0,
            })
        return results
    
    def get_all_results_with_screening(self, days: int = 30) -> List[Dict]:
        """스크리닝 정보와 함께 전체 익일 결과 조회
        
        Returns:
            전체 익일 결과 리스트 (스크리닝 정보 포함)
        """
        rows = self.db.fetch_all(
            """
            SELECT 
                s.screen_date,
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
                si.change_rate as screen_change_rate,
                ndr.gap_rate,
                ndr.day_change_rate,
                ndr.volatility,
                ndr.is_open_up,
                ndr.is_day_up,
                ndr.open_price as next_open,
                ndr.close_price as next_close
            FROM screenings s
            JOIN screening_items si ON s.id = si.screening_id
            JOIN next_day_results ndr ON si.id = ndr.screening_item_id
            WHERE s.screen_date >= DATE('now', ?)
            ORDER BY s.screen_date DESC, si.rank
            """,
            (f'-{days} days',)
        )
        return [dict(row) for row in rows]
    def get_next_day_results(
        self, 
        start_date: date = None, 
        end_date: date = None,
        days: int = 30
    ) -> List[Dict]:
        """익일 결과 조회 (dashboard용)
        
        Args:
            start_date: 시작일 (None이면 days 사용)
            end_date: 종료일 (None이면 오늘)
            days: 조회 기간 (start_date가 없을 때 사용)
        """
        if start_date and end_date:
            rows = self.db.fetch_all(
                """
                SELECT 
                    ndr.*,
                    si.stock_code,
                    si.stock_name,
                    si.rank as screen_rank,
                    si.score_total,
                    s.screen_date
                FROM next_day_results ndr
                JOIN screening_items si ON ndr.screening_item_id = si.id
                JOIN screenings s ON si.screening_id = s.id
                WHERE s.screen_date >= ? AND s.screen_date <= ?
                ORDER BY s.screen_date DESC
                """,
                (start_date.isoformat(), end_date.isoformat())
            )
        else:
            rows = self.db.fetch_all(
                """
                SELECT 
                    ndr.*,
                    si.stock_code,
                    si.stock_name,
                    si.rank as screen_rank,
                    si.score_total,
                    s.screen_date
                FROM next_day_results ndr
                JOIN screening_items si ON ndr.screening_item_id = si.id
                JOIN screenings s ON si.screening_id = s.id
                WHERE s.screen_date >= DATE('now', ?)
                ORDER BY s.screen_date DESC
                """,
                (f'-{days} days',)
            )
        return [dict(row) for row in rows]



def get_screening_repository() -> ScreeningRepository:
    return ScreeningRepository()


def get_next_day_result_repository() -> NextDayResultRepository:
    return NextDayResultRepository()

