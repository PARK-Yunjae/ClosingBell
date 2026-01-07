"""
📈 성과 분석 페이지

기능:
- 일별 수익률 차트
- 누적 수익률 차트
- 순위별 성과 분석
- 통계 지표 (MDD, 샤프, 연속승리 등)
"""

import streamlit as st
import sys
from pathlib import Path
from datetime import date, timedelta
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

st.set_page_config(
    page_title="성과 분석 - ClosingBell",
    page_icon="📈",
    layout="wide",
)

st.title("📈 성과 분석")
st.markdown("---")

try:
    from dashboard.utils.data_loader import (
        load_daily_performance,
        load_hit_rate,
        load_hit_rate_by_rank,
        load_all_results_with_screening,
    )
    from dashboard.utils.calculations import (
        format_percent,
        calculate_cumulative_returns,
        calculate_mdd,
        calculate_streak,
        get_result_emoji,
    )
    
    # ==================== 기간 선택 ====================
    analysis_days = st.slider("분석 기간 (일)", 7, 180, 30)
    
    st.markdown("---")
    
    # ==================== 요약 통계 ====================
    st.subheader("📊 요약 통계")
    
    hit_rate_top3 = load_hit_rate(days=analysis_days, top3_only=True)
    hit_rate_all = load_hit_rate(days=analysis_days, top3_only=False)
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric(
            label="TOP3 승률",
            value=f"{hit_rate_top3['hit_rate']:.1f}%",
            delta=f"{hit_rate_top3['hit_count']}/{hit_rate_top3['total_count']}"
        )
    
    with col2:
        st.metric(
            label="전체 승률",
            value=f"{hit_rate_all['hit_rate']:.1f}%",
            delta=f"{hit_rate_all['hit_count']}/{hit_rate_all['total_count']}"
        )
    
    with col3:
        st.metric(
            label="TOP3 평균 갭",
            value=format_percent(hit_rate_top3.get('avg_gap_rate', 0)),
        )
    
    with col4:
        st.metric(
            label="전체 평균 갭",
            value=format_percent(hit_rate_all.get('avg_gap_rate', 0)),
        )
    
    # 일별 성과 데이터
    daily_df = load_daily_performance(days=analysis_days)
    
    with col5:
        if not daily_df.empty and 'avg_gap_rate' in daily_df.columns:
            gap_rates = daily_df['avg_gap_rate'].dropna().tolist()
            cum_returns = calculate_cumulative_returns(gap_rates)
            mdd = calculate_mdd(cum_returns) if cum_returns else 0
            st.metric(label="MDD", value=f"-{mdd:.2f}%")
        else:
            st.metric(label="MDD", value="-")
    
    st.markdown("---")
    
    # ==================== 일별 수익률 차트 ====================
    st.subheader("📊 일별 수익률 추이")
    
    if not daily_df.empty:
        col1, col2 = st.columns(2)
        
        with col1:
            # 일별 수익률 막대 차트
            fig = go.Figure()
            
            colors = ['#2ecc71' if x > 0 else '#e74c3c' for x in daily_df['avg_gap_rate'].fillna(0)]
            
            fig.add_trace(go.Bar(
                x=daily_df['screen_date'],
                y=daily_df['avg_gap_rate'],
                marker_color=colors,
                name='일별 갭 수익률',
            ))
            
            fig.update_layout(
                title="일별 평균 갭 수익률",
                xaxis_title="날짜",
                yaxis_title="갭 수익률 (%)",
                height=350,
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            # 누적 수익률 라인 차트
            gap_rates = daily_df.sort_values('screen_date')['avg_gap_rate'].dropna().tolist()
            cum_returns = calculate_cumulative_returns(gap_rates)
            dates = daily_df.sort_values('screen_date')['screen_date'].tolist()[:len(cum_returns)]
            
            if cum_returns:
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=dates,
                    y=cum_returns,
                    mode='lines+markers',
                    fill='tozeroy',
                    name='누적 수익률',
                    line=dict(color='#3498db'),
                ))
                
                fig.update_layout(
                    title="누적 갭 수익률",
                    xaxis_title="날짜",
                    yaxis_title="누적 수익률 (%)",
                    height=350,
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("누적 수익률 데이터가 없습니다.")
        
        # 승률 추이
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=daily_df['screen_date'],
            y=daily_df['hit_rate'],
            mode='lines+markers',
            name='승률',
            line=dict(color='#9b59b6'),
        ))
        fig.add_hline(y=50, line_dash="dash", line_color="gray", annotation_text="50%")
        
        fig.update_layout(
            title="일별 승률 추이",
            xaxis_title="날짜",
            yaxis_title="승률 (%)",
            height=300,
            yaxis_range=[0, 100],
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("일별 성과 데이터가 없습니다.")
    
    st.markdown("---")
    
    # ==================== 순위별 성과 분석 ====================
    st.subheader("🏆 순위별 성과 분석")
    
    rank_performance = load_hit_rate_by_rank(days=analysis_days)
    
    if rank_performance:
        rank_df = pd.DataFrame(rank_performance)
        
        col1, col2 = st.columns(2)
        
        with col1:
            # 순위별 평균 갭 수익률
            fig = px.bar(
                rank_df,
                x='rank',
                y='avg_gap_rate',
                color='avg_gap_rate',
                color_continuous_scale='RdYlGn',
                text='avg_gap_rate',
            )
            fig.update_traces(texttemplate='%{text:.2f}%', textposition='outside')
            fig.update_layout(
                title="순위별 평균 갭 수익률",
                xaxis_title="순위",
                yaxis_title="평균 갭 수익률 (%)",
                height=350,
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            # 순위별 승률
            fig = px.bar(
                rank_df,
                x='rank',
                y='hit_rate',
                color='hit_rate',
                color_continuous_scale='Blues',
                text='hit_rate',
            )
            fig.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
            fig.add_hline(y=50, line_dash="dash", line_color="red", annotation_text="50%")
            fig.update_layout(
                title="순위별 승률",
                xaxis_title="순위",
                yaxis_title="승률 (%)",
                height=350,
                yaxis_range=[0, 100],
            )
            st.plotly_chart(fig, use_container_width=True)
        
        # 순위별 테이블
        rank_df_display = rank_df.copy()
        rank_df_display['avg_gap_rate'] = rank_df_display['avg_gap_rate'].apply(lambda x: f"{x:.2f}%")
        rank_df_display['hit_rate'] = rank_df_display['hit_rate'].apply(lambda x: f"{x:.1f}%")
        rank_df_display = rank_df_display.rename(columns={
            'rank': '순위',
            'total_count': '샘플수',
            'hit_count': '승리수',
            'avg_gap_rate': '평균갭',
            'hit_rate': '승률',
        })
        
        st.dataframe(rank_df_display, use_container_width=True, hide_index=True)
    else:
        st.info("순위별 성과 데이터가 없습니다.")
    
    st.markdown("---")
    
    # ==================== 상세 통계 ====================
    st.subheader("📋 상세 통계")
    
    results_df = load_all_results_with_screening(days=analysis_days)
    
    if not results_df.empty and 'gap_rate' in results_df.columns:
        gap_rates = results_df['gap_rate'].dropna()
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown("### 수익률 통계")
            st.metric("최대 갭 수익률", f"{gap_rates.max():.2f}%")
            st.metric("최소 갭 수익률", f"{gap_rates.min():.2f}%")
            st.metric("표준편차", f"{gap_rates.std():.2f}%")
        
        with col2:
            st.markdown("### 연속 기록")
            is_win_list = (results_df['is_open_up'] == 1).tolist()
            max_win, max_loss = calculate_streak(is_win_list)
            st.metric("최대 연속 승리", f"{max_win}회")
            st.metric("최대 연속 패배", f"{max_loss}회")
        
        with col3:
            st.markdown("### 성과 지표")
            positive_returns = gap_rates[gap_rates > 0]
            negative_returns = gap_rates[gap_rates < 0]
            
            avg_win = positive_returns.mean() if len(positive_returns) > 0 else 0
            avg_loss = abs(negative_returns.mean()) if len(negative_returns) > 0 else 0
            
            st.metric("평균 수익", f"+{avg_win:.2f}%")
            st.metric("평균 손실", f"-{avg_loss:.2f}%")
            
            if avg_loss > 0:
                rr_ratio = avg_win / avg_loss
                st.metric("손익비", f"{rr_ratio:.2f}")
            else:
                st.metric("손익비", "∞")
        
        # 수익률 분포 히스토그램
        fig = px.histogram(
            gap_rates,
            nbins=30,
            title="갭 수익률 분포",
            labels={'value': '갭 수익률 (%)', 'count': '빈도'},
        )
        fig.add_vline(x=0, line_dash="dash", line_color="red")
        fig.add_vline(x=gap_rates.mean(), line_dash="dash", line_color="green", annotation_text=f"평균: {gap_rates.mean():.2f}%")
        
        fig.update_layout(height=300)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("상세 통계를 계산할 데이터가 없습니다.")

except Exception as e:
    st.error(f"오류 발생: {e}")
    import traceback
    st.code(traceback.format_exc())
