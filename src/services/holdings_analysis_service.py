"""Holdings analysis service (v9.0)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import logging
logger = logging.getLogger(__name__)
from src.services.analysis_report import generate_analysis_report
from src.services.account_service import get_holdings_watchlist


@dataclass
class HoldingsAnalysisResult:
    analyzed: int
    failed: int
    report_paths: List[str]


def generate_holdings_reports(
    codes: Optional[List[str]] = None,
    full: bool = True,
    include_sold: bool = True,
) -> HoldingsAnalysisResult:
    if codes is None:
        statuses = ["holding"] if not include_sold else ["holding", "sold", "manual"]
        rows = [row for row in get_holdings_watchlist() if row.get("status") in statuses]
        codes = sorted({row.get("stock_code") for row in rows if row.get("stock_code")})

    analyzed = 0
    failed = 0
    report_paths: List[str] = []

    for code in codes:
        try:
            result = generate_analysis_report(code, full=full)
            report_paths.append(str(result.report_path))
            analyzed += 1
        except Exception as e:
            failed += 1
            logger.warning(f"holdings 분석 실패 {code}: {e}")

    return HoldingsAnalysisResult(
        analyzed=analyzed,
        failed=failed,
        report_paths=report_paths,
    )
