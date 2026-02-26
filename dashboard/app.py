"""
ClosingBell v2 — Streamlit 대시보드
배포: closingbell.streamlit.app

기능:
1. 오늘의 추천 + 종목 미니차트 (FinanceDataReader)
2. 업종/주도섹터 분석
3. 성과 추적 (날짜별 수익률)
4. 시스템 현황
"""
import json
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from pathlib import Path
from datetime import datetime, timedelta

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
    logs = {}
    if not LOG_DIR.exists():
        return logs
    for f in sorted(LOG_DIR.glob("*.json")):
        try:
            logs[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
    return logs


@st.cache_data(ttl=600)
def get_stock_chart(code: str, days: int = 60) -> pd.DataFrame | None:
    try:
        import FinanceDataReader as fdr
        end = datetime.now()
        start = end - timedelta(days=days)
        df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if df is not None and len(df) > 0:
            return df
    except Exception:
        pass
    return None


def draw_mini_chart(code: str, name: str, days: int = 60, rec_date: str = ""):
    df = get_stock_chart(code, days)
    if df is None or len(df) < 5:
        st.caption("차트 데이터 없음")
        return

    df = df.reset_index()
    col_map = {}
    for c in df.columns:
        cl = c.lower()
        if cl == "date": col_map[c] = "Date"
        elif cl == "open": col_map[c] = "Open"
        elif cl == "high": col_map[c] = "High"
        elif cl == "low": col_map[c] = "Low"
        elif cl == "close": col_map[c] = "Close"
        elif cl == "volume": col_map[c] = "Volume"
    df = df.rename(columns=col_map)

    if "Close" not in df.columns:
        st.caption("차트 형식 오류")
        return

    df["MA20"] = df["Close"].rolling(20).mean()

    fig = go.Figure()
    if all(c in df.columns for c in ["Open", "High", "Low", "Close"]):
        fig.add_trace(go.Candlestick(
            x=df.get("Date", df.index),
            open=df["Open"], high=df["High"],
            low=df["Low"], close=df["Close"],
            name="가격",
            increasing_line_color="#FF4136",
            decreasing_line_color="#0074D9",
        ))
    fig.add_trace(go.Scatter(
        x=df.get("Date", df.index), y=df["MA20"],
        name="MA20", line=dict(color="orange", width=1.5),
    ))

    # 추천일 세로선 + ⭐ 마커
    if rec_date and "Date" in df.columns:
        rec_dt = pd.Timestamp(rec_date)
        match = df[df["Date"].dt.date == rec_dt.date()]
        if len(match) > 0:
            rec_close = float(match.iloc[0]["Close"])
            fig.add_vline(
                x=rec_dt, line_width=2, line_dash="dash",
                line_color="#FFD700",
            )
            fig.add_trace(go.Scatter(
                x=[rec_dt], y=[rec_close],
                mode="markers+text",
                marker=dict(size=10, color="#FFD700", symbol="star"),
                text=["추천일"], textposition="top center",
                textfont=dict(color="#FFD700", size=10),
                showlegend=False,
            ))

    fig.update_layout(
        height=280, margin=dict(l=0, r=0, t=30, b=0),
        title=dict(text=f"{name} ({code})", font=dict(size=13)),
        xaxis_rangeslider_visible=False, showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)


# ──────────────────────────────────────────────
# 데이터 로드
# ──────────────────────────────────────────────
logs = load_all_logs()
dates = sorted(logs.keys())

if not dates:
    st.title("🔔 ClosingBell v2")
    st.info("아직 스크리닝 데이터가 없습니다. `python main.py --screen` 후 git push 해주세요.")
    st.stop()

# ──────────────────────────────────────────────
# 사이드바
# ──────────────────────────────────────────────
with st.sidebar:
    st.title("🔔 ClosingBell v2")
    page = st.radio("페이지", [
        "🏠 오늘의 추천",
        "🏭 업종/주도섹터",
        "📊 성과 추적",
        "⚙️ 시스템",
    ])
    st.divider()
    st.caption(f"데이터: {dates[0]} ~ {dates[-1]}")
    st.caption(f"총 {len(dates)}일 기록")

# ══════════════════════════════════════════════
# 🏠 오늘의 추천
# ══════════════════════════════════════════════
if page == "🏠 오늘의 추천":
    st.title("🔔 오늘의 추천")

    selected_date = st.selectbox(
        "날짜 선택", options=dates[::-1], index=0,
        format_func=lambda x: f"{x} {'⭐' if x == dates[-1] else ''}",
    )
    data = logs[selected_date]

    if data.get("skipped"):
        st.warning(f"⚠️ 스크리닝 스킵: {data.get('reason', '')}")
        st.stop()

    # 시장 현황
    market = data.get("market", {})
    c1, c2, c3 = st.columns(3)
    c1.metric("코스피", f"{market.get('kospi', 0):,.0f}",
              f"{market.get('kospi_change', 0):+.2f}%")
    c2.metric("코스닥", f"{market.get('kosdaq', 0):,.0f}",
              f"{market.get('kosdaq_change', 0):+.2f}%")
    c3.metric("나스닥 (전일)", f"{market.get('nasdaq', 0):,.0f}",
              f"{market.get('nasdaq_change', 0):+.2f}%")

    # 전일 추천 수익률
    prev_returns = data.get("prev_returns", [])
    if prev_returns:
        st.divider()
        st.subheader("📈 전일 추천 수익률")
        cols = st.columns(len(prev_returns))
        for i, ret in enumerate(prev_returns):
            color = "normal" if ret["return_pct"] >= 0 else "inverse"
            cols[i].metric(
                f"{ret['rank']}위 {ret['name']}",
                f"{ret['today_price']:,}원",
                f"{ret['return_pct']:+.2f}%",
                delta_color=color,
            )

    st.divider()

    # TOP5 + 미니차트
    top5 = data.get("top5", [])
    st.subheader(f"🏆 TOP{len(top5)} 추천 종목")

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for i, stock in enumerate(top5):
        medal = medals[i] if i < len(medals) else f"{i+1}."
        cci_arrows = "↑" * stock.get("cci_slope", 0) or "→"
        ma_arrow = "↑" if stock.get("ma20_slope", 0) > 0 else "→"
        sector = stock.get("sector", "")

        col_info, col_chart = st.columns([2, 3])
        with col_info:
            st.markdown(f"### {medal} {stock['name']} ({stock['code']})")
            if sector:
                st.caption(f"🏭 {sector}")
            st.markdown(f"**{stock['score']}점** · {stock['price']:,}원 ({stock['change_rate']:+.1f}%)")
            st.markdown(
                f"CCI **{stock['cci']:.0f}** {cci_arrows} · "
                f"이격도 **{stock['ma20_gap']:.1f}%** · MA {ma_arrow}"
            )
        with col_chart:
            draw_mini_chart(stock["code"], stock["name"], rec_date=selected_date)

        if i < len(top5) - 1:
            st.divider()

    # 유니버스 전체
    st.divider()
    all_scored = data.get("all_scored", [])
    with st.expander(f"📋 유니버스 전체 ({len(all_scored)}종목)", expanded=False):
        if all_scored:
            df = pd.DataFrame(all_scored)
            cols = [c for c in ["rank", "name", "code", "sector", "score", "price",
                    "change_rate", "cci", "ma20_gap", "cci_slope", "ma20_slope"] if c in df.columns]
            df = df[cols].rename(columns={
                "rank": "순위", "name": "종목명", "code": "코드", "sector": "업종",
                "score": "점수", "price": "현재가", "change_rate": "등락률(%)",
                "cci": "CCI", "ma20_gap": "이격도(%)",
                "cci_slope": "CCI↑", "ma20_slope": "MA↑",
            })
            st.dataframe(df, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════
# 🏭 업종/주도섹터
# ══════════════════════════════════════════════
elif page == "🏭 업종/주도섹터":
    st.title("🏭 업종/주도섹터 분석")

    selected_date = st.selectbox("날짜 선택", options=dates[::-1], index=0)
    data = logs[selected_date]

    if data.get("skipped"):
        st.warning("해당 날짜는 스크리닝 스킵")
        st.stop()

    sector_summary = data.get("sector_summary", [])

    # sector_summary 없으면 all_scored에서 생성
    if not sector_summary:
        all_scored = data.get("all_scored", [])
        if all_scored:
            from collections import defaultdict
            sec = defaultdict(lambda: {"count": 0, "total": 0.0, "stocks": []})
            for s in all_scored:
                k = s.get("sector") or "기타"
                sec[k]["count"] += 1
                sec[k]["total"] += s.get("change_rate", 0)
                sec[k]["stocks"].append(s.get("name", ""))
            sector_summary = sorted([
                {"sector": k, "count": v["count"],
                 "avg_change": round(v["total"] / v["count"], 2),
                 "stocks": v["stocks"][:5]}
                for k, v in sec.items()
            ], key=lambda x: x["avg_change"], reverse=True)

    if not sector_summary:
        st.info("섹터 데이터 없음")
        st.stop()

    # 주도섹터 차트
    st.subheader("🔥 오늘의 주도섹터")
    df_sec = pd.DataFrame(sector_summary)
    colors = ["#FF4136" if v > 0 else "#0074D9" for v in df_sec["avg_change"]]
    fig = go.Figure(go.Bar(
        x=df_sec["sector"], y=df_sec["avg_change"],
        marker_color=colors,
        text=[f"{v:+.1f}%" for v in df_sec["avg_change"]],
        textposition="outside",
    ))
    fig.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0),
                      yaxis_title="평균 등락률 (%)")
    st.plotly_chart(fig, use_container_width=True)

    # 전체 테이블
    st.divider()
    st.subheader("📊 전체 업종 현황")
    df_sec["주요종목"] = df_sec["stocks"].apply(lambda x: ", ".join(x) if isinstance(x, list) else "")
    st.dataframe(
        df_sec[["sector", "count", "avg_change", "주요종목"]].rename(columns={
            "sector": "업종", "count": "종목 수", "avg_change": "평균 등락률(%)"
        }),
        use_container_width=True, hide_index=True,
    )

    # TOP5 섹터 분포
    st.divider()
    st.subheader("🏆 TOP5 종목의 업종")
    top5 = data.get("top5", [])
    if top5:
        for s in top5:
            sec = s.get("sector") or "기타"
            st.markdown(f"**{s['rank']}위 {s['name']}** → {sec} ({s['change_rate']:+.1f}%)")


# ══════════════════════════════════════════════
# 📊 성과 추적
# ══════════════════════════════════════════════
elif page == "📊 성과 추적":
    st.title("📊 성과 추적")

    if len(dates) < 2:
        st.info("최소 2일 이상의 데이터가 필요합니다.")
        st.stop()

    # ── 수익률 데이터 수집 ──
    all_returns = []
    for d in dates:
        for ret in logs[d].get("prev_returns", []):
            all_returns.append({
                "추천일": ret.get("date", ""), "확인일": d,
                "순위": ret.get("rank", 0), "종목명": ret.get("name", ""),
                "코드": ret.get("code", ""),
                "매수가": ret.get("buy_price", 0),
                "확인가": ret.get("today_price", 0),
                "수익률(%)": ret.get("return_pct", 0),
            })

    if not all_returns:
        st.info("📅 수익률 데이터가 아직 없습니다.\n\n"
                "2일 이상 스크리닝하면 전일 추천 수익률이 자동 계산됩니다.")
        st.stop()

    df_ret = pd.DataFrame(all_returns)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 핵심 요약 카드
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    total = len(df_ret)
    wins = (df_ret["수익률(%)"] > 0).sum()
    losses = (df_ret["수익률(%)"] < 0).sum()
    even = (df_ret["수익률(%)"] == 0).sum()
    avg_ret = df_ret["수익률(%)"].mean()
    avg_win = df_ret[df_ret["수익률(%)"] > 0]["수익률(%)"].mean() if wins > 0 else 0
    avg_loss = df_ret[df_ret["수익률(%)"] < 0]["수익률(%)"].mean() if losses > 0 else 0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("총 추천", f"{total}건")
    c2.metric("승률", f"{wins/total*100:.1f}%", f"{wins}승 {losses}패 {even}무")
    c3.metric("평균 수익률", f"{avg_ret:+.2f}%")
    c4.metric("평균 수익 (승)", f"{avg_win:+.2f}%")
    c5.metric("평균 손실 (패)", f"{avg_loss:+.2f}%")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 순위별 상세 성과
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    st.divider()
    st.subheader("🎯 순위별 성과 분석")

    rank_stats = []
    for rank in sorted(df_ret["순위"].unique()):
        rdf = df_ret[df_ret["순위"] == rank]
        r_wins = (rdf["수익률(%)"] > 0).sum()
        r_total = len(rdf)
        rank_stats.append({
            "순위": f"{int(rank)}위",
            "건수": r_total,
            "승": r_wins,
            "패": (rdf["수익률(%)"] < 0).sum(),
            "승률(%)": round(r_wins / r_total * 100, 1) if r_total > 0 else 0,
            "평균수익률(%)": round(rdf["수익률(%)"].mean(), 2),
            "최대수익(%)": round(rdf["수익률(%)"].max(), 2),
            "최대손실(%)": round(rdf["수익률(%)"].min(), 2),
        })

    df_rank = pd.DataFrame(rank_stats)

    # 순위별 차트: 승률 + 평균수익률 나란히
    col_wr, col_ar = st.columns(2)

    with col_wr:
        fig_wr = go.Figure(go.Bar(
            x=df_rank["순위"], y=df_rank["승률(%)"],
            marker_color=["#00B894" if v >= 50 else "#FDCB6E" if v >= 40 else "#E17055"
                          for v in df_rank["승률(%)"]],
            text=[f"{v:.0f}%<br>({w}승{l}패)" for v, w, l
                  in zip(df_rank["승률(%)"], df_rank["승"], df_rank["패"])],
            textposition="outside",
        ))
        fig_wr.add_hline(y=50, line_dash="dash", line_color="gray",
                         annotation_text="50%", annotation_position="right")
        fig_wr.update_layout(height=320, margin=dict(l=0, r=0, t=30, b=0),
                             title=dict(text="순위별 승률", font=dict(size=14)),
                             yaxis_range=[0, max(df_rank["승률(%)"].max() + 15, 60)])
        st.plotly_chart(fig_wr, use_container_width=True)

    with col_ar:
        fig_ar = go.Figure(go.Bar(
            x=df_rank["순위"], y=df_rank["평균수익률(%)"],
            marker_color=["#FF4136" if v > 0 else "#0074D9"
                          for v in df_rank["평균수익률(%)"]],
            text=[f"{v:+.2f}%" for v in df_rank["평균수익률(%)"]],
            textposition="outside",
        ))
        fig_ar.add_hline(y=0, line_color="gray")
        fig_ar.update_layout(height=320, margin=dict(l=0, r=0, t=30, b=0),
                             title=dict(text="순위별 평균 수익률", font=dict(size=14)))
        st.plotly_chart(fig_ar, use_container_width=True)

    # 순위별 상세 테이블
    st.dataframe(df_rank, use_container_width=True, hide_index=True)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 일별 수익률 추이
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    st.divider()
    st.subheader("📅 일별 수익률 추이")

    # 일별 평균 수익률
    daily = df_ret.groupby("추천일").agg(
        평균수익률=("수익률(%)", "mean"),
        종목수=("수익률(%)", "count"),
        승수=("수익률(%)", lambda x: (x > 0).sum()),
    ).reset_index()
    daily["승률(%)"] = (daily["승수"] / daily["종목수"] * 100).round(1)
    daily["누적수익률(%)"] = daily["평균수익률"].cumsum().round(2)

    # 누적 수익률 라인 + 일별 바 차트
    fig_daily = go.Figure()
    fig_daily.add_trace(go.Bar(
        x=daily["추천일"], y=daily["평균수익률"],
        name="일 평균 수익률",
        marker_color=["#FF4136" if v > 0 else "#0074D9" for v in daily["평균수익률"]],
        text=[f"{v:+.1f}%" for v in daily["평균수익률"]],
        textposition="outside",
        yaxis="y",
    ))
    fig_daily.add_trace(go.Scatter(
        x=daily["추천일"], y=daily["누적수익률(%)"],
        name="누적 수익률",
        line=dict(color="#00B894", width=3),
        mode="lines+markers",
        yaxis="y2",
    ))
    fig_daily.update_layout(
        height=380, margin=dict(l=0, r=50, t=10, b=0),
        yaxis=dict(title="일 평균 수익률 (%)"),
        yaxis2=dict(title="누적 수익률 (%)", overlaying="y", side="right"),
        legend=dict(orientation="h", y=1.12),
        barmode="relative",
    )
    st.plotly_chart(fig_daily, use_container_width=True)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 점수대별 성과 (점수가 높으면 실제로 잘 맞는가?)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    st.divider()
    st.subheader("📐 점수대별 성과")
    st.caption("점수가 높은 종목이 실제로 수익률이 좋은가?")

    # 날짜별 top5에서 점수 매칭
    score_returns = []
    for d in dates:
        data = logs[d]
        if data.get("skipped"):
            continue
        idx = dates.index(d)
        if idx + 1 >= len(dates):
            continue
        next_date = dates[idx + 1]
        prev_rets = {r["code"]: r["return_pct"] for r in logs[next_date].get("prev_returns", [])}
        for s in data.get("top5", []):
            code = s.get("code", "")
            if code in prev_rets:
                score_returns.append({
                    "점수": s.get("score", 0),
                    "수익률(%)": prev_rets[code],
                    "종목명": s.get("name", ""),
                    "날짜": d,
                })

    if score_returns:
        df_score = pd.DataFrame(score_returns)

        # 점수 구간 나누기
        bins = [0, 40, 55, 70, 85, 100]
        labels = ["~40", "40~55", "55~70", "70~85", "85~100"]
        df_score["점수대"] = pd.cut(df_score["점수"], bins=bins, labels=labels, right=True)

        score_stats = df_score.groupby("점수대", observed=True).agg(
            건수=("수익률(%)", "count"),
            승률=("수익률(%)", lambda x: round((x > 0).mean() * 100, 1)),
            평균수익률=("수익률(%)", lambda x: round(x.mean(), 2)),
        ).reset_index()

        col_sb, col_sc = st.columns(2)
        with col_sb:
            fig_sb = go.Figure(go.Bar(
                x=score_stats["점수대"], y=score_stats["승률"],
                marker_color=["#00B894" if v >= 50 else "#E17055" for v in score_stats["승률"]],
                text=[f"{v:.0f}%\n({n}건)" for v, n in zip(score_stats["승률"], score_stats["건수"])],
                textposition="outside",
            ))
            fig_sb.add_hline(y=50, line_dash="dash", line_color="gray")
            fig_sb.update_layout(height=300, margin=dict(l=0, r=0, t=30, b=0),
                                 title=dict(text="점수대별 승률", font=dict(size=14)),
                                 xaxis_title="점수 구간")
            st.plotly_chart(fig_sb, use_container_width=True)

        with col_sc:
            fig_sc = go.Figure(go.Scatter(
                x=df_score["점수"], y=df_score["수익률(%)"],
                mode="markers",
                marker=dict(size=8, color=df_score["수익률(%)"],
                            colorscale="RdYlGn", cmin=-5, cmax=5,
                            showscale=True, colorbar=dict(title="%")),
                text=[f"{n}<br>{s}점 → {r:+.1f}%"
                      for n, s, r in zip(df_score["종목명"], df_score["점수"], df_score["수익률(%)"])],
                hovertemplate="%{text}<extra></extra>",
            ))
            fig_sc.add_hline(y=0, line_color="gray")
            fig_sc.update_layout(height=300, margin=dict(l=0, r=0, t=30, b=0),
                                 title=dict(text="점수 vs 수익률 분포", font=dict(size=14)),
                                 xaxis_title="점수", yaxis_title="수익률(%)")
            st.plotly_chart(fig_sc, use_container_width=True)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 최고/최저 종목
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    st.divider()
    col_best, col_worst = st.columns(2)

    with col_best:
        st.subheader("🏆 수익률 TOP 5")
        top = df_ret.nlargest(5, "수익률(%)")
        for _, r in top.iterrows():
            st.markdown(
                f"**{r['종목명']}** ({r['추천일']}) "
                f"— {int(r['순위'])}위 · :red[**{r['수익률(%)']:+.2f}%**]"
            )

    with col_worst:
        st.subheader("💀 수익률 WORST 5")
        bottom = df_ret.nsmallest(5, "수익률(%)")
        for _, r in bottom.iterrows():
            st.markdown(
                f"**{r['종목명']}** ({r['추천일']}) "
                f"— {int(r['순위'])}위 · :blue[**{r['수익률(%)']:+.2f}%**]"
            )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 전체 기록 테이블
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    st.divider()
    st.subheader("📋 전체 기록")
    display_df = df_ret.sort_values(["추천일", "순위"], ascending=[False, True]).copy()
    display_df["결과"] = display_df["수익률(%)"].apply(
        lambda x: "✅ 승" if x > 0 else ("❌ 패" if x < 0 else "➖ 무")
    )
    st.dataframe(display_df, use_container_width=True, hide_index=True)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 날짜별 TOP5 + 익일수익률
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    st.divider()
    st.subheader("📅 날짜별 TOP5 추천")
    top5_rows = []
    for d in dates:
        data = logs[d]
        if data.get("skipped"):
            continue
        for s in data.get("top5", []):
            row = {
                "날짜": d,
                "순위": s.get("rank", 0),
                "종목명": s.get("name", ""),
                "코드": s.get("code", ""),
                "업종": s.get("sector", ""),
                "점수": s.get("score", 0),
                "현재가": s.get("price", 0),
                "등락률(%)": round(s.get("change_rate", 0), 1),
                "CCI": round(s.get("cci", 0), 0),
                "이격도(%)": s.get("ma20_gap", 0),
            }
            # 수익률 매칭
            idx = dates.index(d)
            if idx + 1 < len(dates):
                next_date = dates[idx + 1]
                for ret in logs[next_date].get("prev_returns", []):
                    if ret.get("code") == s.get("code"):
                        row["익일수익률(%)"] = ret.get("return_pct", "")
                        break
            if "익일수익률(%)" not in row:
                row["익일수익률(%)"] = ""
            top5_rows.append(row)

    if top5_rows:
        df_top5 = pd.DataFrame(top5_rows)
        date_filter = st.selectbox(
            "날짜 필터", ["전체"] + dates[::-1], key="top5_date_filter"
        )
        if date_filter != "전체":
            df_top5 = df_top5[df_top5["날짜"] == date_filter]
        st.dataframe(df_top5.sort_values(["날짜", "순위"], ascending=[False, True]),
                     use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════
# ⚙️ 시스템
# ══════════════════════════════════════════════
elif page == "⚙️ 시스템":
    st.title("⚙️ 시스템 현황")

    c1, c2, c3 = st.columns(3)
    c1.metric("총 로그", f"{len(dates)}일")
    c2.metric("최초", dates[0])
    c3.metric("최신", dates[-1])

    # 유니버스 추이
    uni = [{"날짜": d, "종목수": logs[d].get("universe_count", 0)}
           for d in dates if not logs[d].get("skipped")]
    if uni:
        st.subheader("📊 유니버스 추이")
        df_u = pd.DataFrame(uni)
        fig = go.Figure(go.Scatter(
            x=df_u["날짜"], y=df_u["종목수"],
            mode="lines+markers", line=dict(color="#00B894", width=2),
        ))
        fig.update_layout(height=250, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("🔧 점수 배점 (100점)")
    st.dataframe(pd.DataFrame([
        {"지표": "CCI(14)", "배점": 30, "최적": "160~180", "근거": "50.4% 승률"},
        {"지표": "MA20 이격도", "배점": 25, "최적": "2~8%", "근거": "추세 위 적정 거리"},
        {"지표": "등락률", "배점": 20, "최적": "2~8%", "근거": "스윗스팟"},
        {"지표": "CCI 기울기", "배점": 15, "최적": "3일↑", "근거": "모멘텀"},
        {"지표": "MA20 기울기", "배점": 10, "최적": "3일↑", "근거": "중기 추세"},
    ]), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("🚫 제외 필터")
    st.markdown(
        "SPAC · ETF · ETN · 우선주 · 리츠 · 인프라 · "
        "나스닥 -2% · 가격 3,000~150,000원 · 이격도 ±20% 초과"
    )
    st.caption(f"ClosingBell v2 | {dates[-1]}")