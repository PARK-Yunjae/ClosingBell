"""
SQLite 데이터베이스 연결 관리

책임:
- 연결 풀 관리 (단일 연결)
- WAL 모드 설정
- 트랜잭션 관리
- 마이그레이션

의존성:
- sqlite3
- config.settings
"""

import sqlite3
import logging
from pathlib import Path
from typing import Optional, List, Any
from contextlib import contextmanager

from src.config.settings import settings

logger = logging.getLogger(__name__)


# DDL 스크립트
DDL_SCRIPTS = """
-- screenings (스크리닝 실행 기록)
CREATE TABLE IF NOT EXISTS screenings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    screen_date DATE NOT NULL UNIQUE,
    screen_time TEXT NOT NULL DEFAULT '15:00',
    total_count INTEGER NOT NULL DEFAULT 0,
    top3_codes TEXT,
    execution_time_sec REAL,
    status TEXT NOT NULL DEFAULT 'SUCCESS' CHECK(status IN ('SUCCESS', 'FAILED', 'PARTIAL')),
    error_message TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_screenings_date ON screenings(screen_date);
CREATE INDEX IF NOT EXISTS idx_screenings_status ON screenings(status);

-- screening_items (스크리닝 종목 상세)
CREATE TABLE IF NOT EXISTS screening_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    screening_id INTEGER NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    current_price INTEGER NOT NULL,
    change_rate REAL NOT NULL,
    trading_value REAL NOT NULL,
    score_total REAL NOT NULL,
    score_cci_value REAL NOT NULL,
    score_cci_slope REAL NOT NULL,
    score_ma20_slope REAL NOT NULL,
    score_candle REAL NOT NULL,
    score_change REAL NOT NULL,
    raw_cci REAL,
    raw_ma20 REAL,
    rank INTEGER,
    is_top3 INTEGER NOT NULL DEFAULT 0 CHECK(is_top3 IN (0, 1)),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (screening_id) REFERENCES screenings(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_items_screening ON screening_items(screening_id);
CREATE INDEX IF NOT EXISTS idx_items_stock ON screening_items(stock_code);
CREATE INDEX IF NOT EXISTS idx_items_composite ON screening_items(screening_id, is_top3);

-- next_day_results (익일 결과)
CREATE TABLE IF NOT EXISTS next_day_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    screening_item_id INTEGER NOT NULL UNIQUE,
    next_date DATE NOT NULL,
    open_price INTEGER NOT NULL,
    close_price INTEGER NOT NULL,
    high_price INTEGER NOT NULL,
    low_price INTEGER NOT NULL,
    volume INTEGER,
    trading_value REAL,
    open_change_rate REAL NOT NULL,
    day_change_rate REAL NOT NULL,
    high_change_rate REAL NOT NULL,
    gap_rate REAL,
    volatility REAL,
    is_open_up INTEGER NOT NULL CHECK(is_open_up IN (0, 1)),
    is_day_up INTEGER NOT NULL CHECK(is_day_up IN (0, 1)),
    collected_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (screening_item_id) REFERENCES screening_items(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_nextday_item ON next_day_results(screening_item_id);
CREATE INDEX IF NOT EXISTS idx_nextday_date ON next_day_results(next_date);
CREATE INDEX IF NOT EXISTS idx_nextday_open_up ON next_day_results(is_open_up);

-- weight_config (가중치 설정)
CREATE TABLE IF NOT EXISTS weight_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    indicator TEXT NOT NULL UNIQUE,
    weight REAL NOT NULL DEFAULT 1.0 CHECK(weight >= 0.5 AND weight <= 5.0),
    min_weight REAL NOT NULL DEFAULT 0.5,
    max_weight REAL NOT NULL DEFAULT 5.0,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_weight_indicator ON weight_config(indicator);

-- weight_history (가중치 변경 이력)
CREATE TABLE IF NOT EXISTS weight_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    indicator TEXT NOT NULL,
    old_weight REAL NOT NULL,
    new_weight REAL NOT NULL,
    change_reason TEXT,
    correlation REAL,
    sample_size INTEGER,
    changed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_history_indicator ON weight_history(indicator);
CREATE INDEX IF NOT EXISTS idx_history_date ON weight_history(changed_at);

-- trade_journal (매매일지)
CREATE TABLE IF NOT EXISTS trade_journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date DATE NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    trade_type TEXT NOT NULL DEFAULT 'BUY' CHECK(trade_type IN ('BUY', 'SELL')),
    price INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    total_amount INTEGER NOT NULL,
    holding_quantity INTEGER,
    return_rate REAL,
    screening_item_id INTEGER,
    memo TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (screening_item_id) REFERENCES screening_items(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_journal_date ON trade_journal(trade_date);
CREATE INDEX IF NOT EXISTS idx_journal_stock ON trade_journal(stock_code);
CREATE INDEX IF NOT EXISTS idx_journal_screening ON trade_journal(screening_item_id);
"""

# 초기 가중치 데이터
INITIAL_WEIGHTS = """
INSERT OR IGNORE INTO weight_config (indicator, weight) VALUES
    ('cci_value', 1.0),
    ('cci_slope', 1.0),
    ('ma20_slope', 1.0),
    ('candle', 1.0),
    ('change', 1.0);
"""


class Database:
    """SQLite 데이터베이스 관리자"""
    
    def __init__(self, db_path: Optional[Path] = None):
        """
        Args:
            db_path: DB 파일 경로 (None이면 설정에서 로드)
        """
        self.db_path = db_path or settings.database.path
        self._connection: Optional[sqlite3.Connection] = None
        
        # DB 디렉토리 생성
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
    
    def get_connection(self) -> sqlite3.Connection:
        """연결 반환 (싱글톤)"""
        if self._connection is None:
            self._connection = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30.0,
            )
            # Row factory 설정 (dict-like 접근)
            self._connection.row_factory = sqlite3.Row
            
            # WAL 모드 활성화
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=NORMAL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            
            logger.info(f"DB 연결 완료: {self.db_path}")
        
        return self._connection
    
    @contextmanager
    def transaction(self):
        """트랜잭션 컨텍스트 매니저"""
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"트랜잭션 롤백: {e}")
            raise
    
    def execute(
        self,
        sql: str,
        params: tuple = (),
    ) -> sqlite3.Cursor:
        """SQL 실행"""
        conn = self.get_connection()
        try:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor
        except sqlite3.Error as e:
            logger.error(f"SQL 실행 오류: {e}\nSQL: {sql}")
            raise
    
    def execute_many(
        self,
        sql: str,
        params_list: List[tuple],
    ) -> sqlite3.Cursor:
        """다중 SQL 실행"""
        conn = self.get_connection()
        try:
            cursor = conn.executemany(sql, params_list)
            conn.commit()
            return cursor
        except sqlite3.Error as e:
            logger.error(f"SQL 다중 실행 오류: {e}")
            raise
    
    def execute_script(self, script: str):
        """SQL 스크립트 실행"""
        conn = self.get_connection()
        try:
            conn.executescript(script)
            logger.debug("SQL 스크립트 실행 완료")
        except sqlite3.Error as e:
            logger.error(f"SQL 스크립트 오류: {e}")
            raise
    
    def fetch_one(
        self,
        sql: str,
        params: tuple = (),
    ) -> Optional[sqlite3.Row]:
        """단일 행 조회"""
        conn = self.get_connection()
        cursor = conn.execute(sql, params)
        return cursor.fetchone()
    
    def fetch_all(
        self,
        sql: str,
        params: tuple = (),
    ) -> List[sqlite3.Row]:
        """전체 행 조회"""
        conn = self.get_connection()
        cursor = conn.execute(sql, params)
        return cursor.fetchall()
    
    def init_database(self):
        """데이터베이스 초기화 (테이블 생성)"""
        logger.info("데이터베이스 초기화 시작...")
        
        # DDL 실행
        self.execute_script(DDL_SCRIPTS)
        
        # 초기 데이터 삽입
        self.execute_script(INITIAL_WEIGHTS)
        
        logger.info("데이터베이스 초기화 완료")
    
    def close(self):
        """연결 종료"""
        if self._connection:
            self._connection.close()
            self._connection = None
            logger.info("DB 연결 종료")
    
    def vacuum(self):
        """DB 최적화 (VACUUM)"""
        conn = self.get_connection()
        conn.execute("VACUUM")
        logger.info("DB VACUUM 완료")
    
    def backup(self, backup_path: Path):
        """DB 백업"""
        import shutil
        
        # 현재 연결 커밋
        if self._connection:
            self._connection.commit()
        
        # 파일 복사
        shutil.copy2(self.db_path, backup_path)
        logger.info(f"DB 백업 완료: {backup_path}")


# 싱글톤 인스턴스
_database: Optional[Database] = None


def get_database() -> Database:
    """Database 인스턴스 반환"""
    global _database
    if _database is None:
        _database = Database()
    return _database


def init_database():
    """데이터베이스 초기화 유틸리티"""
    db = get_database()
    db.init_database()


if __name__ == "__main__":
    # 테스트
    logging.basicConfig(level=logging.INFO)
    
    db = get_database()
    db.init_database()
    
    # 테이블 확인
    tables = db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    print("\n=== 생성된 테이블 ===")
    for table in tables:
        print(f"- {table['name']}")
    
    # 가중치 확인
    weights = db.fetch_all("SELECT indicator, weight FROM weight_config")
    print("\n=== 초기 가중치 ===")
    for w in weights:
        print(f"- {w['indicator']}: {w['weight']}")
    
    print(f"\nDB 경로: {db.db_path}")
