"""
🏢 거래원 수급 추적 대시보드 v9.1
시각화 강화 + AI 분석
"""

import os
import streamlit as st
import pandas as pd
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

if os.getenv("STREAMLIT_SERVER_HEADLESS", "").lower() == "true":
    os.environ.setdefault("DASHBOARD_ONLY", "true")

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

# ============================================================
# 설정
# ============================================================
st.set_page_config(page_title="거래원 수급 추적", page_icon="🏢", layout="wide")

st.title("🏢 거래원 수급 추적")
with st.sidebar:
    from dashboard.components.sidebar import render_sidebar_nav
    render_sidebar_nav()

# ── 종목명 매핑 ──
@st.cache_data(ttl=3600)
def _load_stock_names():
    try:
        from src.config.app_config import MAPPING_FILE
        if MAPPING_FILE and MAPPING_FILE.exists():
            df = pd.read_csv(MAPPING_FILE, dtype={'code': str})
            return {str(r['code']).zfill(6): r['name'] for _, r in df.iterrows()}
    except Exception:
        pass
    return {}


def _name(code: str) -> str:
    if not code:
        return ""
    return _load_stock_names().get(str(code).zfill(6), code)


# ── DB 연결 ──
try:
    import sys
    from pathlib import Path
    project_root = Path(__file__).resolve().parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from src.infrastructure.database import get_database
    from src.infrastructure.repository import get_broker_signal_repository
    db = get_database()
    broker_repo = get_broker_signal_repository()
    DB_AVAILABLE = True
except Exception as e:
    logger.warning(f"DB 연결 실패: {e}")
    DB_AVAILABLE = False

if not DB_AVAILABLE:
    st.warning("데이터베이스에 연결할 수 없습니다.")
    st.stop()


# ── 공통 차트 함수 ──
def _anomaly_gauge(score: float, title: str = "") -> Optional[go.Figure]:
    """anomaly 점수 게이지"""
    if not HAS_PLOTLY:
        return None
    color = "#dc3545" if score >= 70 else ("#ff9800" if score >= 50 else ("#ffc107" if score >= 35 else "#28a745"))
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        title={"text": title, "font": {"size": 14}},
        number={"font": {"size": 28}},
        gauge={
            "axis": {"range": [0, 100], "tickwidth": 1},
            "bar": {"color": color},
            "steps": [
                {"range": [0, 35], "color": "#d4edda"},
                {"range": [35, 50], "color": "#fff3cd"},
                {"range": [50, 70], "color": "#ffe0b2"},
                {"range": [70, 100], "color": "#f8d7da"},
            ],
            "threshold": {"line": {"color": "red", "width": 3}, "thickness": 0.75, "value": score},
        },
    ))
    fig.update_layout(height=180, margin=dict(l=20, r=20, t=40, b=10))
    return fig


def _radar_chart(unusual: float, asymmetry: float, distribution: float, foreign: float) -> Optional[go.Figure]:
    """4개 세부점수 레이더 차트"""
    if not HAS_PLOTLY:
        return None
    categories = ["비주류", "비대칭", "분포이상", "외국계"]
    values = [unusual, asymmetry, distribution, foreign]
    values_closed = values + [values[0]]
    cats_closed = categories + [categories[0]]

    fig = go.Figure(go.Scatterpolar(
        r=values_closed, theta=cats_closed,
        fill='toself', fillcolor='rgba(255, 107, 107, 0.3)',
        line=dict(color='#FF6B6B', width=2),
        marker=dict(size=6),
    ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 30], tickfont=dict(size=10)),
            angularaxis=dict(tickfont=dict(size=11)),
        ),
        height=220, margin=dict(l=40, r=40, t=20, b=20),
        showlegend=False,
    )
    return fig


def _buyers_sellers_chart(buyers: list, sellers: list) -> Optional[go.Figure]:
    """매수/매도 Top5 수평 바 차트"""
    if not HAS_PLOTLY:
        return None
    fig = make_subplots(rows=1, cols=2, subplot_titles=("📈 매수 Top5", "📉 매도 Top5"))

    if buyers:
        names = [b.get('name', '?')[:6] for b in buyers[:5]]
        qtys = [b.get('qty', 0) for b in buyers[:5]]
        fig.add_trace(go.Bar(y=names[::-1], x=qtys[::-1], orientation='h',
                             marker_color='#FF6B6B', text=[f"{q:,}" for q in qtys[::-1]],
                             textposition='outside'), row=1, col=1)

    if sellers:
        names = [s.get('name', '?')[:6] for s in sellers[:5]]
        qtys = [s.get('qty', 0) for s in sellers[:5]]
        fig.add_trace(go.Bar(y=names[::-1], x=qtys[::-1], orientation='h',
                             marker_color='#6c8ef5', text=[f"{q:,}" for q in qtys[::-1]],
                             textposition='outside'), row=1, col=2)

    fig.update_layout(height=220, margin=dict(l=10, r=10, t=30, b=10), showlegend=False)
    return fig


def _heatmap_plotly(pivot: pd.DataFrame) -> Optional[go.Figure]:
    """Plotly 히트맵"""
    if not HAS_PLOTLY or pivot.empty:
        return None
    fig = go.Figure(go.Heatmap(
        z=pivot.values,
        x=[str(c) for c in pivot.columns],
        y=list(pivot.index),
        colorscale=[
            [0, "#d4edda"], [0.35, "#fff3cd"], [0.5, "#ffe0b2"],
            [0.7, "#f8d7da"], [1.0, "#dc3545"],
        ],
        zmin=0, zmax=100,
        text=pivot.values.astype(int).astype(str),
        texttemplate="%{text}",
        textfont={"size": 11},
        hovertemplate="종목: %{y}<br>날짜: %{x}<br>이상치: %{z}점<extra></extra>",
        colorbar=dict(title="이상치"),
    ))
    fig.update_layout(
        height=max(300, len(pivot) * 35),
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(tickangle=-45),
    )
    return fig



# ============================================================
# 날짜 선택
# ============================================================
col_d1, col_d2 = st.columns([1, 3])
with col_d1:
    selected_date = st.date_input(
        "📅 날짜 선택", value=datetime.now().date(), max_value=datetime.now().date(),
    )

# 휴장일 보정
try:
    from src.utils.market_calendar import is_market_open
    if not is_market_open(selected_date):
        from datetime import timedelta as _td
        corrected = selected_date
        for _ in range(10):
            corrected -= _td(days=1)
            if is_market_open(corrected):
                break
        weekday_kr = ['월','화','수','목','금','토','일'][selected_date.weekday()]
        st.caption(f"⚠️ {selected_date.strftime('%m/%d')}({weekday_kr}) 휴장일 → {corrected.strftime('%m/%d')} 표시")
        selected_date = corrected
except ImportError:
    pass

screen_date_str = selected_date.strftime("%Y-%m-%d")


# ============================================================
# 1. 감시종목 거래원 현황
# ============================================================
st.markdown("---")
st.subheader(f"📊 {screen_date_str} 감시종목 거래원 현황")

try:
    signals = broker_repo.get_signals_by_date(screen_date_str)
except Exception:
    signals = []

if not signals:
    st.info(f"{screen_date_str}의 거래원 데이터가 없습니다.")
else:
    # 요약 카드
    total = len(signals)
    high_cnt = sum(1 for s in signals if (dict(s) if not isinstance(s, dict) else s).get('anomaly_score', 0) >= 50)
    avg_anomaly = sum((dict(s) if not isinstance(s, dict) else s).get('anomaly_score', 0) for s in signals) / total if total else 0

    cols_summary = st.columns(4)
    cols_summary[0].metric("분석 종목", f"{total}개")
    cols_summary[1].metric("이상 감지", f"{high_cnt}개", delta=f"{high_cnt}/{total}" if high_cnt else None,
                           delta_color="inverse" if high_cnt else "off")
    cols_summary[2].metric("평균 이상치", f"{avg_anomaly:.0f}점")
    max_s = max(signals, key=lambda s: (dict(s) if not isinstance(s, dict) else s).get('anomaly_score', 0))
    max_row = dict(max_s) if not isinstance(max_s, dict) else max_s
    cols_summary[3].metric("최고 이상치",
                           f"{_name(max_row.get('stock_code',''))} {max_row.get('anomaly_score',0)}점")

    st.markdown("")

    # 종목별 상세
    for signal in signals:
        row = dict(signal) if not isinstance(signal, dict) else signal
        anomaly = row.get('anomaly_score', 0)
        broker_score = row.get('broker_score', 0)
        tag = row.get('tag', '정상')
        stock_code = row.get('stock_code', '')
        stock_name = row.get('stock_name', '')
        if not stock_name or stock_name == stock_code:
            stock_name = _name(stock_code)

        unusual = row.get('unusual_score', 0)
        asymmetry = row.get('asymmetry_score', 0)
        distribution = row.get('distribution_score', 0)
        foreign = row.get('foreign_score', 0)

        tag_color = "🔴" if anomaly >= 70 else ("🟠" if anomaly >= 50 else ("🟡" if anomaly >= 35 else "🟢"))

        with st.expander(
            f"{tag_color} **{stock_name}** ({stock_code}) — "
            f"이상치: {anomaly}점 | 거래원점수: {broker_score:.0f}/13 | {tag}",
            expanded=(anomaly >= 50),
        ):
            # 매수/매도 데이터
            try:
                buyers = json.loads(row.get('buyers_json', '[]') or '[]')
            except (json.JSONDecodeError, TypeError):
                buyers = []
            try:
                sellers = json.loads(row.get('sellers_json', '[]') or '[]')
            except (json.JSONDecodeError, TypeError):
                sellers = []

            if HAS_PLOTLY:
                # 3컬럼: 게이지 | 레이더 | 매수매도
                c1, c2, c3 = st.columns([1, 1, 2])
                with c1:
                    gauge = _anomaly_gauge(anomaly, "이상치 점수")
                    if gauge:
                        st.plotly_chart(gauge, width="stretch", key=f"gauge_{stock_code}")
                with c2:
                    radar = _radar_chart(unusual, asymmetry, distribution, foreign)
                    if radar:
                        st.plotly_chart(radar, width="stretch", key=f"radar_{stock_code}")
                with c3:
                    bs_chart = _buyers_sellers_chart(buyers, sellers)
                    if bs_chart:
                        st.plotly_chart(bs_chart, width="stretch", key=f"bs_{stock_code}")
                    elif not buyers and not sellers:
                        st.info("매수/매도 데이터 없음")
            else:
                # plotly 없으면 기존 방식
                col_buy, col_sell = st.columns(2)
                with col_buy:
                    st.markdown("**📈 매수 Top5**")
                    for i, b in enumerate(buyers[:5], 1):
                        st.text(f"  {i}. {b.get('name','?')}: {b.get('qty',0):,}주")
                    if not buyers:
                        st.text("  데이터 없음")
                with col_sell:
                    st.markdown("**📉 매도 Top5**")
                    for i, s in enumerate(sellers[:5], 1):
                        st.text(f"  {i}. {s.get('name','?')}: {s.get('qty',0):,}주")
                    if not sellers:
                        st.text("  데이터 없음")

                sub_cols = st.columns(4)
                sub_cols[0].metric("비주류", unusual)
                sub_cols[1].metric("비대칭", asymmetry)
                sub_cols[2].metric("분포이상", distribution)
                sub_cols[3].metric("외국계", foreign)

            # 해석
            notes = []
            if unusual >= 20:
                notes.append("⚠️ 비주류 증권사 거래 비중 높음 (세력 매집 가능)")
            if asymmetry >= 15:
                notes.append("⚠️ 매수/매도 비대칭 큼 (한쪽으로 쏠림)")
            if foreign >= 15:
                notes.append("🌍 외국계 증권사 활동 감지")
            if distribution >= 15:
                notes.append("📊 거래 분포 이상 (특정 증권사 집중)")
            if notes:
                st.markdown(" | ".join(notes))

    # ── AI 분석 (DB에서 읽기) ──
    st.markdown("---")
    st.subheader("🤖 AI 거래원 분석")

    try:
        ai_text = broker_repo.get_ai_summary_by_date(screen_date_str)
    except Exception:
        ai_text = ""

    if ai_text:
        st.markdown(ai_text)
    else:
        st.info("AI 분석 결과가 없습니다. 스케줄러 16:48에 자동 생성됩니다.")


# ============================================================
# 2. 이상 신호 히트맵
# ============================================================
st.markdown("---")
st.subheader("🗺️ 이상 신호 히트맵 (최근 20일)")
st.caption("숫자가 높을수록(빨간색) 거래원 이상 징후가 강합니다.")

try:
    heatmap_data = broker_repo.get_heatmap_data(days=20)
except Exception:
    heatmap_data = []

if heatmap_data:
    df = pd.DataFrame(heatmap_data)

    if 'stock_code' in df.columns:
        names = _load_stock_names()
        df['stock_name'] = df.apply(
            lambda r: names.get(str(r.get('stock_code', '')).zfill(6), r.get('stock_name', r.get('stock_code', '')))
            if not r.get('stock_name') or r.get('stock_name') == r.get('stock_code')
            else r.get('stock_name', ''),
            axis=1,
        )

    if not df.empty and 'screen_date' in df.columns and 'stock_name' in df.columns:
        pivot = df.pivot_table(
            index='stock_name', columns='screen_date',
            values='anomaly_score', aggfunc='max', fill_value=0,
        )
        pivot = pivot.loc[pivot.max(axis=1).sort_values(ascending=False).index].head(15)

        if not pivot.empty:
            hm_fig = _heatmap_plotly(pivot)
            if hm_fig:
                st.plotly_chart(hm_fig, width="stretch")
            else:
                styled = pivot.style.background_gradient(cmap='YlOrRd', vmin=0, vmax=100).format("{:.0f}")
                st.dataframe(styled, width="stretch")
        else:
            st.info("히트맵 데이터가 충분하지 않습니다.")
    else:
        st.info("히트맵 데이터가 충분하지 않습니다.")
else:
    st.info("히트맵용 데이터가 없습니다. 스크리닝 후 누적됩니다.")


# ============================================================
# 3. 외국계 순매수 추이
# ============================================================
st.markdown("---")
st.subheader("🌍 외국계 순매수 추이")

if heatmap_data:
    df_frgn = pd.DataFrame(heatmap_data)

    if 'stock_code' in df_frgn.columns:
        names = _load_stock_names()
        df_frgn['stock_name'] = df_frgn.apply(
            lambda r: names.get(str(r.get('stock_code', '')).zfill(6), r.get('stock_name', r.get('stock_code', '')))
            if not r.get('stock_name') or r.get('stock_name') == r.get('stock_code')
            else r.get('stock_name', ''),
            axis=1,
        )

    if 'frgn_buy' in df_frgn.columns and 'frgn_sell' in df_frgn.columns:
        df_frgn['frgn_net'] = df_frgn['frgn_buy'].fillna(0) - df_frgn['frgn_sell'].fillna(0).abs()

        latest_date = df_frgn['screen_date'].max()
        df_latest = df_frgn[df_frgn['screen_date'] == latest_date].sort_values('frgn_net', ascending=False)

        if not df_latest.empty and HAS_PLOTLY:
            top10 = df_latest.head(10)
            colors = ['#FF6B6B' if v >= 0 else '#6c8ef5' for v in top10['frgn_net']]
            fig_frgn = go.Figure(go.Bar(
                y=top10['stock_name'][::-1],
                x=top10['frgn_net'][::-1],
                orientation='h',
                marker_color=colors[::-1],
                text=[f"{int(v):,}" for v in top10['frgn_net'][::-1]],
                textposition='outside',
            ))
            fig_frgn.update_layout(
                height=350, margin=dict(l=10, r=10, t=10, b=10),
                xaxis_title="순매수량", yaxis_title="",
            )
            st.plotly_chart(fig_frgn, width="stretch")
        elif not df_latest.empty:
            chart_data = df_latest.set_index('stock_name')['frgn_net'].head(10)
            st.bar_chart(chart_data)
        else:
            st.info("외국계 순매수 데이터가 없습니다.")
    else:
        st.info("외국계 데이터 컬럼이 없습니다.")
else:
    st.info("데이터가 누적되면 차트가 표시됩니다.")


# ============================================================
# 푸터
# ============================================================
st.markdown("---")
st.caption("ClosingBell v10.1 | 거래원 수급 추적")