"""
종가매매 스크리너 대시보드

Streamlit 멀티페이지 앱

실행:
    streamlit run dashboard/app.py
"""

import streamlit as st
import sys
from pathlib import Path
from datetime import date, timedelta

# 프로젝트 루트를 path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# 페이지 설정
st.set_page_config(
    page_title="ClosingBell 대시보드",
    page_icon="🔔",
    layout="wide",
    initial_sidebar_state="expanded",
)


# CSS 스타일
st.markdown("""
<style>
    [data-testid="stSidebar"] {
        background-color: #1e1e2f;
    }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {
        color: white;
    }
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        text-align: center;
        padding: 1rem;
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .metric-card {
        background-color: #f8f9fa;
        border-radius: 10px;
        padding: 15px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        text-align: center;
    }
    .top3-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 10px;
        padding: 15px;
        color: white;
        margin-bottom: 10px;
    }
    .positive {
        color: #e74c3c;
    }
    .negative {
        color: #3498db;
    }
</style>
""", unsafe_allow_html=True)


def main():
    """메인 페이지"""
    
    # 헤더
    st.markdown('<h1 class="main-header">🔔 ClosingBell 대시보드</h1>', unsafe_allow_html=True)
    
    st.markdown("---")
    
    # 데이터 로드
    try:
        from dashboard.utils.data_loader import (
            load_today_screening,
            load_screening_items,
            load_hit_rate,
            load_recent_screenings,
            load_weights,
            load_daily_performance,
        )
        from dashboard.utils.calculations import format_percent, get_result_emoji
        
        # 오늘의 스크리닝 결과
        today_screening = load_today_screening()
        
        # ==================== 오늘의 요약 ====================
        st.subheader("📊 오늘의 요약")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            if today_screening:
                st.metric(
                    label="스크리닝 상태",
                    value="✅ 완료",
                    delta=f"{today_screening['total_count']}개 분석"
                )
            else:
                st.metric(
                    label="스크리닝 상태",
                    value="⏳ 대기",
                    delta="아직 실행 전"
                )
        
        with col2:
            hit_rate = load_hit_rate(days=30, top3_only=True)
            st.metric(
                label="30일 승률 (TOP3)",
                value=f"{hit_rate['hit_rate']:.1f}%",
                delta=f"{hit_rate['hit_count']}/{hit_rate['total_count']}"
            )
        
        with col3:
            st.metric(
                label="평균 갭 수익률",
                value=format_percent(hit_rate.get('avg_gap_rate', 0)),
            )
        
        with col4:
            recent = load_recent_screenings(days=30)
            st.metric(
                label="최근 30일 스크리닝",
                value=f"{len(recent)}회",
            )
        
        st.markdown("---")
        
        # ==================== 오늘의 TOP3 ====================
        col_left, col_right = st.columns([2, 1])
        
        with col_left:
            st.subheader("🏆 오늘의 TOP3")
            
            if today_screening:
                top3_items = load_screening_items(today_screening['id'], top3_only=True)
                
                if top3_items:
                    for i, item in enumerate(top3_items, 1):
                        medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
                        
                        with st.container():
                            cols = st.columns([0.5, 2, 1.5, 1, 1])
                            cols[0].markdown(f"### {medal}")
                            cols[1].markdown(f"**{item['stock_name']}** ({item['stock_code']})")
                            cols[2].markdown(f"점수: **{item['score_total']:.1f}**점")
                            
                            change_class = "positive" if item['change_rate'] > 0 else "negative"
                            cols[3].markdown(f"<span class='{change_class}'>{format_percent(item['change_rate'])}</span>", unsafe_allow_html=True)
                            cols[4].markdown(f"CCI: {item['raw_cci']:.0f}" if item['raw_cci'] else "")
                else:
                    st.info("선정된 종목이 없습니다.")
            else:
                st.info("오늘 스크리닝이 아직 실행되지 않았습니다. (15:00 예정)")
        
        with col_right:
            st.subheader("📅 스케줄")
            st.markdown("""
            | 시간 | 작업 |
            |------|------|
            | 12:30 | 프리뷰 알림 |
            | 15:00 | 최종 TOP3 |
            | 16:30 | 익일 결과 수집 |
            """)
            
            st.subheader("⚖️ 현재 가중치")
            weights = load_weights()
            for name, weight in weights.items():
                bar_length = int(weight * 20)
                st.markdown(f"`{name}`: {'█' * bar_length}{'░' * (50 - bar_length)} **{weight:.2f}**")
        
        st.markdown("---")
        
        # ==================== 전일 TOP3 성과 ====================
        st.subheader("📈 전일 TOP3 성과")
        
        yesterday = date.today() - timedelta(days=1)
        from dashboard.utils.data_loader import load_screening_items_by_date
        
        # DB에서 전일 스크리닝 데이터와 익일 결과 조회
        from src.infrastructure.database import get_database
        db = get_database()
        
        yesterday_results = db.fetch_all(
            """
            SELECT 
                si.stock_name, si.stock_code, si.rank, si.score_total,
                ndr.gap_rate, ndr.is_open_up
            FROM screenings s
            JOIN screening_items si ON s.id = si.screening_id AND si.is_top3 = 1
            LEFT JOIN next_day_results ndr ON si.id = ndr.screening_item_id
            WHERE s.screen_date = ?
            ORDER BY si.rank
            """,
            (yesterday.isoformat(),)
        )
        
        if yesterday_results:
            cols = st.columns(3)
            for i, row in enumerate(yesterday_results[:3]):
                with cols[i]:
                    gap = row['gap_rate'] if row['gap_rate'] else None
                    emoji = get_result_emoji(row['is_open_up']) if row['is_open_up'] is not None else "⏳"
                    
                    st.markdown(f"""
                    <div class="metric-card">
                        <h4>{["🥇", "🥈", "🥉"][i]} {row['stock_name']}</h4>
                        <p style="font-size: 24px; font-weight: bold;">
                            {format_percent(gap) if gap else "대기중"}
                        </p>
                        <p>{emoji}</p>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.info("전일 스크리닝 결과가 없습니다.")
        
        st.markdown("---")
        
        # ==================== 빠른 링크 ====================
        st.subheader("🔗 빠른 링크")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            if st.button("📋 스크리닝 기록", use_container_width=True):
                st.switch_page("pages/01_📊_Overview.py")
        
        with col2:
            if st.button("📈 성과 분석", use_container_width=True):
                st.switch_page("pages/03_📈_Analysis.py")
        
        with col3:
            if st.button("⚖️ 가중치 관리", use_container_width=True):
                st.switch_page("pages/02_🔍_Screening.py")
        
        with col4:
            if st.button("🔍 종목 검색", use_container_width=True):
                st.switch_page("pages/04_📝_Journal.py")
        
    except Exception as e:
        st.error(f"데이터 로드 오류: {e}")
        st.info("DB가 초기화되지 않았을 수 있습니다. 스크리닝을 먼저 실행해주세요.")
    
    # 푸터
    st.markdown("---")
    st.markdown("""
    <div style='text-align: center; color: #888;'>
        ClosingBell v1.1 | Made with ❤️ using Streamlit
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
