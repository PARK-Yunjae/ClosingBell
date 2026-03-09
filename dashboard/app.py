"""
ClosingBell v3.5 — Streamlit 대시보드
=======================================
1) 🎯 매수 후보 (워치리스트 기반 확신도 순위)
2) 👁️ 워치리스트 현황 (감시 종목 + 타이밍 가이드)
3) 📈 성과 추적 (순위별 × 기간별 승률 매트릭스)
4) 📋 스크리닝 로그 (일별 TOP3 + 유니버스)
5) 🔥 주도테마
"""
import os
import sys
import json
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from pathlib import Path
from datetime import datetime, timedelta

os.environ.setdefault("DASHBOARD_ONLY", "true")
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

LOG_DIR = project_root / "data" / "logs"
WATCHLIST_DIR = project_root / "data" / "watchlist"
PERF_DIR = project_root / "data" / "performance"
OHLCV_DIR = Path(os.getenv("DATA_DIR", "C:/Coding/data")) / "ohlcv"

st.set_page_config(page_title="ClosingBell v3.5", page_icon="🔔", layout="wide")


# ── 데이터 로드 ──
def load_logs() -> dict[str, dict]:
    logs = {}
    if not LOG_DIR.exists():
        return logs
    for f in sorted(LOG_DIR.glob("*.json")):
        try:
            logs[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return logs


def load_watchlists() -> list[dict]:
    if not WATCHLIST_DIR.exists():
        return []
    result = []
    for f in sorted(WATCHLIST_DIR.glob("*.json"), reverse=True):
        try:
            result.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return result


def load_performance() -> dict:
    path = PERF_DIR / "tracking.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"records": []}


def trading_days_since(date_str: str) -> int:
    d = datetime.strptime(date_str, "%Y-%m-%d")
    today = datetime.now()
    count = 0
    cur = d + timedelta(days=1)
    while cur.date() <= today.date():
        if cur.weekday() < 5:
            count += 1
        cur += timedelta(days=1)
    return count


# ── 사이드바 ──
logs = load_logs()
dates = sorted(logs.keys())

if not dates:
    st.warning("데이터 없음 — 스크리닝 실행 후 확인하세요")
    st.stop()

page = st.sidebar.radio("페이지", [
    "🎯 매수 후보",
    "👁️ 워치리스트",
    "📈 성과 추적",
    "📋 스크리닝 로그",
    "🔥 주도테마",
])

st.sidebar.markdown("---")
st.sidebar.markdown(f"**최신 로그:** {dates[-1]}")
st.sidebar.markdown(f"**데이터:** {len(dates)}일")


# ══════════════════════════════════════════
# 🎯 매수 후보 (워치리스트 기반)
# ══════════════════════════════════════════
if page == "🎯 매수 후보":
    st.title("🎯 매수 후보 — 확신도 순위")
    st.caption("매일 15시 디스코드로 발송되는 TOP3과 동일한 기준")

    watchlists = load_watchlists()
    today = datetime.now().strftime("%Y-%m-%d")

    # 활성 종목 수집
    active_stocks = []
    seen = set()
    for wl in watchlists:
        if wl.get("expires", "") < today:
            continue
        created = wl["created"]
        days = trading_days_since(created)
        if days < 1:
            continue
        for s in wl.get("stocks", []):
            code = s["code"]
            if code in seen:
                continue
            seen.add(code)
            s["_created"] = created
            s["_days"] = days
            active_stocks.append(s)

    if not active_stocks:
        st.info("활성 워치리스트 없음 — 스크리닝 실행 후 다음 날부터 표시됩니다")
    else:
        # 타이밍 기반 예상 점수
        RANK_TIMING = {
            1: {"sweet": 1, "window": (1, 2), "wr": 75, "ret": 3.9},
            2: {"sweet": 4, "window": (3, 5), "wr": 64, "ret": -0.6},
            3: {"sweet": 3, "window": (2, 4), "wr": 71, "ret": 8.0},
        }

        for s in active_stocks:
            rank = s.get("rank", 99)
            timing = RANK_TIMING.get(rank, RANK_TIMING.get(3, {}))
            sweet = timing.get("sweet", 3)
            w = timing.get("window", (1, 5))
            days = s["_days"]
            in_window = w[0] <= days <= w[1]
            diff = abs(days - sweet)

            score = 0
            if in_window and diff == 0:
                score += 30
            elif in_window and diff == 1:
                score += 22
            elif in_window:
                score += 15
            score += {1: 20, 3: 15, 4: 5, 5: 5}.get(rank, 0)

            s["_base_score"] = score
            s["_in_window"] = in_window
            s["_sweet"] = sweet
            s["_wr"] = timing.get("wr", 0)
            s["_ret"] = timing.get("ret", 0)

        active_stocks.sort(key=lambda x: x["_base_score"], reverse=True)

        for i, s in enumerate(active_stocks[:5]):
            score = s["_base_score"]
            grade = "A" if score >= 50 else ("B" if score >= 30 else "C")
            emoji = {"A": "🟢", "B": "🟡", "C": "⚪"}.get(grade)
            sweet_mark = " ★" if s["_days"] == s["_sweet"] and s["_in_window"] else ""
            window_mark = "감시중" if s["_in_window"] else "대기"

            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(
                    f"### {emoji} [{grade}] {s['_created'][5:]} #{s.get('rank','?')} "
                    f"**{s['name']}** ({score}점)")
                st.markdown(
                    f"스크리닝 {s.get('score', 0)}점 | "
                    f"D+{s['_days']}{sweet_mark} | {window_mark} | "
                    f"기대승률 {s['_wr']}% / {s['_ret']:+.1f}%")
            with col2:
                st.metric("원래가격", f"{s.get('entry_price', 0):,}원")


# ══════════════════════════════════════════
# 👁️ 워치리스트 현황
# ══════════════════════════════════════════
elif page == "👁️ 워치리스트":
    st.title("👁️ 워치리스트 현황")

    watchlists = load_watchlists()
    today = datetime.now().strftime("%Y-%m-%d")

    if not watchlists:
        st.info("워치리스트 없음")
    else:
        for wl in watchlists:
            created = wl["created"]
            expires = wl.get("expires", "")
            days = trading_days_since(created)
            is_active = expires >= today
            status = "✅ 활성" if is_active else "⌛ 만료"

            with st.expander(f"{status} {created} (D+{days}) — 만료: {expires}",
                             expanded=is_active):
                rows = []
                for s in wl.get("stocks", []):
                    triggered = s.get("triggered", False)
                    rows.append({
                        "순위": f"#{s.get('rank', '?')}",
                        "종목": s.get("name", ""),
                        "점수": s.get("score", 0),
                        "sweet": f"D+{s.get('sweet_spot_day', '?')}",
                        "윈도우": f"D+{s.get('window_start', '?')}~{s.get('window_end', '?')}",
                        "트리거": "✅" if triggered else "⏳",
                        "확신도": s.get("conviction", "-"),
                    })
                st.dataframe(pd.DataFrame(rows), use_container_width=True,
                             hide_index=True)


# ══════════════════════════════════════════
# 📈 성과 추적
# ══════════════════════════════════════════
elif page == "📈 성과 추적":
    st.title("📈 성과 추적 — 순위별 × 기간별 승률")

    perf = load_performance()
    records = perf.get("records", [])

    if not records:
        st.info("성과 데이터 없음 — `python performance_tracker.py --rebuild` 실행")
    else:
        df = pd.DataFrame(records)
        st.metric("총 기록", f"{len(df)}건",
                  delta=f"{df['rec_date'].nunique()}일 추천")

        # 순위×기간 매트릭스
        st.subheader("순위별 승률 매트릭스")
        matrix_data = []
        for rank in sorted(df["rank"].unique()):
            row = {"순위": f"#{int(rank)}"}
            for day in range(1, 6):
                sub = df[(df["rank"] == rank) & (df["track_day"] == day)]
                if len(sub) > 0:
                    wr = sub["win"].mean() * 100
                    avg = sub["return_pct"].mean()
                    row[f"D+{day}"] = f"{wr:.0f}% / {avg:+.1f}%"
                else:
                    row[f"D+{day}"] = "-"
            matrix_data.append(row)

        st.dataframe(pd.DataFrame(matrix_data), use_container_width=True,
                     hide_index=True)

        # 기간별 전체 승률 차트
        st.subheader("기간별 승률 추이")
        day_stats = []
        for day in range(1, 6):
            sub = df[df["track_day"] == day]
            if len(sub) > 0:
                day_stats.append({
                    "D+": f"D+{day}",
                    "승률": round(sub["win"].mean() * 100, 1),
                    "평균수익": round(sub["return_pct"].mean(), 2),
                    "거래수": len(sub),
                })
        if day_stats:
            ddf = pd.DataFrame(day_stats)
            fig = go.Figure()
            fig.add_trace(go.Bar(x=ddf["D+"], y=ddf["승률"], name="승률(%)",
                                 marker_color=["#e74c3c" if v < 50 else "#00b894"
                                               for v in ddf["승률"]]))
            fig.add_trace(go.Scatter(x=ddf["D+"], y=ddf["평균수익"], name="평균수익(%)",
                                     yaxis="y2", line=dict(color="#3498db", width=3)))
            fig.update_layout(
                yaxis=dict(title="승률 (%)"),
                yaxis2=dict(title="평균수익 (%)", overlaying="y", side="right"),
                height=400, template="plotly_dark",
            )
            st.plotly_chart(fig, use_container_width=True)

            st.caption("D+1 즉시매수 승률 42% → D+2~3 눌림목 진입 시 60~75%")

        # 최고/최저
        if len(df) > 0:
            best = df.loc[df["return_pct"].idxmax()]
            worst = df.loc[df["return_pct"].idxmin()]
            c1, c2 = st.columns(2)
            c1.success(f"🏆 최고: {best['name']} ({best['rec_date']} "
                       f"D+{best['track_day']}) **{best['return_pct']:+.1f}%**")
            c2.error(f"💀 최저: {worst['name']} ({worst['rec_date']} "
                     f"D+{worst['track_day']}) **{worst['return_pct']:+.1f}%**")


# ══════════════════════════════════════════
# 📋 스크리닝 로그
# ══════════════════════════════════════════
elif page == "📋 스크리닝 로그":
    st.title("📋 스크리닝 로그")

    selected_date = st.sidebar.selectbox("날짜 선택", dates[::-1])
    data = logs[selected_date]
    market = data.get("market", {})

    # 시장 현황
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("코스피", f"{market.get('kospi', 0):,.0f}",
              delta=f"{market.get('kospi_change', 0):+.1f}%")
    c2.metric("코스닥", f"{market.get('kosdaq', 0):,.0f}",
              delta=f"{market.get('kosdaq_change', 0):+.1f}%")
    c3.metric("나스닥", f"{market.get('nasdaq', 0):,.0f}",
              delta=f"{market.get('nasdaq_change', 0):+.1f}%")
    c4.metric("유니버스", f"{data.get('universe_count', 0)}종목")

    if data.get("skipped"):
        st.warning(f"스킵: {data.get('reason', '')}")
        st.stop()

    # TOP 카드
    st.subheader("TOP 종목")
    for s in data.get("top", []):
        medal = ["🥇", "🥈", "🥉"][s["rank"] - 1] if s["rank"] <= 3 else ""
        overheat = " 🔥과열" if s.get("overheat") else ""
        vol = f" | 거래량 ×{s['vol_ratio']:.1f}" if s.get("vol_ratio", 0) > 2 else ""

        st.markdown(f"**{medal} #{s['rank']} {s['name']}** ({s['sector']}) — "
                    f"**{s['score']}점**{overheat}")
        st.markdown(
            f"💰 {s['price']:,}원 ({s['change_rate']:+.1f}%) | "
            f"CCI {s['cci']:.0f} | RSI {s['rsi']:.0f} | "
            f"MA20 {s['ma20_gap']:+.1f}% | {s.get('vp_tag', '')}{vol}")

        if s.get("ai_summary"):
            st.caption(f"AI: {s['ai_action']} — {s['ai_summary']}")
        st.markdown("---")

    # 전체 유니버스 테이블
    st.subheader("유니버스 전체")
    all_scored = data.get("all_scored", [])
    if all_scored:
        tdf = pd.DataFrame(all_scored)
        cols = ["rank", "name", "sector", "price", "change_rate", "score",
                "cci", "rsi", "ma20_gap", "vp_tag", "ai_action"]
        show = [c for c in cols if c in tdf.columns]
        st.dataframe(tdf[show], use_container_width=True, hide_index=True)


# ══════════════════════════════════════════
# 🔥 주도테마
# ══════════════════════════════════════════
elif page == "🔥 주도테마":
    st.title("🔥 주도테마")

    selected_date = st.sidebar.selectbox("날짜 선택", dates[::-1])
    data = logs[selected_date]
    themes = data.get("theme_summary", [])

    if not themes:
        st.info("테마 데이터 없음")
    else:
        for t in themes:
            change = t.get("change_rate", 0)
            emoji = "🔥" if change > 2 else ("⚡" if change > 0 else "❄️")
            st.markdown(f"### {emoji} {t['name']} ({change:+.1f}%)")
            st.markdown(f"종목 {t.get('stock_count', 0)}개 | "
                        f"주요: {t.get('main_stock', '')}")


# ── 푸터 ──
st.sidebar.markdown("---")
st.sidebar.markdown("ClosingBell v3.5")
st.sidebar.markdown("[GitHub](https://github.com) | "
                    "[Streamlit Cloud](https://closingbell.streamlit.app)")
