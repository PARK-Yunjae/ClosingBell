import streamlit as st
from datetime import datetime

try:
    from src.config.app_config import (
        APP_FULL_VERSION,
        FOOTER_DASHBOARD,
        SIDEBAR_TITLE,
    )
except ImportError:
    APP_FULL_VERSION = "ClosingBell v9.0"
    FOOTER_DASHBOARD = APP_FULL_VERSION
    SIDEBAR_TITLE = "📊 ClosingBell"


def _sidebar_nav():
    st.page_link("app.py", label="홈")
    st.page_link("pages/1_top5_tracker.py", label="감시종목 TOP5")
    st.page_link("pages/2_nomad_study.py", label="유목민 공부법")
    st.page_link("pages/3_stock_search.py", label="종목 검색")
    st.page_link("pages/4_broker_flow.py", label="거래원 수급")
    st.page_link("pages/5_stock_analysis.py", label="종목 심층 분석")
    st.page_link("pages/6_holdings_watch.py", label="보유종목 관찰")


st.set_page_config(
    page_title="보유종목 관찰",
    page_icon="📌",
    layout="wide",
)

st.sidebar.title(SIDEBAR_TITLE)
_sidebar_nav()

st.title("보유종목 관찰 (v9.0)")
st.caption(APP_FULL_VERSION)

from src.services.account_service import (
    fetch_account_holdings,
    get_holdings_watchlist,
    sync_holdings_watchlist,
    add_manual_watch,
)

st.subheader("계좌 동기화")
col1, col2 = st.columns([1, 3])
with col1:
    if st.button("보유종목 동기화", use_container_width=True):
        try:
            result = sync_holdings_watchlist()
            st.success("동기화 완료")
            st.caption(f"보유중: {result.get('holding_count', 0)}개 · 매도 처리: {result.get('sold_marked', 0)}개")
        except Exception as e:
            st.error(f"동기화 실패: {e}")
with col2:
    st.caption("계좌 보유종목을 누적 관찰 목록에 반영합니다.")

st.subheader("현재 보유종목")
try:
    data = fetch_account_holdings()
    holdings = data.get("holdings", [])
    if holdings:
        st.dataframe(holdings, use_container_width=True)
    else:
        st.info("현재 보유종목이 없습니다.")
except Exception as e:
    st.warning(f"보유종목 조회 실패: {e}")

st.subheader("누적 관찰 목록")
watch_rows = get_holdings_watchlist()
if watch_rows:
    st.dataframe(watch_rows, use_container_width=True)
else:
    st.info("누적 관찰 목록이 비어 있습니다.")

st.subheader("수동 추가")
with st.form("manual_add_form"):
    code = st.text_input("종목코드", placeholder="예: 005930")
    name = st.text_input("종목명(선택)")
    submitted = st.form_submit_button("추가")
    if submitted:
        if not code or not code.isdigit() or len(code) != 6:
            st.error("종목코드는 6자리 숫자만 입력하세요.")
        else:
            add_manual_watch(code, name)
            st.success("추가 완료")

st.markdown("---")
st.caption(FOOTER_DASHBOARD)
