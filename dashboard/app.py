"""
종가매매 스크리너 대시보드

Streamlit 멀티페이지 앱

실행:
    streamlit run dashboard/app.py
"""

import streamlit as st
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# 페이지 설정
st.set_page_config(
    page_title="종가매매 스크리너",
    page_icon="🔔",
    layout="wide",
    initial_sidebar_state="expanded",
)


# 사이드바 스타일
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
        background-color: #f0f2f6;
        border-radius: 10px;
        padding: 20px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
</style>
""", unsafe_allow_html=True)


def main():
    """메인 페이지"""
    
    # 헤더
    st.markdown('<h1 class="main-header">🔔 종가매매 스크리너</h1>', unsafe_allow_html=True)
    
    st.markdown("---")
    
    # 소개
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("""
        ### 👋 환영합니다!
        
        **종가매매 스크리너**는 기술적 분석 기반으로 종가매매에 적합한 종목을 
        자동으로 선별하는 도구입니다.
        
        #### 🎯 주요 기능
        
        - **📊 Overview**: 오늘의 TOP 3 종목 및 시스템 상태
        - **🔍 Screening**: 상세 스크리닝 결과 조회
        - **📈 Analysis**: 성과 분석 및 통계
        - **📝 Journal**: 매매일지 관리
        
        #### 📌 선별 기준
        
        1. 거래대금 300억 이상
        2. CCI(14일) 180 근처
        3. CCI 기울기 상승
        4. MA20 기울기 상승
        5. 양봉 품질 (윗꼬리 짧음)
        6. 적정 상승률 (5~20%)
        """)
    
    with col2:
        st.markdown("""
        ### 📅 스케줄
        
        | 시간 | 작업 |
        |------|------|
        | 12:30 | 프리뷰 알림 |
        | 15:00 | 최종 TOP3 |
        | 16:30 | 일일 학습 |
        
        ### 🔗 빠른 링크
        """)
        
        if st.button("📊 오늘의 TOP3 보기", use_container_width=True):
            st.switch_page("pages/01_📊_Overview.py")
        
        if st.button("🔍 전체 스크리닝 결과", use_container_width=True):
            st.switch_page("pages/02_🔍_Screening.py")
        
        if st.button("📈 성과 분석", use_container_width=True):
            st.switch_page("pages/03_📈_Analysis.py")
    
    st.markdown("---")
    
    # 시스템 상태
    st.subheader("🖥️ 시스템 상태")
    
    try:
        from src.infrastructure.database import get_database
        from src.infrastructure.repository import get_screening_repository, get_weight_repository
        from datetime import date
        
        db = get_database()
        screening_repo = get_screening_repository()
        weight_repo = get_weight_repository()
        
        # 오늘 스크리닝 결과 확인
        today_screening = screening_repo.get_screening_by_date(date.today())
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            if today_screening:
                st.metric(
                    label="오늘 스크리닝",
                    value="✅ 완료",
                    delta=f"{today_screening['total_count']}개 분석"
                )
            else:
                st.metric(
                    label="오늘 스크리닝",
                    value="⏳ 대기",
                    delta="아직 실행 전"
                )
        
        with col2:
            # 최근 30일 스크리닝 수
            recent = screening_repo.get_recent_screenings(days=30)
            st.metric(
                label="최근 30일 스크리닝",
                value=f"{len(recent)}회",
            )
        
        with col3:
            # 현재 가중치
            weights = weight_repo.get_weights()
            if weights:
                st.metric(
                    label="가중치 상태",
                    value="✅ 설정됨",
                )
            else:
                st.metric(
                    label="가중치 상태",
                    value="⚠️ 기본값",
                )
        
        with col4:
            st.metric(
                label="DB 연결",
                value="✅ 정상",
            )
        
    except Exception as e:
        st.error(f"시스템 상태 확인 실패: {e}")
    
    # 푸터
    st.markdown("---")
    st.markdown("""
    <div style='text-align: center; color: #888;'>
        종가매매 스크리너 v1.0 | Made with ❤️ using Streamlit
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
