"""
⚖️ 가중치 관리 페이지

기능:
- 현재 가중치 조회
- 가중치 수동 조정
- 가중치 변경 이력
- 상관관계 분석
"""

import streamlit as st
import sys
from pathlib import Path
from datetime import date
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

st.set_page_config(
    page_title="가중치 관리 - ClosingBell",
    page_icon="⚖️",
    layout="wide",
)

st.title("⚖️ 가중치 관리")
st.markdown("---")

try:
    from dashboard.utils.data_loader import (
        load_weights,
        load_weight_history,
        load_all_results_with_screening,
    )
    from dashboard.utils.calculations import format_percent, calculate_correlation_matrix
    from src.infrastructure.repository import get_weight_repository
    
    # ==================== 현재 가중치 ====================
    st.subheader("📊 현재 가중치")
    
    weights = load_weights()
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # 가중치 바 차트
        weight_df = pd.DataFrame({
            '지표': list(weights.keys()),
            '가중치': list(weights.values()),
        })
        
        fig = px.bar(
            weight_df,
            x='지표',
            y='가중치',
            color='가중치',
            color_continuous_scale='viridis',
            text='가중치',
        )
        fig.update_traces(texttemplate='%{text:.2f}', textposition='outside')
        fig.update_layout(
            showlegend=False,
            yaxis_range=[0, 3],
            height=300,
        )
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.markdown("### 📋 가중치 테이블")
        
        weight_table = pd.DataFrame({
            '지표': list(weights.keys()),
            '가중치': [f"{v:.2f}" for v in weights.values()],
            '범위': ['0.5 ~ 5.0'] * len(weights),
        })
        st.dataframe(weight_table, use_container_width=True, hide_index=True)
        
        # 가중치 합계
        total = sum(weights.values())
        st.info(f"가중치 합계: **{total:.2f}**")
    
    st.markdown("---")
    
    # ==================== 가중치 수동 조정 ====================
    st.subheader("🔧 가중치 수동 조정")
    
    with st.expander("가중치 수정하기", expanded=False):
        st.warning("⚠️ 가중치 변경은 다음 스크리닝부터 적용됩니다.")
        
        new_weights = {}
        cols = st.columns(len(weights))
        
        for i, (name, value) in enumerate(weights.items()):
            with cols[i]:
                new_weights[name] = st.slider(
                    name,
                    min_value=0.5,
                    max_value=5.0,
                    value=float(value),
                    step=0.1,
                    key=f"weight_{name}",
                )
        
        reason = st.text_input("변경 사유", placeholder="예: 백테스트 결과 반영")
        
        col1, col2, col3 = st.columns([1, 1, 2])
        
        with col1:
            if st.button("💾 저장", type="primary", use_container_width=True):
                if reason:
                    try:
                        repo = get_weight_repository()
                        for name, weight in new_weights.items():
                            repo.update_weight(name, weight, reason=reason)
                        st.success("✅ 가중치가 저장되었습니다!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"저장 실패: {e}")
                else:
                    st.error("변경 사유를 입력해주세요.")
        
        with col2:
            if st.button("🔄 초기화", use_container_width=True):
                try:
                    repo = get_weight_repository()
                    default = {'cci_value': 1.0, 'cci_slope': 1.0, 'ma20_slope': 1.0, 'candle': 1.0, 'change': 1.0}
                    for name, weight in default.items():
                        repo.update_weight(name, weight, reason="초기화")
                    st.success("✅ 가중치가 초기화되었습니다!")
                    st.rerun()
                except Exception as e:
                    st.error(f"초기화 실패: {e}")
    
    st.markdown("---")
    
    # ==================== 상관관계 분석 ====================
    st.subheader("📈 지표별 상관관계 분석")
    
    analysis_days = st.slider("분석 기간 (일)", 7, 90, 30, key="corr_days")
    results_df = load_all_results_with_screening(days=analysis_days)
    
    if not results_df.empty:
        col1, col2 = st.columns(2)
        
        with col1:
            # 상관관계 매트릭스
            corr_matrix = calculate_correlation_matrix(results_df)
            
            if not corr_matrix.empty:
                fig = px.imshow(
                    corr_matrix,
                    text_auto='.3f',
                    color_continuous_scale='RdBu_r',
                    zmin=-1, zmax=1,
                )
                fig.update_layout(
                    title="지표별 상관관계 매트릭스",
                    height=400,
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("상관관계 분석을 위한 데이터가 부족합니다.")
        
        with col2:
            # 갭 수익률과의 상관관계 표
            if 'gap_rate' in corr_matrix.columns:
                gap_corr = corr_matrix['gap_rate'].drop('gap_rate').sort_values(ascending=False)
                
                corr_df = pd.DataFrame({
                    '지표': gap_corr.index,
                    '상관계수': gap_corr.values,
                    '강도': ['강함' if abs(v) > 0.05 else '약함' for v in gap_corr.values],
                })
                
                st.markdown("### 익일 갭과의 상관관계")
                
                for _, row in corr_df.iterrows():
                    color = "🟢" if row['상관계수'] > 0 else "🔴"
                    st.markdown(f"{color} **{row['지표']}**: `{row['상관계수']:.4f}`")
    else:
        st.info("분석할 데이터가 없습니다.")
    
    st.markdown("---")
    
    # ==================== 가중치 변경 이력 ====================
    st.subheader("📜 가중치 변경 이력")
    
    history_days = st.slider("이력 조회 기간 (일)", 7, 365, 30, key="history_days")
    history = load_weight_history(days=history_days)
    
    if history:
        history_df = pd.DataFrame(history)
        
        # 시계열 차트
        fig = go.Figure()
        
        for indicator in weights.keys():
            indicator_history = [h for h in history if h['indicator'] == indicator]
            if indicator_history:
                dates = [h['changed_at'] for h in indicator_history]
                values = [h['new_weight'] for h in indicator_history]
                fig.add_trace(go.Scatter(
                    x=dates,
                    y=values,
                    mode='lines+markers',
                    name=indicator,
                ))
        
        fig.update_layout(
            title="가중치 변경 추이",
            xaxis_title="날짜",
            yaxis_title="가중치",
            height=300,
            yaxis_range=[0, 3],
        )
        st.plotly_chart(fig, use_container_width=True)
        
        # 이력 테이블
        display_cols = ['changed_at', 'indicator', 'old_weight', 'new_weight', 'change_reason']
        history_display = history_df[display_cols].rename(columns={
            'changed_at': '변경일시',
            'indicator': '지표',
            'old_weight': '이전',
            'new_weight': '변경후',
            'change_reason': '사유',
        })
        
        st.dataframe(history_display, use_container_width=True, hide_index=True)
    else:
        st.info("가중치 변경 이력이 없습니다.")

except Exception as e:
    st.error(f"오류 발생: {e}")
    import traceback
    st.code(traceback.format_exc())
