"""
Analysis 페이지

성과 분석 및 통계
"""

import streamlit as st
import sys
from pathlib import Path
from datetime import date, timedelta

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

st.set_page_config(page_title="Analysis", page_icon="📈", layout="wide")

st.title("📈 Performance Analysis")
st.markdown("---")


def load_analysis_data():
    """분석 데이터 로드"""
    from src.infrastructure.database import init_database
    from src.infrastructure.repository import (
        get_screening_repository,
        get_next_day_repository,
        get_weight_repository,
        get_repository,
    )
    
    init_database()
    return (
        get_screening_repository(),
        get_next_day_repository(),
        get_weight_repository(),
        get_repository(),
    )


try:
    screening_repo, next_day_repo, weight_repo, repo = load_analysis_data()
    
    # 기간 선택
    col1, col2 = st.columns([1, 3])
    with col1:
        days = st.selectbox("분석 기간", [7, 14, 30, 60, 90], index=2)
    
    st.markdown("---")
    
    # 적중률 통계
    st.subheader("🎯 적중률 통계")
    
    hit_stats = next_day_repo.get_hit_rate(days=days)
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        from dashboard.components.charts import render_win_rate_gauge
        fig = render_win_rate_gauge(hit_stats.get('hit_rate', 0), "전체 승률")
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.metric(
            label="총 샘플",
            value=f"{hit_stats.get('total_count', 0)}개",
        )
    
    with col3:
        st.metric(
            label="적중",
            value=f"{hit_stats.get('hit_count', 0)}개",
        )
    
    with col4:
        st.metric(
            label="적중률",
            value=f"{hit_stats.get('hit_rate', 0):.1f}%",
        )
    
    st.markdown("---")
    
    # 익일 결과 상세
    st.subheader("📊 익일 결과 분석")
    
    next_day_results = repo.get_next_day_results(days=days)
    
    if next_day_results:
        # 통계 계산
        gap_rates = [r.get('gap_rate', 0) for r in next_day_results if r.get('gap_rate') is not None]
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            avg_gap = sum(gap_rates) / len(gap_rates) if gap_rates else 0
            st.metric("평균 갭 상승률", f"{avg_gap:+.2f}%")
        
        with col2:
            max_gap = max(gap_rates) if gap_rates else 0
            st.metric("최대 갭", f"{max_gap:+.2f}%")
        
        with col3:
            min_gap = min(gap_rates) if gap_rates else 0
            st.metric("최소 갭", f"{min_gap:+.2f}%")
        
        with col4:
            win_rate = sum(1 for g in gap_rates if g > 0) / len(gap_rates) * 100 if gap_rates else 0
            st.metric("시초가 상승률", f"{win_rate:.1f}%")
        
        # 일별 데이터 테이블
        st.subheader("📋 익일 결과 상세")
        
        import pandas as pd
        df_data = []
        for r in next_day_results[:30]:
            df_data.append({
                "날짜": r.get('screen_date', ''),
                "종목명": r.get('stock_name', ''),
                "순위": r.get('screen_rank', 0),
                "총점": f"{r.get('score_total', 0):.1f}",
                "갭 상승률": f"{r.get('gap_rate', 0):+.2f}%",
                "당일 수익": f"{r.get('day_change_rate', 0):+.2f}%",
                "결과": "✅" if r.get('gap_rate', 0) > 0 else "❌",
            })
        
        if df_data:
            df = pd.DataFrame(df_data)
            st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("아직 익일 결과 데이터가 없습니다. 데이터가 쌓이면 분석 결과가 표시됩니다.")
    
    st.markdown("---")
    
    # 상관관계 분석
    st.subheader("📈 지표 상관관계 분석")
    
    screening_with_next = repo.get_screening_with_next_day(days=days)
    
    if len(screening_with_next) >= 10:
        from src.domain.weight_optimizer import analyze_correlation
        
        indicator_scores = {
            'cci_value': [r.get('score_cci_value', 0) for r in screening_with_next],
            'cci_slope': [r.get('score_cci_slope', 0) for r in screening_with_next],
            'ma20_slope': [r.get('score_ma20_slope', 0) for r in screening_with_next],
            'candle': [r.get('score_candle', 0) for r in screening_with_next],
            'change': [r.get('score_change', 0) for r in screening_with_next],
        }
        gap_rates_list = [r.get('gap_rate', 0) for r in screening_with_next]
        
        correlations = analyze_correlation(indicator_scores, gap_rates_list)
        corr_dict = {name: r.correlation for name, r in correlations.items()}
        
        from dashboard.components.charts import render_correlation_heatmap
        fig = render_correlation_heatmap(corr_dict, "지표별 갭 상승률 상관계수")
        st.plotly_chart(fig, use_container_width=True)
        
        st.info("""
        💡 **상관계수 해석**
        - **양수**: 해당 지표 점수가 높을수록 익일 갭 상승률도 높음 (좋은 지표)
        - **음수**: 해당 지표 점수가 높을수록 익일 갭 상승률은 낮음 (역효과)
        - **0 근처**: 해당 지표와 수익률 간 상관관계 없음
        """)
    else:
        st.info(f"상관관계 분석을 위해 최소 10개 이상의 샘플이 필요합니다. (현재: {len(screening_with_next)}개)")
    
    st.markdown("---")
    
    # 가중치 이력
    st.subheader("⚖️ 가중치 변경 이력")
    
    weight_history = weight_repo.get_weight_history(days=days)
    
    if weight_history:
        from dashboard.components.charts import render_weight_history_chart
        fig = render_weight_history_chart(weight_history)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("가중치 변경 이력이 없습니다.")

except Exception as e:
    st.error(f"데이터 로드 실패: {e}")
    st.exception(e)
