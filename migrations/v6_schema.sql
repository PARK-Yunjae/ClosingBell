-- ClosingBell v6.0 Schema Migration
-- 실행 전 백업 필수: copy screener.db screener.db.backup
-- 생성일: 2026-01-19

-- =============================================================================
-- 1. closing_top5_history: TOP5 20일 추적 마스터 테이블
-- =============================================================================
CREATE TABLE IF NOT EXISTS closing_top5_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- 스크리닝 정보
    screen_date DATE NOT NULL,
    rank INTEGER NOT NULL CHECK(rank BETWEEN 1 AND 5),
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    
    -- 스크리닝 당시 가격/점수
    screen_price INTEGER NOT NULL,
    screen_score REAL NOT NULL,
    grade TEXT NOT NULL CHECK(grade IN ('S', 'A', 'B', 'C', 'D')),
    
    -- 스크리닝 당시 지표
    cci REAL,
    rsi REAL,
    change_rate REAL,
    disparity_20 REAL,
    consecutive_up INTEGER DEFAULT 0,
    volume_ratio_5 REAL,
    
    -- v6.3: 주도섹터 정보
    sector TEXT,
    sector_rank INTEGER,
    is_leading_sector INTEGER DEFAULT 0,
    
    -- v6.3.1: 거래대금/거래량
    trading_value REAL,
    volume INTEGER,
    
    -- v6.3.2: AI 분석
    ai_summary TEXT,
    ai_risk_level TEXT,
    ai_recommendation TEXT,
    
    -- 추적 상태
    tracking_days INTEGER NOT NULL DEFAULT 0,
    last_tracked_date DATE,
    tracking_status TEXT NOT NULL DEFAULT 'active' 
        CHECK(tracking_status IN ('active', 'completed', 'cancelled')),
    
    -- 데이터 소스
    data_source TEXT NOT NULL DEFAULT 'realtime' 
        CHECK(data_source IN ('realtime', 'backfill')),
    
    -- 메타
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(screen_date, stock_code)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_top5_history_date ON closing_top5_history(screen_date);
CREATE INDEX IF NOT EXISTS idx_top5_history_status ON closing_top5_history(tracking_status);
CREATE INDEX IF NOT EXISTS idx_top5_history_code ON closing_top5_history(stock_code);
CREATE INDEX IF NOT EXISTS idx_top5_history_rank ON closing_top5_history(screen_date, rank);
CREATE INDEX IF NOT EXISTS idx_top5_sector ON closing_top5_history(sector);
CREATE INDEX IF NOT EXISTS idx_top5_leading ON closing_top5_history(is_leading_sector);

-- =============================================================================
-- 2. top5_daily_prices: D+1 ~ D+20 일별 가격
-- =============================================================================
CREATE TABLE IF NOT EXISTS top5_daily_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- FK
    top5_history_id INTEGER NOT NULL,
    
    -- 거래 정보
    trade_date DATE NOT NULL,
    days_after INTEGER NOT NULL CHECK(days_after BETWEEN 1 AND 20),
    
    -- OHLCV
    open_price INTEGER NOT NULL,
    high_price INTEGER NOT NULL,
    low_price INTEGER NOT NULL,
    close_price INTEGER NOT NULL,
    volume INTEGER,
    
    -- 수익률 (스크리닝 가격 대비)
    return_from_screen REAL NOT NULL,  -- 종가 기준
    gap_rate REAL,                     -- 시가 갭
    high_return REAL,                  -- 고가 기준
    low_return REAL,                   -- 저가 기준
    
    -- 데이터 소스
    data_source TEXT NOT NULL DEFAULT 'realtime' 
        CHECK(data_source IN ('realtime', 'backfill')),
    
    -- 메타
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (top5_history_id) REFERENCES closing_top5_history(id) ON DELETE CASCADE,
    UNIQUE(top5_history_id, trade_date)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_top5_prices_history ON top5_daily_prices(top5_history_id);
CREATE INDEX IF NOT EXISTS idx_top5_prices_date ON top5_daily_prices(trade_date);
CREATE INDEX IF NOT EXISTS idx_top5_prices_days ON top5_daily_prices(days_after);

-- =============================================================================
-- 3. nomad_candidates: 유목민 공부법 후보 종목
-- =============================================================================
CREATE TABLE IF NOT EXISTS nomad_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- 기본 정보
    study_date DATE NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    reason_flag TEXT NOT NULL CHECK(reason_flag IN ('상한가', '거래량천만', '상한가+거래량')),
    
    -- 당일 가격 정보
    close_price INTEGER NOT NULL,
    change_rate REAL NOT NULL,
    volume INTEGER NOT NULL,
    trading_value REAL NOT NULL,
    
    -- 기업 정보 (네이버 크롤링)
    market TEXT,  -- KOSPI, KOSDAQ
    sector TEXT,
    market_cap REAL,
    per REAL,
    pbr REAL,
    eps REAL,
    roe REAL,
    
    -- 기업 상세
    business_summary TEXT,
    establishment_date TEXT,
    ceo_name TEXT,
    revenue REAL,
    operating_profit REAL,
    
    -- 뉴스 정보
    news_count INTEGER DEFAULT 0,
    news_status TEXT DEFAULT 'pending' 
        CHECK(news_status IN ('pending', 'collected', 'failed', 'skipped')),
    ai_summary TEXT,
    
    -- 데이터 소스
    data_source TEXT NOT NULL DEFAULT 'realtime' 
        CHECK(data_source IN ('realtime', 'backfill')),
    
    -- 메타
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(study_date, stock_code)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_nomad_date ON nomad_candidates(study_date);
CREATE INDEX IF NOT EXISTS idx_nomad_code ON nomad_candidates(stock_code);
CREATE INDEX IF NOT EXISTS idx_nomad_reason ON nomad_candidates(reason_flag);
CREATE INDEX IF NOT EXISTS idx_nomad_date_reason ON nomad_candidates(study_date, reason_flag);

-- =============================================================================
-- 4. nomad_news: 유목민 뉴스 기사
-- =============================================================================
CREATE TABLE IF NOT EXISTS nomad_news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- FK (denormalized for performance)
    study_date DATE NOT NULL,
    stock_code TEXT NOT NULL,
    
    -- 뉴스 정보
    title TEXT NOT NULL,
    publisher TEXT,
    published_at DATETIME,
    url TEXT NOT NULL,
    snippet TEXT,
    
    -- 메타
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(study_date, stock_code, url)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_nomad_news_date ON nomad_news(study_date);
CREATE INDEX IF NOT EXISTS idx_nomad_news_stock ON nomad_news(stock_code);
CREATE INDEX IF NOT EXISTS idx_nomad_news_composite ON nomad_news(study_date, stock_code);

-- =============================================================================
-- 5. 트리거: updated_at 자동 업데이트
-- =============================================================================
CREATE TRIGGER IF NOT EXISTS trg_top5_history_updated 
AFTER UPDATE ON closing_top5_history
BEGIN
    UPDATE closing_top5_history SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_nomad_candidates_updated 
AFTER UPDATE ON nomad_candidates
BEGIN
    UPDATE nomad_candidates SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
