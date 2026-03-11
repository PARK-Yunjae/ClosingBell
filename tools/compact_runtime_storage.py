"""
Runtime JSON -> SQLite compaction tool.

운영 중 계속 쌓이는 logs/watchlist JSON을 DB로 이관하고
오래된 파일을 정리한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from config import LEGACY_JSON_RETENTION_DAYS, LOG_DIR, WATCHLIST_DIR
from storage import compact_runtime_json, init_storage, list_screen_dates, list_watchlists


def _count_json_files(path: Path) -> int:
    return len(list(path.glob("*.json"))) if path.exists() else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Compact runtime JSON into SQLite")
    parser.add_argument("--delete", action="store_true", help="DB 이관 후 오래된 JSON 삭제")
    parser.add_argument(
        "--keep-days",
        type=int,
        default=LEGACY_JSON_RETENTION_DAYS,
        help="삭제 시 유지할 최근 일수",
    )
    parser.add_argument(
        "--archive",
        action="store_true",
        help="삭제 전 gzip 아카이브 생성",
    )
    args = parser.parse_args()

    init_storage()

    before = {
        "log_json": _count_json_files(LOG_DIR),
        "watchlist_json": _count_json_files(WATCHLIST_DIR),
        "db_logs": len(list_screen_dates()),
        "db_watchlists": len(list_watchlists()),
    }

    result = compact_runtime_json(
        delete_after=args.delete,
        keep_recent_days=args.keep_days,
        gzip_archive=args.archive,
    )

    after = {
        "log_json": _count_json_files(LOG_DIR),
        "watchlist_json": _count_json_files(WATCHLIST_DIR),
        "db_logs": len(list_screen_dates()),
        "db_watchlists": len(list_watchlists()),
    }

    print(json.dumps(
        {
            "before": before,
            "result": result,
            "after": after,
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
