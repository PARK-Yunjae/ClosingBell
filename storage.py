"""
ClosingBell runtime storage.

JSON 파일 수를 줄이기 위해 운영 데이터는 SQLite에 gzip 압축 저장한다.
기존 호출부는 dict/list 형태를 유지하고, 저장 계층만 교체한다.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from config import (
    APP_DB_PATH,
    ARCHIVE_DIR,
    BACKTEST_DIR,
    LEGACY_JSON_RETENTION_DAYS,
    LOG_DIR,
    SAVE_LEGACY_JSON,
    WATCHLIST_DIR,
)


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

            CREATE TABLE IF NOT EXISTS backtest_datasets (
                dataset_name TEXT PRIMARY KEY,
                updated_at TEXT NOT NULL,
                item_count INTEGER NOT NULL,
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


def _dataset_count(data: dict | list) -> int:
    if isinstance(data, (dict, list)):
        return len(data)
    return 1


def save_backtest_dataset(dataset_name: str, data: dict | list) -> None:
    init_storage()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO backtest_datasets(dataset_name, updated_at, item_count, payload)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(dataset_name) DO UPDATE SET
                updated_at = excluded.updated_at,
                item_count = excluded.item_count,
                payload = excluded.payload
            """,
            (
                dataset_name,
                _now_iso(),
                _dataset_count(data),
                sqlite3.Binary(_encode_payload(data)),
            ),
        )


def load_backtest_dataset(dataset_name: str) -> dict | list | None:
    init_storage()
    with _connect() as conn:
        row = conn.execute(
            "SELECT payload FROM backtest_datasets WHERE dataset_name = ?",
            (dataset_name,),
        ).fetchone()
    return _decode_payload(row["payload"]) if row else None


def list_backtest_datasets() -> list[dict]:
    init_storage()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT dataset_name, updated_at, item_count
            FROM backtest_datasets
            ORDER BY dataset_name ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def save_legacy_json(path: Path, data: dict | list) -> None:
    if not SAVE_LEGACY_JSON:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def prune_legacy_json(dir_path: Path, keep_recent_days: int | None = None) -> int:
    keep_recent_days = (
        LEGACY_JSON_RETENTION_DAYS if keep_recent_days is None else keep_recent_days
    )
    cutoff = datetime.now().date() - timedelta(days=max(keep_recent_days, 0))
    removed = 0

    for path in sorted(dir_path.glob("*.json")):
        try:
            day = datetime.strptime(path.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if day >= cutoff:
            continue
        path.unlink(missing_ok=True)
        removed += 1

    return removed


def _archive_json_file(path: Path, archive_dir: Path) -> Path:
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / f"{path.stem}.json.gz"
    target.write_bytes(gzip.compress(path.read_bytes(), compresslevel=9))
    return target


def compact_runtime_json(
    delete_after: bool = False,
    keep_recent_days: int = 0,
    gzip_archive: bool = False,
) -> dict:
    """
    기존 logs/watchlist JSON을 DB로 이관한다.

    delete_after=True 이면 keep_recent_days보다 오래된 JSON을 삭제한다.
    gzip_archive=True 이면 삭제 전에 archive 디렉터리에 gzip으로 보관한다.
    """
    init_storage()
    imported_logs = 0
    imported_watchlists = 0
    removed_logs = 0
    removed_watchlists = 0
    cutoff = datetime.now().date() - timedelta(days=max(keep_recent_days, 0))

    for path in sorted(LOG_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("date"):
                save_screen_result(payload)
                imported_logs += 1
        except Exception:
            continue

        if not delete_after:
            continue
        try:
            day = datetime.strptime(path.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if day >= cutoff:
            continue
        if gzip_archive:
            _archive_json_file(path, ARCHIVE_DIR / "logs")
        path.unlink(missing_ok=True)
        removed_logs += 1

    for path in sorted(WATCHLIST_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("created"):
                save_watchlist_payload(payload)
                imported_watchlists += 1
        except Exception:
            continue

        if not delete_after:
            continue
        try:
            day = datetime.strptime(path.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if day >= cutoff:
            continue
        if gzip_archive:
            _archive_json_file(path, ARCHIVE_DIR / "watchlist")
        path.unlink(missing_ok=True)
        removed_watchlists += 1

    return {
        "imported_logs": imported_logs,
        "imported_watchlists": imported_watchlists,
        "removed_logs": removed_logs,
        "removed_watchlists": removed_watchlists,
    }


def load_screen_results_from_fs() -> list[dict]:
    results = []
    for path in sorted(LOG_DIR.glob("*.json")):
        try:
            results.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            pass
    return results


def load_watchlists_from_fs() -> list[dict]:
    results = []
    for path in sorted(WATCHLIST_DIR.glob("*.json"), reverse=True):
        try:
            results.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            pass
    return results


def load_backtest_dataset_from_fs(dataset_name: str) -> dict | list | None:
    path = BACKTEST_DIR / f"{dataset_name}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def compact_backtest_json(
    delete_after: bool = False,
    gzip_archive: bool = False,
    keep_files: set[str] | None = None,
) -> dict:
    """
    Import backtest JSON datasets into SQLite.

    keep_files contains file names to preserve on disk even when delete_after=True.
    """
    init_storage()
    keep_files = keep_files or set()
    imported = 0
    removed = 0

    for path in sorted(BACKTEST_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            save_backtest_dataset(path.stem, payload)
            imported += 1
        except Exception:
            continue

        if not delete_after or path.name in keep_files:
            continue
        if gzip_archive:
            _archive_json_file(path, ARCHIVE_DIR / "backtest")
        path.unlink(missing_ok=True)
        removed += 1

    return {
        "imported_backtests": imported,
        "removed_backtests": removed,
    }
