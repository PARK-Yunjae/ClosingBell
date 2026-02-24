"""
ClosingBell v2 — Streamlit 대시보드
배포: closingbell.streamlit.app
데이터: data/logs/*.json (Git push로 갱신)
"""
import json
import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime

# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="ClosingBell v2",
    page_icon="🔔",
    layout="wide",
    initial_sidebar_state="expanded",
)

LOG_DIR = Path(__file__).parent.parent / "data" / "logs"


@st.cache_data(ttl=300)
def load_all_logs() -> dict:
    """전체 로그 로드"""
    logs = {}
    if not LOG_DIR.exists():
        return logs
    for f in sorted(LOG_DIR.glob("*.json")):
        try:
            logs[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
    return logs


# ──────────────────────────────────────────────
# 데이터 로드
# ──────────────────────────────────────────────
logs = load_all_logs()
dates = sorted(logs.keys())

if not dates:
    st.title("🔔 ClosingBell v2")
    st.info("아직 스크리닝 데이터가 없습니다. `python main.py --screen` 실행 후 git push 해주세요.")
    st.stop()

# ──────────────────────────────────────────────
# 사이드바
# ──────────────────────────────────────────────
with st.sidebar:
    st.title("🔔 ClosingBell v2")
    page = st.radio("페이지", ["🏠 오늘의 추천", "📊 성과 추적", "⚙️ 시스템"])

# ──────────────────────────────────────────────
# 🏠 오늘의 추천
# ──────────────────────────────────────────────
if page == "🏠 오늘의 추천":
    st.title("🔔 오늘의 추천")

    # 날짜 선택
    selected_date = st.selectbox(
        "날짜 선택",
        options=dates[::-1],
        index=0,
        format_func=lambda x: f"{x} ({'최신' if x == dates[-1] else ''})",
    )
    data = logs[selected_date]

    # 스킵 여부
    if data.get("skipped"):
        st.warning(f"⚠️ 스크리닝 스킵: {data.get('reason', '알 수 없음')}")
        st.stop()

    # 시장 현황
    market = data.get("market", {})
    col1, col2, col3 = st.columns(3)
    col1.metric(
        "코스피",
        f"{market.get('kospi', 0):,.0f}",
        f"{market.get('kospi_change', 0):+.2f}%",
    )
    col2.metric(
        "코스닥",
        f"{market.get('kosdaq', 0):,.0f}",
        f"{market.get('kosdaq_change', 0):+.2f}%",
    )
    col3.metric(
        "나스닥 (전일)",
        f"{market.get('nasdaq', 0):,.0f}",
        f"{market.get('nasdaq_change', 0):+.2f}%",
    )

    st.divider()

    # TOP5
    top5 = data.get("top5", [])
    st.subheader(f"🏆 TOP{len(top5)} 추천 종목")

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for i, stock in enumerate(top5):
        medal = medals[i] if i < len(medals) else f"{i+1}."
        cci_arrows = "↑" * stock.get("cci_slope", 0) or "→"
        ma_arrow = "↑" if stock.get("ma20_slope", 0) > 0 else "→"

        col_a, col_b, col_c = st.columns([3, 2, 3])
        with col_a:
            st.markdown(
                f"### {medal} {stock['name']} ({stock['code']})"
            )
            st.markdown(f"**{stock['score']}점** · {stock['price']:,}원 ({stock['change_rate']:+.1f}%)")
        with col_b:
            st.metric("CCI", f"{stock['cci']:.0f}", cci_arrows)
        with col_c:
            st.metric("MA20 이격도", f"{stock['ma20_gap']:.1f}%", ma_arrow)

        if i < len(top5) - 1:
            st.divider()

    # 유니버스 전체
    st.divider()
    all_scored = data.get("all_scored", [])
    with st.expander(f"📋 유니버스 전체 ({len(all_scored)}종목)", expanded=False):
        if all_scored:
            df = pd.DataFrame(all_scored)
            df = df[["rank", "name", "code", "score", "price", "change_rate", "cci", "ma20_gap", "cci_slope", "ma20_slope"]]
            df.columns = ["순위", "종목명", "코드", "점수", "현재가", "등락률(%)", "CCI", "이격도(%)", "CCI기울기", "MA기울기"]
            st.dataframe(df, use_container_width=True, hide_index=True)

# ──────────────────────────────────────────────
# 📊 성과 추적
# ──────────────────────────────────────────────
elif page == "📊 성과 추적":
    st.title("📊 성과 추적")

    if len(dates) < 2:
        st.info("최소 2일 이상의 데이터가 필요합니다.")
        st.stop()

    # 일별 추천 요약 테이블
    summary_rows = []
    for d in dates:
        data = logs[d]
        if data.get("skipped"):
            summary_rows.append({"날짜": d, "상태": "스킵", "유니버스": 0, "1위": "-", "1위점수": 0})
            continue

        top5 = data.get("top5", [])
        first = top5[0] if top5 else {}
        summary_rows.append({
            "날짜": d,
            "상태": "정상",
            "유니버스": data.get("universe_count", 0),
            "1위": first.get("name", "-"),
            "1위점수": first.get("score", 0),
            "1위등락률": first.get("change_rate", 0),
            "코스피": data.get("market", {}).get("kospi_change", 0),
        })

    df_summary = pd.DataFrame(summary_rows)
    st.dataframe(df_summary, use_container_width=True, hide_index=True)

    # 1위 등락률 차트
    if "1위등락률" in df_summary.columns:
        chart_data = df_summary[df_summary["1위등락률"] != 0].copy()
        if len(chart_data) > 0:
            st.subheader("📈 1위 종목 당일 등락률 추이")
            st.bar_chart(chart_data.set_index("날짜")["1위등락률"])

    # 순위별 분석 (추후 다음날 수익률 데이터 누적 시)
    st.divider()
    st.subheader("🎯 순위별 성과 분석")
    st.info("데이터가 누적되면 순위별 다음날 수익률 분석이 표시됩니다. "
            "`python main.py --backtest 30` 명령으로 확인할 수 있습니다.")

# ──────────────────────────────────────────────
# ⚙️ 시스템
# ──────────────────────────────────────────────
elif page == "⚙️ 시스템":
    st.title("⚙️ 시스템 현황")

    col1, col2, col3 = st.columns(3)
    col1.metric("총 로그 수", f"{len(dates)}일")
    col2.metric("최초 날짜", dates[0] if dates else "-")
    col3.metric("최신 날짜", dates[-1] if dates else "-")

    # 유니버스 종목 수 추이
    uni_data = []
    for d in dates:
        data = logs[d]
        if not data.get("skipped"):
            uni_data.append({"날짜": d, "유니버스": data.get("universe_count", 0)})

    if uni_data:
        st.subheader("📊 유니버스 종목 수 추이")
        df_uni = pd.DataFrame(uni_data)
        st.line_chart(df_uni.set_index("날짜")["유니버스"])

    # 점수 분포 설정
    st.divider()
    st.subheader("🔧 점수 배점")
    st.markdown("""
    | 지표 | 배점 | 최적 구간 | 근거 |
    |------|------|-----------|------|
    | CCI(14) | 30점 | 160~180 | 9.5년 백테스트 50.4% 승률 |
    | MA20 이격도 | 25점 | 2~8% | 추세 위 적정 거리 |
    | 등락률 | 20점 | 2~8% | 스윗스팟 |
    | CCI 기울기 | 15점 | 3일 연속 상승 | 모멘텀 가속 |
    | MA20 기울기 | 10점 | 3일 연속 상승 | 중기 우상향 |
    """)

    st.markdown("---")
    st.caption(f"ClosingBell v2 | 마지막 업데이트: {dates[-1] if dates else '-'}")
