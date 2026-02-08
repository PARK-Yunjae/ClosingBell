"""눌림목(거감음봉) 스캐너 대시보드 - ClosingBell v9.1

거래량 폭발 감시 → 눌림목 시그널 모니터링 + 캔들차트
"""

import os
import sys
import streamlit as st
from datetime import date, datetime, timedelta

# ── 경로 설정 ──
_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)

from dashboard.components.sidebar import render_sidebar_nav

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

# ── 페이지 설정 ──
st.set_page_config(page_title="눌림목 스캐너", page_icon="📉", layout="wide")

with st.sidebar:
    render_sidebar_nav()

st.title("📉 눌림목 스캐너")
st.caption("ClosingBell v10.1 | 거래량 폭발 후 거감음봉 + MA 지지 종목 감시")


# ============================================================
# 종목명 매핑 (stock_mapping.csv → FDR 폴백)
# ============================================================

@st.cache_data(ttl=86400)
def _load_names() -> dict:
    """종목코드 → 종목명 매핑"""
    names = {}

    # 1) stock_mapping.csv
    try:
        from src.config.app_config import MAPPING_FILE
        if MAPPING_FILE and MAPPING_FILE.exists():
            import csv
            with open(MAPPING_FILE, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    code = str(row.get("code", "")).strip().zfill(6)
                    name = row.get("name", "").strip()
                    if code and name:
                        names[code] = name
    except Exception:
        pass

    # 2) FDR 리스팅 (Streamlit Cloud 폴백)
    if len(names) < 100:
        try:
            import FinanceDataReader as fdr
            for market in ["KOSPI", "KOSDAQ"]:
                listing = fdr.StockListing(market)
                if listing is not None and not listing.empty:
                    for _, row in listing.iterrows():
                        code = str(row.get("Code", "")).strip().zfill(6)
                        name = str(row.get("Name", "")).strip()
                        if code and name and code not in names:
                            names[code] = name
        except Exception:
            pass

    return names


def _name(code: str, db_name: str, names: dict) -> str:
    """종목명 해결: DB값 → 매핑 → 코드 그대로"""
    if db_name and db_name != code and not db_name.isdigit():
        return db_name
    return names.get(code, code)


# ============================================================
# FDR OHLCV + 미니 캔들차트
# ============================================================

@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_ohlcv(code: str, days: int = 60):
    """OHLCV 조회: 로컬 CSV → FDR 폴백"""
    if pd is None:
        return None

    # 1) 로컬 CSV
    try:
        from src.config.app_config import OHLCV_DIR, OHLCV_FULL_DIR
        from pathlib import Path
        for d in [OHLCV_DIR, OHLCV_FULL_DIR]:
            if d:
                for fname in [f"{code}.csv", f"A{code}.csv"]:
                    p = Path(d) / fname
                    if p.exists():
                        from src.services.backfill.data_loader import load_single_ohlcv
                        df = load_single_ohlcv(p)
                        if df is not None and not df.empty:
                            return df.tail(days)
    except Exception:
        pass

    # 2) FDR (Cloud)
    try:
        import FinanceDataReader as fdr
        end = datetime.now().date()
        start = end - timedelta(days=days * 2)
        df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if df is not None and not df.empty:
            df = df.reset_index()
            df.columns = [c.lower() for c in df.columns]
            if "date" not in df.columns:
                df = df.rename(columns={"index": "date"})
            return df.tail(days)
    except Exception:
        pass

    return None


def _draw_mini_chart(code: str, spike_date: str = "", signal_date: str = ""):
    """종목별 미니 캔들차트 (60일) + 폭발일/시그널일 마커"""
    if not HAS_PLOTLY or pd is None:
        return

    df = _fetch_ohlcv(code, 60)
    if df is None or len(df) < 5:
        st.caption("📊 차트 데이터 없음")
        return

    df["date"] = pd.to_datetime(df["date"])
    view = df.copy()

    # 비정상 봉 처리
    if len(view) > 1:
        prev_close = view["close"].shift(1)
        spread = (view["high"] - view["low"]).abs()
        abnormal = (spread / prev_close.clip(lower=1)) > 0.30
        view.loc[abnormal, "open"] = view.loc[abnormal, "close"]
        view.loc[abnormal, "high"] = view.loc[abnormal, "close"]
        view.loc[abnormal, "low"] = view.loc[abnormal, "close"]

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.7, 0.3], vertical_spacing=0.06,
    )

    # 캔들스틱
    fig.add_trace(go.Candlestick(
        x=view["date"], open=view["open"],
        high=view["high"], low=view["low"], close=view["close"],
        name="주가",
        increasing_line_color="#e74c3c",
        decreasing_line_color="#3498db",
    ), row=1, col=1)

    # 5일선, 20일선
    for ma_days, color, label in [(5, "#ff9800", "5일선"), (20, "#2196f3", "20일선")]:
        if len(view) >= ma_days:
            ma = view["close"].rolling(ma_days).mean()
            fig.add_trace(go.Scatter(
                x=view["date"], y=ma,
                mode="lines", name=label,
                line=dict(color=color, width=1),
            ), row=1, col=1)

    # 거래량
    colors = ["#e74c3c" if c >= o else "#3498db"
              for c, o in zip(view["close"], view["open"])]
    fig.add_trace(go.Bar(
        x=view["date"], y=view["volume"],
        name="거래량", marker_color=colors,
    ), row=2, col=1)

    # 폭발일 / 시그널일 세로선
    for d_str, label, clr in [
        (spike_date, "🔥폭발", "red"),
        (signal_date, "📉시그널", "orange"),
    ]:
        if d_str:
            try:
                dt = pd.to_datetime(d_str)
                if dt >= view["date"].min() and dt <= view["date"].max():
                    fig.add_vline(
                        x=dt, line_dash="dot", line_color=clr,
                        annotation_text=label,
                        annotation_position="top left",
                    )
            except Exception:
                pass

    fig.update_layout(
        height=320,
        showlegend=False,
        xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=10, b=10),
    )
    fig.update_xaxes(dtick="M1", tickformat="%m/%d", row=2, col=1)
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])

    st.plotly_chart(fig, width="stretch")


# ============================================================
# Repository
# ============================================================

@st.cache_resource
def _get_repo():
    try:
        from src.infrastructure.database import get_database
        db = get_database()
        # 테이블 없으면 자동 생성
        try:
            db.run_migration_v91_pullback()
        except AttributeError:
            # database.py에 메서드 없으면 직접 생성
            db.execute("""CREATE TABLE IF NOT EXISTS volume_spikes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code TEXT NOT NULL, stock_name TEXT NOT NULL,
                spike_date DATE NOT NULL, spike_volume INTEGER NOT NULL,
                volume_ma20 INTEGER DEFAULT 0, spike_ratio REAL DEFAULT 0,
                open_price REAL DEFAULT 0, high_price REAL DEFAULT 0,
                low_price REAL DEFAULT 0, close_price REAL DEFAULT 0,
                change_pct REAL DEFAULT 0, sector TEXT DEFAULT '',
                theme TEXT DEFAULT '', is_leading_sector INTEGER DEFAULT 0,
                status TEXT DEFAULT 'watching',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(spike_date, stock_code))""")
            db.execute("""CREATE TABLE IF NOT EXISTS pullback_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code TEXT NOT NULL, stock_name TEXT NOT NULL,
                spike_date DATE NOT NULL, signal_date DATE NOT NULL,
                days_after INTEGER DEFAULT 0, close_price REAL DEFAULT 0,
                open_price REAL DEFAULT 0, spike_high REAL DEFAULT 0,
                drop_from_high_pct REAL DEFAULT 0, today_volume INTEGER DEFAULT 0,
                spike_volume INTEGER DEFAULT 0, vol_decrease_pct REAL DEFAULT 0,
                ma5 REAL DEFAULT 0, ma20 REAL DEFAULT 0,
                ma_support TEXT DEFAULT '', ma_distance_pct REAL DEFAULT 0,
                is_negative_candle INTEGER DEFAULT 0, sector TEXT DEFAULT '',
                is_leading_sector INTEGER DEFAULT 0, has_recent_news INTEGER DEFAULT 0,
                signal_strength TEXT DEFAULT '', reason TEXT DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(signal_date, stock_code))""")
        except Exception:
            pass
        from src.infrastructure.repository import get_pullback_repository
        return get_pullback_repository()
    except Exception as e:
        st.error(f"Repository 로드 실패: {e}")
        return None


repo = _get_repo()
names = _load_names()

if repo is None:
    st.warning("데이터베이스 연결 실패")
    st.stop()

# ── 날짜 선택 ──
col_date, col_range = st.columns([1, 1])
with col_date:
    sel_date = st.date_input("기준일", value=date.today())
with col_range:
    history_days = st.selectbox("조회 기간", [3, 7, 14, 30], index=1, format_func=lambda x: f"최근 {x}일")

# 휴장일 보정
try:
    from src.utils.market_calendar import is_market_open
    if not is_market_open(sel_date):
        corrected = sel_date
        for _ in range(10):
            corrected -= timedelta(days=1)
            if is_market_open(corrected):
                break
        weekday_kr = ['월','화','수','목','금','토','일'][sel_date.weekday()]
        st.caption(f"⚠️ {sel_date.strftime('%m/%d')}({weekday_kr}) 휴장일 → {corrected.strftime('%m/%d')} 표시")
        sel_date = corrected
except ImportError:
    pass

date_str = sel_date.strftime("%Y-%m-%d")


# ============================================================
# 섹션 1: 눌림목 시그널 + 차트
# ============================================================

st.markdown("---")
st.subheader("🎯 눌림목 시그널")

try:
    today_signals = repo.get_signals_by_date(date_str)
except Exception:
    today_signals = []

# v10.1: S/R + 공매도 조회용 DB
try:
    from src.infrastructure.database import get_database
    _pb_db = get_database()
except Exception:
    _pb_db = None

if not today_signals:
    st.info(f"{date_str}의 눌림목 시그널이 없습니다.")
else:
    for sig in today_signals:
        row = dict(sig) if not isinstance(sig, dict) else sig
        strength = row.get("signal_strength", "")
        emoji = {"강": "🔴", "중": "🟠", "약": "🟡"}.get(strength, "⚪")
        code = row.get("stock_code", "")
        stock_name = _name(code, row.get("stock_name", ""), names)
        close = float(row.get("close_price", 0))
        drop_pct = float(row.get("drop_from_high_pct", 0))
        vol_pct = float(row.get("vol_decrease_pct", 0))
        ma_sup = row.get("ma_support", "")
        ma_dist = float(row.get("ma_distance_pct", 0))
        days_after = row.get("days_after", 0)
        spike_date = row.get("spike_date", "")
        reason = row.get("reason", "")
        sector = row.get("sector", "")
        is_leading = bool(row.get("is_leading_sector", 0))
        has_news = bool(row.get("has_recent_news", 0))

        with st.expander(
            f"{emoji} **{stock_name}** ({code}) | D+{days_after} | 종가 {close:,.0f}원 | 시그널: {strength}",
            expanded=True,
        ):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("종가", f"{close:,.0f}원")
            c2.metric("고점 대비", f"-{drop_pct:.1f}%")
            c3.metric("거래량 비율", f"{vol_pct * 100:.0f}%", help="폭발일 대비")
            c4.metric("MA 지지", f"{ma_sup} ({ma_dist:.1f}%)")

            # 섹터/재료
            info_cols = st.columns(3)
            sector_icon = "🔥 주도섹터" if is_leading else "📂 섹터"
            info_cols[0].caption(f"{sector_icon}: {sector or '-'}")

            # 뉴스 헤드라인 추출
            news_label = "❌ 없음"
            if has_news and reason and "📰" in reason:
                headline = reason.split("📰")[-1].strip().split(" | ")[0].strip()
                if headline and headline != "재료없음":
                    if len(headline) > 30:
                        headline = headline[:27] + "..."
                    news_label = f"✅ {headline}"
                else:
                    news_label = "✅ 살아있음"
            elif has_news:
                news_label = "✅ 살아있음"
            info_cols[1].caption(f"📰 재료: {news_label}")
            info_cols[2].caption(f"📅 폭발일: {spike_date}")

            if reason:
                st.caption(f"💡 {reason}")

            # v10.1: 지지/저항 + 공매도 표시
            try:
                if not _pb_db:
                    raise Exception("no db")
                sr_row = _pb_db.fetch_one(
                    "SELECT nearest_support, nearest_resistance, support_distance_pct, "
                    "resistance_distance_pct, score, summary "
                    "FROM support_resistance_cache WHERE stock_code = ? "
                    "ORDER BY date DESC LIMIT 1", (code,)
                )
                ss_row = _pb_db.fetch_one(
                    "SELECT short_ratio, short_volume, trade_volume "
                    "FROM short_selling_daily WHERE stock_code = ? "
                    "ORDER BY date DESC LIMIT 1", (code,)
                )
                if sr_row or ss_row:
                    sr_cols = st.columns(3)
                    if sr_row:
                        sr = dict(sr_row)
                        sup = sr.get("nearest_support", 0)
                        res = sr.get("nearest_resistance", 0)
                        if sup:
                            sr_cols[0].caption(f"🟢 지지: {sup:,.0f}원 ({sr.get('support_distance_pct', 0):.1f}%↓)")
                        if res:
                            sr_cols[1].caption(f"🔴 저항: {res:,.0f}원 ({sr.get('resistance_distance_pct', 0):.1f}%↑)")
                    if ss_row:
                        ss = dict(ss_row)
                        short_r = ss.get("short_ratio", 0) or 0
                        short_emoji = "🔴" if short_r >= 5 else ("🟡" if short_r >= 2 else "🟢")
                        sr_cols[2].caption(f"📉 공매도: {short_r:.1f}% {short_emoji}")
            except Exception:
                pass  # 테이블 미존재시 무시

            # AI 분석
            ai_comment = row.get("ai_comment", "")
            if ai_comment:
                with st.container():
                    st.markdown(f"🤖 **AI 분석**")
                    for line in ai_comment.split('\n'):
                        line = line.strip()
                        if line:
                            st.caption(line)

            # 미니 차트
            _draw_mini_chart(code, spike_date=spike_date, signal_date=date_str)


# ============================================================
# 섹션 2: 거래량 폭발 감시풀
# ============================================================

st.markdown("---")
st.subheader("🔥 거래량 폭발 감시풀")

try:
    spikes = repo.get_recent_spikes(days=history_days)
except Exception:
    spikes = []

if not spikes:
    st.info(f"최근 {history_days}일간 거래량 폭발 종목이 없습니다.")
else:
    if pd is not None:
        spike_data = []
        for s in spikes:
            r = dict(s) if not isinstance(s, dict) else s
            code = r.get("stock_code", "")
            spike_data.append({
                "폭발일": r.get("spike_date", ""),
                "종목명": _name(code, r.get("stock_name", ""), names),
                "종목코드": code,
                "섹터": r.get("sector", "") or "-",
                "거래량": f"{int(r.get('spike_volume', 0)):,}",
                "MA20 대비": f"{float(r.get('spike_ratio', 0)):.1f}배",
                "등락률": f"{float(r.get('change_pct', 0)):+.1f}%",
                "종가": f"{float(r.get('close_price', 0)):,.0f}",
                "주도": "🔥" if r.get("is_leading_sector") else "",
            })
        df_spikes = pd.DataFrame(spike_data)
        st.dataframe(df_spikes, width="stretch", hide_index=True)

    # 감시풀 차트 (접기)
    if HAS_PLOTLY:
        with st.expander("📊 감시풀 종목 차트 보기", expanded=False):
            chart_cols = st.columns(2)
            for i, s in enumerate(spikes[:6]):
                r = dict(s) if not isinstance(s, dict) else s
                code = r.get("stock_code", "")
                stock_name = _name(code, r.get("stock_name", ""), names)
                with chart_cols[i % 2]:
                    st.caption(f"**{stock_name}** ({code})")
                    _draw_mini_chart(code, spike_date=r.get("spike_date", ""))


# ============================================================
# 섹션 3: 시그널 히스토리
# ============================================================

st.markdown("---")
st.subheader("📋 시그널 히스토리")

try:
    history = repo.get_signals_with_spikes(days=history_days)
except Exception:
    history = []

if not history:
    st.info(f"최근 {history_days}일간 눌림목 시그널이 없습니다.")
else:
    if pd is not None:
        hist_data = []
        for h in history:
            r = dict(h) if not isinstance(h, dict) else h
            strength = r.get("signal_strength", "")
            emoji = {"강": "🔴", "중": "🟠", "약": "🟡"}.get(strength, "⚪")
            code = r.get("stock_code", "")
            hist_data.append({
                "시그널일": r.get("signal_date", ""),
                "강도": f"{emoji} {strength}",
                "종목명": _name(code, r.get("stock_name", ""), names),
                "종목코드": code,
                "D+N": f"D+{r.get('days_after', 0)}",
                "종가": f"{float(r.get('close_price', 0)):,.0f}",
                "고점대비": f"-{float(r.get('drop_from_high_pct', 0)):.1f}%",
                "거감률": f"{float(r.get('vol_decrease_pct', 0)) * 100:.0f}%",
                "MA지지": r.get("ma_support", ""),
                "섹터": r.get("sector", "") or "-",
                "재료": "✅" if r.get("has_recent_news") else "❌",
                "폭발일": r.get("spike_date", ""),
            })
        df_hist = pd.DataFrame(hist_data)
        st.dataframe(df_hist, width="stretch", hide_index=True)


# ============================================================
# 섹션 4: 통계 차트
# ============================================================

if HAS_PLOTLY and spikes and pd is not None:
    st.markdown("---")
    st.subheader("📊 거래량 폭발 일별 분포")

    spike_dates = {}
    for s in spikes:
        r = dict(s) if not isinstance(s, dict) else s
        d = r.get("spike_date", "")
        spike_dates[d] = spike_dates.get(d, 0) + 1

    if spike_dates:
        fig = go.Figure(data=[go.Bar(
            x=list(spike_dates.keys()),
            y=list(spike_dates.values()),
            marker_color="#ff6b35",
            text=list(spike_dates.values()),
            textposition="outside",
        )])
        fig.update_layout(
            height=250,
            xaxis_title="날짜", yaxis_title="종목 수",
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig, width="stretch")


# ── D+1~D+5 성과 추적 ──
st.markdown("---")
st.subheader("📊 눌림목 D+1~D+5 성과")
st.caption("시그널 발생 후 실제 수익률 추적 (OHLCV 기반, 매일 16:07 자동 갱신)")

try:
    from src.services.pullback_tracker import get_pullback_performance

    perf_days = st.selectbox("분석 기간", [7, 14, 30, 90], index=2,
                             format_func=lambda x: f"최근 {x}일", key="pb_perf")
    perf = get_pullback_performance(days=perf_days)

    if perf.get("tracked_signals", 0) > 0:
        st.markdown(f"**추적 시그널: {perf['tracked_signals']}개** / 전체 {perf['total_signals']}개")

        # D+1 ~ D+5 전체 통계
        d_cols = st.columns(5)
        for i in range(1, 6):
            d_stat = perf.get(f"d{i}", {})
            with d_cols[i - 1]:
                avg = d_stat.get("avg", 0)
                wr = d_stat.get("win_rate", 0)
                n = d_stat.get("n", 0)
                color = "normal" if avg > 0 else "inverse"
                st.metric(
                    f"D+{i}",
                    f"{avg:+.2f}%",
                    delta=f"승률 {wr:.0f}% ({n}건)",
                    delta_color=color,
                )

        # 시그널 강도별 비교
        by_str = perf.get("by_strength", {})
        if by_str:
            st.markdown("**시그널 강도별 D+1 성과:**")
            str_cols = st.columns(len(by_str))
            for i, (strength, data) in enumerate(sorted(by_str.items())):
                with str_cols[i]:
                    emoji = {"강": "🔴", "중": "🟠", "약": "🟡"}.get(strength, "⚪")
                    d1 = data.get("d1", {})
                    d5 = data.get("d5", {})
                    st.markdown(f"**{emoji} {strength}**")
                    st.write(f"D+1: {d1.get('avg', 0):+.2f}% (승률 {d1.get('win_rate', 0):.0f}%)")
                    st.write(f"D+5: {d5.get('avg', 0):+.2f}% (승률 {d5.get('win_rate', 0):.0f}%)")
    else:
        st.info("📊 아직 추적 데이터가 없습니다. 시그널 발생 다음 거래일부터 자동 수집됩니다.")

except ImportError:
    st.info("pullback_tracker 모듈 미설치 - D+1~D+5 추적 비활성")
except Exception as e:
    st.warning(f"성과 로드 실패: {e}")


# ── 조건 안내 ──
st.markdown("---")
with st.expander("📖 스캐닝 조건 상세"):
    st.markdown("""
**1단계: 거래량 폭발 감지** (매일 16:05)
- 당일 거래량 ≥ **1,000만주**
- 20일 이동평균 대비 **3배 이상**
- 감시풀에 등록, D+1 ~ D+3까지 모니터링

**2단계: 눌림목 시그널** (매일 14:55)
- 거래량 급감: 폭발일 대비 **20% 이하** (80%+ 감소)
- **음봉** (종가 < 시가)
- **5일선 or 20일선** ±2% 이내
- 고점 대비 낙폭 **15% 이내**

**시그널 강도**
- 🔴 **강**: 거래량 85%↑ 급감 + 고점 근접 (5% 이내)
- 🟠 **중**: 기본 조건 충족
- 🟡 **약**: 경계선 조건

**Enrichment**
- 📂 섹터: stock_mapping.csv → FDR 리스팅
- 🔥 주도섹터: sector_service 판별
- 📰 재료: 네이버 뉴스 최근 3일
- 🏢 기업: DART 프로필 (매출/위험도)

**디스코드 알림**: 시그널 발생 시 자동 웹훅 발송
""")

st.caption("ClosingBell v10.1")