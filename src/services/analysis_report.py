"""
Analysis report generator (v9.0)

Generates reports/YYYYMMDD_<code>.md with:
1) OHLCV summary
2) Volume Profile summary
3) Technical analysis (CCI/RSI/MACD/BB/MA)
4) Broker flow summary
5) News/Disclosures timeline
6) Entry/Exit plan + summary
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src.analyzers.stock_report import generate_stock_report


@dataclass
class AnalysisResult:
    report_path: Path
    summary: str


def generate_analysis_report(stock_code: str, full: bool = False) -> AnalysisResult:
    code = str(stock_code).zfill(6)
    today = date.today()

    report_dir = Path("reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{today.strftime('%Y%m%d')}_{code}.md"

    report = generate_stock_report(code, full=full)
    report_path.write_text("\n".join(report.lines) + "\n", encoding="utf-8")

    return AnalysisResult(report_path=report_path, summary=report.summary)

