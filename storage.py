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
            """
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
