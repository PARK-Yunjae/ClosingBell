"""📝 매매일지 (v10.1)

보유종목 변화 자동 감지 → trade_journal 기록
시그널 출처 자동 연결 (TOP5/눌림목/유목민/수동)
주간 리포트 + 누적 성과
"""
import streamlit as st
from datetime import datetime, date, timedelta

try:
    from src.config.app_config import APP_FULL_VERSION, SIDEBAR_TITLE
except ImportError:
    APP_FULL_VERSION = "ClosingBell v10.1"
    SIDEBAR_TITLE = "🔔 ClosingBell"

try:
    from dashboard.components.sidebar import render_sidebar_nav
except ImportError:
    def render_sidebar_nav():
        st.page_link("app.py", label="🏠 홈")


st.set_page_config(
    page_title="매매일지",
    page_icon="📝",
    layout="wide",
)

with st.sidebar:
    render_sidebar_nav()

st.title("📝 매매일지")
st.caption(APP_FULL_VERSION)


# ── 서비스 로드 ──
try:
    from src.services.trade_journal_service import (
        get_journal_entries,
        get_journal_stats,
        get_signal_source_stats,
        generate_weekly_report,
    )
    service_ok = True
except Exception as e:
    service_ok = False
    st.error(f"trade_journal_service 로드 실패: {e}")

if not service_ok:
    st.stop()


# ── 탭 구성 ──
tab1, tab2, tab3 = st.tabs(["📋 거래 내역", "📊 성과 분석", "📄 주간 리포트"])


# ===== 탭 1: 거래 내역 =====
with tab1:
    col1, col2 = st.columns([1, 3])
    with col1:
        days = st.selectbox("조회 기간", [7, 14, 30, 90, 365], index=2,
                           format_func=lambda x: f"최근 {x}일")
    with col2:
        trade_filter = st.radio("유형", ["전체", "매수", "매도"], horizontal=True)

    type_map = {"전체": None, "매수": "BUY", "매도": "SELL"}
    entries = get_journal_entries(days=days, trade_type=type_map[trade_filter])

    if entries:
        st.markdown(f"**총 {len(entries)}건**")

        for entry in entries:
            trade_type = entry.get("trade_type", "?")
            emoji = "🟢" if trade_type == "BUY" else "🔴"
            name = entry.get("stock_name", "?")
            code = entry.get("stock_code", "?")
            qty = entry.get("quantity", 0)
            price = entry.get("price", 0)
            total = entry.get("total_amount", 0)
            ret = entry.get("return_rate", 0)
            memo = entry.get("memo", "")
            trade_date = entry.get("trade_date", "?")

            ret_str = f" **({ret:+.1f}%)**" if ret else ""
            type_str = "매수" if trade_type == "BUY" else "매도"

            with st.container():
                cols = st.columns([1, 2, 1, 1, 2])
                cols[0].markdown(f"**{trade_date}**")
                cols[1].markdown(f"{emoji} **{name}** ({code})")
                cols[2].markdown(f"{type_str} {qty:,}주")
                cols[3].markdown(f"@{price:,}원{ret_str}")
                cols[4].markdown(f"💬 {memo.replace('[자동] ', '')}" if memo else "")
                st.divider()
    else:
        st.info("📭 거래 내역이 없습니다.")
        st.markdown("""
        **매매일지는 자동으로 기록됩니다:**
        - 스케줄러가 매일 보유종목을 동기화할 때
        - 새 종목 매수 / 수량 변경 / 매도 감지 시
        - 시그널 출처 (TOP5/눌림목/유목민) 자동 연결
        """)


# ===== 탭 2: 성과 분석 =====
with tab2:
    stats_period = st.selectbox("분석 기간", [7, 14, 30, 90], index=2,
                                format_func=lambda x: f"최근 {x}일",
                                key="stats_period")
    stats = get_journal_stats(days=stats_period)

    if stats["total_trades"] > 0:
        # 핵심 지표: 승률보다 '돈을 버는가'
        st.markdown("#### 💰 핵심: 돈을 버는 구조인가?")
        col1, col2, col3, col4 = st.columns(4)

        ev = stats.get("expected_value", 0)
        pf = stats.get("profit_factor", 0)
        plr = stats.get("profit_loss_ratio", 0)

        col1.metric(
            "기대값 (EV)",
            f"{ev:+.2f}%",
            delta="양수 = 장기 수익 가능" if ev > 0 else "음수 = 구조 개선 필요",
            delta_color="normal" if ev > 0 else "inverse",
        )
        col2.metric(
            "손익비 (R:R)",
            f"{plr:.2f}",
            delta="1 이상 = 익절 > 손절" if plr >= 1 else "1 미만 = 손절이 더 큼",
            delta_color="normal" if plr >= 1 else "inverse",
        )
        col3.metric(
            "Profit Factor",
            f"{pf:.2f}",
            delta="1.5+ 우수" if pf >= 1.5 else ("1+ 양호" if pf >= 1 else "1 미만 위험"),
        )
        col4.metric("총 실현손익", f"{stats['total_pnl']:+,.0f}원")

        st.markdown("---")

        # 기존 승률 통계
        st.markdown("#### 📊 기본 통계")
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("총 거래", f"{stats['total_trades']}건")
        col2.metric("승률", f"{stats['win_rate']:.0f}%",
                    delta=f"{stats['wins']}승 {stats['losses']}패")
        col3.metric("평균 수익률", f"{stats['avg_return']:+.1f}%")
        col4.metric("평균 익절", f"+{stats.get('avg_win', 0):.1f}%")
        col5.metric("평균 손절", f"{stats.get('avg_loss', 0):.1f}%")

        st.markdown("---")

        # 시그널 출처별 손익비 분석 — 어디서 돈을 버는가?
        st.markdown("#### 🎯 시그널 출처별 — 어디서 돈을 버는가?")
        st.caption("_적중률이 아니라 '돈을 번다는 것' 그 자체가 중요하다_ — 유목민")

        source_stats = get_signal_source_stats(days=stats_period)

        if source_stats:
            for ss in source_stats:
                src = ss["source"]
                emoji = {"TOP5": "📈", "눌림목": "📉", "유목민": "📚", "수동": "✋"}.get(src, "📊")

                ev_color = "🟢" if ss["expected_value"] > 0 else "🔴"

                with st.container():
                    cols = st.columns([1.5, 1, 1, 1, 1, 1])
                    cols[0].markdown(f"**{emoji} {src}** ({ss['trades']}건)")
                    cols[1].markdown(f"승률 {ss['win_rate']:.0f}%")
                    cols[2].markdown(f"손익비 **{ss['profit_loss_ratio']:.2f}**")
                    cols[3].markdown(f"기대값 {ev_color} **{ss['expected_value']:+.2f}%**")
                    cols[4].markdown(f"익절 +{ss['avg_win']:.1f}% / 손절 {ss['avg_loss']:.1f}%")
                    cols[5].markdown(f"누적 {ss['total_pnl']:+.1f}%")
                    st.divider()
        else:
            st.info("시그널 출처별 분석에 매도 기록이 필요합니다.")

    else:
        st.info("매도 기록이 없어 성과를 분석할 수 없습니다.")
        st.markdown("""
        **유목민 책에서 배운 핵심:**
        > 주식은 적중률 싸움이 아니라 '돈을 번다는 것' 그 자체입니다.
        
        매매일지가 쌓이면 승률 대신 **기대값(EV)**과 **손익비(R:R)**로 
        자신의 강점을 찾을 수 있습니다.
        """)


# ===== 탭 3: 주간 리포트 =====
with tab3:
    target = st.date_input("기준 주", value=date.today())
    report = generate_weekly_report(target)
    st.markdown(report)

    if st.button("📋 클립보드 복사용 텍스트"):
        st.code(report, language="markdown")
