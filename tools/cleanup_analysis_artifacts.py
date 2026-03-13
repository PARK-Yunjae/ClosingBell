"""
Cleanup generated analysis outputs under data/analysis.

Default mode is a dry run. Use --delete to remove old analysis folders.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from config import ANALYSIS_DIR, ANALYSIS_KEEP_LATEST


RAW_DIR_NAMES = {"backtest", "datasets", "logs", "performance", "watchlist"}
RAW_FILE_NAMES = {"recent_factor_dataset.csv", "v36_simulation.csv", "holder_analysis.csv"}


def _walk_size(path: Path) -> tuple[int, int]:
    if path.is_file():
        return 1, path.stat().st_size
    file_count = 0
    total_bytes = 0
    for child in path.rglob("*"):
        if child.is_file():
            file_count += 1
            total_bytes += child.stat().st_size
    return file_count, total_bytes


def _format_entry(path: Path) -> dict:
    file_count, total_bytes = _walk_size(path)
    return {
        "name": path.name,
        "path": str(path),
        "is_dir": path.is_dir(),
        "files": file_count,
        "bytes": total_bytes,
    }


def _delete_entry(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _raw_targets(root: Path) -> list[Path]:
    targets: list[Path] = []
    raw_dirs = sorted(
        [path for path in root.rglob("*") if path.is_dir() and path.name in RAW_DIR_NAMES],
        key=lambda path: len(path.parts),
    )
    targets.extend(raw_dirs)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if (
            path.name not in RAW_FILE_NAMES
            and not path.name.endswith("_dataset.csv")
            and path.suffix.lower() != ".csv"
        ):
            continue
        if any(parent in path.parents for parent in raw_dirs):
            continue
        targets.append(path)
    return targets


def _prune_empty_dirs(root: Path) -> list[Path]:
    removed: list[Path] = []
    dirs = sorted(
        [root, *[path for path in root.rglob("*") if path.is_dir()]],
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for path in dirs:
        if any(path.iterdir()):
            continue
        path.rmdir()
        removed.append(path)
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description="Cleanup generated analysis artifacts")
    parser.add_argument("--delete", action="store_true", help="Actually delete selected artifacts")
    parser.add_argument(
        "--keep-latest",
        type=int,
        default=ANALYSIS_KEEP_LATEST,
        help="Number of newest timestamp folders to keep",
    )
    parser.add_argument(
        "--trim-reports-only",
        action="store_true",
        help="Keep report/json files but remove raw logs, datasets, and CSV artifacts inside analysis runs",
    )
    args = parser.parse_args()

    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    entries = sorted(ANALYSIS_DIR.iterdir(), key=lambda item: item.name, reverse=True)
    keep_latest = max(args.keep_latest, 0)
    preserved = entries[:keep_latest]
    targets = entries[keep_latest:]

    summary = {
        "analysis_dir": str(ANALYSIS_DIR),
        "mode": "delete" if args.delete else "dry_run",
        "trim_reports_only": args.trim_reports_only,
        "kept": [_format_entry(path) for path in preserved],
        "targets": [_format_entry(path) for path in targets],
        "trim_targets": [],
        "trimmed": [],
        "pruned_dirs": [],
        "removed": [],
    }

    if args.trim_reports_only:
        trim_candidates: list[Path] = []
        for path in entries:
            if path.is_dir():
                trim_candidates.extend(_raw_targets(path))
        summary["trim_targets"] = [_format_entry(path) for path in trim_candidates]
        if args.delete:
            for path in trim_candidates:
                if path.exists():
                    summary["trimmed"].append(_format_entry(path))
                    _delete_entry(path)
            for path in entries:
                if path.is_dir() and path.exists():
                    for pruned in _prune_empty_dirs(path):
                        summary["pruned_dirs"].append(_format_entry(pruned))

    if args.delete:
        for path in targets:
            summary["removed"].append(_format_entry(path))
            _delete_entry(path)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
