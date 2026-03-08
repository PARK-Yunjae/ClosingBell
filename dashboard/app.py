"""
ClosingBell v3 — Streamlit 대시보드
====================================
1) TOP3 카드뷰 (매물대+거래원+AI 포함)
2) 유니버스 전체 테이블 (정렬/필터)
3) 성과 추적 (순위별 승률, AI 정확도)
4) 주도테마
"""
import os
import sys
import json
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from pathlib import Path
from datetime import datetime, timedelta

# 환경 설정 (Streamlit Cloud에서 API 키 없이 동작)
os.environ.setdefault("DASHBOARD_ONLY", "true")
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

LOG_DIR = project_root / "data" / "logs"
OHLCV_DIR = Path(os.getenv("DATA_DIR", "C:/Coding/data")) / "ohlcv"

# ── 페이지 설정 ──
st.set_page_config(page_title="ClosingBell v3", page_icon="🔔", layout="wide")


def load_logs() -> dict[str, dict]:
    """날짜별 로그 로드"""
    logs = {}
    if not LOG_DIR.exists():
        return logs
    for f in sorted(LOG_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            logs[f.stem] = data
        except Exception:
            pass
    return logs


def _clean_code(code: str) -> str:
    """종목코드에서 _AL, _NX 접미사 제거"""
    for suffix in ("_AL", "_NX", "_SOR"):
        if code.endswith(suffix):
            code = code[:-len(suffix)]
    return code.strip().zfill(6)


def draw_mini_chart(code: str, name: str, rec_date: str = ""):
    """60일 캔들차트 + MA20 + 추천일 마커"""
    code = _clean_code(code)
    df = None

    # 1) 로컬 CSV 먼저 (빠르고 안정적)
    csv_path = OHLCV_DIR / f"{code}.csv"
    if csv_path.exists():
        try:
            raw = pd.read_csv(csv_path)
            raw.columns = [c.lower() for c in raw.columns]
            raw["Date"] = pd.to_datetime(raw["date"])
            df = raw.set_index("Date").rename(columns={
                "open": "Open", "high": "High", "low": "Low",
                "close": "Close", "volume": "Volume"
            }).tail(60)
        except Exception:
            df = None

    # 2) 로컬 CSV 없거나 데이터 부족하면 FDR
    if df is None or len(df) < 10:
        try:
            import FinanceDataReader as fdr
            end = datetime.now()
            start = end - timedelta(days=90)
            fdr_df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
            if fdr_df is not None and len(fdr_df) >= 5:
                df = fdr_df
        except Exception:
            pass

    if df is None or len(df) < 5:
        return None

    df["MA20"] = df["Close"].rolling(20).mean()

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"], name="캔들",
        increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
    ))
    fig.add_trace(go.Scatter(
        x=df.index, y=df["MA20"], name="MA20",
        line=dict(color="#FFB74D", width=1.5),
    ))

    # 추천일 마커
    if rec_date:
        try:
            rd = pd.Timestamp(rec_date)
            if rd in df.index:
                fig.add_vline(x=rd, line_dash="dash", line_color="gold", line_width=2)
                fig.add_annotation(x=rd, y=df.loc[rd, "High"] * 1.02,
                                    text="⭐", showarrow=False, font_size=16)
        except Exception:
            pass

    fig.update_layout(
        height=280, margin=dict(l=0, r=0, t=10, b=0),
        xaxis_rangeslider_visible=False, showlegend=False,
        plot_bgcolor="#1a1a2e", paper_bgcolor="#1a1a2e",
        font_color="#e0e0e0",
        xaxis=dict(gridcolor="#333"), yaxis=dict(gridcolor="#333"),
    )
    return fig


def main():
    logs = load_logs()
    dates = sorted(logs.keys())

    if not dates:
        st.title("🔔 ClosingBell v3")
        st.info("아직 데이터가 없습니다. 스크리닝을 실행해주세요.")
        return

    # ── 사이드바 ──
    st.sidebar.title("🔔 ClosingBell v3")
    selected_date = st.sidebar.selectbox("날짜 선택", dates[::-1])
    page = st.sidebar.radio("페이지", ["📊 TOP3 카드", "📋 유니버스 전체",
                                        "📈 성과 추적", "🔥 주도테마"])

    data = logs[selected_date]

    if data.get("skipped"):
        st.warning(f"스킵: {data.get('reason', '')}")
        return

    market = data.get("market", {})

    # ── 시장 헤더 ──
    cols = st.columns(4)
    cols[0].metric("코스피", f"{market.get('kospi', 0):,.0f}",
                    f"{market.get('kospi_change', 0):+.1f}%")
    cols[1].metric("코스닥", f"{market.get('kosdaq', 0):,.0f}",
                    f"{market.get('kosdaq_change', 0):+.1f}%")
    cols[2].metric("나스닥(전일)", f"{market.get('nasdaq', 0):,.0f}",
                    f"{market.get('nasdaq_change', 0):+.1f}%")
    cols[3].metric("유니버스", f"{data.get('universe_count', 0)}종목")

    st.divider()

    # ════════════════════════════════════════
    if page == "📊 TOP3 카드":
        st.header("📊 오늘의 관심종목 TOP3")

        top = data.get("top", [])
        for stock in top:
            with st.container():
                medal = ["🥇", "🥈", "🥉"][stock["rank"] - 1] if stock["rank"] <= 3 else ""
                clean = _clean_code(stock["code"])
                st.subheader(f"{medal} {stock['name']} ({clean}) — {stock['score']}점")

                c1, c2 = st.columns([2, 3])

                with c1:
                    st.markdown(f"**💰 {stock['price']:,}원** ({stock['change_rate']:+.1f}%)")

                    # 매물대
                    vp_tag = stock.get("vp_tag", "")
                    vp_emoji = {"위 매물 적음": "✅", "매물대 중립": "➖", "위 저항 강함": "❌"}.get(vp_tag, "❓")
                    st.markdown(f"📍 **매물대**: {vp_tag} {vp_emoji}")

                    # 거래원
                    broker_sig = stock.get("broker_signal", "중립")
                    br_emoji = "✅" if "매수" in broker_sig or "매집" in broker_sig else "➖"
                    broker_top = stock.get("broker_top_buy", "")
                    st.markdown(f"🏦 **거래원**: {broker_sig} {br_emoji}"
                                + (f" (매수1위: {broker_top})" if broker_top else ""))

                    # DART
                    dart_risk = stock.get("dart_risk", "확인불가")
                    dart_emoji = {"정상": "✅", "주의": "⚠️", "위험": "❌"}.get(dart_risk, "❓")
                    dart_note = stock.get("dart_note", "")
                    st.markdown(f"📋 **공시**: {dart_risk} {dart_emoji}"
                                + (f" ({dart_note})" if dart_note else ""))

                    # AI 판단
                    action = stock.get("ai_action", "관망")
                    risk = stock.get("ai_risk", "보통")
                    a_emoji = {"매수관심": "🟢", "관망": "🟡", "주의": "🔴"}.get(action, "🟡")
                    r_emoji = {"낮음": "✅", "보통": "⚠️", "높음": "🚫"}.get(risk, "⚠️")
                    st.markdown(f"▶ **{action}** {a_emoji} | 위험도 {risk} {r_emoji}")

                    summary = stock.get("ai_summary", "")
                    if summary:
                        st.caption(f'💡 "{summary}"')

                with c2:
                    fig = draw_mini_chart(stock["code"], stock["name"], selected_date)
                    if fig:
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("차트 로드 불가")

                st.divider()

    # ════════════════════════════════════════
    elif page == "📋 유니버스 전체":
        st.header("📋 유니버스 전체 종목")

        all_scored = data.get("all_scored", [])
        if not all_scored:
            st.info("데이터 없음")
            return

        df = pd.DataFrame(all_scored)
        display_cols = ["rank", "name", "score", "change_rate",
                        "vp_tag", "broker_signal", "ai_action", "ai_risk",
                        "dart_risk", "price"]

        # 필터
        col1, col2, col3 = st.columns(3)
        with col1:
            action_filter = st.multiselect("AI 판단", ["매수관심", "관망", "주의"], default=[])
        with col2:
            vp_filter = st.multiselect("매물대", ["위 매물 적음", "매물대 중립", "위 저항 강함"], default=[])
        with col3:
            min_score = st.slider("최소 점수", 0, 100, 0)

        filtered = df.copy()
        if action_filter:
            filtered = filtered[filtered["ai_action"].isin(action_filter)]
        if vp_filter:
            filtered = filtered[filtered["vp_tag"].isin(vp_filter)]
        if min_score > 0:
            filtered = filtered[filtered["score"] >= min_score]

        available_cols = [c for c in display_cols if c in filtered.columns]
        st.dataframe(
            filtered[available_cols].rename(columns={
                "rank": "순위", "name": "종목명", "score": "점수",
                "change_rate": "등락률", "vp_tag": "매물대",
                "broker_signal": "거래원", "ai_action": "AI판단",
                "ai_risk": "위험도", "dart_risk": "DART", "price": "현재가",
            }),
            use_container_width=True, hide_index=True,
        )

        st.caption(f"총 {len(filtered)}종목 표시 (전체 {len(all_scored)}종목)")

    # ════════════════════════════════════════
    elif page == "📈 성과 추적":
        st.header("📈 성과 추적")

        # 날짜별 전일 수익률 수집
        returns_data = []
        for d, log in logs.items():
            for r in log.get("prev_returns", []):
                returns_data.append({
                    "date": d, "name": r.get("name", ""), "rank": r.get("rank", 0),
                    "return_pct": r.get("return_pct", 0),
                })

        if not returns_data:
            st.info("아직 성과 데이터가 없습니다 (최소 2일 운영 필요)")
            return

        df = pd.DataFrame(returns_data)

        # 전체 승률
        total = len(df)
        wins = (df["return_pct"] > 0).sum()
        avg_ret = df["return_pct"].mean()

        c1, c2, c3 = st.columns(3)
        c1.metric("전체 승률", f"{wins / total * 100:.1f}%" if total > 0 else "N/A")
        c2.metric("평균 수익률", f"{avg_ret:+.2f}%")
        c3.metric("총 추천 수", f"{total}건")

        # 순위별 승률
        if "rank" in df.columns:
            rank_stats = df.groupby("rank").agg(
                count=("return_pct", "count"),
                win_rate=("return_pct", lambda x: (x > 0).mean() * 100),
                avg_return=("return_pct", "mean"),
            ).round(2)
            st.subheader("순위별 성과")
            st.dataframe(rank_stats, use_container_width=True)

        # 일별 수익률 차트
        daily = df.groupby("date")["return_pct"].mean().reset_index()
        fig = go.Figure(go.Bar(
            x=daily["date"], y=daily["return_pct"],
            marker_color=["#26a69a" if v > 0 else "#ef5350" for v in daily["return_pct"]],
        ))
        fig.update_layout(
            height=300, title="일별 평균 수익률",
            plot_bgcolor="#1a1a2e", paper_bgcolor="#1a1a2e", font_color="#e0e0e0",
        )
        st.plotly_chart(fig, use_container_width=True)

    # ════════════════════════════════════════
    elif page == "🔥 주도테마":
        st.header("🔥 주도테마")

        themes = data.get("theme_summary", [])
        if not themes:
            st.info("테마 데이터 없음")
            return

        df = pd.DataFrame(themes)
        display_cols = [c for c in ["name", "change_rate", "stock_count",
                                     "rising_count", "main_stock"] if c in df.columns]
        st.dataframe(
            df[display_cols].rename(columns={
                "name": "테마명", "change_rate": "등락률(%)",
                "stock_count": "종목수", "rising_count": "상승",
                "main_stock": "대표종목",
            }),
            use_container_width=True, hide_index=True,
        )

    # ── 푸터 ──
    st.sidebar.divider()
    st.sidebar.caption(f"ClosingBell v3 | {selected_date}")
    st.sidebar.caption("점수: CCI 25 + 이격도 20 + 등락률 15 + 기울기 20 + RSI 5 + 매물대 10 + 거래원 5")


if __name__ == "__main__":
    main()
else:
    main()
