"""
종가매매 TOP5 20일 추적 대시보드
================================

v6.0: D+1 ~ D+20 수익률 추적
"""

import streamlit as st
import sys
import os
from pathlib import Path
from datetime import date, timedelta
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

st.set_page_config(
    page_title="TOP5 20일 추적",
    page_icon="📊",
    layout="wide",
)

st.title("📊 종가매매 TOP5 20일 추적")
st.markdown("**D+1 ~ D+20 수익률 분석** | _시간이 지나면 어떻게 될까?_")
st.markdown("---")


# ==================== 데이터 로드 ====================
@st.cache_data(ttl=300)
def load_top5_dates(limit=60):
    """TOP5 데이터가 있는 날짜 목록"""
    try:
        from src.infrastructure.repository import get_top5_history_repository
        repo = get_top5_history_repository()
        return repo.get_dates_with_data(limit)
    except Exception as e:
        st.error(f"날짜 로드 실패: {e}")
        return []


@st.cache_data(ttl=300)
def load_top5_data(screen_date):
    """특정 날짜의 TOP5 + 일별 가격"""
    try:
        from src.infrastructure.repository import (
            get_top5_history_repository,
            get_top5_prices_repository
        )
        
        history_repo = get_top5_history_repository()
        prices_repo = get_top5_prices_repository()
        
        # TOP5 이력
        top5 = history_repo.get_by_date(screen_date)
        
        # 각 종목의 일별 가격
        for item in top5:
            item['daily_prices'] = prices_repo.get_by_history(item['id'])
        
        return top5
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return []


def create_return_chart(stock_name, daily_prices, screen_price):
    """20일 수익률 차트"""
    if not daily_prices:
        return None
    
    df = pd.DataFrame(daily_prices)
    
    fig = go.Figure()
    
    # 종가 수익률
    fig.add_trace(go.Scatter(
        x=df['days_after'],
        y=df['return_from_screen'],
        mode='lines+markers',
        name='종가 수익률',
        line=dict(color='#2196F3', width=2),
        marker=dict(size=6),
    ))
    
    # 고가 수익률
    if 'high_return' in df.columns:
        fig.add_trace(go.Scatter(
            x=df['days_after'],
            y=df['high_return'],
            mode='lines+markers',
            name='고가 수익률',
            line=dict(color='#4CAF50', width=1, dash='dot'),
            marker=dict(size=4),
        ))
    
    # 저가 수익률
    if 'low_return' in df.columns:
        fig.add_trace(go.Scatter(
            x=df['days_after'],
            y=df['low_return'],
            mode='lines+markers',
            name='저가 수익률',
            line=dict(color='#F44336', width=1, dash='dot'),
            marker=dict(size=4),
        ))
    
    # 기준선
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    
    fig.update_layout(
        title=dict(text=f"{stock_name} 20일 수익률", font=dict(size=14)),
        height=300,
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis_title="D+N",
        yaxis_title="수익률 (%)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    
    return fig


def grade_color(grade):
    """등급 색상"""
    colors = {
        'S': '#FFD700',  # 금색
        'A': '#4CAF50',  # 녹색
        'B': '#2196F3',  # 파랑
        'C': '#FFC107',  # 노랑
        'D': '#F44336',  # 빨강
    }
    return colors.get(grade, '#9E9E9E')


# ==================== 사이드바: 날짜 선택 ====================
dates = load_top5_dates(60)

if not dates:
    st.warning("📭 아직 수집된 TOP5 데이터가 없습니다.")
    st.markdown("""
    ### 🚀 데이터 수집 방법
    
    ```bash
    # 과거 데이터 백필 (최초 1회)
    python main.py --backfill 20
    ```
    """)
    st.stop()

st.sidebar.markdown("### 📅 날짜 선택")
selected_date = st.sidebar.selectbox(
    "스크리닝 날짜",
    dates,
    format_func=lambda x: x
)

st.sidebar.markdown("---")
st.sidebar.markdown(f"**선택된 날짜**: {selected_date}")
st.sidebar.markdown(f"**전체 데이터**: {len(dates)}일")


# ==================== 메인 컨텐츠 ====================
top5_data = load_top5_data(selected_date)

if not top5_data:
    st.warning(f"📭 {selected_date} 날짜에 TOP5 데이터가 없습니다.")
    st.stop()

# 요약 카드
st.subheader(f"📈 {selected_date} TOP5 요약")

cols = st.columns(5)
for i, item in enumerate(top5_data[:5]):
    with cols[i]:
        # D+1 갭률 계산
        d1_gap = None
        if item.get('daily_prices'):
            d1 = next((p for p in item['daily_prices'] if p['days_after'] == 1), None)
            if d1:
                d1_gap = d1.get('gap_rate')
        
        st.markdown(f"""
        <div style="
            background: linear-gradient(135deg, {grade_color(item['grade'])}22, {grade_color(item['grade'])}11);
            border-left: 4px solid {grade_color(item['grade'])};
            padding: 10px;
            border-radius: 5px;
            margin-bottom: 10px;
        ">
            <div style="font-size: 12px; color: #888;">#{item['rank']}</div>
            <div style="font-size: 16px; font-weight: bold;">{item['stock_name']}</div>
            <div style="font-size: 14px;">
                <span style="color: {grade_color(item['grade'])}; font-weight: bold;">{item['grade']}</span>
                ({item['screen_score']:.1f}점)
            </div>
            <div style="font-size: 13px; color: #666;">{item['screen_price']:,}원</div>
            <div style="font-size: 13px; color: {'#4CAF50' if d1_gap and d1_gap > 0 else '#F44336'};">
                D+1: {f"{d1_gap:+.2f}%" if d1_gap is not None else "-"}
            </div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("---")

# 종목별 상세
st.subheader("📋 종목별 상세 분석")

for item in top5_data:
    with st.expander(f"**#{item['rank']} {item['stock_name']}** ({item['stock_code']}) - {item['grade']}등급 ({item['screen_score']:.1f}점)", expanded=(item['rank'] == 1)):
        col1, col2 = st.columns([2, 1])
        
        with col1:
            # 20일 수익률 차트
            if item.get('daily_prices'):
                fig = create_return_chart(item['stock_name'], item['daily_prices'], item['screen_price'])
                if fig:
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("아직 일별 가격 데이터가 없습니다.")
        
        with col2:
            # 스크리닝 지표
            st.markdown("##### 📊 스크리닝 지표")
            cci = item.get('cci')
            rsi = item.get('rsi')
            disparity = item.get('disparity_20')
            vol_ratio = item.get('volume_ratio_5')
            st.write(f"• CCI: {cci:.1f}" if cci else "• CCI: -")
            st.write(f"• RSI: {rsi:.1f}" if rsi else "• RSI: -")
            st.write(f"• 등락률: {item.get('change_rate', 0):.2f}%")
            st.write(f"• 이격도(20): {disparity:.1f}" if disparity else "• 이격도(20): -")
            st.write(f"• 연속양봉: {item.get('consecutive_up', 0)}일")
            st.write(f"• 거래량비(5): {vol_ratio:.1f}" if vol_ratio else "• 거래량비(5): -")
            
            st.markdown("---")
            
            # 성과 요약
            if item.get('daily_prices'):
                st.markdown("##### 📈 성과 요약")
                
                prices = item['daily_prices']
                max_return = max((p.get('high_return') or 0 for p in prices), default=0)
                min_return = min((p.get('low_return') or 0 for p in prices), default=0)
                final_return = prices[-1]['return_from_screen'] if prices else 0
                
                st.write(f"• 최대 수익: **{max_return:+.2f}%**")
                st.write(f"• 최대 손실: **{min_return:+.2f}%**")
                st.write(f"• 최종 수익: **{final_return:+.2f}%**")
                
                st.markdown("---")
                
                st.markdown("##### 📋 상태")
                status = item.get('tracking_status', 'active')
                status_emoji = {'active': '🔵', 'completed': '✅', 'cancelled': '❌'}
                st.write(f"• 상태: {status_emoji.get(status, '❓')} {status}")
                st.write(f"• 추적일수: {item.get('tracking_days', 0)}일")
                st.write(f"• 데이터소스: {item.get('data_source', 'realtime')}")


# ==================== 통계 요약 ====================
st.markdown("---")
st.subheader("📊 전체 통계")

# 모든 종목의 D+1 갭률
all_d1_gaps = []
for item in top5_data:
    if item.get('daily_prices'):
        d1 = next((p for p in item['daily_prices'] if p['days_after'] == 1), None)
        if d1 and d1.get('gap_rate') is not None:
            all_d1_gaps.append(d1['gap_rate'])

if all_d1_gaps:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("D+1 평균 갭", f"{sum(all_d1_gaps)/len(all_d1_gaps):+.2f}%")
    col2.metric("D+1 승률", f"{sum(1 for g in all_d1_gaps if g > 0) / len(all_d1_gaps) * 100:.1f}%")
    col3.metric("최대 갭", f"{max(all_d1_gaps):+.2f}%")
    col4.metric("최소 갭", f"{min(all_d1_gaps):+.2f}%")


# ==================== 푸터 ====================
st.markdown("---")
st.caption("ClosingBell v6.0 | TOP5 20일 추적")
