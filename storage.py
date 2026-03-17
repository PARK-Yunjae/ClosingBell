"""
ClosingBell runtime storage.

Operational data is stored in SQLite so the scheduler, Discord notifier,
watchlist persistence, and buy-pick tracking all share one source of truth.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
from datetime import datetime

from config import APP_DB_PATH


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(APP_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for name, col_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}")


def _encode_payload(data: dict | list) -> bytes:
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
    return gzip.compress(raw.encode("utf-8"), compresslevel=9)


def _decode_payload(blob: bytes | memoryview | None) -> dict | list | None:
    if blob is None:
        return None
    if isinstance(blob, memoryview):
        blob = blob.tobytes()
    return json.loads(gzip.decompress(blob).decode("utf-8"))


def init_storage() -> None:
    APP_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS screen_runs (
                run_date TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                payload BLOB NOT NULL
            );

            CREATE TABLE IF NOT EXISTS watchlists (
                created TEXT PRIMARY KEY,
                expires TEXT,
                updated_at TEXT NOT NULL,
                payload BLOB NOT NULL
            );

            CREATE TABLE IF NOT EXISTS buy_pick_runs (
                pick_date TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                pick_count INTEGER NOT NULL,
                payload BLOB NOT NULL
            );

            CREATE TABLE IF NOT EXISTS buy_pick_outcomes (
                pick_date TEXT NOT NULL,
                code TEXT NOT NULL,
                track_day INTEGER NOT NULL,
                track_date TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload BLOB NOT NULL,
                PRIMARY KEY (pick_date, code, track_day)
            );

            CREATE TABLE IF NOT EXISTS notification_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                ref_date TEXT,
                sent_at TEXT NOT NULL,
                status TEXT NOT NULL,
                response_code INTEGER,
                payload BLOB NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pick_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT,
                rank INTEGER,
                days_elapsed INTEGER,
                pool_type TEXT,
                structure_score REAL,
                expectation_score REAL,
                risk_score REAL,
                final_score REAL,
                conviction TEXT,
                market_regime TEXT,
                kospi_change REAL,
                kosdaq_change REAL,
                nasdaq_change REAL,
                theme_1 TEXT,
                theme_2 TEXT,
                event_warning TEXT,
                price INTEGER,
                change_rate REAL,
                ma5_gap REAL,
                ma20_gap REAL,
                vol_decline REAL,
                rsi REAL,
                cci REAL,
                vp_above_pct REAL,
                overheat INTEGER,
                supply_score INTEGER,
                short_ratio REAL,
                foreign_net INTEGER,
                dart_risk TEXT,
                news_risk TEXT,
                foreign_macro_risk TEXT,
                youtube_risk TEXT,
                action_label TEXT,
                d1_return REAL,
                d2_return REAL,
                d3_return REAL,
                d5_return REAL,
                UNIQUE(snapshot_date, code)
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_pick_snapshots_date_code
            ON pick_snapshots(snapshot_date, code);

            CREATE TABLE IF NOT EXISTS market_regime_daily (
                date TEXT PRIMARY KEY,
                kospi_change REAL,
                kosdaq_change REAL,
                nasdaq_change REAL,
                regime TEXT,
                themes TEXT,
                macro_risk TEXT,
                event_warning TEXT
            );
            """
        )
        _ensure_columns(
            conn,
            "pick_snapshots",
            {
                "theme_1": "TEXT",
                "theme_2": "TEXT",
                "event_warning": "TEXT",
                "ma20_gap": "REAL",
                "overheat": "INTEGER",
                "short_ratio": "REAL",
                "foreign_net": "INTEGER",
                "foreign_macro_risk": "TEXT",
                "youtube_risk": "TEXT",
                "d2_return": "REAL",
            },
        )
        _ensure_columns(
            conn,
            "market_regime_daily",
            {
                "date": "TEXT",
                "kospi_change": "REAL",
                "kosdaq_change": "REAL",
                "nasdaq_change": "REAL",
                "regime": "TEXT",
                "themes": "TEXT",
                "macro_risk": "TEXT",
                "event_warning": "TEXT",
            },
        )


def save_screen_result(result: dict) -> None:
    init_storage()
    run_date = result.get("date")
    if not run_date:
        raise ValueError("screen result missing date")

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO screen_runs(run_date, created_at, payload)
            VALUES (?, ?, ?)
            ON CONFLICT(run_date) DO UPDATE SET
                created_at = excluded.created_at,
                payload = excluded.payload
            """,
            (run_date, _now_iso(), sqlite3.Binary(_encode_payload(result))),
        )


def get_screen_result(run_date: str) -> dict | None:
    init_storage()
    with _connect() as conn:
        row = conn.execute(
            "SELECT payload FROM screen_runs WHERE run_date = ?",
            (run_date,),
        ).fetchone()
    return _decode_payload(row["payload"]) if row else None


def list_screen_dates(desc: bool = False) -> list[str]:
    init_storage()
    order = "DESC" if desc else "ASC"
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT run_date FROM screen_runs ORDER BY run_date {order}"
        ).fetchall()
    return [row["run_date"] for row in rows]


def iter_screen_results(desc: bool = False) -> list[dict]:
    init_storage()
    order = "DESC" if desc else "ASC"
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT payload FROM screen_runs ORDER BY run_date {order}"
        ).fetchall()
    return [_decode_payload(row["payload"]) for row in rows]


def save_watchlist_payload(watchlist: dict) -> None:
    init_storage()
    created = watchlist.get("created")
    if not created:
        raise ValueError("watchlist missing created")

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO watchlists(created, expires, updated_at, payload)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(created) DO UPDATE SET
                expires = excluded.expires,
                updated_at = excluded.updated_at,
                payload = excluded.payload
            """,
            (
                created,
                watchlist.get("expires", ""),
                _now_iso(),
                sqlite3.Binary(_encode_payload(watchlist)),
            ),
        )


def get_watchlist(created: str) -> dict | None:
    init_storage()
    with _connect() as conn:
        row = conn.execute(
            "SELECT payload FROM watchlists WHERE created = ?",
            (created,),
        ).fetchone()
    return _decode_payload(row["payload"]) if row else None


def list_watchlists(desc: bool = True) -> list[dict]:
    init_storage()
    order = "DESC" if desc else "ASC"
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT payload FROM watchlists ORDER BY created {order}"
        ).fetchall()
    return [_decode_payload(row["payload"]) for row in rows]


def load_active_watchlists(today: str | None = None) -> list[dict]:
    init_storage()
    today = today or datetime.now().strftime("%Y-%m-%d")
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT payload
            FROM watchlists
            WHERE COALESCE(expires, '') >= ?
            ORDER BY created DESC
            """,
            (today,),
        ).fetchall()
    return [_decode_payload(row["payload"]) for row in rows]


def save_buy_picks(pick_date: str, picks: list[dict]) -> None:
    init_storage()
    payload = {
        "pick_date": pick_date,
        "created_at": _now_iso(),
        "picks": picks,
    }
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO buy_pick_runs(pick_date, created_at, pick_count, payload)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(pick_date) DO UPDATE SET
                created_at = excluded.created_at,
                pick_count = excluded.pick_count,
                payload = excluded.payload
            """,
            (
                pick_date,
                payload["created_at"],
                len(picks),
                sqlite3.Binary(_encode_payload(payload)),
            ),
        )


def get_buy_picks(pick_date: str) -> dict | None:
    init_storage()
    with _connect() as conn:
        row = conn.execute(
            "SELECT payload FROM buy_pick_runs WHERE pick_date = ?",
            (pick_date,),
        ).fetchone()
    return _decode_payload(row["payload"]) if row else None


def list_buy_pick_dates(desc: bool = True) -> list[str]:
    init_storage()
    order = "DESC" if desc else "ASC"
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT pick_date FROM buy_pick_runs ORDER BY pick_date {order}"
        ).fetchall()
    return [row["pick_date"] for row in rows]


def iter_buy_pick_runs(desc: bool = True) -> list[dict]:
    init_storage()
    order = "DESC" if desc else "ASC"
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT payload FROM buy_pick_runs ORDER BY pick_date {order}"
        ).fetchall()
    return [_decode_payload(row["payload"]) for row in rows]


def save_buy_pick_outcomes(records: list[dict]) -> int:
    init_storage()
    if not records:
        return 0

    updated_at = _now_iso()
    rows = [
        (
            record["pick_date"],
            str(record["code"]).strip().zfill(6),
            int(record["track_day"]),
            record["track_date"],
            updated_at,
            sqlite3.Binary(_encode_payload(record)),
        )
        for record in records
        if record.get("pick_date")
        and record.get("code")
        and record.get("track_day") is not None
        and record.get("track_date")
    ]
    if not rows:
        return 0

    with _connect() as conn:
        conn.executemany(
            """
            INSERT INTO buy_pick_outcomes(
                pick_date, code, track_day, track_date, updated_at, payload
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(pick_date, code, track_day) DO UPDATE SET
                track_date = excluded.track_date,
                updated_at = excluded.updated_at,
                payload = excluded.payload
            """,
            rows,
        )
    return len(rows)


def get_buy_pick_outcomes(pick_date: str) -> list[dict]:
    init_storage()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT payload
            FROM buy_pick_outcomes
            WHERE pick_date = ?
            ORDER BY code ASC, track_day ASC
            """,
            (pick_date,),
        ).fetchall()
    return [_decode_payload(row["payload"]) for row in rows]


def iter_buy_pick_outcomes(desc: bool = True) -> list[dict]:
    init_storage()
    order = "DESC" if desc else "ASC"
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT payload
            FROM buy_pick_outcomes
            ORDER BY pick_date {order}, code ASC, track_day ASC
            """
        ).fetchall()
    return [_decode_payload(row["payload"]) for row in rows]


def save_notification_event(
    event_type: str,
    payload: dict,
    status: str,
    ref_date: str | None = None,
    response_code: int | None = None,
) -> int:
    init_storage()
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO notification_events(
                event_type, ref_date, sent_at, status, response_code, payload
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                ref_date or "",
                _now_iso(),
                status,
                response_code,
                sqlite3.Binary(_encode_payload(payload)),
            ),
        )
        return int(cursor.lastrowid)


def iter_notification_events(
    desc: bool = True,
    limit: int | None = None,
) -> list[dict]:
    init_storage()
    order = "DESC" if desc else "ASC"
    sql = f"""
        SELECT event_id, event_type, ref_date, sent_at, status, response_code, payload
        FROM notification_events
        ORDER BY event_id {order}
    """
    params: tuple = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (limit,)

    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()

    events = []
    for row in rows:
        decoded = _decode_payload(row["payload"]) or {}
        events.append(
            {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "ref_date": row["ref_date"],
                "sent_at": row["sent_at"],
                "status": row["status"],
                "response_code": row["response_code"],
                "payload": decoded,
            }
        )
    return events


# ──────────────────────────────────────────────
# pick_snapshots — v4 조건 스냅샷 저장
# ──────────────────────────────────────────────

def save_pick_snapshot(pick: dict, market_snapshot: dict | None = None) -> None:
    """매수추천 순간의 4계층 점수 + 시장 컨텍스트를 정규 테이블에 저장."""
    init_storage()
    ms = market_snapshot or pick.get("market_snapshot", {})
    action = pick.get("action", {})
    supply = pick.get("supply", {})
    market_theme_items = pick.get("market_theme_items", []) or []
    short_info = supply.get("short_selling", {}) if isinstance(supply, dict) else {}
    investor_info = supply.get("investor", {}) if isinstance(supply, dict) else {}
    snapshot_date = pick.get("pick_date") or datetime.now().strftime("%Y-%m-%d")
    theme_1 = pick.get("theme_name") or (market_theme_items[0].get("name", "") if market_theme_items else "")
    theme_2 = market_theme_items[1].get("name", "") if len(market_theme_items) > 1 else ""

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO pick_snapshots(
                snapshot_date, code, name, rank, days_elapsed, pool_type,
                structure_score, expectation_score, risk_score, final_score, conviction,
                market_regime, kospi_change, kosdaq_change, nasdaq_change,
                theme_1, theme_2, event_warning,
                price, change_rate, ma5_gap, ma20_gap, vol_decline, rsi, cci, vp_above_pct, overheat,
                supply_score, short_ratio, foreign_net, dart_risk, news_risk,
                foreign_macro_risk, youtube_risk, action_label
            )
            VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?
            )
            ON CONFLICT(snapshot_date, code) DO UPDATE SET
                name = excluded.name,
                rank = excluded.rank,
                days_elapsed = excluded.days_elapsed,
                pool_type = excluded.pool_type,
                structure_score = excluded.structure_score,
                expectation_score = excluded.expectation_score,
                risk_score = excluded.risk_score,
                final_score = excluded.final_score,
                conviction = excluded.conviction,
                market_regime = excluded.market_regime,
                kospi_change = excluded.kospi_change,
                kosdaq_change = excluded.kosdaq_change,
                nasdaq_change = excluded.nasdaq_change,
                theme_1 = excluded.theme_1,
                theme_2 = excluded.theme_2,
                event_warning = excluded.event_warning,
                price = excluded.price,
                change_rate = excluded.change_rate,
                ma5_gap = excluded.ma5_gap,
                ma20_gap = excluded.ma20_gap,
                vol_decline = excluded.vol_decline,
                rsi = excluded.rsi,
                cci = excluded.cci,
                vp_above_pct = excluded.vp_above_pct,
                overheat = excluded.overheat,
                supply_score = excluded.supply_score,
                short_ratio = excluded.short_ratio,
                foreign_net = excluded.foreign_net,
                dart_risk = excluded.dart_risk,
                news_risk = excluded.news_risk,
                foreign_macro_risk = excluded.foreign_macro_risk,
                youtube_risk = excluded.youtube_risk,
                action_label = excluded.action_label
            """,
            (
                snapshot_date,
                pick.get("code", ""),
                pick.get("name", ""),
                pick.get("rank"),
                pick.get("days_elapsed"),
                pick.get("pool_type", ""),
                pick.get("structure_score"),
                pick.get("expectation_score"),
                pick.get("risk_score"),
                pick.get("conviction_score"),
                pick.get("conviction", "C"),
                pick.get("market_regime", ""),
                ms.get("kospi_change"),
                ms.get("kosdaq_change"),
                ms.get("nasdaq_change"),
                theme_1,
                theme_2,
                pick.get("event_warning", ""),
                pick.get("current_price"),
                pick.get("change_rate"),
                pick.get("ma5_gap"),
                pick.get("ma20_gap"),
                pick.get("vol_decline"),
                pick.get("rsi"),
                pick.get("cci"),
                pick.get("vp_above_pct"),
                1 if pick.get("overheat") else 0,
                supply.get("total_score"),
                short_info.get("short_ratio"),
                pick.get("foreign_net", investor_info.get("foreign_net")),
                pick.get("dart_risk", ""),
                pick.get("news_risk", ""),
                pick.get("foreign_macro_risk", ""),
                pick.get("youtube_risk", ""),
                action.get("label", ""),
            ),
        )


def save_market_regime_daily(snapshot: dict) -> None:
    init_storage()
    trade_date = snapshot.get("date")
    if not trade_date:
        raise ValueError("market snapshot missing date")

    themes = snapshot.get("themes", [])
    themes_json = json.dumps(themes, ensure_ascii=False, separators=(",", ":"))
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO market_regime_daily(
                date, kospi_change, kosdaq_change, nasdaq_change,
                regime, themes, macro_risk, event_warning
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                kospi_change = excluded.kospi_change,
                kosdaq_change = excluded.kosdaq_change,
                nasdaq_change = excluded.nasdaq_change,
                regime = excluded.regime,
                themes = excluded.themes,
                macro_risk = excluded.macro_risk,
                event_warning = excluded.event_warning
            """,
            (
                trade_date,
                snapshot.get("kospi_change"),
                snapshot.get("kosdaq_change"),
                snapshot.get("nasdaq_change"),
                snapshot.get("regime", ""),
                themes_json,
                snapshot.get("macro_risk", ""),
                snapshot.get("event_warning", ""),
            ),
        )


def delete_pick_snapshots(snapshot_date: str) -> int:
    init_storage()
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM pick_snapshots WHERE snapshot_date = ?",
            (snapshot_date,),
        )
        return cursor.rowcount


def update_pick_snapshot_returns(records: list[dict]) -> int:
    init_storage()
    if not records:
        return 0

    col_map = {1: "d1_return", 2: "d2_return", 3: "d3_return", 5: "d5_return"}
    updated = 0
    with _connect() as conn:
        for record in records:
            target_col = col_map.get(int(record.get("track_day", 0) or 0))
            if not target_col:
                continue
            cursor = conn.execute(
                f"""
                UPDATE pick_snapshots
                SET {target_col} = ?
                WHERE snapshot_date = ? AND code = ?
                """,
                (
                    record.get("return_pct"),
                    record.get("pick_date"),
                    str(record.get("code", "")).strip().zfill(6),
                ),
            )
            updated += cursor.rowcount
    return updated
