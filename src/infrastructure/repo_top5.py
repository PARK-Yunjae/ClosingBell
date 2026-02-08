"""
repo_top5: Top5HistoryRepository, Top5DailyPricesRepository
"""

import json
import logging
from datetime import date
from typing import List, Optional, Dict

from src.infrastructure.database import get_database, Database

logger = logging.getLogger(__name__)

class Top5HistoryRepository:
    """closing_top5_history 테이블 CRUD"""
    
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()
    
    def upsert(self, data: dict) -> int:
        """TOP5 이력 삽입/갱신 (UNIQUE 충돌 시 UPDATE) - v6.3.1 거래대금 추가"""
        existing = self.db.fetch_one(
            "SELECT id FROM closing_top5_history WHERE screen_date = ? AND stock_code = ?",
            (data['screen_date'], data['stock_code'])
        )
        
        if existing:
            self.db.execute(
                """
                UPDATE closing_top5_history SET
                    rank = ?, stock_name = ?, screen_price = ?, screen_score = ?, grade = ?,
                    cci = ?, rsi = ?, change_rate = ?, disparity_20 = ?,
                    consecutive_up = ?, volume_ratio_5 = ?, data_source = ?,
                    sector = ?, sector_rank = ?, is_leading_sector = ?,
                    trading_value = ?, volume = ?
                WHERE id = ?
                """,
                (
                    data['rank'], data['stock_name'], data['screen_price'],
                    data['screen_score'], data['grade'],
                    data.get('cci'), data.get('rsi'), data.get('change_rate'),
                    data.get('disparity_20'), data.get('consecutive_up', 0),
                    data.get('volume_ratio_5'), data.get('data_source', 'realtime'),
                    data.get('sector'), data.get('sector_rank'), data.get('is_leading_sector', 0),
                    data.get('trading_value'), data.get('volume'),
                    existing['id']
                )
            )
            return existing['id']
        else:
            cursor = self.db.execute(
                """
                INSERT INTO closing_top5_history 
                (screen_date, rank, stock_code, stock_name, screen_price, screen_score, grade,
                 cci, rsi, change_rate, disparity_20, consecutive_up, volume_ratio_5, data_source,
                 sector, sector_rank, is_leading_sector, trading_value, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data['screen_date'], data['rank'], data['stock_code'], data['stock_name'],
                    data['screen_price'], data['screen_score'], data['grade'],
                    data.get('cci'), data.get('rsi'), data.get('change_rate'),
                    data.get('disparity_20'), data.get('consecutive_up', 0),
                    data.get('volume_ratio_5'), data.get('data_source', 'realtime'),
                    data.get('sector'), data.get('sector_rank'), data.get('is_leading_sector', 0),
                    data.get('trading_value'), data.get('volume')
                )
            )
            return cursor.lastrowid
    
    def update_ai_fields(
        self, 
        screen_date: str, 
        stock_code: str,
        ai_summary: Optional[str] = None,
        ai_risk_level: Optional[str] = None,
        ai_recommendation: Optional[str] = None,
    ) -> bool:
        """AI 분석 결과만 업데이트 (기존 값 보존, 빈 값 덮어쓰기 방지)
        
        Args:
            screen_date: 스크리닝 날짜 (YYYY-MM-DD)
            stock_code: 종목코드
            ai_summary: AI 요약 (None이면 기존 값 유지)
            ai_risk_level: AI 위험도 (None이면 기존 값 유지)
            ai_recommendation: AI 추천 (None이면 기존 값 유지)
            
        Returns:
            업데이트 성공 여부
            
        Note:
            - 전달값이 None이면 기존 값 유지 (COALESCE)
            - 전달값이 ''(빈 문자열)이면 기존 값 유지 (빈 값 덮어쓰기 금지)
            - record가 없으면 조용히 skip (False 반환)
        """
        # 레코드 존재 확인
        existing = self.db.fetch_one(
            "SELECT id, ai_summary, ai_risk_level, ai_recommendation FROM closing_top5_history WHERE screen_date = ? AND stock_code = ?",
            (screen_date, stock_code)
        )
        
        if not existing:
            logger.debug(f"AI 업데이트 스킵 - 레코드 없음: {screen_date} {stock_code}")
            return False
        
        # 빈 값 덮어쓰기 방지: None 또는 빈 문자열이면 기존 값 사용
        final_summary = ai_summary if ai_summary else existing.get('ai_summary')
        final_risk_level = ai_risk_level if ai_risk_level else existing.get('ai_risk_level')
        final_recommendation = ai_recommendation if ai_recommendation else existing.get('ai_recommendation')
        
        self.db.execute(
            """
            UPDATE closing_top5_history SET
                ai_summary = ?,
                ai_risk_level = ?,
                ai_recommendation = ?
            WHERE id = ?
            """,
            (final_summary, final_risk_level, final_recommendation, existing['id'])
        )
        
        logger.debug(f"AI 필드 업데이트 완료: {screen_date} {stock_code} - {final_recommendation}/{final_risk_level}")
        return True
    
    def has_ai_analysis(self, screen_date: str, stock_code: str) -> bool:
        """해당 종목의 AI 분석이 이미 완료되었는지 확인 (중복 호출 방지)
        
        Args:
            screen_date: 스크리닝 날짜 (YYYY-MM-DD)
            stock_code: 종목코드
            
        Returns:
            AI 분석 완료 여부 (ai_recommendation이 있으면 True)
        """
        row = self.db.fetch_one(
            "SELECT ai_recommendation FROM closing_top5_history WHERE screen_date = ? AND stock_code = ?",
            (screen_date, stock_code)
        )
        
        if not row:
            return False
        
        # ai_recommendation이 NULL이 아니고 빈 문자열이 아니면 분석 완료
        ai_rec = row.get('ai_recommendation')
        return ai_rec is not None and ai_rec != ''
    
    def update_short_sr_fields(
        self, screen_date: str, stock_code: str,
        short_ratio: float = 0, short_score: float = 0, short_tags: str = "",
        sr_score: float = 0, sr_nearest_support: float = 0, 
        sr_nearest_resistance: float = 0, sr_tags: str = "",
    ) -> bool:
        """v10.0: 공매도/지지저항 분석 결과 업데이트"""
        existing = self.db.fetch_one(
            "SELECT id FROM closing_top5_history WHERE screen_date = ? AND stock_code = ?",
            (screen_date, stock_code)
        )
        if not existing:
            return False
        
        try:
            self.db.execute(
                """
                UPDATE closing_top5_history SET
                    short_ratio = ?, short_score = ?, short_tags = ?,
                    sr_score = ?, sr_nearest_support = ?, sr_nearest_resistance = ?, sr_tags = ?
                WHERE id = ?
                """,
                (short_ratio, short_score, short_tags,
                 sr_score, sr_nearest_support, sr_nearest_resistance, sr_tags,
                 existing['id'])
            )
            return True
        except Exception as e:
            logger.warning(f"공매도/SR 필드 업데이트 실패: {e}")
            return False
    
    def get_stocks_without_ai(self, screen_date: str) -> List[dict]:
        """AI 분석이 없는 종목 목록 조회 (중복 호출 방지용)
        
        Args:
            screen_date: 스크리닝 날짜 (YYYY-MM-DD)
            
        Returns:
            AI 분석이 없는 종목 리스트
        """
        rows = self.db.fetch_all(
            """
            SELECT * FROM closing_top5_history 
            WHERE screen_date = ? 
              AND (ai_recommendation IS NULL OR ai_recommendation = '')
            ORDER BY rank
            """,
            (screen_date,)
        )
        return [dict(row) for row in rows]
    
    def get_active_items(self) -> List[dict]:
        """tracking_status='active'인 항목들"""
        rows = self.db.fetch_all(
            "SELECT * FROM closing_top5_history WHERE tracking_status = 'active' ORDER BY screen_date DESC, rank"
        )
        return [dict(row) for row in rows]
    
    def get_by_date(self, screen_date: str) -> List[dict]:
        """특정 날짜의 TOP5"""
        rows = self.db.fetch_all(
            "SELECT * FROM closing_top5_history WHERE screen_date = ? ORDER BY rank",
            (screen_date,)
        )
        return [dict(row) for row in rows]
    
    def get_dates_with_data(self, days: int = 60) -> List[str]:
        """데이터가 있는 날짜 목록"""
        rows = self.db.fetch_all(
            "SELECT DISTINCT screen_date FROM closing_top5_history ORDER BY screen_date DESC LIMIT ?",
            (days,)
        )
        return [row['screen_date'] for row in rows]
    
    def update_tracking_days(self, id: int, days: int, last_date: str):
        """추적 일수 업데이트"""
        self.db.execute(
            "UPDATE closing_top5_history SET tracking_days = ?, last_tracked_date = ? WHERE id = ?",
            (days, last_date, id)
        )
    
    def update_status(self, id: int, status: str):
        """상태 변경"""
        self.db.execute(
            "UPDATE closing_top5_history SET tracking_status = ? WHERE id = ?",
            (status, id)
        )
    
    def get_by_id(self, id: int) -> Optional[dict]:
        """ID로 조회"""
        row = self.db.fetch_one("SELECT * FROM closing_top5_history WHERE id = ?", (id,))
        return dict(row) if row else None
    
    def delete_by_date(self, screen_date: str) -> int:
        """특정 날짜의 TOP5 데이터 삭제 (실시간 저장 전 호출)
        
        Returns:
            삭제된 행 수
        """
        cursor = self.db.execute(
            "DELETE FROM closing_top5_history WHERE screen_date = ?",
            (screen_date,)
        )
        deleted = cursor.rowcount
        if deleted > 0:
            logger.info(f"TOP5 기존 데이터 삭제: {screen_date} ({deleted}건)")
        return deleted
    
    def search_occurrences(self, query: str, limit: int = 200) -> List[dict]:
        """종목 검색 - TOP5 출현 기록 조회 (v6.3.2)
        
        종목코드 또는 종목명으로 검색하여 해당 종목이 TOP5에 등장한 날짜들을 반환
        
        Args:
            query: 종목코드(6자리) 또는 종목명 일부
            limit: 최대 결과 수
            
        Returns:
            출현 기록 리스트 (최신 날짜 순)
        """
        # 6자리 숫자면 종목코드로 검색
        if query.isdigit() and len(query) == 6:
            rows = self.db.fetch_all(
                """
                SELECT screen_date, rank, stock_code, stock_name, screen_price, 
                       screen_score, grade, change_rate, trading_value, data_source
                FROM closing_top5_history 
                WHERE stock_code = ?
                ORDER BY screen_date DESC
                LIMIT ?
                """,
                (query, limit)
            )
        else:
            # 종목명으로 검색 (LIKE)
            rows = self.db.fetch_all(
                """
                SELECT screen_date, rank, stock_code, stock_name, screen_price, 
                       screen_score, grade, change_rate, trading_value, data_source
                FROM closing_top5_history 
                WHERE stock_name LIKE ?
                ORDER BY screen_date DESC
                LIMIT ?
                """,
                (f'%{query}%', limit)
            )
        
        return [dict(row) for row in rows]
    
    def has_realtime(self, screen_date: str) -> bool:
        """해당 날짜에 realtime 데이터가 있는지 확인 (v6.3.2)
        
        Args:
            screen_date: 날짜 (YYYY-MM-DD)
            
        Returns:
            realtime 데이터 존재 여부
        """
        row = self.db.fetch_one(
            "SELECT COUNT(*) as cnt FROM closing_top5_history WHERE screen_date = ? AND data_source = 'realtime'",
            (screen_date,)
        )
        return row['cnt'] > 0 if row else False
    
    def delete_backfill_by_date(self, screen_date: str) -> int:
        """특정 날짜의 backfill 데이터만 삭제 (v6.3.2)
        
        realtime 데이터는 보존하고 backfill 데이터만 삭제
        
        Args:
            screen_date: 날짜 (YYYY-MM-DD)
            
        Returns:
            삭제된 행 수
        """
        cursor = self.db.execute(
            "DELETE FROM closing_top5_history WHERE screen_date = ? AND data_source = 'backfill'",
            (screen_date,)
        )
        deleted = cursor.rowcount
        if deleted > 0:
            logger.info(f"TOP5 backfill 데이터 삭제: {screen_date} ({deleted}건)")
        return deleted
    
    def upsert_backfill_safe(self, data: dict) -> Optional[int]:
        """백필 데이터 안전 삽입 - realtime이 있으면 삽입하지 않음 (v6.3.2)
        
        Args:
            data: TOP5 데이터 딕셔너리
            
        Returns:
            생성/갱신된 ID 또는 None (realtime이 이미 존재하는 경우)
        """
        screen_date = data['screen_date']
        stock_code = data['stock_code']
        
        # 해당 날짜+종목에 realtime 데이터가 있는지 확인
        existing = self.db.fetch_one(
            "SELECT id, data_source FROM closing_top5_history WHERE screen_date = ? AND stock_code = ?",
            (screen_date, stock_code)
        )
        
        if existing:
            if existing['data_source'] == 'realtime':
                # realtime 데이터가 있으면 덮어쓰지 않음
                logger.debug(f"realtime 데이터 존재, 백필 스킵: {screen_date} {stock_code}")
                return None
            else:
                # backfill 데이터면 업데이트
                return self.upsert(data)
        else:
            # 새로 삽입
            return self.upsert(data)


class Top5DailyPricesRepository:
    """top5_daily_prices 테이블 CRUD"""
    
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()
    
    def insert(self, data: dict) -> int:
        """일별 가격 삽입"""
        existing = self.db.fetch_one(
            "SELECT id FROM top5_daily_prices WHERE top5_history_id = ? AND trade_date = ?",
            (data['top5_history_id'], data['trade_date'])
        )
        
        if existing:
            return existing['id']
        
        cursor = self.db.execute(
            """
            INSERT INTO top5_daily_prices
            (top5_history_id, trade_date, days_after, open_price, high_price, low_price, close_price,
             volume, return_from_screen, gap_rate, high_return, low_return, data_source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data['top5_history_id'], data['trade_date'], data['days_after'],
                data['open_price'], data['high_price'], data['low_price'], data['close_price'],
                data.get('volume'), data['return_from_screen'],
                data.get('gap_rate'), data.get('high_return'), data.get('low_return'),
                data.get('data_source', 'realtime')
            )
        )
        return cursor.lastrowid
    
    def get_by_history(self, history_id: int) -> List[dict]:
        """특정 TOP5 종목의 모든 일별 가격"""
        rows = self.db.fetch_all(
            "SELECT * FROM top5_daily_prices WHERE top5_history_id = ? ORDER BY days_after",
            (history_id,)
        )
        return [dict(row) for row in rows]
    
    def exists(self, history_id: int, trade_date: str) -> bool:
        """중복 체크"""
        row = self.db.fetch_one(
            "SELECT id FROM top5_daily_prices WHERE top5_history_id = ? AND trade_date = ?",
            (history_id, trade_date)
        )
        return row is not None
    
    def get_collected_days(self, history_id: int) -> List[int]:
        """수집된 D+N 목록"""
        rows = self.db.fetch_all(
            "SELECT days_after FROM top5_daily_prices WHERE top5_history_id = ? ORDER BY days_after",
            (history_id,)
        )
        return [row['days_after'] for row in rows]



def get_top5_history_repository() -> Top5HistoryRepository:
    return Top5HistoryRepository()


def get_top5_daily_prices_repository() -> Top5DailyPricesRepository:
    return Top5DailyPricesRepository()

