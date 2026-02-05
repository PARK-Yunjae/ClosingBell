"""
🏢 거래원 수급 추적 대시보드 v8.0
"""

import streamlit as st
import pandas as pd
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ============================================================
# 설정
# ============================================================
st.set_page_config(
    page_title="거래원 수급 추적",
    page_icon="🏢",
    layout="wide",
)

st.title("🏢 거래원 수급 추적")

# ============================================================
# DB 연결
# ============================================================
try:
    import sys
    from pathlib import Path
    # 프로젝트 루트 추가
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


# ============================================================
# 날짜 선택
# ============================================================
col1, col2 = st.columns([1, 3])
with col1:
    selected_date = st.date_input(
        "📅 날짜 선택",
        value=datetime.now().date(),
        max_value=datetime.now().date(),
    )

screen_date_str = selected_date.strftime("%Y-%m-%d")

# ============================================================
# 1. 오늘의 감시종목 TOP5 거래원 현황
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
    for signal in signals:
        anomaly = signal.get('anomaly_score', 0)
        broker_score = signal.get('broker_score', 0)
        tag = signal.get('tag', '정상')
        stock_name = signal.get('stock_name', '')
        stock_code = signal.get('stock_code', '')
        
        # 태그 색상
        if anomaly >= 70:
            tag_color = "🔴"
        elif anomaly >= 50:
            tag_color = "🟠"
        elif anomaly >= 35:
            tag_color = "🟡"
        else:
            tag_color = "🟢"
        
        with st.expander(
            f"{tag_color} {stock_name} ({stock_code}) — "
            f"거래원점수: {broker_score:.0f}/13 ({tag}) | anomaly: {anomaly}점",
            expanded=(anomaly >= 50)
        ):
            col_buy, col_sell = st.columns(2)
            
            # 매수 Top5
            buyers_json = signal.get('buyers_json', '[]')
            try:
                buyers = json.loads(buyers_json) if buyers_json else []
            except (json.JSONDecodeError, TypeError):
                buyers = []
            
            with col_buy:
                st.markdown("**📈 매수 Top5**")
                if buyers:
                    for i, b in enumerate(buyers, 1):
                        name = b.get('name', '?')
                        qty = b.get('qty', 0)
                        st.text(f"  {i}. {name}: {qty:,}주")
                else:
                    st.text("  데이터 없음")
            
            # 매도 Top5
            sellers_json = signal.get('sellers_json', '[]')
            try:
                sellers = json.loads(sellers_json) if sellers_json else []
            except (json.JSONDecodeError, TypeError):
                sellers = []
            
            with col_sell:
                st.markdown("**📉 매도 Top5**")
                if sellers:
                    for i, s in enumerate(sellers, 1):
                        name = s.get('name', '?')
                        qty = s.get('qty', 0)
                        st.text(f"  {i}. {name}: {qty:,}주")
                else:
                    st.text("  데이터 없음")
            
            # 세부 점수
            st.markdown("**세부 점수**")
            sub_cols = st.columns(4)
            sub_cols[0].metric("비주류", signal.get('unusual_score', 0))
            sub_cols[1].metric("비대칭", signal.get('asymmetry_score', 0))
            sub_cols[2].metric("분포이상", signal.get('distribution_score', 0))
            sub_cols[3].metric("외국계", signal.get('foreign_score', 0))

# ============================================================
# 2. 이상 신호 히트맵 (최근 20일)
# ============================================================
st.markdown("---")
st.subheader("🗺️ 이상 신호 히트맵 (최근 20일)")

try:
    heatmap_data = broker_repo.get_heatmap_data(days=20)
except Exception:
    heatmap_data = []

if heatmap_data:
    df = pd.DataFrame(heatmap_data)
    
    if not df.empty and 'screen_date' in df.columns and 'stock_name' in df.columns:
        pivot = df.pivot_table(
            index='stock_name',
            columns='screen_date',
            values='anomaly_score',
            aggfunc='max',
            fill_value=0,
        )
        
        if not pivot.empty:
            # 가장 활발한 종목 순 정렬
            pivot = pivot.loc[pivot.max(axis=1).sort_values(ascending=False).index]
            
            # 상위 15개만 표시
            pivot = pivot.head(15)
            
            # Streamlit 히트맵 스타일
            styled = pivot.style.background_gradient(
                cmap='YlOrRd', vmin=0, vmax=100
            ).format("{:.0f}")
            
            st.dataframe(styled, use_container_width=True)
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
    
    if 'frgn_buy' in df_frgn.columns and 'frgn_sell' in df_frgn.columns:
        df_frgn['frgn_net'] = df_frgn['frgn_buy'].fillna(0) - df_frgn['frgn_sell'].fillna(0).abs()
        
        # 최근 날짜 기준 종목별 순매수
        latest_date = df_frgn['screen_date'].max()
        df_latest = df_frgn[df_frgn['screen_date'] == latest_date].sort_values('frgn_net', ascending=False)
        
        if not df_latest.empty:
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
st.caption("ClosingBell v8.0 | 거래원 수급 추적 | ka10040 기반")
