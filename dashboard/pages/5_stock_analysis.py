"""
🧾 종목 심층 분석 대시보드 v9.0
"""

import os
from pathlib import Path

import streamlit as st

try:
    from src.config.app_config import (
        APP_FULL_VERSION,
        FOOTER_DASHBOARD,
        SIDEBAR_TITLE,
    )
except ImportError:
    APP_FULL_VERSION = "ClosingBell v9.0"
    FOOTER_DASHBOARD = APP_FULL_VERSION
    SIDEBAR_TITLE = "ClosingBell"


def _sidebar_nav():
    st.page_link("app.py", label="홈")
    st.page_link("pages/1_top5_tracker.py", label="감시종목 TOP5")
    st.page_link("pages/2_nomad_study.py", label="유목민 공부법")
    st.page_link("pages/3_stock_search.py", label="종목 검색")
    st.page_link("pages/4_broker_flow.py", label="거래원 수급")
    st.page_link("pages/5_stock_analysis.py", label="종목 심층 분석")


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
        selected = st.selectbox("보유/관찰 종목", options=["직접 입력"] + holding_codes, index=0)
        if selected != "직접 입력":
            code = selected.split()[0]
            st.text_input("종목코드", value=code, disabled=True)
        else:
            code = st.text_input("종목코드", value="", placeholder="예: 090710")
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


def _find_latest_report(code_value: str) -> Path | None:
    if not code_value:
        return None
    report_dir = Path("reports")
    if not report_dir.exists():
        return None
    files = sorted(report_dir.glob(f"*_{code_value}.md"))
    return files[-1] if files else None


if run and not dashboard_only:
    if not code or not code.isdigit():
        st.error("종목코드를 숫자 6자리로 입력해주세요.")
    else:
        from src.services.analysis_report import generate_analysis_report

        result = generate_analysis_report(code, full=full)
        st.success(f"리포트 생성 완료: {result.report_path}")
        st.caption(f"요약: {result.summary}")

        report_path = Path(result.report_path)
        if report_path.exists():
            st.markdown("---")
            st.markdown(report_path.read_text(encoding="utf-8"))
        else:
            st.warning("리포트 파일을 찾을 수 없습니다.")

if dashboard_only and code and code.isdigit():
    latest = _find_latest_report(code)
    if latest and latest.exists():
        st.success(f"최신 리포트: {latest.name}")
        st.markdown("---")
        st.markdown(latest.read_text(encoding="utf-8"))
    else:
        st.warning("리포트가 없습니다. 스케줄러 실행 후 확인하세요.")

st.markdown("---")
st.caption(FOOTER_DASHBOARD)
