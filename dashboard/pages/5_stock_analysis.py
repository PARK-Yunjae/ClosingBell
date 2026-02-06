"""
🧾 종목 심층 분석 대시보드 v9.0
"""

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import streamlit as st

try:
    import pandas as pd
except Exception:
    pd = None

try:
    from src.config.app_config import (
        APP_FULL_VERSION,
        FOOTER_DASHBOARD,
        SIDEBAR_TITLE,
        OHLCV_DIR,
        OHLCV_FULL_DIR,
    )
except ImportError:
    APP_FULL_VERSION = "ClosingBell v9.0"
    FOOTER_DASHBOARD = APP_FULL_VERSION
    SIDEBAR_TITLE = "ClosingBell"
    OHLCV_DIR = None
    OHLCV_FULL_DIR = None


def _sidebar_nav():
    st.page_link("app.py", label="홈")
    st.page_link("pages/1_top5_tracker.py", label="감시종목 TOP5")
    st.page_link("pages/2_nomad_study.py", label="유목민 공부법")
    st.page_link("pages/3_stock_search.py", label="종목 검색")
    st.page_link("pages/4_broker_flow.py", label="거래원 수급")
    st.page_link("pages/5_stock_analysis.py", label="종목 심층 분석")


def _find_latest_report(code_value: str) -> Path | None:
    if not code_value:
        return None
    report_dir = Path("reports")
    if not report_dir.exists():
        return None
    files = sorted(report_dir.glob(f"*_{code_value}.md"))
    return files[-1] if files else None


def _list_reports() -> List[Path]:
    report_dir = Path("reports")
    if not report_dir.exists():
        return []
    return sorted(report_dir.glob("*_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)


def _load_report_sections(report_path: Path) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {}
    if not report_path or not report_path.exists():
        return sections
    lines = report_path.read_text(encoding="utf-8").splitlines()
    current = "Summary"
    sections[current] = []
    for line in lines:
        if line.startswith("## "):
            current = line.replace("## ", "").strip()
            sections[current] = []
            continue
        sections[current].append(line)
    return sections


def _resolve_ohlcv_path(code: str) -> Optional[Path]:
    candidates: List[Path] = []
    bases: List[Path] = []

    for base in [OHLCV_FULL_DIR, OHLCV_DIR]:
        if base and base not in bases:
            bases.append(base)

    try:
        from src.config.backfill_config import get_backfill_config
        cfg = get_backfill_config()
        base = cfg.get_active_ohlcv_dir()
        if base and base not in bases:
            bases.append(base)
    except Exception:
        pass

    for base in bases:
        candidates.append(Path(base) / f"{code}.csv")
        candidates.append(Path(base) / f"A{code}.csv")

    for path in candidates:
        if path.exists():
            return path
    return None


def _load_ohlcv_df(code: str) -> Tuple[Optional["pd.DataFrame"], str]:
    if pd is None:
        return None, "pandas not available"

    path = _resolve_ohlcv_path(code)
    if path:
        try:
            from src.services.backfill.data_loader import load_single_ohlcv
            df = load_single_ohlcv(path)
            if df is not None and not df.empty:
                return df, str(path)
        except Exception:
            pass

    # Online fallback (FDR)
    try:
        import FinanceDataReader as fdr
        end = datetime.now().date()
        start = end - timedelta(days=365 * 2)
        df = fdr.DataReader(code, start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
        if df is not None and not df.empty:
            df = df.reset_index()
            df.columns = [c.lower() for c in df.columns]
            if "date" not in df.columns and "index" in df.columns:
                df = df.rename(columns={"index": "date"})
            return df, "FDR"
    except Exception:
        pass

    return None, "not found"


st.set_page_config(
    page_title="종목 심층 분석",
    page_icon="🧾",
    layout="wide",
)

st.sidebar.title(SIDEBAR_TITLE)
_sidebar_nav()

st.title("🧾 종목 심층 분석 (v9.0)")
st.caption(APP_FULL_VERSION)

dashboard_only = os.getenv("DASHBOARD_ONLY", "").lower() == "true"
if dashboard_only:
    st.info("보기 전용: 스케줄러에서 생성된 리포트만 표시합니다.")

col1, col2 = st.columns([2, 1])
with col1:
    try:
        from src.services.account_service import get_holdings_watchlist
        holdings = [
            row for row in get_holdings_watchlist()
            if row.get("status") in ("holding", "sold", "manual")
        ]
    except Exception:
        holdings = []

    holding_codes = [
        f"{h.get('stock_code')} {h.get('stock_name','')}".strip() for h in holdings
    ]
    holding_codes = [c for c in holding_codes if c]

    if holding_codes:
        selected = st.selectbox("보유/관찰 종목", options=["최근 리포트"] + holding_codes, index=0)
        if selected != "최근 리포트":
            code = selected.split()[0]
        else:
            code = ""
    else:
        code = st.text_input("종목코드", value="", placeholder="예: 090710")

with col2:
    full = st.checkbox("상세 모드 (최근 거래원 5건)", value=False)

run = st.button(
    "분석 리포트 생성",
    type="primary",
    use_container_width=True,
    disabled=dashboard_only,
)

if run and not dashboard_only:
    if not code or not code.isdigit():
        st.error("종목코드를 숫자 6자리로 입력해주세요.")
    else:
        from src.services.analysis_report import generate_analysis_report
        result = generate_analysis_report(code, full=full)
        st.success(f"리포트 생성 완료: {result.report_path}")
        st.caption(f"요약: {result.summary}")

# Dashboard view
report_path = None
if code and code.isdigit():
    report_path = _find_latest_report(code)
else:
    reports = _list_reports()
    report_path = reports[0] if reports else None

if report_path and report_path.exists():
    st.subheader(f"리포트: {report_path.name}")
    sections = _load_report_sections(report_path)

    tabs = st.tabs(["요약", "차트", "리포트"])

    with tabs[0]:
        for key in ["Holdings Snapshot", "OHLCV Summary", "Volume Profile", "Broker Flow", "DART Company Profile"]:
            if key in sections:
                st.markdown(f"### {key}")
                st.markdown("\n".join(sections[key]).strip() or "-")

    with tabs[1]:
        if code and code.isdigit():
            df, source = _load_ohlcv_df(code)
            if df is None or df.empty:
                st.warning(f"차트 데이터를 불러오지 못했습니다. ({source})")
            else:
                df = df.sort_values("date").reset_index(drop=True)
                last = df.iloc[-1]
                prev = df.iloc[-2] if len(df) > 1 else None
                change_pct = 0.0
                if prev is not None and float(prev["close"]) > 0:
                    change_pct = (float(last["close"]) - float(prev["close"])) / float(prev["close"]) * 100.0

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("종가", f"{int(last['close']):,}", f"{change_pct:+.2f}%")
                c2.metric("고가", f"{int(last['high']):,}")
                c3.metric("저가", f"{int(last['low']):,}")
                c4.metric("거래량", f"{int(last['volume']):,}")

                view = df.tail(200).set_index("date")
                st.markdown("#### 종가 추이")
                st.line_chart(view["close"])
                st.markdown("#### 거래량")
                st.bar_chart(view["volume"])

    with tabs[2]:
        st.markdown(report_path.read_text(encoding="utf-8"))
else:
    st.warning("리포트가 없습니다. 스케줄러 실행 후 확인하세요.")

st.markdown("---")
st.caption(FOOTER_DASHBOARD)
