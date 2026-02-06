"""📌 보유종목 관찰 (v9.1)"""
import streamlit as st
from datetime import datetime

try:
    from src.config.app_config import (
        APP_FULL_VERSION,
        FOOTER_DASHBOARD,
        SIDEBAR_TITLE,
    )
except ImportError:
    APP_FULL_VERSION = "ClosingBell v9.1"
    FOOTER_DASHBOARD = APP_FULL_VERSION
    SIDEBAR_TITLE = "🔔 ClosingBell"

try:
    from dashboard.components.sidebar import render_sidebar_nav
except ImportError:
    def render_sidebar_nav():
        st.page_link("app.py", label="🏠 홈")
        st.page_link("pages/1_top5_tracker.py", label="📊 감시종목 TOP5")
        st.page_link("pages/2_nomad_study.py", label="📚 유목민 공부법")
        st.page_link("pages/3_stock_search.py", label="🔍 종목 검색")
        st.page_link("pages/4_broker_flow.py", label="💰 거래원 수급")
        st.page_link("pages/5_stock_analysis.py", label="🧾 종목 심층 분석")
        st.page_link("pages/6_holdings_watch.py", label="📌 보유종목 관찰")


st.set_page_config(
    page_title="보유종목 관찰",
    page_icon="📌",
    layout="wide",
)

with st.sidebar:
    render_sidebar_nav()

st.title("📌 보유종목 관찰")
st.caption(APP_FULL_VERSION)

# ── 데이터 로딩 ──
try:
    from src.services.account_service import (
        fetch_account_holdings,
        get_holdings_watchlist,
        sync_holdings_watchlist,
    )
    service_ok = True
except Exception:
    service_ok = False

if not service_ok:
    st.error("account_service를 불러올 수 없습니다.")
    st.stop()

# ── 현재 보유종목 ──
st.subheader("💰 현재 보유종목")
try:
    data = fetch_account_holdings()
    holdings = data.get("holdings", [])
    if holdings:
        import pandas as pd
        df = pd.DataFrame(holdings)

        # 컬럼 한글화
        col_rename = {
            "code": "종목코드", "name": "종목명", "qty": "수량",
            "price": "평균단가", "cur_price": "현재가",
            "eval_pl": "평가손익", "prft_rt": "수익률(%)",
        }
        df = df.rename(columns={k: v for k, v in col_rename.items() if k in df.columns})

        st.dataframe(df, width="stretch", hide_index=True)

        # 요약 카드
        total_eval = sum(float(h.get("eval_pl", 0) or 0) for h in holdings)
        cols = st.columns(3)
        cols[0].metric("보유 종목 수", f"{len(holdings)}개")
        cols[1].metric("총 평가손익", f"{total_eval:,.0f}원")
        avg_prt = sum(float(h.get("prft_rt", 0) or 0) for h in holdings) / len(holdings) if holdings else 0
        cols[2].metric("평균 수익률", f"{avg_prt:+.2f}%")
    else:
        st.info("현재 보유종목이 없습니다.")
except Exception as e:
    st.warning(f"보유종목 조회 실패: {e}")

# ── 누적 관찰 목록 ──
st.subheader("📋 누적 관찰 목록")
st.caption("스케줄러가 매일 16:50에 자동 동기화합니다.")

watch_rows = get_holdings_watchlist()
if watch_rows:
    import pandas as pd
    wdf = pd.DataFrame(watch_rows)

    wcol_rename = {
        "stock_code": "종목코드", "stock_name": "종목명",
        "status": "상태", "first_seen": "첫 관찰",
        "last_seen": "최근 관찰", "last_qty": "수량",
        "last_price": "단가", "source": "출처",
    }
    wdf = wdf.rename(columns={k: v for k, v in wcol_rename.items() if k in wdf.columns})

    drop_cols = ["id", "notes", "created_at", "updated_at"]
    wdf = wdf.drop(columns=[c for c in drop_cols if c in wdf.columns], errors="ignore")

    st.dataframe(wdf, width="stretch", hide_index=True)
else:
    st.info("누적 관찰 목록이 비어 있습니다. 스케줄러 실행 후 자동 반영됩니다.")

# ── 최근 리포트 ──
st.subheader("📄 최근 분석 리포트")
st.caption("스케줄러가 매일 보유종목 리포트를 자동 생성합니다.")

from pathlib import Path
report_dir = Path("reports")
if report_dir.exists():
    holding_codes = set()
    for row in watch_rows or []:
        code = row.get("stock_code")
        if code:
            holding_codes.add(code)

    if holding_codes:
        found = []
        for code in sorted(holding_codes):
            reports = sorted(report_dir.glob(f"*_{code}.md"), reverse=True)
            if reports:
                found.append((code, reports[0]))

        if found:
            for code, rpath in found:
                name = ""
                for row in (watch_rows or []):
                    if row.get("stock_code") == code:
                        name = row.get("stock_name", "")
                        break
                with st.expander(f"📄 {code} {name} — {rpath.name}", expanded=False):
                    text = rpath.read_text(encoding="utf-8")
                    st.markdown(text[:3000])
                    if len(text) > 3000:
                        st.caption("... (종목 심층 분석 페이지에서 전체 보기)")
        else:
            st.info("아직 리포트가 없습니다. 스케줄러 실행 후 자동 생성됩니다.")
    else:
        st.info("관찰 중인 종목이 없습니다.")
else:
    st.info("reports 폴더가 없습니다.")

st.markdown("---")
st.caption(FOOTER_DASHBOARD)