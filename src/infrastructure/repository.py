"""
데이터 접근 레이어

책임:
- CRUD 오퍼레이션
- 복잡한 쿼리 캡슐화
- 데이터 모델 변환

의존성:
- infrastructure.database
- domain.models
"""

import json
import logging
from datetime import date, datetime
from typing import List, Optional, Dict, Any

from src.infrastructure.database import get_database, Database
from src.domain.models import (
    StockScore,
    ScoreDetail,
    Weights,
    ScreeningResult,
    ScreeningStatus,
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
    
    def get_next_day_results(self, days: int = 30) -> List[Dict]:
        """최근 N일간 익일 결과 조회"""
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
