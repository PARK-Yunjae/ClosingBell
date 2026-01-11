"""
📋 스크리닝 기록 페이지

기능:
- 날짜별 스크리닝 결과 조회
- TOP3/전체 종목 토글
- 익일 결과 표시
- CSV 다운로드
"""

import streamlit as st
import sys
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

st.set_page_config(
    page_title="스크리닝 기록 - ClosingBell",
    page_icon="📋",
    layout="wide",
)

st.title("📋 스크리닝 기록")
st.markdown("---")

try:
    from dashboard.utils.data_loader import (
        load_recent_screenings,
        load_screening_by_date,
        load_screening_items,
        load_screening_history_df,
    )
    from dashboard.utils.calculations import format_percent, get_result_emoji
    
    # ==================== 필터 ====================
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        # 최근 스크리닝 날짜 목록
        recent = load_recent_screenings(days=60)
        available_dates = [r['screen_date'] for r in recent] if recent else []
        
        if available_dates:
            selected_date = st.selectbox(
                "📅 날짜 선택",
                options=available_dates,
                format_func=lambda x: f"{x} ({['월','화','수','목','금','토','일'][date.fromisoformat(x).weekday()]})"
            )
        else:
            selected_date = None
            st.warning("스크리닝 기록이 없습니다.")
    
    with col2:
        top3_only = st.checkbox("🏆 TOP3만 보기", value=False)
    
    with col3:
        show_details = st.checkbox("📊 상세 점수 보기", value=False)
    
    st.markdown("---")
    
    # ==================== 스크리닝 결과 테이블 ====================
    if selected_date:
        screening = load_screening_by_date(date.fromisoformat(selected_date))
        
        if screening:
            # 스크리닝 요약
            st.subheader(f"📊 {selected_date} 스크리닝 결과")
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("분석 종목", f"{screening['total_count']}개")
            col2.metric("스크리닝 시각", screening['screen_time'])
            col3.metric("상태", "✅ 성공" if screening['status'] == 'SUCCESS' else "❌ 실패")
            col4.metric("실행 시간", f"{screening.get('execution_time_sec', 0):.1f}초")
            
            st.markdown("---")
            
            # 종목 목록
            items = load_screening_items(screening['id'], top3_only=top3_only)
            
            if items:
                # DataFrame으로 변환
                df = pd.DataFrame(items)
                
                # 컬럼 선택
                display_cols = ['rank', 'stock_name', 'stock_code', 'score_total', 'change_rate', 'raw_cci']
                
                if show_details:
                    display_cols.extend([
                        'score_cci_value', 'score_cci_slope', 'score_ma20_slope',
                        'score_candle', 'score_change'
                    ])
                
                # 익일 결과 조회
                from src.infrastructure.database import get_database
                db = get_database()
                
                next_day_data = {}
                for item in items:
                    ndr = db.fetch_one(
                        "SELECT gap_rate, is_open_up FROM next_day_results WHERE screening_item_id = ?",
                        (item['id'],)
                    )
                    if ndr:
                        next_day_data[item['id']] = dict(ndr)
                
                # 결과 컬럼 추가
                df['익일갭'] = df['id'].apply(
                    lambda x: format_percent(next_day_data[x]['gap_rate']) if x in next_day_data and next_day_data[x]['gap_rate'] else "대기중"
                )
                df['결과'] = df['id'].apply(
                    lambda x: get_result_emoji(next_day_data[x]['is_open_up']) if x in next_day_data and next_day_data[x]['is_open_up'] is not None else "⏳"
                )
                
                display_cols.extend(['익일갭', '결과'])
                
                # 컬럼명 변경
                col_names = {
                    'rank': '순위',
                    'stock_name': '종목명',
                    'stock_code': '종목코드',
                    'score_total': '총점',
                    'change_rate': '당일등락률',
                    'raw_cci': 'CCI',
                    'score_cci_value': 'CCI값점수',
                    'score_cci_slope': 'CCI기울기',
                    'score_ma20_slope': 'MA20기울기',
                    'score_candle': '양봉품질',
                    'score_change': '상승률점수',
                }
                
                df_display = df[display_cols].rename(columns=col_names)
                
                # 스타일 적용
                def highlight_top3(row):
                    if row['순위'] <= 3:
                        return ['background-color: #fff3cd'] * len(row)
                    return [''] * len(row)
                
                st.dataframe(
                    df_display.style.apply(highlight_top3, axis=1),
                    use_container_width=True,
                    hide_index=True,
                )
                
                # CSV 다운로드
                csv = df_display.to_csv(index=False).encode('utf-8-sig')
                st.download_button(
                    label="📥 CSV 다운로드",
                    data=csv,
                    file_name=f"screening_{selected_date}.csv",
                    mime="text/csv",
                )
            else:
                st.info("종목 데이터가 없습니다.")
        else:
            st.warning("선택한 날짜의 스크리닝 데이터가 없습니다.")
    
    # ==================== 최근 스크리닝 히스토리 ====================
    st.markdown("---")
    st.subheader("📈 최근 스크리닝 히스토리")
    
    history_days = st.slider("조회 기간 (일)", 7, 90, 30)
    history_df = load_screening_history_df(days=history_days)
    
    if not history_df.empty:
        # 일별 요약
        daily_summary = history_df.groupby('screen_date').agg({
            'stock_code': 'count',
            'is_top3': 'sum',
            'is_open_up': lambda x: x.sum() if x.notna().any() else 0,
            'gap_rate': 'mean',
        }).reset_index()
        
        daily_summary.columns = ['날짜', '분석종목수', 'TOP3수', '승리수', '평균갭']
        daily_summary['평균갭'] = daily_summary['평균갭'].apply(
            lambda x: format_percent(x) if pd.notna(x) else "-"
        )
        
        st.dataframe(daily_summary, use_container_width=True, hide_index=True)
    else:
        st.info("스크리닝 히스토리가 없습니다.")

except Exception as e:
    st.error(f"오류 발생: {e}")
    import traceback
    st.code(traceback.format_exc())
    
