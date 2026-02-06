"""
데이터 접근 레이어 (v6.0)

책임:
- CRUD 오퍼레이션
- 복잡한 쿼리 캡슐화
- 데이터 모델 변환

v6.0 추가:
- Top5HistoryRepository: TOP5 20일 추적 마스터
- Top5DailyPricesRepository: D+1~D+20 일별 가격
- NomadCandidatesRepository: 유목민 후보 종목
- NomadNewsRepository: 유목민 뉴스

의존성:
- infrastructure.database
- domain.models
"""

import json
import logging
from datetime import date
from typing import List, Optional, Dict

from src.infrastructure.database import get_database, Database
from src.domain.models import (
    StockScore,
    Weights,
    ScreeningResult,
    NextDayResult,
)

logger = logging.getLogger(__name__)


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


class WeightRepository:
    """가중치 저장소"""
    
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()
    
    def get_weights(self) -> Weights:
        """현재 가중치 조회"""
        rows = self.db.fetch_all(
            "SELECT indicator, weight FROM weight_config WHERE is_active = 1"
        )
        
        weight_dict = {row['indicator']: row['weight'] for row in rows}
        return Weights.from_dict(weight_dict)
    
    def update_weight(
        self,
        indicator: str,
        new_weight: float,
        reason: str = "",
        correlation: Optional[float] = None,
        sample_size: Optional[int] = None,
    ):
        """가중치 업데이트"""
        # 현재 가중치 조회
        current = self.db.fetch_one(
            "SELECT weight FROM weight_config WHERE indicator = ?",
            (indicator,)
        )
        
        if not current:
            logger.error(f"알 수 없는 지표: {indicator}")
            return
        
        old_weight = current['weight']
        
        # 가중치 업데이트
        self.db.execute(
            """
            UPDATE weight_config SET weight = ?, updated_at = CURRENT_TIMESTAMP
            WHERE indicator = ?
            """,
            (new_weight, indicator)
        )
        
        # 이력 저장
        self.db.execute(
            """
            INSERT INTO weight_history 
            (indicator, old_weight, new_weight, change_reason, correlation, sample_size)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (indicator, old_weight, new_weight, reason, correlation, sample_size)
        )
        
        logger.info(f"가중치 업데이트: {indicator} {old_weight} -> {new_weight}")
    
    def update_weights(
        self,
        weights: Weights,
        reason: str = "",
    ):
        """전체 가중치 업데이트"""
        weight_dict = weights.to_dict()
        for indicator, weight in weight_dict.items():
            self.update_weight(indicator, weight, reason)
    
    def get_weight_history(self, days: int = 30) -> List[Dict]:
        """가중치 변경 이력 조회"""
        rows = self.db.fetch_all(
            """
            SELECT * FROM weight_history 
            WHERE changed_at >= DATE('now', ?)
            ORDER BY changed_at DESC
            """,
            (f'-{days} days',)
        )
        return [dict(row) for row in rows]


class TradeJournalRepository:
    """매매일지 저장소"""
    
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()
    
    def add_trade(
        self,
        trade_date: date,
        stock_code: str,
        stock_name: str,
        trade_type: str,
        price: int,
        quantity: int,
        screening_item_id: Optional[int] = None,
        memo: str = "",
    ) -> int:
        """매매 기록 추가"""
        total_amount = price * quantity
        
        cursor = self.db.execute(
            """
            INSERT INTO trade_journal 
            (trade_date, stock_code, stock_name, trade_type, price, quantity, 
             total_amount, screening_item_id, memo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_date.isoformat(),
                stock_code,
                stock_name,
                trade_type,
                price,
                quantity,
                total_amount,
                screening_item_id,
                memo,
            )
        )
        
        logger.info(f"매매 기록 추가: {stock_name} {trade_type} {quantity}주 @ {price:,}")
        return cursor.lastrowid
    
    def get_trades(self, days: int = 30) -> List[Dict]:
        """매매 기록 조회"""
        rows = self.db.fetch_all(
            """
            SELECT * FROM trade_journal 
            WHERE trade_date >= DATE('now', ?)
            ORDER BY trade_date DESC, created_at DESC
            """,
            (f'-{days} days',)
        )
        return [dict(row) for row in rows]
    
    def get_trade_summary(self) -> Dict:
        """매매 요약 조회"""
        row = self.db.fetch_one(
            """
            SELECT 
                COUNT(*) as total_trades,
                SUM(CASE WHEN trade_type = 'BUY' THEN total_amount ELSE 0 END) as total_buy,
                SUM(CASE WHEN trade_type = 'SELL' THEN total_amount ELSE 0 END) as total_sell,
                AVG(return_rate) as avg_return_rate
            FROM trade_journal
            """
        )
        return dict(row) if row else {}


class Repository:
    """통합 저장소 (Learner Service용)"""
    
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()
        self.screening = ScreeningRepository(self.db)
        self.next_day = NextDayResultRepository(self.db)
        self.weight = WeightRepository(self.db)
        self.journal = TradeJournalRepository(self.db)
    
    def get_screening_results_by_date(self, screen_date: date) -> List[Dict]:
        """특정 날짜의 스크리닝 결과 조회"""
        screening = self.screening.get_screening_by_date(screen_date)
        if not screening:
            return []
        
        items = self.screening.get_screening_items(screening['id'])
        
        # StockScore 형태로 변환
        results = []
        for item in items:
            results.append(type('ScreeningItem', (), {
                'stock_code': item['stock_code'],
                'stock_name': item['stock_name'],
                'rank': item['rank'],
                'score_total': item['score_total'],
            })())
        
        return results
    
    def save_next_day_result(
        self,
        stock_code: str,
        screen_date: date,
        gap_rate: float,
        day_return: float,
        volatility: float,
        next_open: int,
        next_close: int,
        next_high: int,
        next_low: int,
        high_change_rate: float = 0.0,
    ):
        """익일 결과 저장 (간소화 버전)"""
        # 해당 종목의 screening_item_id 찾기
        row = self.db.fetch_one(
            """
            SELECT si.id FROM screening_items si
            JOIN screenings s ON si.screening_id = s.id
            WHERE s.screen_date = ? AND si.stock_code = ?
            """,
            (screen_date.isoformat(), stock_code)
        )
        
        if not row:
            logger.warning(f"스크리닝 아이템 없음: {stock_code} / {screen_date}")
            return
        
        item_id = row['id']
        
        # 중복 체크
        existing = self.db.fetch_one(
            "SELECT id FROM next_day_results WHERE screening_item_id = ?",
            (item_id,)
        )
        
        if existing:
            logger.debug(f"익일 결과 이미 존재: {stock_code}")
            return
        
        # 저장 (open_change_rate, high_change_rate 추가)
        next_date = screen_date
        self.db.execute(
            """
            INSERT INTO next_day_results 
            (screening_item_id, next_date, open_price, close_price, high_price, 
             low_price, open_change_rate, day_change_rate, high_change_rate,
             gap_rate, volatility, is_open_up, is_day_up)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                next_date.isoformat(),
                next_open,
                next_close,
                next_high,
                next_low,
                gap_rate,        # open_change_rate (시가 상승률 = gap_rate)
                day_return,      # day_change_rate
                high_change_rate,  # high_change_rate
                gap_rate,        # gap_rate
                volatility,
                1 if gap_rate > 0 else 0,
                1 if day_return > 0 else 0,
            )
        )
        logger.debug(f"익일 결과 저장: {stock_code}")
    
    def get_next_day_results(
        self, 
        start_date: date = None, 
        end_date: date = None,
        days: int = 30
    ) -> List[Dict]:
        """익일 결과 조회
        
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
    
    def get_screening_with_next_day(self, days: int = 30) -> List[Dict]:
        """스크리닝 결과와 익일 결과 조인 조회 (상관관계 분석용)"""
        rows = self.db.fetch_all(
            """
            SELECT 
                si.stock_code,
                si.stock_name,
                si.score_total,
                si.score_cci_value,
                si.score_cci_slope,
                si.score_ma20_slope,
                si.score_candle,
                si.score_change,
                si.rank,
                ndr.gap_rate,
                ndr.day_change_rate,
                ndr.volatility
            FROM screening_items si
            JOIN screenings s ON si.screening_id = s.id
            JOIN next_day_results ndr ON si.id = ndr.screening_item_id
            WHERE s.screen_date >= DATE('now', ?)
            ORDER BY s.screen_date DESC
            """,
            (f'-{days} days',)
        )
        return [dict(row) for row in rows]
    
    def get_current_weights(self) -> Optional[Dict[str, float]]:
        """현재 가중치 조회 (딕셔너리 형태)"""
        rows = self.db.fetch_all(
            "SELECT indicator, weight FROM weight_config WHERE is_active = 1"
        )
        
        if not rows:
            return None
        
        return {row['indicator']: row['weight'] for row in rows}
    
    def get_k_signal_results(self, days: int = 30) -> List[Dict]:
        """v5.4: K값 전략 제거됨 - 빈 리스트 반환"""
        return []
    
    def get_k_strategy_config(self) -> Dict[str, float]:
        """v5.4: K값 전략 제거됨 - 빈 딕셔너리 반환"""
        return {}
    
    def update_k_strategy_param(
        self, 
        param_name: str, 
        new_value: float, 
        reason: str = ""
    ):
        """v5.4: K값 전략 제거됨 - 아무 작업 안함"""
        pass
    
    def update_weights(self, weights: Dict[str, float]):
        """전체 가중치 업데이트"""
        for indicator, weight in weights.items():
            self.db.execute(
                """
                UPDATE weight_config SET weight = ?, updated_at = CURRENT_TIMESTAMP
                WHERE indicator = ?
                """,
                (weight, indicator)
            )
        logger.info(f"가중치 업데이트 완료: {weights}")
    
    def save_weight_history(
        self,
        weights: Dict[str, float],
        correlations: Dict[str, float],
        reason: str,
    ):
        """가중치 변경 이력 저장"""
        for indicator, weight in weights.items():
            correlation = correlations.get(indicator)
            
            # 이전 가중치 조회
            old = self.db.fetch_one(
                "SELECT weight FROM weight_config WHERE indicator = ?",
                (indicator,)
            )
            old_weight = old['weight'] if old else 1.0
            
            self.db.execute(
                """
                INSERT INTO weight_history 
                (indicator, old_weight, new_weight, change_reason, correlation)
                VALUES (?, ?, ?, ?, ?)
                """,
                (indicator, old_weight, weight, reason, correlation)
            )
        logger.info(f"가중치 이력 저장 완료")


# ============================================================
# K값 시그널 Repository
# ============================================================

class KSignalRepository:
    """K값 돌파 시그널 저장소"""
    
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()
    
    def save_signal(self, signal: dict) -> int:
        """K값 시그널 저장
        
        Args:
            signal: 시그널 딕셔너리
            
        Returns:
            생성된 signal ID
        """
        signal_date = signal.get('signal_date', date.today().isoformat())
        if isinstance(signal_date, date):
            signal_date = signal_date.isoformat()
        
        # 기존 데이터 확인 (같은 날짜 + 종목)
        existing = self.db.fetch_one(
            "SELECT id FROM k_signals WHERE signal_date = ? AND stock_code = ?",
            (signal_date, signal['stock_code'])
        )
        
        if existing:
            # 업데이트
            signal_id = existing['id']
            self.db.execute(
                """
                UPDATE k_signals SET
                    signal_time = ?,
                    stock_name = ?,
                    current_price = ?,
                    open_price = ?,
                    breakout_price = ?,
                    prev_high = ?,
                    prev_low = ?,
                    prev_close = ?,
                    k_value = ?,
                    range_value = ?,
                    prev_change_pct = ?,
                    volume_ratio = ?,
                    trading_value = ?,
                    stop_loss_pct = ?,
                    take_profit_pct = ?,
                    stop_loss_price = ?,
                    take_profit_price = ?,
                    index_change = ?,
                    index_above_ma5 = ?,
                    score = ?,
                    confidence = ?,
                    rank = ?
                WHERE id = ?
                """,
                (
                    signal.get('signal_time', '15:00'),
                    signal.get('stock_name', ''),
                    signal.get('current_price', 0),
                    signal.get('open_price', 0),
                    signal.get('breakout_price', 0),
                    signal.get('prev_high', 0),
                    signal.get('prev_low', 0),
                    signal.get('prev_close', 0),
                    signal.get('k_value', 0.3),
                    signal.get('range_value', 0),
                    signal.get('prev_change_pct', 0),
                    signal.get('volume_ratio', 0),
                    signal.get('trading_value', 0),
                    signal.get('stop_loss_pct', -2.0),
                    signal.get('take_profit_pct', 5.0),
                    signal.get('stop_loss_price', 0),
                    signal.get('take_profit_price', 0),
                    signal.get('index_change', 0),
                    1 if signal.get('index_above_ma5', True) else 0,
                    signal.get('score', 0),
                    signal.get('confidence', 0),
                    signal.get('rank', 0),
                    signal_id,
                )
            )
        else:
            # 새로 생성
            cursor = self.db.execute(
                """
                INSERT INTO k_signals
                (signal_date, signal_time, stock_code, stock_name,
                 current_price, open_price, breakout_price, prev_high, prev_low, prev_close,
                 k_value, range_value, prev_change_pct, volume_ratio, trading_value,
                 stop_loss_pct, take_profit_pct, stop_loss_price, take_profit_price,
                 index_change, index_above_ma5, score, confidence, rank)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal_date,
                    signal.get('signal_time', '15:00'),
                    signal['stock_code'],
                    signal.get('stock_name', ''),
                    signal.get('current_price', 0),
                    signal.get('open_price', 0),
                    signal.get('breakout_price', 0),
                    signal.get('prev_high', 0),
                    signal.get('prev_low', 0),
                    signal.get('prev_close', 0),
                    signal.get('k_value', 0.3),
                    signal.get('range_value', 0),
                    signal.get('prev_change_pct', 0),
                    signal.get('volume_ratio', 0),
                    signal.get('trading_value', 0),
                    signal.get('stop_loss_pct', -2.0),
                    signal.get('take_profit_pct', 5.0),
                    signal.get('stop_loss_price', 0),
                    signal.get('take_profit_price', 0),
                    signal.get('index_change', 0),
                    1 if signal.get('index_above_ma5', True) else 0,
                    signal.get('score', 0),
                    signal.get('confidence', 0),
                    signal.get('rank', 0),
                )
            )
            signal_id = cursor.lastrowid
        
        return signal_id
    
    def save_signals(self, signals: List[dict]) -> int:
        """여러 시그널 저장
        
        Args:
            signals: 시그널 리스트
            
        Returns:
            저장된 개수
        """
        saved = 0
        for i, sig in enumerate(signals):
            try:
                sig['rank'] = i + 1
                self.save_signal(sig)
                saved += 1
            except Exception as e:
                logger.error(f"K시그널 저장 실패 {sig.get('stock_code', '?')}: {e}")
        
        logger.info(f"K값 시그널 {saved}개 저장")
        return saved
    
    def get_signals_without_result(self, signal_date: date = None) -> List[dict]:
        """익일 결과 없는 시그널 조회
        
        Args:
            signal_date: 시그널 날짜 (기본: 어제)
            
        Returns:
            시그널 리스트
        """
        if signal_date is None:
            from datetime import timedelta
            signal_date = date.today() - timedelta(days=1)
        
        rows = self.db.fetch_all(
            """
            SELECT s.* FROM k_signals s
            LEFT JOIN k_signal_results r ON s.id = r.k_signal_id
            WHERE s.signal_date = ? AND r.id IS NULL
            ORDER BY s.rank
            """,
            (signal_date.isoformat(),)
        )
        
        return [dict(row) for row in rows]
    
    def get_signals_by_date(self, signal_date: date) -> List[dict]:
        """날짜별 시그널 조회"""
        rows = self.db.fetch_all(
            "SELECT * FROM k_signals WHERE signal_date = ? ORDER BY rank",
            (signal_date.isoformat(),)
        )
        return [dict(row) for row in rows]
    
    def save_result(self, k_signal_id: int, result: dict) -> int:
        """익일 결과 저장
        
        Args:
            k_signal_id: 시그널 ID
            result: 결과 딕셔너리
            
        Returns:
            결과 ID
        """
        # 기존 결과 확인
        existing = self.db.fetch_one(
            "SELECT id FROM k_signal_results WHERE k_signal_id = ?",
            (k_signal_id,)
        )
        
        if existing:
            return existing['id']
        
        cursor = self.db.execute(
            """
            INSERT INTO k_signal_results
            (k_signal_id, next_date, next_open, next_high, next_low, next_close,
             entry_price, exit_price, profit_pct, hit_stop_loss, hit_take_profit,
             is_win, max_profit_pct, max_loss_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                k_signal_id,
                result['next_date'],
                result['next_open'],
                result['next_high'],
                result['next_low'],
                result['next_close'],
                result['entry_price'],
                result['exit_price'],
                result['profit_pct'],
                1 if result.get('hit_stop_loss') else 0,
                1 if result.get('hit_take_profit') else 0,
                1 if result['profit_pct'] > 0 else 0,
                result.get('max_profit_pct', 0),
                result.get('max_loss_pct', 0),
            )
        )
        return cursor.lastrowid
    
    def get_results_with_signals(self, days: int = 30) -> List[dict]:
        """시그널 + 결과 조인 조회 (분석용)
        
        Args:
            days: 조회 기간
            
        Returns:
            시그널+결과 리스트
        """
        rows = self.db.fetch_all(
            """
            SELECT s.*, r.next_date, r.next_open, r.next_high, r.next_low, r.next_close,
                   r.entry_price, r.exit_price, r.profit_pct, r.hit_stop_loss, 
                   r.hit_take_profit, r.is_win, r.max_profit_pct, r.max_loss_pct
            FROM k_signals s
            JOIN k_signal_results r ON s.id = r.k_signal_id
            WHERE s.signal_date >= date('now', ?)
            ORDER BY s.signal_date DESC, s.rank
            """,
            (f'-{days} days',)
        )
        return [dict(row) for row in rows]
    
    def get_performance_summary(self, days: int = 30) -> dict:
        """K값 전략 성과 요약
        
        Args:
            days: 분석 기간
            
        Returns:
            성과 통계
        """
        data = self.get_results_with_signals(days)
        
        if not data:
            return {}
        
        wins = sum(1 for d in data if d['is_win'])
        profits = [d['profit_pct'] for d in data]
        
        return {
            'total_signals': len(data),
            'wins': wins,
            'losses': len(data) - wins,
            'win_rate': (wins / len(data)) * 100 if data else 0,
            'avg_profit': sum(profits) / len(profits) if profits else 0,
            'max_profit': max(profits) if profits else 0,
            'max_loss': min(profits) if profits else 0,
            'total_profit': sum(profits),
        }


class KStrategyConfigRepository:
    """K값 전략 설정 저장소"""
    
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()
    
    def get_config(self) -> dict:
        """현재 설정 조회"""
        rows = self.db.fetch_all(
            "SELECT param_name, param_value FROM k_strategy_config WHERE is_active = 1"
        )
        return {row['param_name']: row['param_value'] for row in rows}
    
    def update_config(self, param_name: str, new_value: float, reason: str = None,
                     win_rate_before: float = None, win_rate_after: float = None,
                     sample_size: int = None):
        """설정 업데이트
        
        Args:
            param_name: 파라미터 이름
            new_value: 새 값
            reason: 변경 사유
        """
        # 현재 값 조회
        current = self.db.fetch_one(
            "SELECT param_value, min_value, max_value FROM k_strategy_config WHERE param_name = ?",
            (param_name,)
        )
        
        if not current:
            logger.warning(f"존재하지 않는 파라미터: {param_name}")
            return
        
        old_value = current['param_value']
        min_val = current['min_value'] or float('-inf')
        max_val = current['max_value'] or float('inf')
        
        # 범위 제한
        new_value = max(min_val, min(max_val, new_value))
        
        # 업데이트
        self.db.execute(
            "UPDATE k_strategy_config SET param_value = ?, updated_at = CURRENT_TIMESTAMP WHERE param_name = ?",
            (new_value, param_name)
        )
        
        # 이력 저장
        self.db.execute(
            """
            INSERT INTO k_strategy_history
            (param_name, old_value, new_value, change_reason, win_rate_before, win_rate_after, sample_size)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (param_name, old_value, new_value, reason, win_rate_before, win_rate_after, sample_size)
        )
        
        logger.info(f"K전략 설정 업데이트: {param_name} {old_value} → {new_value}")
    
    def get_history(self, days: int = 30) -> List[dict]:
        """설정 변경 이력 조회"""
        rows = self.db.fetch_all(
            """
            SELECT * FROM k_strategy_history
            WHERE changed_at >= date('now', ?)
            ORDER BY changed_at DESC
            """,
            (f'-{days} days',)
        )
        return [dict(row) for row in rows]


# 싱글톤 인스턴스
_repository: Optional[Repository] = None


def get_repository() -> Repository:
    """통합 Repository 인스턴스 반환"""
    global _repository
    if _repository is None:
        _repository = Repository()
    return _repository


# 편의 함수들
def get_screening_repository() -> ScreeningRepository:
    return ScreeningRepository()

def get_weight_repository() -> WeightRepository:
    return WeightRepository()

def get_next_day_repository() -> NextDayResultRepository:
    return NextDayResultRepository()

def get_trade_journal_repository() -> TradeJournalRepository:
    return TradeJournalRepository()


# v5.4: K값 전략 제거 - 아래 함수들은 호환성을 위해 빈 값 반환
def get_k_signal_repository():
    """v5.4: K값 전략 제거됨 - 빈 객체 반환"""
    return None

def get_k_strategy_config_repository():
    """v5.4: K값 전략 제거됨 - 빈 객체 반환"""
    return None


# ========================================================================
# v6.0 Repository 클래스들: TOP5 20일 추적 + 유목민 공부법
# ========================================================================

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


class NomadCandidatesRepository:
    """nomad_candidates 테이블 CRUD"""
    
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()
    
    def upsert(self, data: dict) -> int:
        """후보 삽입/갱신"""
        existing = self.db.fetch_one(
            "SELECT id FROM nomad_candidates WHERE study_date = ? AND stock_code = ?",
            (data['study_date'], data['stock_code'])
        )
        
        if existing:
            self.db.execute(
                """
                UPDATE nomad_candidates SET
                    stock_name = ?, reason_flag = ?, close_price = ?, change_rate = ?,
                    volume = ?, trading_value = ?, data_source = ?
                WHERE id = ?
                """,
                (
                    data['stock_name'], data['reason_flag'], data['close_price'],
                    data['change_rate'], data['volume'], data['trading_value'],
                    data.get('data_source', 'realtime'), existing['id']
                )
            )
            return existing['id']
        else:
            cursor = self.db.execute(
                """
                INSERT INTO nomad_candidates
                (study_date, stock_code, stock_name, reason_flag, close_price, change_rate,
                 volume, trading_value, data_source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data['study_date'], data['stock_code'], data['stock_name'],
                    data['reason_flag'], data['close_price'], data['change_rate'],
                    data['volume'], data['trading_value'],
                    data.get('data_source', 'realtime')
                )
            )
            return cursor.lastrowid
    
    def insert(self, data: dict) -> int:
        """후보 삽입 (upsert 별칭) - nomad_collector 호환용"""
        return self.upsert(data)
    
    def get_by_date(self, study_date: str) -> List[dict]:
        """특정 날짜의 후보"""
        rows = self.db.fetch_all(
            "SELECT * FROM nomad_candidates WHERE study_date = ? ORDER BY change_rate DESC",
            (study_date,)
        )
        return [dict(row) for row in rows]
    
    def get_by_date_and_reason(self, study_date: str, reason_flag: str) -> List[dict]:
        """날짜 + 사유로 조회"""
        rows = self.db.fetch_all(
            "SELECT * FROM nomad_candidates WHERE study_date = ? AND reason_flag = ? ORDER BY change_rate DESC",
            (study_date, reason_flag)
        )
        return [dict(row) for row in rows]
    
    def get_by_date_and_code(self, study_date: str, stock_code: str) -> Optional[dict]:
        """특정 종목 조회"""
        row = self.db.fetch_one(
            "SELECT * FROM nomad_candidates WHERE study_date = ? AND stock_code = ?",
            (study_date, stock_code)
        )
        return dict(row) if row else None
    
    def update_company_info(self, study_date: str, stock_code: str, info: dict):
        """기업 정보 업데이트"""
        self.db.execute(
            """
            UPDATE nomad_candidates SET
                market = ?, sector = ?, market_cap = ?, per = ?, pbr = ?,
                eps = ?, roe = ?, business_summary = ?, establishment_date = ?,
                ceo_name = ?, revenue = ?, operating_profit = ?
            WHERE study_date = ? AND stock_code = ?
            """,
            (
                info.get('market'), info.get('sector'), info.get('market_cap'),
                info.get('per'), info.get('pbr'), info.get('eps'), info.get('roe'),
                info.get('business_summary'), info.get('establishment_date'),
                info.get('ceo_name'), info.get('revenue'), info.get('operating_profit'),
                study_date, stock_code
            )
        )
    
    def update_news_status(self, study_date: str, stock_code: str, status: str, count: int):
        """뉴스 상태 업데이트"""
        self.db.execute(
            "UPDATE nomad_candidates SET news_status = ?, news_count = ? WHERE study_date = ? AND stock_code = ?",
            (status, count, study_date, stock_code)
        )
    
    def update_ai_summary_by_date(self, study_date: str, stock_code: str, summary: str):
        """AI 요약 업데이트 (날짜+종목코드 기준)"""
        self.db.execute(
            "UPDATE nomad_candidates SET ai_summary = ? WHERE study_date = ? AND stock_code = ?",
            (summary, study_date, stock_code)
        )
    
    def get_dates_with_data(self, days: int = 60) -> List[str]:
        """데이터가 있는 날짜 목록"""
        rows = self.db.fetch_all(
            "SELECT DISTINCT study_date FROM nomad_candidates ORDER BY study_date DESC LIMIT ?",
            (days,)
        )
        return [row['study_date'] for row in rows]
    
    def get_uncollected_news(self, limit: int = 20) -> List[dict]:
        """뉴스 미수집 후보 조회"""
        rows = self.db.fetch_all(
            """
            SELECT * FROM nomad_candidates 
            WHERE news_collected = 0 OR news_collected IS NULL
            ORDER BY study_date DESC, change_rate DESC
            LIMIT ?
            """,
            (limit,)
        )
        return [dict(row) for row in rows]
    
    def delete_by_date(self, study_date: str):
        """특정 날짜의 후보 삭제 (재수집용)
        
        Args:
            study_date: 삭제할 날짜 (YYYY-MM-DD)
        """
        # 관련 뉴스도 함께 삭제
        self.db.execute(
            "DELETE FROM nomad_news WHERE study_date = ?",
            (study_date,)
        )
        self.db.execute(
            "DELETE FROM nomad_candidates WHERE study_date = ?",
            (study_date,)
        )
        logger.info(f"  날짜 {study_date} 데이터 삭제 완료")
    
    def update_news_collected(self, candidate_id: int, news_count: int = 0):
        """뉴스 수집 완료 표시 (news_count 업데이트 포함)
        
        Args:
            candidate_id: 후보 ID
            news_count: 수집된 뉴스 개수 (0이면 nomad_news 테이블에서 카운트)
        """
        if news_count == 0:
            # study_date, stock_code로 실제 뉴스 개수 조회
            candidate = self.db.fetch_one(
                "SELECT study_date, stock_code FROM nomad_candidates WHERE id = ?",
                (candidate_id,)
            )
            if candidate:
                count_row = self.db.fetch_one(
                    "SELECT COUNT(*) as cnt FROM nomad_news WHERE study_date = ? AND stock_code = ?",
                    (candidate['study_date'], candidate['stock_code'])
                )
                news_count = count_row['cnt'] if count_row else 0
        
        self.db.execute(
            """UPDATE nomad_candidates 
               SET news_collected = 1, news_count = ?, news_status = 'collected', updated_at = CURRENT_TIMESTAMP 
               WHERE id = ?""",
            (news_count, candidate_id)
        )
    
    def get_uncollected_company_info(self, limit: int = 20) -> List[dict]:
        """기업정보 미수집 후보 조회"""
        rows = self.db.fetch_all(
            """
            SELECT * FROM nomad_candidates 
            WHERE company_info_collected = 0 OR company_info_collected IS NULL
            ORDER BY study_date DESC, change_rate DESC
            LIMIT ?
            """,
            (limit,)
        )
        return [dict(row) for row in rows]
    
    def update_company_info_by_id(self, candidate_id: int, info: dict):
        """기업 정보 업데이트 (ID 기준) - v6.1 확장"""
        self.db.execute(
            """
            UPDATE nomad_candidates SET
                -- 기본 정보
                market = ?, sector = ?, market_cap = ?, market_cap_rank = ?,
                -- 밸류에이션
                per = ?, pbr = ?, eps = ?, bps = ?, roe = ?,
                -- 컨센서스
                consensus_per = ?, consensus_eps = ?,
                -- 외국인
                foreign_rate = ?, foreign_shares = ?,
                -- 투자의견
                analyst_opinion = ?, analyst_recommend = ?, target_price = ?,
                -- 52주
                high_52w = ?, low_52w = ?,
                -- 배당
                dividend_yield = ?,
                -- 기업상세
                business_summary = ?, establishment_date = ?,
                ceo_name = ?, revenue = ?, operating_profit = ?,
                -- 메타
                company_info_collected = 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                # 기본 정보
                info.get('market'), info.get('sector'), info.get('market_cap'), info.get('market_cap_rank'),
                # 밸류에이션
                info.get('per'), info.get('pbr'), info.get('eps'), info.get('bps'), info.get('roe'),
                # 컨센서스
                info.get('consensus_per'), info.get('consensus_eps'),
                # 외국인
                info.get('foreign_rate'), info.get('foreign_shares'),
                # 투자의견
                info.get('analyst_opinion'), info.get('analyst_recommend'), info.get('target_price'),
                # 52주
                info.get('high_52w'), info.get('low_52w'),
                # 배당
                info.get('dividend_yield'),
                # 기업상세
                info.get('business_summary'), info.get('establishment_date'),
                info.get('ceo_name'), info.get('revenue'), info.get('operating_profit'),
                # ID
                candidate_id
            )
        )
    
    def update_company_info_by_code(self, stock_code: str, info: dict):
        """기업 정보 업데이트 (종목코드 기준) - v6.2"""
        self.db.execute(
            """
            UPDATE nomad_candidates SET
                market = ?, sector = ?, market_cap = ?, market_cap_rank = ?,
                per = ?, pbr = ?, eps = ?, bps = ?, roe = ?,
                consensus_per = ?, consensus_eps = ?,
                foreign_rate = ?, foreign_shares = ?,
                analyst_opinion = ?, analyst_recommend = ?, target_price = ?,
                high_52w = ?, low_52w = ?,
                dividend_yield = ?,
                business_summary = ?, establishment_date = ?,
                ceo_name = ?, revenue = ?, operating_profit = ?,
                company_info_collected = 1, updated_at = CURRENT_TIMESTAMP
            WHERE stock_code = ?
            """,
            (
                info.get('market'), info.get('sector'), info.get('market_cap'), info.get('market_cap_rank'),
                info.get('per'), info.get('pbr'), info.get('eps'), info.get('bps'), info.get('roe'),
                info.get('consensus_per'), info.get('consensus_eps'),
                info.get('foreign_rate'), info.get('foreign_shares'),
                info.get('analyst_opinion'), info.get('analyst_recommend'), info.get('target_price'),
                info.get('high_52w'), info.get('low_52w'),
                info.get('dividend_yield'),
                info.get('business_summary'), info.get('establishment_date'),
                info.get('ceo_name'), info.get('revenue'), info.get('operating_profit'),
                stock_code
            )
        )
    
    def update_ai_summary(self, candidate_id: int, summary: str):
        """AI 요약 업데이트 (ID 기준) - v6.2"""
        self.db.execute(
            "UPDATE nomad_candidates SET ai_summary = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (summary, candidate_id)
        )
    
    def search_occurrences(self, query: str, limit: int = 200) -> List[dict]:
        """종목 검색 - 유목민 출현 기록 조회 (v6.3.2)
        
        종목코드 또는 종목명으로 검색하여 해당 종목이 유목민에 등장한 날짜들을 반환
        
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
                SELECT study_date, stock_code, stock_name, reason_flag, 
                       close_price, change_rate, volume, trading_value, data_source
                FROM nomad_candidates 
                WHERE stock_code = ?
                ORDER BY study_date DESC
                LIMIT ?
                """,
                (query, limit)
            )
        else:
            # 종목명으로 검색 (LIKE)
            rows = self.db.fetch_all(
                """
                SELECT study_date, stock_code, stock_name, reason_flag, 
                       close_price, change_rate, volume, trading_value, data_source
                FROM nomad_candidates 
                WHERE stock_name LIKE ?
                ORDER BY study_date DESC
                LIMIT ?
                """,
                (f'%{query}%', limit)
            )
        
        return [dict(row) for row in rows]


class NomadNewsRepository:
    """nomad_news 테이블 CRUD (v6.0)"""
    
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()
    
    def insert(self, data: dict) -> int:
        """뉴스 삽입 (study_date + stock_code 사용)"""
        # study_date, stock_code 필수
        study_date = data.get('study_date') or data.get('news_date')
        stock_code = data.get('stock_code')
        news_url = data.get('news_url') or data.get('url', '')
        
        if not study_date or not stock_code:
            raise ValueError("study_date, stock_code 필수")
        
        # 중복 체크 (study_date + stock_code + url)
        existing = self.db.fetch_one(
            "SELECT id FROM nomad_news WHERE study_date = ? AND stock_code = ? AND url = ?",
            (study_date, stock_code, news_url)
        )
        
        if existing:
            return existing['id']
        
        cursor = self.db.execute(
            """
            INSERT INTO nomad_news
            (study_date, stock_code, title, publisher, published_at, url, snippet)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                study_date,
                stock_code,
                data.get('news_title') or data.get('title', '')[:200],
                data.get('news_source') or data.get('publisher', ''),
                data.get('published_at') or data.get('news_date'),
                news_url,
                data.get('summary') or data.get('snippet', ''),
            )
        )
        return cursor.lastrowid
    
    def get_by_candidate_id(self, candidate_id: int) -> List[dict]:
        """후보 ID로 뉴스 조회 (deprecated - get_by_candidate 사용)"""
        # candidate_id로 study_date, stock_code 조회
        candidate = self.db.fetch_one(
            "SELECT study_date, stock_code FROM nomad_candidates WHERE id = ?",
            (candidate_id,)
        )
        if not candidate:
            return []
        return self.get_by_candidate(candidate['study_date'], candidate['stock_code'])
    
    def get_by_candidate(self, study_date: str, stock_code: str) -> List[dict]:
        """후보의 뉴스 조회 (날짜+종목코드)"""
        # nomad_news 테이블에서 직접 조회 (candidate_id 없이)
        rows = self.db.fetch_all(
            "SELECT * FROM nomad_news WHERE study_date = ? AND stock_code = ? ORDER BY published_at DESC",
            (study_date, stock_code)
        )
        
        if not rows:
            return []
        
        # 필드명 호환 매핑 (대시보드용)
        result = []
        for row in rows:
            item = dict(row)
            # 호환성 필드 추가
            item['news_title'] = item.get('title', '')
            item['news_url'] = item.get('url', '')
            item['news_source'] = item.get('publisher', '')
            item['news_date'] = item.get('published_at', '')
            item['summary'] = item.get('snippet', '')
            item['sentiment'] = '중립'  # 기본값
            result.append(item)
        
        return result
    
    def count_by_candidate(self, study_date: str, stock_code: str) -> int:
        """후보의 뉴스 개수"""
        row = self.db.fetch_one(
            "SELECT COUNT(*) as cnt FROM nomad_news WHERE study_date = ? AND stock_code = ?",
            (study_date, stock_code)
        )
        return row['cnt'] if row else 0
    
    def get_summary_stats(self) -> dict:
        """뉴스 통계"""
        row = self.db.fetch_one(
            """
            SELECT 
                COUNT(*) as total_news,
                COUNT(DISTINCT candidate_id) as candidates_with_news,
                SUM(CASE WHEN sentiment = 'positive' THEN 1 ELSE 0 END) as positive,
                SUM(CASE WHEN sentiment = 'negative' THEN 1 ELSE 0 END) as negative,
                SUM(CASE WHEN sentiment = 'neutral' THEN 1 ELSE 0 END) as neutral
            FROM nomad_news
            """
        )
        return dict(row) if row else {}


# ============================================================
# TV200 스냅샷 Repository (v6.3.3)
# ============================================================

class TV200SnapshotRepository:
    """TV200 조건검색 결과 스냅샷 저장소 (v6.3.3)
    
    유니버스 소스 오브 트루스(Source of Truth)를 저장하여
    백필에서 실시간과 동일한 유니버스를 사용할 수 있도록 함
    """
    
    def __init__(self, db: Database = None):
        self.db = db or get_database()
        self._ensure_table()
    
    def _ensure_table(self):
        """테이블이 없으면 생성"""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS tv200_snapshot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                screen_date TEXT NOT NULL,
                run_at TEXT NOT NULL,
                source TEXT DEFAULT 'TV200',
                filter_stage TEXT DEFAULT 'after',
                stock_count INTEGER DEFAULT 0,
                codes_json TEXT,
                names_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(screen_date, filter_stage)
            )
        """)
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_tv200_snapshot_date ON tv200_snapshot(screen_date)"
        )
    
    def save_snapshot(
        self,
        screen_date: str,
        codes: List[str],
        names: Dict[str, str] = None,
        filter_stage: str = 'after',
        source: str = 'TV200',
    ) -> int:
        """TV200 스냅샷 저장
        
        Args:
            screen_date: 스크리닝 기준 날짜 (YYYY-MM-DD)
            codes: 종목코드 리스트
            names: 종목코드 → 종목명 매핑 (선택)
            filter_stage: 'before' (필터 전) 또는 'after' (필터 후)
            source: 소스 (TV200, manual 등)
            
        Returns:
            저장된 row ID (업데이트 시에도 ID 반환)
        """
        import json
        from datetime import datetime
        
        codes_json = json.dumps(codes, ensure_ascii=False)
        names_json = json.dumps(names, ensure_ascii=False) if names else None
        run_at = datetime.now().isoformat()
        
        cursor = self.db.execute(
            """
            INSERT INTO tv200_snapshot 
                (screen_date, run_at, source, filter_stage, stock_count, codes_json, names_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(screen_date, filter_stage) DO UPDATE SET
                run_at = excluded.run_at,
                source = excluded.source,
                stock_count = excluded.stock_count,
                codes_json = excluded.codes_json,
                names_json = excluded.names_json
            """,
            (screen_date, run_at, source, filter_stage, len(codes), codes_json, names_json)
        )
        
        # 저장된 ID 조회
        row = self.db.fetch_one(
            "SELECT id FROM tv200_snapshot WHERE screen_date = ? AND filter_stage = ?",
            (screen_date, filter_stage)
        )
        
        logger.info(f"TV200 스냅샷 저장: {screen_date} ({filter_stage}) - {len(codes)}개")
        return row['id'] if row else 0
    
    def get_snapshot(
        self,
        screen_date: str,
        filter_stage: str = 'after'
    ) -> Optional[Dict]:
        """특정 날짜의 TV200 스냅샷 조회
        
        Args:
            screen_date: 스크리닝 날짜 (YYYY-MM-DD)
            filter_stage: 'before' 또는 'after'
            
        Returns:
            스냅샷 정보 dict 또는 None
        """
        import json
        
        row = self.db.fetch_one(
            """
            SELECT * FROM tv200_snapshot 
            WHERE screen_date = ? AND filter_stage = ?
            """,
            (screen_date, filter_stage)
        )
        
        if not row:
            return None
        
        result = dict(row)
        result['codes'] = json.loads(result['codes_json']) if result['codes_json'] else []
        result['names'] = json.loads(result['names_json']) if result['names_json'] else {}
        
        return result
    
    def get_codes_for_date(
        self,
        screen_date: str,
        filter_stage: str = 'after'
    ) -> List[str]:
        """특정 날짜의 유니버스 코드 리스트만 반환
        
        Args:
            screen_date: 스크리닝 날짜 (YYYY-MM-DD)
            filter_stage: 'before' 또는 'after'
            
        Returns:
            종목코드 리스트 (없으면 빈 리스트)
        """
        snapshot = self.get_snapshot(screen_date, filter_stage)
        return snapshot['codes'] if snapshot else []
    
    def has_snapshot(self, screen_date: str, filter_stage: str = 'after') -> bool:
        """해당 날짜에 스냅샷이 있는지 확인"""
        row = self.db.fetch_one(
            "SELECT 1 FROM tv200_snapshot WHERE screen_date = ? AND filter_stage = ?",
            (screen_date, filter_stage)
        )
        return row is not None
    
    def get_all_dates(self, filter_stage: str = 'after') -> List[str]:
        """스냅샷이 있는 모든 날짜 목록"""
        rows = self.db.fetch_all(
            """
            SELECT screen_date FROM tv200_snapshot 
            WHERE filter_stage = ? 
            ORDER BY screen_date DESC
            """,
            (filter_stage,)
        )
        return [row['screen_date'] for row in rows]
    
    def compare_universe(
        self,
        screen_date: str,
        backfill_codes: List[str]
    ) -> Dict:
        """TV200 유니버스와 백필 유니버스 비교
        
        Args:
            screen_date: 스크리닝 날짜
            backfill_codes: 백필로 재현한 종목코드 리스트
            
        Returns:
            비교 결과 dict
        """
        tv200_codes = self.get_codes_for_date(screen_date)
        
        if not tv200_codes:
            return {
                'tv200_count': 0,
                'backfill_count': len(backfill_codes),
                'common_count': 0,
                'only_in_tv200': [],
                'only_in_backfill': backfill_codes,
                'match_rate': 0.0,
                'has_snapshot': False,
            }
        
        tv200_set = set(tv200_codes)
        backfill_set = set(backfill_codes)
        
        common = tv200_set & backfill_set
        only_tv200 = tv200_set - backfill_set
        only_backfill = backfill_set - tv200_set
        
        match_rate = len(common) / len(tv200_set) * 100 if tv200_set else 0
        
        return {
            'tv200_count': len(tv200_codes),
            'backfill_count': len(backfill_codes),
            'common_count': len(common),
            'only_in_tv200': sorted(list(only_tv200)),
            'only_in_backfill': sorted(list(only_backfill)),
            'match_rate': match_rate,
            'has_snapshot': True,
        }
    
    def get_summary_stats(self) -> Dict:
        """스냅샷 통계"""
        row = self.db.fetch_one(
            """
            SELECT 
                COUNT(DISTINCT screen_date) as total_dates,
                MIN(screen_date) as first_date,
                MAX(screen_date) as last_date,
                AVG(stock_count) as avg_count
            FROM tv200_snapshot
            WHERE filter_stage = 'after'
            """
        )
        return dict(row) if row else {}


def get_tv200_snapshot_repository() -> TV200SnapshotRepository:
    return TV200SnapshotRepository()


# ============================================================
# v6.5 DART 연동: CompanyProfileRepository
# ============================================================
class CompanyProfileRepository:
    """DART 기업 프로필 캐시 Repository
    
    company_profiles 테이블 관리
    - 기업개황 (DART)
    - 재무요약 (DART)
    - 위험공시 요약
    """
    
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()
        self._ensure_table()
    
    def _ensure_table(self):
        """테이블 생성 확인"""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS company_profiles (
                stock_code TEXT PRIMARY KEY,
                corp_code TEXT,
                corp_name TEXT,
                corp_name_eng TEXT,
                ceo_nm TEXT,
                corp_cls TEXT,
                induty_code TEXT,
                est_dt TEXT,
                acc_mt TEXT,
                fiscal_year TEXT,
                revenue REAL,
                operating_profit REAL,
                net_income REAL,
                total_equity REAL,
                total_assets REAL,
                has_critical_risk INTEGER DEFAULT 0,
                has_high_risk INTEGER DEFAULT 0,
                risk_level TEXT DEFAULT '낮음',
                risk_summary TEXT,
                updated_at TEXT DEFAULT (datetime('now', 'localtime')),
                data_source TEXT DEFAULT 'DART'
            )
        """)
    
    def get_by_code(self, stock_code: str) -> Optional[Dict]:
        """종목코드로 프로필 조회"""
        row = self.db.fetch_one(
            "SELECT * FROM company_profiles WHERE stock_code = ?",
            (stock_code,)
        )
        return dict(row) if row else None
    
    def upsert(self, stock_code: str, profile: Dict) -> bool:
        """프로필 저장/업데이트
        
        Args:
            stock_code: 종목코드
            profile: get_full_company_profile() 결과
        """
        try:
            basic = profile.get('basic') or {}
            financial = profile.get('financial') or {}
            risk = profile.get('risk') or {}
            
            self.db.execute("""
                INSERT INTO company_profiles (
                    stock_code, corp_code, corp_name, corp_name_eng, ceo_nm,
                    corp_cls, induty_code, est_dt, acc_mt,
                    fiscal_year, revenue, operating_profit, net_income,
                    total_equity, total_assets,
                    has_critical_risk, has_high_risk, risk_level, risk_summary,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
                ON CONFLICT(stock_code) DO UPDATE SET
                    corp_code = excluded.corp_code,
                    corp_name = excluded.corp_name,
                    corp_name_eng = excluded.corp_name_eng,
                    ceo_nm = excluded.ceo_nm,
                    corp_cls = excluded.corp_cls,
                    induty_code = excluded.induty_code,
                    est_dt = excluded.est_dt,
                    acc_mt = excluded.acc_mt,
                    fiscal_year = excluded.fiscal_year,
                    revenue = excluded.revenue,
                    operating_profit = excluded.operating_profit,
                    net_income = excluded.net_income,
                    total_equity = excluded.total_equity,
                    total_assets = excluded.total_assets,
                    has_critical_risk = excluded.has_critical_risk,
                    has_high_risk = excluded.has_high_risk,
                    risk_level = excluded.risk_level,
                    risk_summary = excluded.risk_summary,
                    updated_at = datetime('now', 'localtime')
            """, (
                stock_code,
                basic.get('corp_code'),
                basic.get('corp_name'),
                basic.get('corp_name_eng'),
                basic.get('ceo_nm'),
                basic.get('corp_cls'),
                basic.get('induty_code'),
                basic.get('est_dt'),
                basic.get('acc_mt'),
                financial.get('fiscal_year'),
                financial.get('revenue'),
                financial.get('operating_profit'),
                financial.get('net_income'),
                financial.get('total_equity'),
                financial.get('total_assets'),
                1 if risk.get('has_critical_risk') else 0,
                1 if risk.get('has_high_risk') else 0,
                risk.get('risk_level', '낮음'),
                risk.get('summary'),
            ))
            return True
        except Exception as e:
            logger.error(f"프로필 저장 실패 ({stock_code}): {e}")
            return False
    
    def get_all(self, limit: int = 100) -> List[Dict]:
        """전체 프로필 조회"""
        rows = self.db.fetch_all(
            "SELECT * FROM company_profiles ORDER BY updated_at DESC LIMIT ?",
            (limit,)
        )
        return [dict(r) for r in rows]
    
    def get_cached_count(self) -> int:
        """캐시된 프로필 수"""
        row = self.db.fetch_one("SELECT COUNT(*) as cnt FROM company_profiles")
        return row['cnt'] if row else 0
    
    def is_stale(self, stock_code: str, hours: int = 24) -> bool:
        """캐시가 오래되었는지 확인
        
        Args:
            stock_code: 종목코드
            hours: TTL (시간)
        """
        row = self.db.fetch_one(
            """
            SELECT updated_at,
                   (julianday('now', 'localtime') - julianday(updated_at)) * 24 as age_hours
            FROM company_profiles
            WHERE stock_code = ?
            """,
            (stock_code,)
        )
        if not row:
            return True  # 캐시 없음 = stale
        return row['age_hours'] > hours
    
    def delete(self, stock_code: str) -> bool:
        """프로필 삭제"""
        try:
            self.db.execute(
                "DELETE FROM company_profiles WHERE stock_code = ?",
                (stock_code,)
            )
            return True
        except Exception:
            return False


def get_company_profile_repository() -> CompanyProfileRepository:
    """CompanyProfileRepository 인스턴스 반환"""
    return CompanyProfileRepository()


# v6.0 Repository 편의 함수들
def get_top5_history_repository() -> Top5HistoryRepository:
    return Top5HistoryRepository()

def get_top5_prices_repository() -> Top5DailyPricesRepository:
    return Top5DailyPricesRepository()

def get_nomad_candidates_repository() -> NomadCandidatesRepository:
    return NomadCandidatesRepository()

def get_nomad_news_repository() -> NomadNewsRepository:
    return NomadNewsRepository()


# ============================================================
# v8.0: BrokerSignalRepository - 거래원 수급 신호
# ============================================================

class BrokerSignalRepository:
    """거래원 수급 신호 저장/조회"""
    
    def __init__(self):
        from src.infrastructure.database import get_database
        self.db = get_database()
        self._ensure_ai_column()

    def _ensure_ai_column(self):
        """v9.1: ai_summary 컬럼 추가"""
        try:
            cols = self.db.fetch_all("PRAGMA table_info(broker_signals)")
            if not any(c['name'] == 'ai_summary' for c in cols):
                self.db.execute("ALTER TABLE broker_signals ADD COLUMN ai_summary TEXT")
                logger.info("broker_signals: ai_summary 컬럼 추가")
        except Exception:
            pass
    
    def save_signal(
        self,
        screen_date: str,
        stock_code: str,
        stock_name: str,
        anomaly_score: int,
        broker_score: float,
        tag: str = "",
        buyers_json: str = "",
        sellers_json: str = "",
        unusual_score: int = 0,
        asymmetry_score: int = 0,
        distribution_score: int = 0,
        foreign_score: int = 0,
        frgn_buy: int = 0,
        frgn_sell: int = 0,
    ) -> bool:
        """거래원 신호 저장 (UPSERT)"""
        try:
            self.db.execute("""
                INSERT INTO broker_signals 
                    (screen_date, stock_code, stock_name, anomaly_score, broker_score,
                     tag, buyers_json, sellers_json, unusual_score, asymmetry_score,
                     distribution_score, foreign_score, frgn_buy, frgn_sell)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(screen_date, stock_code) DO UPDATE SET
                    stock_name=excluded.stock_name,
                    anomaly_score=excluded.anomaly_score,
                    broker_score=excluded.broker_score,
                    tag=excluded.tag,
                    buyers_json=excluded.buyers_json,
                    sellers_json=excluded.sellers_json,
                    unusual_score=excluded.unusual_score,
                    asymmetry_score=excluded.asymmetry_score,
                    distribution_score=excluded.distribution_score,
                    foreign_score=excluded.foreign_score,
                    frgn_buy=excluded.frgn_buy,
                    frgn_sell=excluded.frgn_sell
            """, (
                screen_date, stock_code, stock_name, anomaly_score, broker_score,
                tag, buyers_json, sellers_json, unusual_score, asymmetry_score,
                distribution_score, foreign_score, frgn_buy, frgn_sell,
            ))
            return True
        except Exception as e:
            logger.error(f"broker_signals 저장 실패: {e}")
            return False
    
    def get_signals_by_date(self, screen_date: str) -> list:
        """특정 날짜의 거래원 신호 조회"""
        return self.db.fetch_all(
            "SELECT * FROM broker_signals WHERE screen_date = ? ORDER BY anomaly_score DESC",
            (screen_date,)
        )
    
    def get_signals_by_code(self, stock_code: str, limit: int = 20) -> list:
        """특정 종목의 거래원 신호 이력 조회"""
        return self.db.fetch_all(
            "SELECT * FROM broker_signals WHERE stock_code = ? ORDER BY screen_date DESC LIMIT ?",
            (stock_code, limit)
        )
    
    def get_heatmap_data(self, days: int = 20) -> list:
        """히트맵용 데이터 (최근 N일, 종목×날짜 anomaly_score)"""
        return self.db.fetch_all("""
            SELECT screen_date, stock_code, stock_name, anomaly_score, broker_score, tag
            FROM broker_signals
            WHERE screen_date >= date('now', ? || ' days')
            ORDER BY screen_date DESC, anomaly_score DESC
        """, (f"-{days}",))

    def save_ai_summary(self, screen_date: str, ai_summary: str) -> bool:
        """날짜별 거래원 AI 분석 결과 저장 (첫 번째 종목 레코드에 저장)"""
        try:
            self.db.execute("""
                UPDATE broker_signals SET ai_summary = ?
                WHERE screen_date = ? AND id = (
                    SELECT id FROM broker_signals
                    WHERE screen_date = ?
                    ORDER BY anomaly_score DESC LIMIT 1
                )
            """, (ai_summary, screen_date, screen_date))
            return True
        except Exception as e:
            logger.error(f"broker AI summary 저장 실패: {e}")
            return False

    def get_ai_summary_by_date(self, screen_date: str) -> str:
        """날짜별 거래원 AI 분석 결과 조회"""
        try:
            row = self.db.fetch_one("""
                SELECT ai_summary FROM broker_signals
                WHERE screen_date = ? AND ai_summary IS NOT NULL AND ai_summary != ''
                LIMIT 1
            """, (screen_date,))
            return row['ai_summary'] if row else ""
        except Exception:
            return ""


def get_broker_signal_repository() -> BrokerSignalRepository:
    return BrokerSignalRepository()


if __name__ == "__main__":
    # 테스트
    from src.infrastructure.database import init_database
    
    logging.basicConfig(level=logging.INFO)
    
    # DB 초기화
    init_database()
    
    # 가중치 테스트
    weight_repo = get_weight_repository()
    weights = weight_repo.get_weights()
    print(f"\n현재 가중치: {weights.to_dict()}")
    
    # 가중치 업데이트 테스트
    weight_repo.update_weight('cci_value', 1.2, reason='테스트')
    weights = weight_repo.get_weights()
    print(f"업데이트 후 가중치: {weights.to_dict()}")
    
    # 이력 확인
    history = weight_repo.get_weight_history()
    print(f"\n가중치 변경 이력: {len(history)}건")
    for h in history[:3]:
        print(f"  - {h['indicator']}: {h['old_weight']} -> {h['new_weight']}")