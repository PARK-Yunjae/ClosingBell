"""Import large backtest JSON datasets into SQLite and optionally delete them."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import BACKTEST_DIR
from storage import compact_backtest_json, list_backtest_datasets


DEFAULT_KEEP = ["summary.json", "summary_v2.json", "summary_repaired.json"]


def _size_mb(path: Path) -> float:
    return round(path.stat().st_size / 1024 / 1024, 2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compact backtest JSON datasets into SQLite")
    parser.add_argument("--delete", action="store_true", help="delete JSON after import")
    parser.add_argument("--archive", action="store_true", help="gzip archive deleted JSON")
    parser.add_argument(
        "--keep",
        nargs="*",
        default=DEFAULT_KEEP,
        help="JSON file names to keep on disk when --delete is used",
    )
    args = parser.parse_args()

    before = {
        path.name: _size_mb(path)
        for path in sorted(BACKTEST_DIR.glob("*.json"))
    }
    result = compact_backtest_json(
        delete_after=args.delete,
        gzip_archive=args.archive,
        keep_files=set(args.keep),
    )
    datasets = list_backtest_datasets()
    after = {
        path.name: _size_mb(path)
        for path in sorted(BACKTEST_DIR.glob("*.json"))
    }

    print(json.dumps(
        {
            "before_files": before,
            "after_files": after,
            "result": result,
            "datasets": datasets,
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
