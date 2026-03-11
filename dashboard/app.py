import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

os.environ.setdefault("DASHBOARD_ONLY", "true")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage import get_buy_picks, iter_buy_pick_outcomes, iter_notification_events, iter_screen_results, list_buy_pick_dates, list_watchlists as list_watchlists_db, load_backtest_dataset

LOG_DIR = ROOT / "data" / "logs"
WATCHLIST_DIR = ROOT / "data" / "watchlist"
PERF_DIR = ROOT / "data" / "performance"
OHLCV_DIR = Path(os.getenv("DATA_DIR", "C:/Coding/data")) / "ohlcv"
NAV = ["Overview", "Pick Vault", "Dispatch Log", "Watchlist Lab", "Performance Lab", "Screening Log", "Theme Radar"]
COLORS = {"navy": "#143A52", "teal": "#1E6F74", "mint": "#2A9D8F", "coral": "#E76F51", "gold": "#E9C46A", "bg": "#FFF9F1", "ink": "#16202A"}

st.set_page_config(page_title="ClosingBell", page_icon="CB", layout="wide", initial_sidebar_state="expanded")
st.markdown(
    f"""
    <style>
    .stApp {{background: radial-gradient(circle at top left, rgba(233,196,106,.18), transparent 22%), linear-gradient(180deg, #fffdf9, #f4ebdd);}}
    section[data-testid="stSidebar"] {{background: linear-gradient(180deg, #102A43, #143A52 60%, #1E6F74);}}
    section[data-testid="stSidebar"] * {{color: #f7f5ef !important;}}
    .block-container {{padding-top:1.5rem;padding-bottom:2.5rem;}}
    .hero {{padding:1.35rem 1.5rem;border-radius:24px;background:linear-gradient(135deg, rgba(20,58,82,.98), rgba(30,111,116,.92));color:#f8f4ed;box-shadow:0 20px 50px rgba(20,58,82,.16);margin-bottom:1rem;}}
    .hero h1 {{margin:0;font-size:2rem;}}
    .hero p {{margin:.55rem 0 0 0;color:rgba(248,244,237,.82);}}
    .pill {{display:inline-block;padding:.35rem .7rem;margin:.8rem .35rem 0 0;border-radius:999px;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.12);font-size:.84rem;}}
    .kicker {{display:inline-block;margin-bottom:.6rem;padding:.28rem .6rem;border-radius:999px;background:rgba(20,58,82,.08);color:{COLORS["navy"]};font-size:.78rem;font-weight:700;text-transform:uppercase;}}
    div[data-testid="stMetric"] {{background:rgba(255,255,255,.82);border:1px solid rgba(20,58,82,.08);border-radius:20px;padding:.7rem .9rem;box-shadow:0 10px 30px rgba(20,58,82,.06);}}
    .pick {{padding:1rem 1.1rem;background:rgba(255,255,255,.84);border:1px solid rgba(20,58,82,.08);border-radius:20px;box-shadow:0 8px 24px rgba(20,58,82,.06);margin-bottom:.8rem;}}
    .pick h4 {{margin:0 0 .35rem 0;color:{COLORS["ink"]};}}
    .pick .meta {{color:#5E6A75;font-size:.92rem;margin-bottom:.35rem;}}
    .pick .note {{color:{COLORS["ink"]};font-size:.95rem;line-height:1.45;}}
    </style>
    """,
    unsafe_allow_html=True,
)


def hero(title: str, subtitle: str, pills: list[str]) -> None:
    pills_html = "".join(f"<span class='pill'>{p}</span>" for p in pills)
    st.markdown(f"<div class='hero'><h1>{title}</h1><p>{subtitle}</p>{pills_html}</div>", unsafe_allow_html=True)


def kicker(text: str) -> None:
    st.markdown(f"<div class='kicker'>{text}</div>", unsafe_allow_html=True)


def fmt_date(v) -> str:
    if isinstance(v, pd.Timestamp):
        return "-" if pd.isna(v) else v.strftime("%Y-%m-%d")
    return str(v)[:10] if v is not None else "-"


def fmt_dt(v) -> str:
    if isinstance(v, pd.Timestamp):
        return "-" if pd.isna(v) else v.strftime("%Y-%m-%d %H:%M")
    return str(v)[:16] if v is not None else "-"


def fmt_pct(v) -> str:
    try:
        return f"{float(v):+.2f}%"
    except Exception:
        return "-"


def grade_color(g: str) -> str:
    return {"A": COLORS["coral"], "B": COLORS["gold"], "C": COLORS["mint"]}.get(str(g), COLORS["teal"])


@st.cache_data(show_spinner=False)
def load_logs() -> dict[str, dict]:
    logs = {}
    for item in iter_screen_results():
        if item and item.get("date"):
            logs[item["date"]] = item
    if logs:
        return logs
    for path in sorted(LOG_DIR.glob("*.json")):
        try:
            logs[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return logs


@st.cache_data(show_spinner=False)
def load_watchlists() -> list[dict]:
    rows = list_watchlists_db(desc=True)
    if rows:
        return rows
    out = []
    for path in sorted(WATCHLIST_DIR.glob("*.json"), reverse=True):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            pass
    return out


@st.cache_data(show_spinner=False)
def load_df(name: str, date_cols: tuple[str, ...]) -> pd.DataFrame:
    if name == "tracking":
        path = PERF_DIR / "tracking.json"
        data = json.loads(path.read_text(encoding="utf-8")).get("records", []) if path.exists() else []
    else:
        data = load_backtest_dataset(name) or []
    df = pd.DataFrame(data)
    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


@st.cache_data(show_spinner=False)
def load_saved_picks() -> pd.DataFrame:
    rows = []
    for pick_date in list_buy_pick_dates(desc=False):
        payload = get_buy_picks(pick_date) or {}
        for order, item in enumerate(payload.get("picks", []), start=1):
            rows.append({"pick_date": pick_date, "pick_order": order, **item})
    df = pd.DataFrame(rows)
    if "pick_date" in df.columns:
        df["pick_date"] = pd.to_datetime(df["pick_date"], errors="coerce")
    return df


@st.cache_data(show_spinner=False)
def load_live_pick_perf() -> pd.DataFrame:
    df = pd.DataFrame(iter_buy_pick_outcomes(desc=False))
    for col in ("pick_date", "signal_date", "track_date", "watchlist_date"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


@st.cache_data(show_spinner=False)
def load_notifications() -> pd.DataFrame:
    rows = []
    for item in iter_notification_events(desc=True):
        payload = item.get("payload", {}) or {}
        embeds = payload.get("embeds", []) or []
        first = embeds[0] if embeds else {}
        rows.append(
            {
                "event_id": item.get("event_id"),
                "event_type": item.get("event_type"),
                "ref_date": item.get("ref_date"),
                "sent_at": pd.to_datetime(item.get("sent_at"), errors="coerce"),
                "status": item.get("status"),
                "response_code": item.get("response_code"),
                "embed_count": len(embeds),
                "title": first.get("title", ""),
                "description": first.get("description", payload.get("content", "")),
                "content": payload.get("content", ""),
                "payload": payload,
            }
        )
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def load_ohlcv(code: str) -> pd.DataFrame:
    path = OHLCV_DIR / f"{str(code).zfill(6)}.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df.columns = [c.lower().strip() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


def trading_days_since(date_value) -> int:
    start = pd.to_datetime(date_value, errors="coerce")
    if pd.isna(start):
        return 0
    cur = start.to_pydatetime() + timedelta(days=1)
    today = datetime.now()
    days = 0
    while cur.date() <= today.date():
        if cur.weekday() < 5:
            days += 1
        cur += timedelta(days=1)
    return days


def active_watchlists(watchlists: list[dict]) -> tuple[list[dict], pd.DataFrame]:
    today = datetime.now().strftime("%Y-%m-%d")
    active, rows = [], []
    for wl in watchlists:
        stocks = wl.get("stocks", [])
        status = "active" if wl.get("expires", "") >= today else "expired"
        rows.append({"created": wl.get("created"), "expires": wl.get("expires"), "days_elapsed": trading_days_since(wl.get("created")), "stock_count": len(stocks), "triggered_count": sum(1 for x in stocks if x.get("triggered")), "status": status})
        if status == "active":
            active.append(wl)
    return active, pd.DataFrame(rows)


def day_profile_chart(df: pd.DataFrame, label: str = "留ㅼ닔?좏샇", bar_color: str = COLORS["navy"], line_color: str = COLORS["coral"]) -> go.Figure | None:
    if df.empty:
        return None
    grp = df.groupby("track_day").agg(win_rate=("win", "mean"), avg_ret=("return_pct", "mean")).reset_index()
    grp["win_rate"] *= 100
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=grp["track_day"], y=grp["win_rate"], name=f"{label} ?밸쪧", marker_color=bar_color), secondary_y=False)
    fig.add_trace(go.Scatter(x=grp["track_day"], y=grp["avg_ret"], name=f"{label} ?됯퇏?섏씡", line=dict(color=line_color, width=3)), secondary_y=True)
    fig.update_layout(height=340, margin=dict(l=8, r=8, t=16, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,.72)", font=dict(color=COLORS["ink"]), legend=dict(orientation="h", y=1.02, x=0))
    fig.update_xaxes(tickmode="array", tickvals=grp["track_day"], ticktext=[f"D+{int(x)}" for x in grp["track_day"]], showgrid=False)
    fig.update_yaxes(title_text="?밸쪧 (%)", secondary_y=False, gridcolor="rgba(20,58,82,.08)")
    fig.update_yaxes(title_text="?섏씡瑜?(%)", secondary_y=True, showgrid=False)
    return fig


def rolling_chart(df: pd.DataFrame, window: int = 20) -> go.Figure | None:
    day1 = df[df["track_day"] == 1].copy()
    if day1.empty:
        return None
    daily = day1.groupby("signal_date").agg(win_rate=("win", "mean"), avg_ret=("return_pct", "mean")).reset_index().sort_values("signal_date")
    daily["rolling_wr"] = daily["win_rate"].rolling(window, min_periods=5).mean() * 100
    daily["rolling_ret"] = daily["avg_ret"].rolling(window, min_periods=5).mean()
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=daily["signal_date"], y=daily["rolling_wr"], name=f"{window}??D+1 ?밸쪧", line=dict(color=COLORS["navy"], width=3)), secondary_y=False)
    fig.add_trace(go.Scatter(x=daily["signal_date"], y=daily["rolling_ret"], name=f"{window}??D+1 ?됯퇏?섏씡", line=dict(color=COLORS["coral"], width=2)), secondary_y=True)
    fig.update_layout(height=340, margin=dict(l=8, r=8, t=16, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,.72)", font=dict(color=COLORS["ink"]), legend=dict(orientation="h", y=1.02, x=0))
    fig.update_yaxes(title_text="?밸쪧 (%)", secondary_y=False, gridcolor="rgba(20,58,82,.08)")
    fig.update_yaxes(title_text="?섏씡瑜?(%)", secondary_y=True, showgrid=False)
    return fig


def heatmap(df: pd.DataFrame) -> go.Figure | None:
    if df.empty:
        return None
    pivot = df.pivot_table(index="rank", columns="track_day", values="return_pct", aggfunc="mean").sort_index()
    if pivot.empty:
        return None
    fig = go.Figure(go.Heatmap(z=pivot.values, x=[f"D+{int(x)}" for x in pivot.columns], y=[f"#{int(x)}" for x in pivot.index], colorscale=[[0, "#0B3C49"], [.45, "#F6F4EF"], [1, "#E76F51"]], zmid=0, colorbar=dict(title="?됯퇏?섏씡")))
    fig.update_layout(height=340, margin=dict(l=8, r=8, t=16, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,.72)", font=dict(color=COLORS["ink"]))
    return fig


def conviction_scatter(signals: pd.DataFrame, perf: pd.DataFrame) -> go.Figure | None:
    day1 = perf[perf["track_day"] == 1].copy()
    if signals.empty or day1.empty:
        return None
    left = signals.copy()
    date_col = next((col for col in ("check_date", "pick_date", "signal_date") if col in left.columns), None)
    if not date_col:
        return None
    left["check_key"] = left[date_col].dt.strftime("%Y-%m-%d")
    signal_col = "pick_date" if "pick_date" in day1.columns else "signal_date"
    day1["signal_key"] = day1[signal_col].dt.strftime("%Y-%m-%d")
    merged = day1.merge(left[["code", "rank", "check_key", "conviction", "conviction_score", "signal_type"]], left_on=["code", "rank", "signal_key"], right_on=["code", "rank", "check_key"], how="left")
    if merged.empty:
        return None
    fig = go.Figure()
    for grade in ("A", "B", "C"):
        sub = merged[merged["conviction"] == grade]
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(x=sub["conviction_score"], y=sub["high_ret"] if "high_ret" in sub.columns else sub["return_pct"], mode="markers", name=f"{grade} grade", marker=dict(size=9, color=grade_color(grade), opacity=.75, line=dict(color="#fff", width=.8)), text=sub["signal_type"].fillna("base"), hovertemplate="score %{x}<br>return %{y:.2f}%<br>%{text}<extra></extra>"))
    fig.update_layout(height=360, margin=dict(l=8, r=8, t=16, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,.72)", font=dict(color=COLORS["ink"]), legend=dict(orientation="h", y=1.02, x=0))
    fig.update_xaxes(title="Conviction Score", gridcolor="rgba(20,58,82,.08)")
    fig.update_yaxes(title="D+1 High Return" if "high_ret" in merged.columns else "D+1 Close Return", gridcolor="rgba(20,58,82,.08)")
    return fig


def price_chart(code: str, signal_date, watchlist_date=None) -> go.Figure | None:
    df = load_ohlcv(code)
    anchor = pd.to_datetime(signal_date, errors="coerce")
    if df.empty or pd.isna(anchor):
        return None
    idxs = df.index[df["date"] <= anchor]
    if len(idxs) == 0:
        return None
    i = int(idxs[-1]); win = df.iloc[max(0, i - 35): min(len(df), i + 11)].copy()
    fig = go.Figure(go.Candlestick(x=win["date"], open=win["open"], high=win["high"], low=win["low"], close=win["close"], increasing_line_color=COLORS["coral"], decreasing_line_color=COLORS["teal"], increasing_fillcolor=COLORS["coral"], decreasing_fillcolor=COLORS["teal"], name="OHLC"))
    for d, name, color in ((watchlist_date, "Watchlist", COLORS["gold"]), (signal_date, "Signal", COLORS["navy"])):
        dt = pd.to_datetime(d, errors="coerce")
        row = win.loc[win["date"] == dt]
        if pd.isna(dt) or row.empty:
            continue
        fig.add_trace(go.Scatter(x=row["date"], y=row["close"], mode="markers+text", text=[name], textposition="top center", marker=dict(size=11, color=color, line=dict(color="#fff", width=1.5)), name=name))
    fig.update_layout(height=420, margin=dict(l=8, r=8, t=24, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,.75)", font=dict(color=COLORS["ink"]), xaxis_rangeslider_visible=False, legend=dict(orientation="h", y=1.02, x=0))
    fig.update_xaxes(showgrid=False); fig.update_yaxes(gridcolor="rgba(20,58,82,.08)")
    return fig


def pick_timeline_chart(df: pd.DataFrame) -> go.Figure | None:
    if df.empty:
        return None
    work = df.sort_values("track_day").copy()
    fig = go.Figure()
    if "open_ret" in work.columns:
        fig.add_trace(go.Scatter(x=work["track_day"], y=work["open_ret"], mode="lines+markers", name="Open", line=dict(color=COLORS["gold"], width=2)))
    if "high_ret" in work.columns:
        fig.add_trace(go.Scatter(x=work["track_day"], y=work["high_ret"], mode="lines+markers", name="High", line=dict(color=COLORS["mint"], width=2)))
    fig.add_trace(go.Scatter(x=work["track_day"], y=work["return_pct"], mode="lines+markers", name="Close", line=dict(color=COLORS["coral"], width=3)))
    fig.add_hline(y=0, line_color="rgba(20,58,82,.25)", line_dash="dash")
    fig.update_layout(height=260, margin=dict(l=8, r=8, t=16, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,.72)", font=dict(color=COLORS["ink"]), legend=dict(orientation="h", y=1.02, x=0))
    fig.update_xaxes(tickmode="array", tickvals=work["track_day"], ticktext=[f"D+{int(x)}" for x in work["track_day"]], gridcolor="rgba(20,58,82,.08)")
    fig.update_yaxes(title="Return %", gridcolor="rgba(20,58,82,.08)")
    return fig


logs = load_logs()
if not logs:
    st.warning("?ㅽ겕由щ떇 濡쒓렇媛 ?놁뒿?덈떎. 癒쇱? ??醫낅즺 ?ㅽ겕由щ떇???ㅽ뻾?섏꽭??")
    st.stop()
watchlists = load_watchlists()
signals = load_df("buy_signals", ("watchlist_date", "check_date"))
buy_perf = load_df("buy_performance_v2", ("signal_date", "track_date"))
if buy_perf.empty:
    buy_perf = load_df("buy_performance", ("signal_date", "track_date"))
screen_perf = load_df("tracking", ("rec_date", "track_date"))
saved_picks = load_saved_picks()
live_pick_perf = load_live_pick_perf()
notifications = load_notifications()
active_wls, wl_summary = active_watchlists(watchlists)
latest_date = max(logs)
latest_log = logs[latest_date]
source = "saved" if not saved_picks.empty else ("archive" if not signals.empty else "empty")
available_dates = sorted((saved_picks["pick_date"].dropna().dt.strftime("%Y-%m-%d").unique() if source == "saved" else signals["check_date"].dropna().dt.strftime("%Y-%m-%d").unique()), reverse=True) if source != "empty" else []
perf_view = live_pick_perf if not live_pick_perf.empty else buy_perf
perf_mode = "Live Saved Picks" if not live_pick_perf.empty else "Backtest Signal Archive"

st.sidebar.title("ClosingBell")
st.sidebar.caption("signal archive and live picks")
page = st.sidebar.radio("Workspace", NAV, index=0)
st.sidebar.markdown("---")
st.sidebar.markdown(f"**Latest screen:** `{latest_date}`")
st.sidebar.markdown(f"**Active watchlists:** `{len(active_wls)}`")
st.sidebar.markdown(f"**Signal dates:** `{len(available_dates)}`")
st.sidebar.markdown(f"**Saved pick dates:** `{saved_picks['pick_date'].nunique() if not saved_picks.empty else 0}`")
st.sidebar.markdown(f"**Dispatch events:** `{len(notifications):,}`")

if page == "Overview":
    d1 = perf_view[perf_view["track_day"] == 1] if not perf_view.empty else pd.DataFrame()
    d3 = perf_view[perf_view["track_day"] == 3] if not perf_view.empty else pd.DataFrame()
    hero("ClosingBell Overview", "Screening, watchlists, and buy-pick performance in one place.", [f"Latest log {latest_date}", f"Active watchlists {len(active_wls)}", f"Signal archive {len(signals)}", perf_mode])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Active Watchlists", len(active_wls))
    c2.metric("Backtest Signals", f"{len(signals):,}")
    c3.metric("D+1 Close WR", f"{d1['win'].mean() * 100:.1f}%" if not d1.empty else "-", delta=f"{d1['return_pct'].mean():+.2f}%" if not d1.empty else None)
    c4.metric("D+3 Avg Return", f"{d3['return_pct'].mean():+.2f}%" if not d3.empty else "-", delta=f"{len(live_pick_perf):,} live rows" if not live_pick_perf.empty else (f"{len(saved_picks):,} saved rows" if not saved_picks.empty else "saved picks pending"))
    l, r = st.columns([1.15, 1])
    with l:
        kicker("Flow")
        fig = day_profile_chart(perf_view)
        if fig:
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    with r:
        kicker("Rolling D+1")
        fig = rolling_chart(perf_view, 20)
        if fig:
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    l2, r2 = st.columns(2)
    with l2:
        kicker("Latest Top Rank")
        top_df = pd.DataFrame(latest_log.get("top", []))
        if not top_df.empty:
            cols = [c for c in ["rank", "name", "sector", "price", "change_rate", "score", "cci", "rsi"] if c in top_df.columns]
            st.dataframe(top_df[cols], width="stretch", hide_index=True)
    with r2:
        kicker("Conviction Mix")
        counts = signals["conviction"].value_counts() if not signals.empty else pd.Series(dtype=int)
        if not counts.empty:
            fig = go.Figure(go.Bar(x=counts.index.tolist(), y=counts.values.tolist(), marker_color=[grade_color(x) for x in counts.index.tolist()]))
            fig.update_layout(height=320, margin=dict(l=8, r=8, t=16, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,.72)", font=dict(color=COLORS["ink"]))
            fig.update_yaxes(gridcolor="rgba(20,58,82,.08)")
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

elif page == "Pick Vault":
    mode = "Saved Picks" if source == "saved" else "Backtest Signal Archive"
    hero("Pick Vault", "Saved picks are shown first. If none exist yet, the dashboard falls back to the backtest signal archive.", [mode, f"Available dates {len(available_dates)}", "Using archive" if source != "saved" else "Using saved picks"])
    if source == "empty":
        st.info("No pick data available.")
    else:
        selected = st.sidebar.selectbox("Pick Date", available_dates, key="pick_date")
        if source == "saved":
            day_rows = saved_picks[saved_picks["pick_date"].dt.strftime("%Y-%m-%d") == selected].sort_values(["pick_order", "conviction_score"], ascending=[True, False]).copy()
        else:
            day_rows = signals[(signals["check_date"].dt.strftime("%Y-%m-%d") == selected) & (signals["conviction"].isin(["A", "B"]))].sort_values(["conviction_score", "rank", "days_elapsed"], ascending=[False, True, True]).head(8).copy()
        left, right = st.columns([.95, 1.05])
        with left:
            kicker("Daily Cards")
            if source != "saved":
                st.warning("Saved pick history is still empty. Showing the signal archive instead.")
            if day_rows.empty:
                st.info("No rows for the selected date.")
            for _, row in day_rows.iterrows():
                grade = str(row.get("conviction", "C"))
                signal_type = row.get("signal_type", "") or "base signal"
                price = row.get("current_price", row.get("buy_price", 0))
                risk = row.get("risk_flags", [])
                risk_text = ", ".join(risk) if isinstance(risk, list) and risk else "no special risk"
                card_html = (
                    f"<div class='pick'>"
                    f"<h4>{row.get('name', row.get('code', ''))} <span style='color:{grade_color(grade)}'>[{grade}]</span> #{row.get('rank', '-')}</h4>"
                    f"<div class='meta'>{mode} | conviction {row.get('conviction_score', 0)} | D+{int(row.get('days_elapsed', 0) or 0)}</div>"
                    f"<div class='note'>{signal_type}<br/>DART {row.get('dart_risk', 'unknown')} · AI {row.get('ai_action', 'unknown')} · price {int(price):,}</div>"
                    f"<div class='meta' style='margin-top:.45rem;'>risk: {risk_text}</div>"
                    f"</div>"
                )
                st.markdown(card_html, unsafe_allow_html=True)
        with right:
            kicker("Detail Chart")
            if day_rows.empty:
                st.info("No detail chart available.")
            else:
                labels = day_rows.apply(lambda row: f"{row.get('name', row.get('code', ''))} | #{row.get('rank', '-')} | {row.get('conviction', '-')} | {int(row.get('conviction_score', 0) or 0)} pts", axis=1).tolist()
                idx = st.selectbox("Detail Symbol", range(len(labels)), format_func=lambda i: labels[i], key="detail_idx")
                row = day_rows.iloc[int(idx)]
                fig = price_chart(str(row.get("code", "")), row.get("check_date", row.get("pick_date")), row.get("watchlist_date"))
                if fig:
                    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
                perf_rows = pd.DataFrame()
                key_date = fmt_date(row.get("check_date") or row.get("signal_date") or row.get("pick_date"))
                code = str(row.get("code", "")).zfill(6)
                if source == "saved" and not live_pick_perf.empty:
                    perf_rows = live_pick_perf[(live_pick_perf["pick_date"].dt.strftime("%Y-%m-%d") == key_date) & (live_pick_perf["code"].astype(str).str.zfill(6) == code)].sort_values("track_day").copy()
                elif not buy_perf.empty:
                    perf_rows = buy_perf[(buy_perf["signal_date"].dt.strftime("%Y-%m-%d") == key_date) & (buy_perf["code"].astype(str).str.zfill(6) == code)].sort_values("track_day").copy()
                if not perf_rows.empty:
                    timeline = pick_timeline_chart(perf_rows)
                    if timeline is not None:
                        st.plotly_chart(timeline, width="stretch", config={"displayModeBar": False})
                    perf_rows["Bucket"] = perf_rows["track_day"].apply(lambda x: f"D+{int(x)}")
                    cols = ["Bucket", "track_date", "return_pct"] + [c for c in ("open_ret", "high_ret", "low_ret") if c in perf_rows.columns]
                    st.dataframe(perf_rows[cols].rename(columns={"track_date": "Track Date", "return_pct": "Close Return", "open_ret": "Open Return", "high_ret": "High Return", "low_ret": "Low Return"}), width="stretch", hide_index=True)
                elif source == "saved":
                    st.info("Live outcome rows will appear after OHLCV tracking runs for the next trading days.")
                if source == "saved" and not notifications.empty:
                    matched = notifications[notifications["ref_date"] == key_date].head(3).copy()
                    if not matched.empty:
                        kicker("Dispatch Snapshot")
                        for _, event in matched.iterrows():
                            desc = str(event.get("description", "") or event.get("content", "") or "").replace("\n", "<br/>")
                            card_html = (
                                f"<div class='pick'>"
                                f"<h4>{event.get('title', event.get('event_type', 'dispatch'))}</h4>"
                                f"<div class='meta'>{event.get('event_type', 'event')} | {event.get('status', '-')}"
                                f" | {fmt_dt(event.get('sent_at'))}</div>"
                                f"<div class='note'>{desc[:480]}</div>"
                                f"</div>"
                            )
                            st.markdown(card_html, unsafe_allow_html=True)
        kicker("History Table")
        if not day_rows.empty:
            date_col = "pick_date" if source == "saved" else "check_date"
            day_rows[date_col] = day_rows[date_col].apply(fmt_date)
            cols = [c for c in [date_col, "name", "code", "rank", "conviction", "conviction_score", "days_elapsed", "signal_type", "dart_risk", "ai_action", "current_price", "buy_price"] if c in day_rows.columns]
            st.dataframe(day_rows[cols].rename(columns={date_col: "Date", "name": "Name", "code": "Code", "rank": "Rank", "conviction": "Grade", "conviction_score": "Conviction", "days_elapsed": "D+Elapsed", "signal_type": "Signal", "dart_risk": "DART", "ai_action": "AI", "current_price": "Price", "buy_price": "Base Price"}), width="stretch", hide_index=True)

elif page == "Dispatch Log":
    hero("Dispatch Log", "Review webhook delivery history and inspect the exact embeds sent to Discord.", [f"Events {len(notifications):,}", "Stored in SQLite", "Sent / failed / disabled"])
    if notifications.empty:
        st.info("No notification events have been recorded yet.")
    else:
        left, right = st.columns([.88, 1.12])
        with left:
            kicker("Recent Events")
            show = notifications.copy()
            show["sent_at"] = show["sent_at"].apply(fmt_dt)
            cols = [c for c in ["sent_at", "event_type", "ref_date", "status", "response_code", "embed_count", "title"] if c in show.columns]
            st.dataframe(show[cols].rename(columns={"sent_at": "Sent At", "event_type": "Event", "ref_date": "Ref Date", "status": "Status", "response_code": "HTTP", "embed_count": "Embeds", "title": "Title"}), width="stretch", hide_index=True)
        with right:
            kicker("Event Detail")
            labels = notifications.apply(lambda row: f"{fmt_dt(row.get('sent_at'))} | {row.get('event_type', 'event')} | {row.get('status', '-')}", axis=1).tolist()
            idx = st.selectbox("Dispatch Event", range(len(labels)), format_func=lambda i: labels[i], key="dispatch_event")
            event = notifications.iloc[int(idx)]
            payload = event.get("payload", {}) or {}
            embeds = payload.get("embeds", []) or []
            st.markdown(f"**Status:** `{event.get('status', '-')}`")
            st.markdown(f"**Event Type:** `{event.get('event_type', '-')}`")
            st.markdown(f"**Ref Date:** `{event.get('ref_date', '-')}`")
            st.markdown(f"**HTTP:** `{event.get('response_code', '-')}`")
            if payload.get("content"):
                st.code(payload.get("content", ""), language="markdown")
            for embed in embeds[:5]:
                title = embed.get("title", "embed")
                desc = embed.get("description", "")
                st.markdown(f"### {title}")
                if desc:
                    st.markdown(desc)
                fields = embed.get("fields", []) or []
                if fields:
                    field_rows = [{"Field": f.get("name", ""), "Value": f.get("value", ""), "Inline": f.get("inline", False)} for f in fields]
                    st.dataframe(pd.DataFrame(field_rows), width="stretch", hide_index=True)

elif page == "Watchlist Lab":
    avg_text = f"Avg stock count {wl_summary['stock_count'].mean():.1f}" if not wl_summary.empty else "Avg stock count -"
    hero("Watchlist Lab", "Inspect watchlist lifecycle, duration, stock count, and trigger status.", [f"Total watchlists {len(watchlists)}", f"Active {len(active_wls)}", avg_text])
    if wl_summary.empty:
        st.info("No watchlists available.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Active", int((wl_summary["status"] == "active").sum()))
        c2.metric("Expired", int((wl_summary["status"] == "expired").sum()))
        c3.metric("Triggered", int(wl_summary["triggered_count"].sum()))
        c4.metric("Avg Duration", f"{wl_summary['days_elapsed'].mean():.1f}d")
        l, r = st.columns([.92, 1.08])
        with l:
            kicker("Lifecycle")
            show = wl_summary.sort_values("created", ascending=False).head(40).rename(columns={"created": "Created", "expires": "Expires", "days_elapsed": "Days", "stock_count": "Stocks", "triggered_count": "Triggered", "status": "Status"})
            st.dataframe(show, width="stretch", hide_index=True)
        with r:
            kicker("Detail")
            dates = [wl.get("created", "") for wl in watchlists if wl.get("created")]
            selected = st.selectbox("Watchlist Date", dates, key="wl_date")
            payload = next((wl for wl in watchlists if wl.get("created") == selected), None)
            if payload:
                sdf = pd.DataFrame(payload.get("stocks", []))
                if not sdf.empty:
                    cols = [c for c in ["rank", "name", "score", "entry_price", "sweet_spot_day", "window_start", "window_end", "triggered", "trigger_date", "conviction"] if c in sdf.columns]
                    st.dataframe(sdf[cols].rename(columns={"rank": "Rank", "name": "Name", "score": "Screen Score", "entry_price": "Entry", "sweet_spot_day": "Sweet", "window_start": "Start", "window_end": "End", "triggered": "Triggered", "trigger_date": "Trigger Date", "conviction": "Grade"}), width="stretch", hide_index=True)

elif page == "Performance Lab":
    perf_text = f"{perf_mode} rows {len(perf_view):,}" if not perf_view.empty else f"{perf_mode} rows 0"
    screen_text = f"Screen rows {len(screen_perf):,}" if not screen_perf.empty else "Screen rows 0"
    hero("Performance Lab", "Live saved-pick outcomes are shown first. Backtest remains the fallback benchmark.", [perf_text, screen_text, "D+1 to D+5 close/open/high"])
    if perf_view.empty:
        st.info("No buy-signal performance data available.")
    else:
        d1 = perf_view[perf_view["track_day"] == 1]
        d3 = perf_view[perf_view["track_day"] == 3]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("D+1 Close WR", f"{d1['win'].mean() * 100:.1f}%")
        c2.metric("D+1 Open Avg", fmt_pct(d1["open_ret"].mean()) if "open_ret" in d1.columns else "-")
        c3.metric("D+1 High Avg", fmt_pct(d1["high_ret"].mean()) if "high_ret" in d1.columns else "-")
        c4.metric("D+3 Close Avg", fmt_pct(d3["return_pct"].mean()) if not d3.empty else "-")
        l, r = st.columns([1.05, .95])
        with l:
            kicker("Day Profile")
            fig = day_profile_chart(perf_view)
            if fig:
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        with r:
            kicker("Rank Heatmap")
            fig = heatmap(perf_view)
            if fig:
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        l2, r2 = st.columns([1.05, .95])
        with l2:
            kicker("Rolling D+1")
            fig = rolling_chart(perf_view, 20)
            if fig:
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        with r2:
            kicker("Screening Reference")
            fig = day_profile_chart(screen_perf, "Screening", COLORS["gold"], COLORS["navy"])
            if fig:
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        kicker("Conviction Scatter")
        scatter_base = saved_picks if not live_pick_perf.empty and not saved_picks.empty else signals
        fig = conviction_scatter(scatter_base, perf_view)
        if fig:
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

elif page == "Screening Log":
    hero("Screening Log", "Inspect market state and scoring output by date. Logs are loaded from SQLite first.", [f"Latest {latest_date}", f"Universe {latest_log.get('universe_count', 0)}", f"Top {len(latest_log.get('top', []))}"])
    selected = st.sidebar.selectbox("Log Date", sorted(logs.keys(), reverse=True), key="screen_log")
    payload = logs[selected]
    market = payload.get("market", {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("KOSPI", f"{market.get('kospi', 0):,.0f}", delta=f"{market.get('kospi_change', 0):+.2f}%")
    c2.metric("KOSDAQ", f"{market.get('kosdaq', 0):,.0f}", delta=f"{market.get('kosdaq_change', 0):+.2f}%")
    c3.metric("NASDAQ", f"{market.get('nasdaq', 0):,.0f}", delta=f"{market.get('nasdaq_change', 0):+.2f}%")
    c4.metric("Universe", f"{payload.get('universe_count', 0)}", delta=f"overheat {payload.get('overheat_count', 0)}")
    if payload.get("skipped"):
        st.warning(payload.get("reason", "Skipped log."))
    else:
        l, r = st.columns([.94, 1.06])
        with l:
            kicker("Top Picks")
            for _, row in pd.DataFrame(payload.get("top", [])).iterrows():
                card = (
                    f"<div class='pick'><h4>#{int(row.get('rank', 0))} {row.get('name', row.get('code', ''))}</h4>"
                    f"<div class='meta'>{row.get('sector', 'unknown sector')} | score {row.get('score', 0)} | price {int(row.get('price', 0)):,}</div>"
                    f"<div class='note'>CCI {row.get('cci', 0):.0f} · RSI {row.get('rsi', 0):.0f} · MA20 {row.get('ma20_gap', 0):+.1f}%<br/>"
                    f"volume {row.get('vol_ratio', 0):.1f}x · AI {row.get('ai_action', 'unknown')}</div></div>"
                )
                st.markdown(card, unsafe_allow_html=True)
        with r:
            kicker("Universe Table")
            udf = pd.DataFrame(payload.get("all_scored", []))
            if not udf.empty:
                cols = [c for c in ["rank", "name", "sector", "price", "change_rate", "score", "cci", "rsi", "ma20_gap", "vol_ratio", "vp_tag", "dart_risk", "ai_action"] if c in udf.columns]
                st.dataframe(udf[cols], width="stretch", hide_index=True)

elif page == "Theme Radar":
    hero("Theme Radar", "Review theme snapshots and related names by date.", [f"Theme dates {len(logs)}", "theme_summary source"])
    selected = st.sidebar.selectbox("Theme Date", sorted(logs.keys(), reverse=True), key="theme_date")
    themes = logs[selected].get("theme_summary", [])
    if not themes:
        st.info("No theme data for the selected date.")
    else:
        df = pd.DataFrame(themes)
        l, r = st.columns([1.05, .95])
        with l:
            kicker("Theme Table")
            cols = [c for c in ["name", "change_rate", "stock_count", "main_stock"] if c in df.columns]
            st.dataframe(df[cols], width="stretch", hide_index=True)
        with r:
            kicker("Theme Momentum")
            changes = df["change_rate"] if "change_rate" in df.columns else pd.Series([0] * len(df))
            names = df["name"] if "name" in df.columns else pd.Series([""] * len(df))
            fig = go.Figure(go.Bar(x=changes, y=names, orientation="h", marker_color=[COLORS["coral"] if x >= 0 else COLORS["teal"] for x in changes]))
            fig.update_layout(height=360, margin=dict(l=8, r=8, t=16, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,.72)", font=dict(color=COLORS["ink"]))
            fig.update_xaxes(title="Change (%)", gridcolor="rgba(20,58,82,.08)")
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

st.sidebar.markdown("---")
st.sidebar.caption("Dashboard refreshed from runtime SQLite")
