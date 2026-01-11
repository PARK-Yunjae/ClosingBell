"""
🔍 종목 상세 분석 페이지

기능:
- 종목 검색
- 종목별 스크리닝 이력
- 개별 종목 성과 분석
- 자주 등장하는 종목 목록
"""

import streamlit as st
import sys
from pathlib import Path
from datetime import date, timedelta
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

st.set_page_config(
    page_title="종목 상세 - ClosingBell",
    page_icon="🔍",
    layout="wide",
)

st.title("🔍 종목 상세 분석")
st.markdown("---")

try:
    from dashboard.utils.data_loader import (
        load_unique_stocks,
        load_stock_history,
        load_screening_history_df,
    )
    from dashboard.utils.calculations import format_percent, get_result_emoji
    
    # ==================== 기간 선택 ====================
    analysis_days = st.slider("분석 기간 (일)", 30, 365, 90)
    
    st.markdown("---")
    
    # ==================== 자주 등장하는 종목 ====================
    st.subheader("🔥 자주 등장하는 종목 TOP 20")
    
    unique_stocks = load_unique_stocks(days=analysis_days)
    
    if unique_stocks:
        top_stocks = unique_stocks[:20]
        top_df = pd.DataFrame(top_stocks)
        
        col1, col2 = st.columns(2)
        
        with col1:
            # 등장 횟수 차트
            fig = px.bar(
                top_df.head(10),
                x='stock_name',
                y='appearance_count',
                color='top3_count',
                color_continuous_scale='Blues',
                text='appearance_count',
                hover_data=['stock_code', 'avg_score', 'win_rate'],
            )
            fig.update_traces(textposition='outside')
            fig.update_layout(
                title="등장 횟수 TOP 10",
                xaxis_title="종목명",
                yaxis_title="등장 횟수",
                height=400,
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            # TOP3 선정 비율
            top_df['top3_rate'] = (top_df['top3_count'] / top_df['appearance_count'] * 100).round(1)
            
            fig = px.scatter(
                top_df.head(20),
                x='appearance_count',
                y='avg_gap_rate',
                size='top3_count',
                color='win_rate',
                color_continuous_scale='RdYlGn',
                hover_name='stock_name',
                text='stock_name',
            )
            fig.update_traces(textposition='top center')
            fig.update_layout(
                title="등장횟수 vs 평균 갭 수익률",
                xaxis_title="등장 횟수",
                yaxis_title="평균 갭 수익률 (%)",
                height=400,
            )
            st.plotly_chart(fig, use_container_width=True)
        
        # 테이블
        display_df = top_df[['stock_name', 'stock_code', 'appearance_count', 'top3_count', 'avg_score', 'avg_gap_rate', 'win_rate']].copy()
        display_df['avg_score'] = display_df['avg_score'].apply(lambda x: f"{x:.1f}" if pd.notna(x) else "-")
        display_df['avg_gap_rate'] = display_df['avg_gap_rate'].apply(lambda x: f"{x:.2f}%" if pd.notna(x) else "-")
        display_df['win_rate'] = display_df['win_rate'].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "-")
        
        display_df = display_df.rename(columns={
            'stock_name': '종목명',
            'stock_code': '종목코드',
            'appearance_count': '등장횟수',
            'top3_count': 'TOP3선정',
            'avg_score': '평균점수',
            'avg_gap_rate': '평균갭',
            'win_rate': '승률',
        })
        
        st.dataframe(display_df, use_container_width=True, hide_index=True)
        
        # 종목 선택 드롭다운
        stock_options = [(s['stock_name'], s['stock_code']) for s in unique_stocks]
    else:
        stock_options = []
        st.info("스크리닝 데이터가 없습니다.")
    
    st.markdown("---")
    
    # ==================== 종목 검색 ====================
    st.subheader("🔎 종목 검색")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        if stock_options:
            selected_option = st.selectbox(
                "종목 선택",
                options=stock_options,
                format_func=lambda x: f"{x[0]} ({x[1]})",
            )
            selected_code = selected_option[1] if selected_option else None
        else:
            selected_code = st.text_input("종목코드 입력", placeholder="예: 005930")
    
    with col2:
        search_btn = st.button("🔍 검색", type="primary", use_container_width=True)
    
    # ==================== 종목 상세 정보 ====================
    if selected_code:
        st.markdown("---")
        
        # 종목 이력 로드
        stock_history = load_stock_history(selected_code, days=analysis_days)
        
        if not stock_history.empty:
            # 종목 기본 정보
            stock_info = next((s for s in unique_stocks if s['stock_code'] == selected_code), None)
            
            if stock_info:
                st.subheader(f"📊 {stock_info['stock_name']} ({selected_code})")
                
                col1, col2, col3, col4, col5 = st.columns(5)
                
                with col1:
                    st.metric("스크리닝 횟수", f"{stock_info['appearance_count']}회")
                
                with col2:
                    st.metric("TOP3 선정", f"{stock_info['top3_count']}회")
                
                with col3:
                    top3_rate = (stock_info['top3_count'] / stock_info['appearance_count'] * 100) if stock_info['appearance_count'] > 0 else 0
                    st.metric("TOP3 비율", f"{top3_rate:.1f}%")
                
                with col4:
                    st.metric("평균 점수", f"{stock_info['avg_score']:.1f}점" if stock_info['avg_score'] else "-")
                
                with col5:
                    avg_gap = stock_info.get('avg_gap_rate', 0)
                    st.metric("평균 갭 수익률", format_percent(avg_gap) if avg_gap else "-")
            
            st.markdown("---")
            
            # 스크리닝 이력 차트
            col1, col2 = st.columns(2)
            
            with col1:
                # 순위 추이
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=stock_history['screen_date'],
                    y=stock_history['rank'],
                    mode='lines+markers',
                    name='순위',
                    line=dict(color='#3498db'),
                ))
                fig.add_hline(y=3, line_dash="dash", line_color="orange", annotation_text="TOP3")
                fig.update_layout(
                    title="순위 추이",
                    xaxis_title="날짜",
                    yaxis_title="순위",
                    height=300,
                    yaxis=dict(autorange="reversed"),  # 순위는 낮을수록 좋으므로 역순
                )
                st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                # 점수 추이
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=stock_history['screen_date'],
                    y=stock_history['score_total'],
                    mode='lines+markers',
                    name='점수',
                    line=dict(color='#9b59b6'),
                ))
                fig.update_layout(
                    title="점수 추이",
                    xaxis_title="날짜",
                    yaxis_title="총점",
                    height=300,
                )
                st.plotly_chart(fig, use_container_width=True)
            
            # 갭 수익률 추이
            if 'gap_rate' in stock_history.columns:
                valid_gaps = stock_history[stock_history['gap_rate'].notna()]
                
                if not valid_gaps.empty:
                    fig = go.Figure()
                    
                    colors = ['#2ecc71' if x > 0 else '#e74c3c' for x in valid_gaps['gap_rate']]
                    
                    fig.add_trace(go.Bar(
                        x=valid_gaps['screen_date'],
                        y=valid_gaps['gap_rate'],
                        marker_color=colors,
                        name='갭 수익률',
                    ))
                    fig.add_hline(y=0, line_dash="solid", line_color="gray")
                    
                    fig.update_layout(
                        title="익일 갭 수익률 추이",
                        xaxis_title="날짜",
                        yaxis_title="갭 수익률 (%)",
                        height=300,
                    )
                    st.plotly_chart(fig, use_container_width=True)
            
            # 상세 이력 테이블
            st.subheader("📋 스크리닝 이력")
            
            history_display = stock_history.copy()
            history_display['gap_rate'] = history_display['gap_rate'].apply(
                lambda x: format_percent(x) if pd.notna(x) else "대기중"
            )
            history_display['is_open_up'] = history_display['is_open_up'].apply(
                lambda x: get_result_emoji(x) if pd.notna(x) else "⏳"
            )
            history_display['is_top3'] = history_display['is_top3'].apply(
                lambda x: "🏆" if x == 1 else ""
            )
            
            display_cols = ['screen_date', 'rank', 'is_top3', 'score_total', 'raw_cci', 'change_rate', 'gap_rate', 'is_open_up']
            display_cols = [c for c in display_cols if c in history_display.columns]
            
            history_display = history_display[display_cols].rename(columns={
                'screen_date': '날짜',
                'rank': '순위',
                'is_top3': 'TOP3',
                'score_total': '점수',
                'raw_cci': 'CCI',
                'change_rate': '당일등락률',
                'gap_rate': '익일갭',
                'is_open_up': '결과',
            })
            
            st.dataframe(history_display, use_container_width=True, hide_index=True)
            
            # 성과 요약
            st.subheader("📊 성과 요약")
            
            valid_results = stock_history[stock_history['gap_rate'].notna()]
            
            if not valid_results.empty:
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    win_count = (valid_results['is_open_up'] == 1).sum()
                    total = len(valid_results)
                    win_rate = (win_count / total * 100) if total > 0 else 0
                    st.metric("승률", f"{win_rate:.1f}%", delta=f"{win_count}/{total}")
                
                with col2:
                    avg_gap = valid_results['gap_rate'].mean()
                    st.metric("평균 갭", format_percent(avg_gap))
                
                with col3:
                    max_gap = valid_results['gap_rate'].max()
                    st.metric("최대 갭", format_percent(max_gap))
                
                with col4:
                    min_gap = valid_results['gap_rate'].min()
                    st.metric("최소 갭", format_percent(min_gap))
            else:
                st.info("익일 결과 데이터가 없습니다.")
        else:
            st.warning(f"'{selected_code}' 종목의 스크리닝 이력이 없습니다.")

except Exception as e:
    st.error(f"오류 발생: {e}")
    import traceback
    st.code(traceback.format_exc())
