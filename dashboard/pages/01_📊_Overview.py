"""
Overview 페이지

오늘의 TOP 3 종목 및 시스템 상태
"""

import streamlit as st
import sys
from pathlib import Path
from datetime import date, datetime, timedelta

# 프로젝트 루트
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

st.set_page_config(page_title="Overview", page_icon="📊", layout="wide")

st.title("📊 Overview")
st.markdown("---")


def load_data():
    """데이터 로드"""
    from src.infrastructure.database import init_database
    from src.infrastructure.repository import get_screening_repository, get_weight_repository
    
    init_database()
    return get_screening_repository(), get_weight_repository()


def render_top3_cards(items):
    """TOP 3 카드 렌더링"""
    cols = st.columns(3)
    
    for i, item in enumerate(items[:3]):
        with cols[i]:
            # 색상 결정
            if i == 0:
                bg_color = "linear-gradient(135deg, #ffd700 0%, #ffb700 100%)"  # 금색
                medal = "🥇"
            elif i == 1:
                bg_color = "linear-gradient(135deg, #c0c0c0 0%, #a0a0a0 100%)"  # 은색
                medal = "🥈"
            else:
                bg_color = "linear-gradient(135deg, #cd7f32 0%, #b06000 100%)"  # 동색
                medal = "🥉"
            
            st.markdown(f"""
            <div style="
                background: {bg_color};
                padding: 20px;
                border-radius: 15px;
                text-align: center;
                color: white;
                box-shadow: 0 4px 15px rgba(0,0,0,0.2);
            ">
                <h2 style="margin: 0;">{medal} {item['rank']}위</h2>
                <h3 style="margin: 10px 0;">{item['stock_name']}</h3>
                <p style="margin: 5px 0; font-size: 0.9em; opacity: 0.9;">{item['stock_code']}</p>
                <h2 style="margin: 10px 0;">{item['current_price']:,}원</h2>
                <p style="margin: 5px 0; font-size: 1.2em;">
                    {'+' if item['change_rate'] >= 0 else ''}{item['change_rate']:.2f}%
                </p>
                <p style="margin: 15px 0 5px 0; font-size: 1.3em; font-weight: bold;">
                    📊 {item['score_total']:.1f}점 / 50점
                </p>
            </div>
            """, unsafe_allow_html=True)
            
            # 점수 상세 expander
            with st.expander("점수 상세 보기"):
                st.write(f"CCI 값: {item['score_cci_value']:.1f}")
                st.write(f"CCI 기울기: {item['score_cci_slope']:.1f}")
                st.write(f"MA20 기울기: {item['score_ma20_slope']:.1f}")
                st.write(f"양봉 품질: {item['score_candle']:.1f}")
                st.write(f"상승률: {item['score_change']:.1f}")
                st.write(f"---")
                st.write(f"CCI 원시값: {item.get('raw_cci', 0):.1f}")


def render_recent_summary(screenings):
    """최근 7일 스크리닝 요약"""
    st.subheader("📅 최근 7일 스크리닝")
    
    if not screenings:
        st.info("최근 스크리닝 데이터가 없습니다.")
        return
    
    # 테이블로 표시
    data = []
    for s in screenings[:7]:
        data.append({
            "날짜": s['screen_date'],
            "시간": s['screen_time'],
            "분석 종목": f"{s['total_count']}개",
            "상태": s['status'],
        })
    
    st.dataframe(data, use_container_width=True, hide_index=True)


def render_weight_status(weight_repo):
    """가중치 현황"""
    st.subheader("⚖️ 현재 가중치")
    
    weights = weight_repo.get_weights()
    
    if not weights:
        st.warning("가중치가 설정되지 않았습니다.")
        return
    
    weight_dict = weights.to_dict()
    
    cols = st.columns(5)
    labels = {
        'cci_value': 'CCI 값',
        'cci_slope': 'CCI 기울기',
        'ma20_slope': 'MA20 기울기',
        'candle': '양봉 품질',
        'change': '상승률',
    }
    
    for i, (key, value) in enumerate(weight_dict.items()):
        with cols[i]:
            st.metric(
                label=labels.get(key, key),
                value=f"{value:.2f}",
            )
    
    # 가중치 변경 이력
    with st.expander("가중치 변경 이력"):
        history = weight_repo.get_weight_history(days=30)
        if history:
            for h in history[:10]:
                st.write(f"• {h['indicator']}: {h['old_weight']:.2f} → {h['new_weight']:.2f} ({h.get('changed_at', '')})")
        else:
            st.info("변경 이력이 없습니다.")


# 메인 로직
try:
    screening_repo, weight_repo = load_data()
    
    # 오늘 스크리닝 결과
    today = date.today()
    today_screening = screening_repo.get_screening_by_date(today)
    
    if today_screening:
        st.success(f"✅ 오늘 스크리닝 완료! ({today_screening['screen_time']})")
        
        # TOP 3 조회
        top3_items = screening_repo.get_top3_items(today_screening['id'])
        
        if top3_items:
            st.subheader("🏆 오늘의 TOP 3")
            render_top3_cards(top3_items)
        else:
            st.warning("TOP 3 종목이 없습니다.")
    else:
        st.info(f"⏳ 오늘({today}) 스크리닝이 아직 실행되지 않았습니다.")
        
        # 가장 최근 스크리닝 찾기
        recent = screening_repo.get_recent_screenings(days=7)
        if recent:
            latest = recent[0]
            st.write(f"가장 최근 스크리닝: {latest['screen_date']} {latest['screen_time']}")
            
            top3_items = screening_repo.get_top3_items(latest['id'])
            if top3_items:
                st.subheader(f"🏆 {latest['screen_date']} TOP 3")
                render_top3_cards(top3_items)
    
    st.markdown("---")
    
    # 2열 레이아웃
    col1, col2 = st.columns(2)
    
    with col1:
        render_recent_summary(screening_repo.get_recent_screenings(days=7))
    
    with col2:
        render_weight_status(weight_repo)
    
    st.markdown("---")
    
    # 시스템 상태
    st.subheader("🖥️ 시스템 정보")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.info(f"📅 현재 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    with col2:
        from src.infrastructure.scheduler import is_market_open
        market_status = "🟢 장 운영일" if is_market_open() else "🔴 휴장일"
        st.info(f"📈 오늘: {market_status}")
    
    with col3:
        st.info(f"🔔 다음 스크리닝: 15:00")

except Exception as e:
    st.error(f"데이터 로드 실패: {e}")
    st.exception(e)
