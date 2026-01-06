"""
Screening 페이지

스크리닝 결과 상세 조회
"""

import streamlit as st
import sys
from pathlib import Path
from datetime import date, datetime, timedelta
import pandas as pd

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

st.set_page_config(page_title="Screening", page_icon="🔍", layout="wide")

st.title("🔍 Screening Results")
st.markdown("---")


@st.cache_data(ttl=60)
def load_screening_data(screen_date):
    """스크리닝 데이터 로드 (캐시)"""
    from src.infrastructure.database import init_database
    from src.infrastructure.repository import get_screening_repository
    
    init_database()
    repo = get_screening_repository()
    
    screening = repo.get_screening_by_date(screen_date)
    if not screening:
        return None, []
    
    items = repo.get_screening_items(screening['id'])
    return screening, items


# 날짜 선택
col1, col2 = st.columns([1, 3])

with col1:
    selected_date = st.date_input(
        "날짜 선택",
        value=date.today(),
        max_value=date.today(),
    )

# 데이터 로드
screening, items = load_screening_data(selected_date)

if screening:
    with col2:
        st.success(f"✅ {screening['screen_date']} {screening['screen_time']} 스크리닝 결과")
        st.write(f"분석 종목: {screening['total_count']}개 | 상태: {screening['status']}")
    
    st.markdown("---")
    
    # 필터 옵션
    col1, col2, col3 = st.columns(3)
    
    with col1:
        min_score = st.slider("최소 점수", 0.0, 50.0, 0.0, 1.0)
    
    with col2:
        sort_by = st.selectbox(
            "정렬 기준",
            ["순위", "총점", "CCI값", "등락률", "거래대금"],
        )
    
    with col3:
        show_top_n = st.selectbox("표시 개수", [10, 20, 30, 50, "전체"])
    
    # 데이터 필터링
    filtered_items = [i for i in items if i['score_total'] >= min_score]
    
    # 정렬
    sort_map = {
        "순위": ("rank", False),
        "총점": ("score_total", True),
        "CCI값": ("score_cci_value", True),
        "등락률": ("change_rate", True),
        "거래대금": ("trading_value", True),
    }
    sort_key, reverse = sort_map[sort_by]
    filtered_items = sorted(filtered_items, key=lambda x: x.get(sort_key, 0), reverse=reverse)
    
    # 개수 제한
    if show_top_n != "전체":
        filtered_items = filtered_items[:show_top_n]
    
    # 테이블 데이터 준비
    df_data = []
    for item in filtered_items:
        df_data.append({
            "순위": item['rank'],
            "종목명": item['stock_name'],
            "코드": item['stock_code'],
            "현재가": f"{item['current_price']:,}",
            "등락률": f"{item['change_rate']:+.2f}%",
            "총점": f"{item['score_total']:.1f}",
            "CCI값": f"{item['score_cci_value']:.1f}",
            "CCI기울기": f"{item['score_cci_slope']:.1f}",
            "MA20": f"{item['score_ma20_slope']:.1f}",
            "양봉": f"{item['score_candle']:.1f}",
            "상승률": f"{item['score_change']:.1f}",
            "TOP3": "⭐" if item.get('is_top3') else "",
        })
    
    df = pd.DataFrame(df_data)
    
    st.subheader(f"📋 스크리닝 결과 ({len(filtered_items)}개)")
    
    # 테이블 표시
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "순위": st.column_config.NumberColumn(width="small"),
            "종목명": st.column_config.TextColumn(width="medium"),
            "코드": st.column_config.TextColumn(width="small"),
            "현재가": st.column_config.TextColumn(width="medium"),
            "등락률": st.column_config.TextColumn(width="small"),
            "총점": st.column_config.TextColumn(width="small"),
            "TOP3": st.column_config.TextColumn(width="small"),
        },
    )
    
    # 종목 상세 조회
    st.markdown("---")
    st.subheader("🔎 종목 상세")
    
    stock_names = [f"{i['stock_name']} ({i['stock_code']})" for i in items[:20]]
    selected_stock = st.selectbox("종목 선택", stock_names if stock_names else ["선택"])
    
    if selected_stock and selected_stock != "선택":
        stock_code = selected_stock.split("(")[1].rstrip(")")
        stock_data = next((i for i in items if i['stock_code'] == stock_code), None)
        
        if stock_data:
            col1, col2 = st.columns([1, 1])
            
            with col1:
                st.markdown(f"""
                ### {stock_data['stock_name']}
                - **종목코드**: {stock_data['stock_code']}
                - **현재가**: {stock_data['current_price']:,}원
                - **등락률**: {stock_data['change_rate']:+.2f}%
                - **거래대금**: {stock_data['trading_value']:,.0f}억원
                - **순위**: {stock_data['rank']}위
                - **총점**: {stock_data['score_total']:.1f}점
                """)
            
            with col2:
                # 레이더 차트
                from dashboard.components.charts import render_score_radar_chart
                
                fig = render_score_radar_chart(stock_data, f"{stock_data['stock_name']} 점수 분포")
                st.plotly_chart(fig, use_container_width=True)

else:
    st.warning(f"📭 {selected_date} 스크리닝 결과가 없습니다.")
    
    # 최근 스크리닝 목록
    from src.infrastructure.repository import get_screening_repository
    repo = get_screening_repository()
    recent = repo.get_recent_screenings(days=30)
    
    if recent:
        st.subheader("📅 최근 스크리닝 일자")
        for s in recent[:10]:
            if st.button(f"{s['screen_date']} ({s['total_count']}개)", key=s['screen_date']):
                st.session_state['selected_date'] = s['screen_date']
                st.rerun()
