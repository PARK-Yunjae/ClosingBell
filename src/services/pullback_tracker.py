"""눌림목 D+1~D+5 자동 추적 서비스 v10.1

pullback_signals 발생 후 D+1~D+5 가격을 OHLCV에서 자동 수집
→ pullback_daily_prices 테이블에 기록
→ 대시보드에서 실시간 성과 확인 가능

사용:
    from src.services.pullback_tracker import update_pullback_tracking
"""

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from src.infrastructure.database import get_database
from src.config.app_config import DATA_DIR

logger = logging.getLogger(__name__)


# ============================================================
# DB 마이그레이션 (자동)
# ============================================================

def _ensure_table():
    """pullback_daily_prices 테이블 생성 (없으면)"""
    db = get_database()
    db.execute("""
        CREATE TABLE IF NOT EXISTS pullback_daily_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pullback_signal_id INTEGER NOT NULL,
            stock_code TEXT NOT NULL,
            trade_date DATE NOT NULL,
            days_after INTEGER NOT NULL,
            open_price REAL DEFAULT 0,
            high_price REAL DEFAULT 0,
            low_price REAL DEFAULT 0,
            close_price REAL DEFAULT 0,
            volume INTEGER DEFAULT 0,
            gap_rate REAL DEFAULT 0,
            return_from_signal REAL DEFAULT 0,
            high_return REAL DEFAULT 0,
            low_return REAL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(pullback_signal_id, trade_date)
        )
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_pb_prices_signal 
        ON pullback_daily_prices(pullback_signal_id)
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_pb_prices_date 
        ON pullback_daily_prices(trade_date)
    """)


# ============================================================
# 핵심 추적 로직
# ============================================================

def update_pullback_tracking(tracking_days: int = 5, lookback_days: int = 10):
    """눌림목 시그널의 D+1~D+5 가격 추적 업데이트
    
    Args:
        tracking_days: 추적할 일수 (기본 5일)
        lookback_days: 몇 일 전 시그널까지 추적 (기본 10일)
    
    Returns:
        {"signals_tracked": int, "prices_updated": int}
    """
    _ensure_table()
    db = get_database()
    
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    today_str = date.today().isoformat()
    
    # 1. 최근 눌림목 시그널 조회 (아직 D+5 미완료인 것들)
    signals = db.fetch_all(
        """SELECT id, stock_code, stock_name, signal_date, close_price
        FROM pullback_signals 
        WHERE signal_date >= ?
        ORDER BY signal_date DESC""",
        (cutoff,),
    )
    
    if not signals:
        logger.info("[pullback_tracker] 추적할 시그널 없음")
        return {"signals_tracked": 0, "prices_updated": 0}
    
    signals_tracked = 0
    prices_updated = 0
    
    # OHLCV 데이터 경로
    ohlcv_dir = DATA_DIR / "ohlcv_kiwoom"
    
    # API 폴백용 클라이언트 (lazy init)
    _api_client = None
    
    def _get_api_client():
        nonlocal _api_client
        if _api_client is None:
            try:
                from src.adapters.kiwoom_rest_client import get_kiwoom_client
                _api_client = get_kiwoom_client()
            except Exception as e:
                logger.warning(f"[pullback_tracker] API 클라이언트 초기화 실패: {e}")
        return _api_client
    
    def _load_ohlcv_df(stock_code: str) -> Optional[pd.DataFrame]:
        """OHLCV CSV 로드, 없으면 API 폴백"""
        csv_path = ohlcv_dir / f"{stock_code}.csv"
        
        # 1순위: CSV 파일
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path)
                df.columns = df.columns.str.lower()
                df['date'] = pd.to_datetime(df['date'])
                return df.sort_values('date')
            except Exception as e:
                logger.debug(f"[pullback_tracker] CSV 로드 실패 ({stock_code}): {e}")
        
        # 2순위: 키움 API
        client = _get_api_client()
        if client:
            try:
                prices = client.get_daily_prices(stock_code, count=30)
                if prices:
                    rows = []
                    for p in prices:
                        rows.append({
                            'date': pd.to_datetime(getattr(p, 'date', None) or getattr(p, 'trade_date', None)),
                            'open': getattr(p, 'open', 0) or getattr(p, 'open_price', 0),
                            'high': getattr(p, 'high', 0) or getattr(p, 'high_price', 0),
                            'low': getattr(p, 'low', 0) or getattr(p, 'low_price', 0),
                            'close': getattr(p, 'close', 0) or getattr(p, 'close_price', 0),
                            'volume': getattr(p, 'volume', 0),
                        })
                    df = pd.DataFrame(rows)
                    df = df.dropna(subset=['date'])
                    if not df.empty:
                        logger.info(f"[pullback_tracker] API 폴백: {stock_code} → {len(df)}일")
                        return df.sort_values('date')
            except Exception as e:
                logger.debug(f"[pullback_tracker] API 조회 실패 ({stock_code}): {e}")
        
        logger.debug(f"[pullback_tracker] OHLCV 없음: {stock_code}")
        return None
    
    for sig in signals:
        signal_id = sig["id"]
        stock_code = sig["stock_code"]
        signal_date = sig["signal_date"]
        signal_close = sig["close_price"]
        
        if not signal_close or signal_close <= 0:
            continue
        
        # 이미 추적 완료된 일수 확인
        existing = db.fetch_all(
            "SELECT days_after FROM pullback_daily_prices "
            "WHERE pullback_signal_id = ? ORDER BY days_after",
            (signal_id,),
        )
        existing_days = {r["days_after"] for r in existing}
        
        # D+tracking_days까지 완료되면 스킵
        if len(existing_days) >= tracking_days:
            continue
        
        # OHLCV 데이터 로드 (CSV → API 폴백)
        df = _load_ohlcv_df(stock_code)
        if df is None:
            continue
        
        try:
            # signal_date 이후의 거래일 데이터
            signal_dt = pd.to_datetime(signal_date)
            future = df[df['date'] > signal_dt].head(tracking_days)
            
            if future.empty:
                continue
            
            signals_tracked += 1
            
            for day_n, (_, row) in enumerate(future.iterrows(), 1):
                if day_n in existing_days:
                    continue
                
                trade_date = row['date'].strftime('%Y-%m-%d')
                
                # 수익률 계산
                open_price = row.get('open', 0)
                close_price = row.get('close', 0)
                high_price = row.get('high', 0)
                low_price = row.get('low', 0)
                volume = int(row.get('volume', 0))
                
                gap_rate = (open_price / signal_close - 1) * 100 if day_n == 1 else 0
                return_from_signal = (close_price / signal_close - 1) * 100
                high_return = (high_price / signal_close - 1) * 100
                low_return = (low_price / signal_close - 1) * 100
                
                db.execute(
                    """INSERT OR IGNORE INTO pullback_daily_prices 
                    (pullback_signal_id, stock_code, trade_date, days_after,
                     open_price, high_price, low_price, close_price, volume,
                     gap_rate, return_from_signal, high_return, low_return)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (signal_id, stock_code, trade_date, day_n,
                     open_price, high_price, low_price, close_price, volume,
                     gap_rate, return_from_signal, high_return, low_return),
                )
                prices_updated += 1
                
        except Exception as e:
            logger.warning(f"[pullback_tracker] {stock_code} 처리 실패: {e}")
            continue
    
    logger.info(
        f"[pullback_tracker] 완료: {signals_tracked}개 시그널, "
        f"{prices_updated}개 가격 업데이트"
    )
    return {"signals_tracked": signals_tracked, "prices_updated": prices_updated}


# ============================================================
# 성과 조회
# ============================================================

def get_pullback_performance(days: int = 30) -> Dict:
    """눌림목 D+1~D+5 성과 통계
    
    Returns:
        {d1_avg, d1_win_rate, d3_avg, d5_avg, 
         by_strength: {강/중/약: {d1_avg, win_rate, ...}},
         total_signals, tracked_signals}
    """
    _ensure_table()
    db = get_database()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    
    # 시그널 + 가격 조인
    rows = db.fetch_all(
        """SELECT 
            s.id, s.signal_strength, s.signal_date,
            p.days_after, p.gap_rate, p.return_from_signal, 
            p.high_return, p.low_return
        FROM pullback_signals s
        JOIN pullback_daily_prices p ON s.id = p.pullback_signal_id
        WHERE s.signal_date >= ?
        ORDER BY s.signal_date DESC, p.days_after""",
        (cutoff,),
    )
    
    if not rows:
        return {"total_signals": 0, "tracked_signals": 0}
    
    # D+N별 통계
    from collections import defaultdict
    by_day = defaultdict(list)
    by_strength_day = defaultdict(lambda: defaultdict(list))
    
    for r in rows:
        r = dict(r)
        day_n = r["days_after"]
        ret = r["return_from_signal"]
        strength = r.get("signal_strength", "?")
        
        by_day[day_n].append(ret)
        by_strength_day[strength][day_n].append(ret)
    
    def _calc(returns):
        if not returns:
            return {"avg": 0, "win_rate": 0, "n": 0}
        wins = [r for r in returns if r > 0]
        return {
            "avg": sum(returns) / len(returns),
            "win_rate": len(wins) / len(returns) * 100,
            "n": len(returns),
        }
    
    # 전체 D+N 통계
    overall = {}
    for d in range(1, 6):
        overall[f"d{d}"] = _calc(by_day.get(d, []))
    
    # 시그널 강도별 D+1 통계
    by_strength = {}
    for strength in by_strength_day:
        d1_data = by_strength_day[strength].get(1, [])
        d5_data = by_strength_day[strength].get(5, [])
        by_strength[strength] = {
            "d1": _calc(d1_data),
            "d5": _calc(d5_data),
        }
    
    # 시그널 카운트
    total = db.fetch_one(
        "SELECT COUNT(*) as cnt FROM pullback_signals WHERE signal_date >= ?",
        (cutoff,),
    )
    tracked = db.fetch_one(
        """SELECT COUNT(DISTINCT pullback_signal_id) as cnt 
        FROM pullback_daily_prices p
        JOIN pullback_signals s ON s.id = p.pullback_signal_id
        WHERE s.signal_date >= ?""",
        (cutoff,),
    )
    
    return {
        **overall,
        "by_strength": by_strength,
        "total_signals": total["cnt"] if total else 0,
        "tracked_signals": tracked["cnt"] if tracked else 0,
    }


def get_pullback_detail(signal_id: int) -> List[Dict]:
    """특정 시그널의 D+1~D+5 상세"""
    _ensure_table()
    db = get_database()
    return [dict(r) for r in db.fetch_all(
        "SELECT * FROM pullback_daily_prices WHERE pullback_signal_id = ? ORDER BY days_after",
        (signal_id,),
    )]


# ============================================================
# 스케줄러 진입점
# ============================================================

def run_pullback_tracking():
    """스케줄러에서 호출하는 진입점"""
    try:
        result = update_pullback_tracking(tracking_days=5, lookback_days=10)
        logger.info(f"[pullback_tracker] {result}")
        return result
    except Exception as e:
        logger.error(f"[pullback_tracker] 실패: {e}")
        return {"error": str(e)}
