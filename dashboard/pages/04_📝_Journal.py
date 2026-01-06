"""
Journal 페이지

매매일지 관리
"""

import streamlit as st
import sys
from pathlib import Path
from datetime import date, datetime
import pandas as pd

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

st.set_page_config(page_title="Journal", page_icon="📝", layout="wide")

st.title("📝 Trade Journal")
st.markdown("---")


def load_journal_data():
    """매매일지 데이터 로드"""
    from src.infrastructure.database import init_database
    from src.infrastructure.repository import get_trade_journal_repository
    
    init_database()
    return get_trade_journal_repository()


try:
    journal_repo = load_journal_data()
    
    # 탭 생성
    tab1, tab2 = st.tabs(["📋 매매 기록", "➕ 새 기록 추가"])
    
    # 매매 기록 탭
    with tab1:
        st.subheader("📋 매매 기록")
        
        # 기간 선택
        col1, col2 = st.columns([1, 3])
        with col1:
            days = st.selectbox("조회 기간", [7, 14, 30, 60, 90, 180], index=2)
        
        trades = journal_repo.get_trades(days=days)
        
        if trades:
            # 요약 통계
            summary = journal_repo.get_trade_summary()
            
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("총 거래 횟수", f"{summary.get('total_trades', 0)}회")
            
            with col2:
                total_buy = summary.get('total_buy', 0) or 0
                st.metric("총 매수 금액", f"{total_buy:,.0f}원")
            
            with col3:
                total_sell = summary.get('total_sell', 0) or 0
                st.metric("총 매도 금액", f"{total_sell:,.0f}원")
            
            with col4:
                avg_return = summary.get('avg_return_rate', 0) or 0
                st.metric("평균 수익률", f"{avg_return:+.2f}%")
            
            st.markdown("---")
            
            # 거래 목록 테이블
            df_data = []
            for t in trades:
                df_data.append({
                    "날짜": t['trade_date'],
                    "종목명": t['stock_name'],
                    "코드": t['stock_code'],
                    "구분": "🔴 매수" if t['trade_type'] == 'BUY' else "🔵 매도",
                    "가격": f"{t['price']:,}",
                    "수량": f"{t['quantity']:,}",
                    "금액": f"{t['total_amount']:,}",
                    "수익률": f"{t.get('return_rate', 0) or 0:+.2f}%" if t.get('return_rate') else "-",
                    "메모": t.get('memo', '')[:20],
                })
            
            df = pd.DataFrame(df_data)
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("매매 기록이 없습니다. '새 기록 추가' 탭에서 기록을 추가하세요.")
    
    # 새 기록 추가 탭
    with tab2:
        st.subheader("➕ 새 매매 기록 추가")
        
        with st.form("new_trade_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                trade_date = st.date_input("거래일", value=date.today())
                stock_code = st.text_input("종목코드", placeholder="예: 005930")
                stock_name = st.text_input("종목명", placeholder="예: 삼성전자")
                trade_type = st.selectbox("거래 구분", ["BUY", "SELL"], format_func=lambda x: "매수" if x == "BUY" else "매도")
            
            with col2:
                price = st.number_input("가격", min_value=0, step=100)
                quantity = st.number_input("수량", min_value=0, step=1)
                memo = st.text_area("메모", placeholder="매매 사유 등")
            
            submitted = st.form_submit_button("💾 저장", use_container_width=True)
            
            if submitted:
                if stock_code and stock_name and price > 0 and quantity > 0:
                    try:
                        journal_repo.add_trade(
                            trade_date=trade_date,
                            stock_code=stock_code,
                            stock_name=stock_name,
                            trade_type=trade_type,
                            price=int(price),
                            quantity=int(quantity),
                            memo=memo,
                        )
                        st.success("✅ 매매 기록이 저장되었습니다!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"저장 실패: {e}")
                else:
                    st.warning("모든 필수 항목을 입력해주세요.")
        
        st.markdown("---")
        
        # 빠른 입력 (오늘 TOP3에서)
        st.subheader("⚡ 빠른 입력 (오늘 TOP3)")
        
        from src.infrastructure.repository import get_screening_repository
        screening_repo = get_screening_repository()
        today_screening = screening_repo.get_screening_by_date(date.today())
        
        if today_screening:
            top3 = screening_repo.get_top3_items(today_screening['id'])
            
            for item in top3:
                col1, col2, col3 = st.columns([2, 1, 1])
                
                with col1:
                    st.write(f"**{item['stock_name']}** ({item['stock_code']})")
                    st.write(f"현재가: {item['current_price']:,}원")
                
                with col2:
                    if st.button(f"매수", key=f"buy_{item['stock_code']}"):
                        st.session_state['quick_buy'] = item
                        st.info(f"{item['stock_name']} 매수 기록을 위 폼에서 작성하세요.")
                
                with col3:
                    if st.button(f"매도", key=f"sell_{item['stock_code']}"):
                        st.session_state['quick_sell'] = item
                        st.info(f"{item['stock_name']} 매도 기록을 위 폼에서 작성하세요.")
        else:
            st.info("오늘 스크리닝 결과가 없습니다.")

except Exception as e:
    st.error(f"데이터 로드 실패: {e}")
    st.exception(e)
