"""v6 스키마 수정 - 기업정보 + 뉴스 컬럼 포함"""
import sqlite3
from pathlib import Path

DB_PATH = Path(r"C:\Coding\ClosingBell\data\screener.db")

def fix_schema():
    print("🔧 v6 스키마 수정 시작...")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. 기존 v6 테이블 삭제
    print("   기존 테이블 삭제 중...")
    cursor.execute("DROP TABLE IF EXISTS nomad_news")
    cursor.execute("DROP TABLE IF EXISTS top5_daily_prices")
    cursor.execute("DROP TABLE IF EXISTS nomad_candidates")
    cursor.execute("DROP TABLE IF EXISTS closing_top5_history")
    
    # 2. 새 스키마로 재생성
    print("   새 스키마로 재생성 중...")
    
    # closing_top5_history
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS closing_top5_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        screen_date TEXT NOT NULL,
        rank INTEGER NOT NULL CHECK(rank BETWEEN 1 AND 5),
        stock_code TEXT NOT NULL,
        stock_name TEXT NOT NULL,
        screen_price INTEGER NOT NULL,
        screen_score REAL,
        grade TEXT CHECK(grade IN ('S', 'A', 'B', 'C', 'D')),
        cci REAL,
        rsi REAL,
        change_rate REAL,
        disparity_20 REAL,
        consecutive_up INTEGER DEFAULT 0,
        volume_ratio_5 REAL,
        tracking_status TEXT DEFAULT 'active' CHECK(tracking_status IN ('active', 'completed', 'stopped')),
        tracking_days INTEGER DEFAULT 0,
        last_tracked_date TEXT,
        data_source TEXT DEFAULT 'realtime',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(screen_date, rank)
    )
    """)
    
    # top5_daily_prices
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS top5_daily_prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        top5_history_id INTEGER NOT NULL,
        trade_date TEXT NOT NULL,
        days_after INTEGER NOT NULL CHECK(days_after BETWEEN 1 AND 20),
        open_price INTEGER,
        high_price INTEGER,
        low_price INTEGER,
        close_price INTEGER,
        volume INTEGER,
        return_from_screen REAL,
        gap_rate REAL,
        high_return REAL,
        low_return REAL,
        data_source TEXT DEFAULT 'realtime',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(top5_history_id, days_after),
        FOREIGN KEY (top5_history_id) REFERENCES closing_top5_history(id)
    )
    """)
    
    # nomad_candidates (기업정보 컬럼 포함)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS nomad_candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        
        -- 기본 정보
        study_date TEXT NOT NULL,
        stock_code TEXT NOT NULL,
        stock_name TEXT NOT NULL,
        reason_flag TEXT NOT NULL CHECK(reason_flag IN ('상한가', '거래량천만', '상한가+거래량')),
        
        -- 당일 가격 정보
        close_price INTEGER,
        change_rate REAL,
        volume INTEGER,
        trading_value REAL,
        
        -- 기업 정보 (네이버 금융)
        market TEXT,
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
        
        -- 뉴스/학습 상태
        news_collected INTEGER DEFAULT 0,
        news_count INTEGER DEFAULT 0,
        company_info_collected INTEGER DEFAULT 0,
        study_completed INTEGER DEFAULT 0,
        study_note TEXT,
        ai_summary TEXT,
        
        -- 메타
        data_source TEXT DEFAULT 'realtime',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(study_date, stock_code)
    )
    """)
    
    # nomad_news (sentiment 영어)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS nomad_news (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_id INTEGER NOT NULL,
        news_date TEXT,
        news_title TEXT NOT NULL,
        news_source TEXT,
        news_url TEXT,
        summary TEXT,
        sentiment TEXT CHECK(sentiment IN ('positive', 'negative', 'neutral')),
        relevance_score REAL,
        category TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (candidate_id) REFERENCES nomad_candidates(id)
    )
    """)
    
    # 인덱스 생성
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_top5_history_date ON closing_top5_history(screen_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_top5_history_code ON closing_top5_history(stock_code)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_top5_prices_history ON top5_daily_prices(top5_history_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_nomad_date ON nomad_candidates(study_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_nomad_reason ON nomad_candidates(reason_flag)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_nomad_news_candidate ON nomad_news(candidate_id)")
    
    conn.commit()
    conn.close()
    
    print("✅ v6 스키마 수정 완료!")
    print("")
    print("📋 포함된 컬럼:")
    print("  [기업정보] 시장, 업종, 시총, PER, PBR, EPS, ROE")
    print("  [기업상세] 사업내용, 대표자, 설립일, 매출, 영업이익")
    print("  [뉴스] sentiment(positive/negative/neutral), 관련도, 카테고리")
    print("")
    print("다음 단계:")
    print("  python main.py --backfill 20")
    print("  python main.py --run-news")

if __name__ == "__main__":
    fix_schema()
