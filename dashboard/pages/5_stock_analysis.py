"""
🧭 종목 심층 분석 대시보드 v9.0
"""

import streamlit as st
from pathlib import Path

try:
    from src.config.app_config import (
        APP_FULL_VERSION,
        FOOTER_DASHBOARD,
        SIDEBAR_TITLE,
    )
except ImportError:
    APP_FULL_VERSION = "ClosingBell v9.0"
    FOOTER_DASHBOARD = APP_FULL_VERSION
    SIDEBAR_TITLE = "🔔 ClosingBell"


def _sidebar_nav():
    st.page_link("app.py", label="홈")
    st.page_link("pages/1_top5_tracker.py", label="감시종목 TOP5")
    st.page_link("pages/2_nomad_study.py", label="유목민 공부법")
    st.page_link("pages/3_stock_search.py", label="종목 검색")
    st.page_link("pages/4_broker_flow.py", label="거래원 수급")
    st.page_link("pages/5_stock_analysis.py", label="종목 심층 분석")


st.set_page_config(
    page_title="종목 심층 분석",
    page_icon="🧭",
    layout="wide",
)

st.sidebar.title(SIDEBAR_TITLE)
_sidebar_nav()

st.title("🧭 종목 심층 분석 (v9.0)")
st.caption(APP_FULL_VERSION)

col1, col2 = st.columns([2, 1])
with col1:
    code = st.text_input("종목코드", value="", placeholder="예: 090710")
with col2:
    full = st.checkbox("상세 모드 (최근 거래원 5건)", value=False)

run = st.button("분석 리포트 생성", type="primary", use_container_width=True)

if run:
    if not code or not code.isdigit():
        st.error("종목코드는 숫자 6자리로 입력해주세요.")
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

st.markdown("---")
st.caption(FOOTER_DASHBOARD)
