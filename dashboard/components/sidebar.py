"""대시보드 공통 사이드바 네비게이션 (v9.1)"""
import streamlit as st

SIDEBAR_TITLE = "🔔 ClosingBell"

NAV_ITEMS = [
    ("app.py", "🏠 홈"),
    ("pages/1_top5_tracker.py", "📊 감시종목 TOP5"),
    ("pages/2_nomad_study.py", "📚 유목민 공부법"),
    ("pages/3_stock_search.py", "🔍 종목 검색"),
    ("pages/4_broker_flow.py", "💰 거래원 수급"),
    ("pages/5_stock_analysis.py", "🧾 종목 심층 분석"),
    ("pages/6_holdings_watch.py", "📌 보유종목 관찰"),
]

# Streamlit 기본 네비게이션 강제 숨김 CSS
_HIDE_DEFAULT_NAV = """
<style>
[data-testid="stSidebarNav"] { display: none !important; }
div[data-testid="stSidebarNav"] { display: none !important; }
section[data-testid="stSidebarNav"] { display: none !important; }
ul[data-testid="stSidebarNavItems"] { display: none !important; }
</style>
"""


def render_sidebar_nav():
    """공통 사이드바 네비게이션 렌더링 (자동 네비 숨김 포함)"""
    st.markdown(_HIDE_DEFAULT_NAV, unsafe_allow_html=True)
    st.markdown(f"## {SIDEBAR_TITLE}")
    for path, label in NAV_ITEMS:
        st.page_link(path, label=label)