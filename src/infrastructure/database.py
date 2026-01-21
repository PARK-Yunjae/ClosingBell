"""
SQLite 데이터베이스 연결 관리 (v6.0)

책임:
- 연결 풀 관리 (단일 연결)
- WAL 모드 설정
- 트랜잭션 관리
- 마이그레이션

v6.0 추가 테이블:
- closing_top5_history: TOP5 20일 추적 마스터
- top5_daily_prices: D+1~D+20 일별 가격
- nomad_candidates: 유목민 후보 종목
- nomad_news: 유목민 뉴스

의존성:
- sqlite3
- config.settings
"""

import sqlite3
import logging
from pathlib import Path
from typing import Optional, List
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

-- nomad_studies (유목민 공부 기록) v5.2
CREATE TABLE IF NOT EXISTS nomad_studies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    study_date DATE NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    screen_rank INTEGER NOT NULL,
    
    -- 기업 정보
    market_cap REAL,
    industry TEXT,
    main_business TEXT,
    major_shareholder TEXT,
    shareholder_ratio REAL,
    
    -- 재무 지표
    per REAL,
    pbr REAL,
    roe REAL,
    debt_ratio REAL,
    
    -- 종가매매 지표
    score_total REAL,
    volume_ratio REAL,
    cci REAL,
    change_rate REAL,
    
    -- AI 분석
    news_summary TEXT,
    investment_points TEXT,
    risk_factors TEXT,
    selection_reason TEXT,
    
    -- 메타
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(study_date, stock_code)
);

CREATE INDEX IF NOT EXISTS idx_nomad_date ON nomad_studies(study_date);
CREATE INDEX IF NOT EXISTS idx_nomad_stock ON nomad_studies(stock_code);

-- k_signals (K값 돌파 시그널) v5.3
CREATE TABLE IF NOT EXISTS k_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_date DATE NOT NULL,
    signal_time TEXT NOT NULL DEFAULT '15:00',
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    
    -- 가격 정보
    current_price INTEGER NOT NULL,
    open_price INTEGER NOT NULL,
    breakout_price INTEGER NOT NULL,
    prev_high INTEGER,
    prev_low INTEGER,
    prev_close INTEGER,
    
    -- K값 전략 파라미터
    k_value REAL NOT NULL DEFAULT 0.3,
    range_value INTEGER,
    
    -- 지표
    prev_change_pct REAL,
    volume_ratio REAL,
    trading_value REAL,
    
    -- 손익가
    stop_loss_pct REAL DEFAULT -2.0,
    take_profit_pct REAL DEFAULT 5.0,
    stop_loss_price INTEGER,
    take_profit_price INTEGER,
    
    -- 지수 상태
    index_change REAL,
    index_above_ma5 INTEGER DEFAULT 1,
    
    -- 점수
    score REAL,
    confidence REAL,
    rank INTEGER,
    
    -- 메타
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(signal_date, stock_code)
);

CREATE INDEX IF NOT EXISTS idx_k_signals_date ON k_signals(signal_date);
CREATE INDEX IF NOT EXISTS idx_k_signals_stock ON k_signals(stock_code);
CREATE INDEX IF NOT EXISTS idx_k_signals_rank ON k_signals(signal_date, rank);

-- k_signal_results (K값 시그널 익일 결과) v5.3
CREATE TABLE IF NOT EXISTS k_signal_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    k_signal_id INTEGER NOT NULL UNIQUE,
    
    -- 익일 가격
    next_date DATE NOT NULL,
    next_open INTEGER NOT NULL,
    next_high INTEGER NOT NULL,
    next_low INTEGER NOT NULL,
    next_close INTEGER NOT NULL,
    
    -- 수익률 (익일 시가 매도 기준)
    entry_price INTEGER NOT NULL,
    exit_price INTEGER NOT NULL,
    profit_pct REAL NOT NULL,
    
    -- 손익 상태
    hit_stop_loss INTEGER DEFAULT 0,
    hit_take_profit INTEGER DEFAULT 0,
    is_win INTEGER NOT NULL DEFAULT 0,
    
    -- 최대 수익/손실
    max_profit_pct REAL,
    max_loss_pct REAL,
    
    -- 메타
    collected_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (k_signal_id) REFERENCES k_signals(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_k_results_signal ON k_signal_results(k_signal_id);
CREATE INDEX IF NOT EXISTS idx_k_results_date ON k_signal_results(next_date);
CREATE INDEX IF NOT EXISTS idx_k_results_win ON k_signal_results(is_win);

-- k_strategy_config (K값 전략 설정) v5.3
CREATE TABLE IF NOT EXISTS k_strategy_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    param_name TEXT NOT NULL UNIQUE,
    param_value REAL NOT NULL,
    min_value REAL,
    max_value REAL,
    is_active INTEGER DEFAULT 1,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_k_config_param ON k_strategy_config(param_name);

-- k_strategy_history (K값 전략 파라미터 변경 이력) v5.3
CREATE TABLE IF NOT EXISTS k_strategy_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    param_name TEXT NOT NULL,
    old_value REAL NOT NULL,
    new_value REAL NOT NULL,
    change_reason TEXT,
    win_rate_before REAL,
    win_rate_after REAL,
    sample_size INTEGER,
    changed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_k_history_param ON k_strategy_history(param_name);
CREATE INDEX IF NOT EXISTS idx_k_history_date ON k_strategy_history(changed_at);
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

# 초기 K값 전략 설정 (백테스트 최적값)
INITIAL_K_CONFIG = """
INSERT OR IGNORE INTO k_strategy_config (param_name, param_value, min_value, max_value) VALUES
    ('k_value', 0.3, 0.1, 0.9),
    ('stop_loss_pct', -2.0, -5.0, -1.0),
    ('take_profit_pct', 5.0, 2.0, 10.0),
    ('min_trading_value', 200.0, 50.0, 500.0),
    ('min_volume_ratio', 2.0, 1.0, 5.0),
    ('prev_change_min', 0.0, -5.0, 5.0),
    ('prev_change_max', 10.0, 5.0, 20.0);
"""

# 마이그레이션 스크립트 (버전별)
MIGRATIONS = {
    # v1.1: next_day_results에 is_top3 컬럼 추가 (분석 편의용)
    "v1.1_add_is_top3_to_next_day": """
        -- is_top3 컬럼 추가 (없는 경우에만)
        ALTER TABLE next_day_results ADD COLUMN is_top3 INTEGER DEFAULT 0;
        
        -- 인덱스 추가
        CREATE INDEX IF NOT EXISTS idx_nextday_is_top3 ON next_day_results(is_top3);
    """,
    
    # v1.2: next_day_results에 screen_rank 컬럼 추가
    "v1.2_add_screen_rank_to_next_day": """
        ALTER TABLE next_day_results ADD COLUMN screen_rank INTEGER DEFAULT 0;
    """,
}

# ========================================================================
# v6.0 마이그레이션: TOP5 20일 추적 + 유목민 공부법
# ========================================================================
SCHEMA_VERSION = "6.0"

MIGRATIONS_V6 = """
-- closing_top5_history: TOP5 20일 추적 마스터 테이블
CREATE TABLE IF NOT EXISTS closing_top5_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    screen_date DATE NOT NULL,
    rank INTEGER NOT NULL CHECK(rank BETWEEN 1 AND 5),
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    screen_price INTEGER NOT NULL,
    screen_score REAL NOT NULL,
    grade TEXT NOT NULL CHECK(grade IN ('S', 'A', 'B', 'C', 'D')),
    cci REAL,
    rsi REAL,
    change_rate REAL,
    disparity_20 REAL,
    consecutive_up INTEGER DEFAULT 0,
    volume_ratio_5 REAL,
    tracking_days INTEGER NOT NULL DEFAULT 0,
    last_tracked_date DATE,
    tracking_status TEXT NOT NULL DEFAULT 'active' 
        CHECK(tracking_status IN ('active', 'completed', 'cancelled')),
    data_source TEXT NOT NULL DEFAULT 'realtime' 
        CHECK(data_source IN ('realtime', 'backfill')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(screen_date, stock_code)
);

CREATE INDEX IF NOT EXISTS idx_top5_history_date ON closing_top5_history(screen_date);
CREATE INDEX IF NOT EXISTS idx_top5_history_status ON closing_top5_history(tracking_status);
CREATE INDEX IF NOT EXISTS idx_top5_history_code ON closing_top5_history(stock_code);
CREATE INDEX IF NOT EXISTS idx_top5_history_rank ON closing_top5_history(screen_date, rank);

-- top5_daily_prices: D+1 ~ D+20 일별 가격
CREATE TABLE IF NOT EXISTS top5_daily_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    top5_history_id INTEGER NOT NULL,
    trade_date DATE NOT NULL,
    days_after INTEGER NOT NULL CHECK(days_after BETWEEN 1 AND 20),
    open_price INTEGER NOT NULL,
    high_price INTEGER NOT NULL,
    low_price INTEGER NOT NULL,
    close_price INTEGER NOT NULL,
    volume INTEGER,
    return_from_screen REAL NOT NULL,
    gap_rate REAL,
    high_return REAL,
    low_return REAL,
    data_source TEXT NOT NULL DEFAULT 'realtime' 
        CHECK(data_source IN ('realtime', 'backfill')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (top5_history_id) REFERENCES closing_top5_history(id) ON DELETE CASCADE,
    UNIQUE(top5_history_id, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_top5_prices_history ON top5_daily_prices(top5_history_id);
CREATE INDEX IF NOT EXISTS idx_top5_prices_date ON top5_daily_prices(trade_date);
CREATE INDEX IF NOT EXISTS idx_top5_prices_days ON top5_daily_prices(days_after);

-- nomad_candidates: 유목민 공부법 후보 종목
CREATE TABLE IF NOT EXISTS nomad_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    study_date DATE NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    reason_flag TEXT NOT NULL CHECK(reason_flag IN ('상한가', '거래량천만', '상한가+거래량')),
    close_price INTEGER NOT NULL,
    change_rate REAL NOT NULL,
    volume INTEGER NOT NULL,
    trading_value REAL NOT NULL,
    market TEXT,
    sector TEXT,
    market_cap REAL,
    market_cap_rank INTEGER,
    per REAL,
    pbr REAL,
    eps REAL,
    bps REAL,
    roe REAL,
    consensus_per REAL,
    consensus_eps REAL,
    foreign_rate REAL,
    foreign_shares INTEGER,
    analyst_opinion REAL,
    analyst_recommend TEXT,
    target_price INTEGER,
    high_52w INTEGER,
    low_52w INTEGER,
    dividend_yield REAL,
    business_summary TEXT,
    establishment_date TEXT,
    ceo_name TEXT,
    revenue REAL,
    operating_profit REAL,
    company_info_collected INTEGER DEFAULT 0,
    news_collected INTEGER DEFAULT 0,
    news_count INTEGER DEFAULT 0,
    news_status TEXT DEFAULT 'pending' 
        CHECK(news_status IN ('pending', 'collected', 'failed', 'skipped')),
    ai_summary TEXT,
    data_source TEXT NOT NULL DEFAULT 'realtime' 
        CHECK(data_source IN ('realtime', 'backfill')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(study_date, stock_code)
);

CREATE INDEX IF NOT EXISTS idx_nomad_date ON nomad_candidates(study_date);
CREATE INDEX IF NOT EXISTS idx_nomad_code ON nomad_candidates(stock_code);
CREATE INDEX IF NOT EXISTS idx_nomad_reason ON nomad_candidates(reason_flag);
CREATE INDEX IF NOT EXISTS idx_nomad_date_reason ON nomad_candidates(study_date, reason_flag);

-- nomad_news: 유목민 뉴스 기사
CREATE TABLE IF NOT EXISTS nomad_news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    study_date DATE NOT NULL,
    stock_code TEXT NOT NULL,
    title TEXT NOT NULL,
    publisher TEXT,
    published_at DATETIME,
    url TEXT NOT NULL,
    snippet TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(study_date, stock_code, url)
);

CREATE INDEX IF NOT EXISTS idx_nomad_news_date ON nomad_news(study_date);
CREATE INDEX IF NOT EXISTS idx_nomad_news_stock ON nomad_news(stock_code);
CREATE INDEX IF NOT EXISTS idx_nomad_news_composite ON nomad_news(study_date, stock_code);
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
        # v5.4: K값 초기화 제거 (K값 전략 폐기)
        # self.execute_script(INITIAL_K_CONFIG)
        
        # 마이그레이션 실행
        self.run_migrations()
        
        # v6.0 마이그레이션 실행
        self.run_migration_v6()
        
        logger.info("데이터베이스 초기화 완료")
    
    def run_migrations(self):
        """마이그레이션 실행 (컬럼 추가 등)"""
        for name, script in MIGRATIONS.items():
            try:
                # 마이그레이션 필요 여부 확인 (간단한 체크)
                if "ADD COLUMN is_top3" in script:
                    # is_top3 컬럼이 이미 있는지 확인
                    cols = self.fetch_all("PRAGMA table_info(next_day_results)")
                    col_names = [c['name'] for c in cols]
                    if 'is_top3' in col_names:
                        logger.debug(f"마이그레이션 스킵 (이미 적용됨): {name}")
                        continue
                
                if "ADD COLUMN screen_rank" in script:
                    cols = self.fetch_all("PRAGMA table_info(next_day_results)")
                    col_names = [c['name'] for c in cols]
                    if 'screen_rank' in col_names:
                        logger.debug(f"마이그레이션 스킵 (이미 적용됨): {name}")
                        continue
                
                # 마이그레이션 실행 (각 문장 개별 실행)
                for statement in script.strip().split(';'):
                    statement = statement.strip()
                    if statement and not statement.startswith('--'):
                        try:
                            self.execute(statement)
                        except sqlite3.OperationalError as e:
                            if "duplicate column name" in str(e).lower():
                                logger.debug(f"컬럼 이미 존재: {statement[:50]}...")
                            else:
                                raise
                
                logger.info(f"마이그레이션 완료: {name}")
                
            except Exception as e:
                logger.warning(f"마이그레이션 실패 (무시): {name} - {e}")
    
    def run_migration_v6(self):
        """v6.0 마이그레이션 실행 (TOP5 20일 추적 + 유목민 공부법)"""
        try:
            # 테이블 존재 여부 확인
            tables = self.fetch_all(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?, ?, ?, ?)",
                ('closing_top5_history', 'top5_daily_prices', 'nomad_candidates', 'nomad_news')
            )
            existing_tables = {t['name'] for t in tables}
            
            if len(existing_tables) == 4:
                logger.debug("v6.0 마이그레이션 스킵 (이미 적용됨)")
                return True
            
            logger.info("v6.0 마이그레이션 시작...")
            
            # 마이그레이션 실행
            self.execute_script(MIGRATIONS_V6)
            
            # 검증
            tables = self.fetch_all(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?, ?, ?, ?)",
                ('closing_top5_history', 'top5_daily_prices', 'nomad_candidates', 'nomad_news')
            )
            
            if len(tables) == 4:
                logger.info(f"v6.0 마이그레이션 완료: {SCHEMA_VERSION}")
                return True
            else:
                logger.error(f"v6.0 마이그레이션 검증 실패: {len(tables)}/4 테이블")
                return False
                
        except Exception as e:
            logger.error(f"v6.0 마이그레이션 실패: {e}")
            return False
    
    def update_next_day_is_top3(self):
        """기존 next_day_results 데이터의 is_top3 값 업데이트"""
        try:
            self.execute("""
                UPDATE next_day_results
                SET is_top3 = (
                    SELECT si.is_top3 
                    FROM screening_items si 
                    WHERE si.id = next_day_results.screening_item_id
                )
                WHERE is_top3 IS NULL OR is_top3 = 0
            """)
            
            self.execute("""
                UPDATE next_day_results
                SET screen_rank = (
                    SELECT si.rank 
                    FROM screening_items si 
                    WHERE si.id = next_day_results.screening_item_id
                )
                WHERE screen_rank IS NULL OR screen_rank = 0
            """)
            
            logger.info("next_day_results is_top3/screen_rank 업데이트 완료")
        except Exception as e:
            logger.warning(f"is_top3 업데이트 실패: {e}")
    
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
