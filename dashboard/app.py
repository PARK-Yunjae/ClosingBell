"""
ClosingBell 대시보드 v6.2
==========================

📊 종가매매 TOP5 20일 추적 + 유목민 공부법

v6.2 변경사항:
- CCI 하드 필터 (250+)
- 대기업 표시 (점수 가산 없음)
- 네이버 금융 기업정보
- Gemini 2.0 Flash AI 분석

기능:
- 전체 승률 요약
- 누적 수익률 그래프
- 최근 결과 테이블
"""

import streamlit as st
import sys
import os
from pathlib import Path
from datetime import date, timedelta
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Streamlit Cloud 모드 (API 키 불필요)
os.environ["DASHBOARD_ONLY"] = "true"

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

st.set_page_config(
    page_title="ClosingBell v6.2",
    page_icon="🔔",
    layout="wide",
)

# ==================== 헤더 ====================
st.title("🔔 ClosingBell v6.2")
st.markdown("**종가매매 TOP5 추적 + 유목민 공부법** | _차트가 모든 것을 반영한다_ 📈")
st.markdown("---")


# ==================== 데이터 로드 ====================
@st.cache_data(ttl=300)
def load_all_results(days=60):
    """익일 결과 데이터 로드"""
    try:
        from src.infrastructure.repository import get_repository
        repo = get_repository()
        
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        
        results = repo.get_next_day_results(start_date=start_date, end_date=end_date)
        return results
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return []


@st.cache_data(ttl=300)
def load_top5_summary():
    """TOP5 20일 추적 요약"""
    try:
        from src.infrastructure.repository import get_top5_history_repository
        repo = get_top5_history_repository()
        
        dates = repo.get_dates_with_data(30)
        return {'dates_count': len(dates), 'latest_date': dates[0] if dates else None}
    except Exception:
        return {'dates_count': 0, 'latest_date': None}


@st.cache_data(ttl=300)
def load_nomad_summary():
    """유목민 공부법 요약"""
    try:
        from src.infrastructure.repository import get_nomad_candidates_repository
        repo = get_nomad_candidates_repository()
        
        dates = repo.get_dates_with_data(30)
        return {'dates_count': len(dates), 'latest_date': dates[0] if dates else None}
    except Exception:
        return {'dates_count': 0, 'latest_date': None}


# ==================== 통계 함수 ====================
def calc_stats(results):
    """승률 통계 계산"""
    if not results:
        return {'total': 0, 'wins': 0, 'win_rate': 0, 'avg_gap': 0, 'avg_high': 0}
    
    total = len(results)
    wins = sum(1 for r in results if (r.get('gap_rate') or 0) > 0)
    avg_gap = sum(r.get('gap_rate') or 0 for r in results) / total
    avg_high = sum(r.get('high_change_rate') or 0 for r in results) / total
    
    return {
        'total': total,
        'wins': wins,
        'win_rate': (wins / total * 100) if total > 0 else 0,
        'avg_gap': avg_gap,
        'avg_high': avg_high,
    }


def create_cumulative_chart(results, title):
    """누적 수익률 차트"""
    if not results:
        return None
    
    df = pd.DataFrame(results)
    df['screen_date'] = pd.to_datetime(df['screen_date'])
    
    daily = df.groupby('screen_date')['gap_rate'].mean().reset_index()
    daily = daily.sort_values('screen_date')
    daily['gap_rate'] = daily['gap_rate'].fillna(0)
    daily['cumulative'] = (1 + daily['gap_rate'] / 100).cumprod() - 1
    daily['cumulative_pct'] = daily['cumulative'] * 100
    
    colors = ['#4CAF50' if x > 0 else '#F44336' for x in daily['gap_rate']]
    
    fig = make_subplots(
        rows=2, cols=1,
        row_heights=[0.7, 0.3],
        shared_xaxes=True,
        vertical_spacing=0.05,
    )
    
    fig.add_trace(
        go.Scatter(
            x=daily['screen_date'],
            y=daily['cumulative_pct'],
            mode='lines+markers',
            name='누적 수익률',
            line=dict(color='#2196F3', width=2),
            marker=dict(size=5),
            fill='tozeroy',
            fillcolor='rgba(33, 150, 243, 0.1)',
        ),
        row=1, col=1
    )
    
    fig.add_trace(
        go.Bar(
            x=daily['screen_date'],
            y=daily['gap_rate'],
            name='일별 갭수익률',
            marker_color=colors,
        ),
        row=2, col=1
    )
    
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5, row=1, col=1)
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5, row=2, col=1)
    
    fig.update_layout(
        title=dict(text=title, font=dict(size=16)),
        height=400,
        margin=dict(l=10, r=10, t=40, b=10),
        showlegend=False,
        xaxis2_title="날짜",
        yaxis_title="누적 수익률 (%)",
        yaxis2_title="일별 (%)",
    )
    
    return fig


def create_gauge(value, title):
    """승률 게이지"""
    color = "#4CAF50" if value >= 60 else "#FFC107" if value >= 50 else "#F44336"
    
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        number={'suffix': '%', 'font': {'size': 36}, 'valueformat': '.1f'},
        gauge={
            'axis': {'range': [0, 100], 'tickwidth': 1},
            'bar': {'color': color},
            'steps': [
                {'range': [0, 50], 'color': 'rgba(244, 67, 54, 0.1)'},
                {'range': [50, 60], 'color': 'rgba(255, 193, 7, 0.1)'},
                {'range': [60, 100], 'color': 'rgba(76, 175, 80, 0.1)'},
            ],
        },
        title={'text': title, 'font': {'size': 14}},
    ))
    
    fig.update_layout(height=180, margin=dict(l=20, r=20, t=40, b=10))
    return fig


# ==================== 기능 요약 카드 ====================
st.subheader("📌 주요 기능")

col1, col2 = st.columns(2)

with col1:
    top5_summary = load_top5_summary()
    st.markdown("### 📈 종가매매 TOP5")
    if top5_summary['dates_count'] > 0:
        st.success(f"✅ {top5_summary['dates_count']}일 데이터 | 최신: {top5_summary['latest_date']}")
    else:
        st.warning("⚠️ 데이터 없음")
    st.caption("D+1 ~ D+20 수익률 추적, CCI 하드필터(250+)")

with col2:
    nomad_summary = load_nomad_summary()
    st.markdown("### 📚 유목민 공부법")
    if nomad_summary['dates_count'] > 0:
        st.success(f"✅ {nomad_summary['dates_count']}일 데이터 | 최신: {nomad_summary['latest_date']}")
    else:
        st.warning("⚠️ 데이터 없음")
    st.caption("상한가/거래량천만 종목, 네이버 기업정보, AI 분석")

st.info("👈 **사이드바에서 페이지를 선택하세요**")
st.markdown("---")


# ==================== 메인 컨텐츠 (D+1 성과) ====================
st.subheader("📊 D+1 성과 요약 (최근 60일)")

results = load_all_results(60)

if results:
    stats = calc_stats(results)
    
    # 상단: 요약 카드
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("📈 총 거래", f"{stats['total']}건")
    col2.metric("✅ 승리", f"{stats['wins']}건")
    col3.metric("📊 승률", f"{stats['win_rate']:.1f}%", 
                delta="Good" if stats['win_rate'] >= 60 else None)
    col4.metric("💰 평균 갭", f"{stats['avg_gap']:+.1f}%")
    col5.metric("📈 평균 고가", f"{stats['avg_high']:+.1f}%")
    
    st.markdown("---")
    
    # 중단: 승률 게이지 + 누적 수익률
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.plotly_chart(create_gauge(stats['win_rate'], "전체 승률"), use_container_width=True)
        
        st.markdown("##### 📋 상세 통계")
        st.write(f"• 승리: {stats['wins']}건 / {stats['total']}건")
        st.write(f"• 평균 갭수익률: {stats['avg_gap']:+.1f}%")
        st.write(f"• 평균 고가수익률: {stats['avg_high']:+.1f}%")
    
    with col2:
        fig = create_cumulative_chart(results, "📈 누적 수익률 & 일별 갭수익률")
        if fig:
            st.plotly_chart(fig, use_container_width=True)
    
    st.markdown("---")
    
    # 하단: 최근 결과 테이블
    st.subheader(f"📋 최근 결과 ({min(stats['total'], 10)}건)")
    
    df = pd.DataFrame(results)
    df['screen_date'] = pd.to_datetime(df['screen_date'])
    df = df.sort_values('screen_date', ascending=False)
    
    display_df = df[['screen_date', 'stock_code', 'stock_name', 'gap_rate', 'high_change_rate']].head(10)
    display_df.columns = ['날짜', '종목코드', '종목명', '갭수익률(%)', '고가수익률(%)']
    display_df['날짜'] = display_df['날짜'].dt.strftime('%m/%d')
    display_df['갭수익률(%)'] = display_df['갭수익률(%)'].apply(lambda x: f"{x:+.1f}" if pd.notna(x) else "-")
    display_df['고가수익률(%)'] = display_df['고가수익률(%)'].apply(lambda x: f"{x:+.1f}" if pd.notna(x) else "-")
    
    st.dataframe(display_df, use_container_width=True, hide_index=True)

else:
    st.info("📭 아직 수집된 데이터가 없습니다.")
    
    st.markdown("""
    ### 🚀 시작하기
    
    ```bash
    # 1. 과거 데이터 백필 (최초 1회)
    python main.py --backfill 20
    
    # 2. 스크리닝 실행
    python main.py --run
    
    # 3. 대시보드 확인
    streamlit run dashboard/app.py
    ```
    """)


# ==================== 사이드바 ====================
st.sidebar.markdown("---")
st.sidebar.markdown("### 🔔 ClosingBell v6.2")
st.sidebar.markdown("---")
st.sidebar.markdown("""
**v6.2 업데이트:**
- CCI 하드필터 (250+)
- 대기업 표시
- 네이버 기업정보
- Gemini 2.0 Flash AI

**전략:**
- 종가매매 TOP5 (점수제)
- 익일 시가 매도
""")


# ==================== 푸터 ====================
st.markdown("---")
st.caption("ClosingBell v6.2 | CCI 하드필터 + 대기업 표시 + AI 분석")
