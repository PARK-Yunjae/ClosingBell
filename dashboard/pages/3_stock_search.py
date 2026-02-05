"""
ClosingBell - 종목 검색 페이지

종목코드/종목명으로 TOP5/유목민 출현 이력 검색
- 요약 카드 (등장 횟수, 평균 랭크, 최근 등장일)
- 필터 (기간, 소스, TOP5/유목민)
- 히스토리 테이블 (정렬 가능)
- 차트 (OHLCV 기반)
"""

import streamlit as st
import pandas as pd
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# 전역상수 import
try:
    from src.config.app_config import (
        APP_VERSION, APP_FULL_VERSION, SIDEBAR_TITLE, FOOTER_SEARCH,
    )
except ImportError:
    APP_VERSION = "v9.0"
    APP_FULL_VERSION = f"ClosingBell {APP_VERSION}"
    SIDEBAR_TITLE = "🔔 ClosingBell"
    FOOTER_SEARCH = f"{APP_FULL_VERSION} | 종목 상세 분석"

st.set_page_config(
    page_title=f"종목 검색 | {APP_FULL_VERSION}",
    page_icon="🔍",
    layout="wide",
)

# ==================== 사이드바 네비게이션 ====================
with st.sidebar:
    st.markdown(f"## {SIDEBAR_TITLE}")
st.page_link("app.py", label="홈")
st.page_link("pages/1_top5_tracker.py", label="종가매매 TOP5")
st.page_link("pages/2_nomad_study.py", label="유목민 공부법")
st.page_link("pages/3_stock_search.py", label="종목 검색")
st.page_link("pages/4_broker_flow.py", label="거래원 수급")
st.page_link("pages/5_stock_analysis.py", label="종목 심층 분석")
    st.markdown("---")

st.title("🔍 종목 검색")
st.markdown("종목코드 또는 종목명으로 **TOP5/유목민** 출현 이력을 검색합니다.")


# Repository 로드
@st.cache_resource
def get_repositories():
    from src.infrastructure.database import init_database
    from src.infrastructure.repository import (
        get_top5_history_repository,
        get_nomad_candidates_repository,
    )
    
    init_database()
    
    return {
        'top5': get_top5_history_repository(),
        'nomad': get_nomad_candidates_repository(),
    }


repos = get_repositories()


# OHLCV 차트 로드 (키움 기반, 로컬 파일 폴백)
OHLCV_PATH = Path(os.getenv("DATA_DIR", "C:/Coding/data")) / "ohlcv_kiwoom"

@st.cache_data(ttl=3600)
def load_ohlcv(stock_code: str, days: int = 60):
    """OHLCV 데이터 로드 (FinanceDataReader 우선, 로컬 파일 폴백)"""
    
    # 1. FinanceDataReader로 시도 (Streamlit Cloud 호환)
    try:
        import FinanceDataReader as fdr
        from datetime import timedelta
        
        end = datetime.now()
        start = end - timedelta(days=days + 30)  # 영업일 고려
        
        df = fdr.DataReader(stock_code, start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
        
        if df is not None and not df.empty:
            df = df.reset_index()
            df.columns = df.columns.str.lower()
            
            # 컬럼명 표준화
            if 'index' in df.columns:
                df = df.rename(columns={'index': 'date'})
            
            df = df.tail(days)  # 최근 N일
            
            if not df.empty:
                return df
    except Exception:
        pass  # FDR 실패시 로컬 파일 시도
    
    # 2. 로컬 파일 폴백 (로컬 개발용)
    try:
        file_path = OHLCV_PATH / f"{stock_code}.csv"
        if not file_path.exists():
            return None
        
        df = pd.read_csv(file_path)
        df.columns = df.columns.str.lower()
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date', ascending=False).head(days)
        df = df.sort_values('date')
        return df
    except Exception:
        return None


def create_candlestick_chart(df: pd.DataFrame, stock_name: str, highlight_dates: list = None):
    """캔들스틱 차트 생성 (한국식: 상승=빨강, 하락=파랑)"""
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        
        fig = make_subplots(
            rows=2, cols=1,
            row_heights=[0.7, 0.3],
            shared_xaxes=True,
            vertical_spacing=0.05,
        )
        
        # 캔들스틱 (한국식: 상승=빨강, 하락=파랑)
        fig.add_trace(
            go.Candlestick(
                x=df['date'],
                open=df['open'],
                high=df['high'],
                low=df['low'],
                close=df['close'],
                name='가격',
                increasing_line_color='#F44336',  # 상승=빨강
                increasing_fillcolor='#F44336',
                decreasing_line_color='#2196F3',  # 하락=파랑
                decreasing_fillcolor='#2196F3',
            ),
            row=1, col=1
        )
        
        # TOP5/유목민 출현일 표시
        if highlight_dates:
            for d in highlight_dates:
                fig.add_vline(
                    x=d,
                    line_dash="dash",
                    line_color="orange",
                    opacity=0.7,
                    row=1, col=1
                )
        
        # 거래량 (한국식: 양봉=빨강, 음봉=파랑)
        colors = ['#F44336' if c >= o else '#2196F3' 
                  for c, o in zip(df['close'], df['open'])]
        fig.add_trace(
            go.Bar(x=df['date'], y=df['volume'], name='거래량', marker_color=colors),
            row=2, col=1
        )
        
        fig.update_layout(
            title=f"📈 {stock_name} 차트 (최근 60일)",
            height=500,
            xaxis_rangeslider_visible=False,
            showlegend=False,
        )
        
        return fig
    except ImportError:
        return None


# ============================================================
# 사이드바: 검색 조건
# ============================================================
st.sidebar.header("🔍 검색 조건")

# 검색어 입력
search_query = st.sidebar.text_input(
    "종목코드 또는 종목명",
    placeholder="예: 005930 또는 삼성",
    help="2글자 이상 입력하세요"
)

# 기간 필터
period_options = {
    "최근 7일": 7,
    "최근 30일": 30,
    "최근 90일": 90,
    "최근 1년": 365,
    "전체": 9999,
}
selected_period = st.sidebar.selectbox("기간", list(period_options.keys()), index=1)
days_back = period_options[selected_period]

# 데이터 소스 필터
source_options = ["전체", "realtime", "backfill"]
selected_source = st.sidebar.selectbox("데이터 소스", source_options)

# 구분 필터
show_top5 = st.sidebar.checkbox("TOP5", value=True)
show_nomad = st.sidebar.checkbox("유목민", value=True)


# ============================================================
# 검색 함수 (캐시)
# ============================================================
@st.cache_data(ttl=60)
def search_top5(query: str, limit: int = 200):
    """TOP5 히스토리 검색"""
    return repos['top5'].search_occurrences(query, limit=limit)


@st.cache_data(ttl=60)
def search_nomad(query: str, limit: int = 200):
    """유목민 히스토리 검색"""
    return repos['nomad'].search_occurrences(query, limit=limit)


def filter_by_period(df: pd.DataFrame, days: int, date_col: str = 'screen_date') -> pd.DataFrame:
    """기간 필터"""
    if days >= 9999 or df.empty:
        return df
    
    cutoff = (datetime.now() - timedelta(days=days)).date()
    
    # 날짜 컬럼 처리
    df_copy = df.copy()
    if date_col in df_copy.columns:
        df_copy[date_col] = pd.to_datetime(df_copy[date_col]).dt.date
        return df_copy[df_copy[date_col] >= cutoff]
    
    return df_copy


def filter_by_source(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """소스 필터"""
    if source == "전체" or 'data_source' not in df.columns:
        return df
    return df[df['data_source'] == source]


# ============================================================
# 메인 검색 로직
# ============================================================
if search_query and len(search_query) >= 2:
    
    # 검색 실행
    top5_results = []
    nomad_results = []
    
    if show_top5:
        top5_results = search_top5(search_query)
    
    if show_nomad:
        nomad_results = search_nomad(search_query)
    
    # DataFrame 변환
    df_top5 = pd.DataFrame(top5_results) if top5_results else pd.DataFrame()
    df_nomad = pd.DataFrame(nomad_results) if nomad_results else pd.DataFrame()
    
    # 필터 적용
    if not df_top5.empty:
        df_top5 = filter_by_period(df_top5, days_back, 'screen_date')
        df_top5 = filter_by_source(df_top5, selected_source)
    
    if not df_nomad.empty:
        df_nomad = filter_by_period(df_nomad, days_back, 'study_date')
        # nomad는 data_source 컬럼이 없을 수 있음
    
    # ============================================================
    # 요약 카드
    # ============================================================
    st.markdown("---")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        top5_count = len(df_top5)
        st.metric("🏆 TOP5 등장", f"{top5_count}회")
    
    with col2:
        nomad_count = len(df_nomad)
        st.metric("📚 유목민 등장", f"{nomad_count}회")
    
    with col3:
        # 최근 등장일
        latest_date = None
        if not df_top5.empty:
            latest_top5 = pd.to_datetime(df_top5['screen_date']).max()
            latest_date = latest_top5
        if not df_nomad.empty:
            latest_nomad = pd.to_datetime(df_nomad['study_date']).max()
            if latest_date is None or latest_nomad > latest_date:
                latest_date = latest_nomad
        
        if latest_date:
            st.metric("📅 최근 등장", latest_date.strftime("%Y-%m-%d"))
        else:
            st.metric("📅 최근 등장", "-")
    
    with col4:
        # 평균 랭크 (TOP5만)
        if not df_top5.empty and 'rank' in df_top5.columns:
            avg_rank = df_top5['rank'].mean()
            st.metric("📊 평균 랭크", f"{avg_rank:.1f}")
        else:
            st.metric("📊 평균 랭크", "-")
    
    # ============================================================
    # TOP5 히스토리 테이블
    # ============================================================
    if show_top5 and not df_top5.empty:
        st.markdown("---")
        st.subheader("🏆 TOP5 출현 이력")
        
        # 컬럼 선택 및 포맷
        display_cols = ['screen_date', 'stock_code', 'stock_name', 'rank', 
                       'screen_score', 'grade', 'change_rate', 'cci', 
                       'trading_value', 'data_source']
        
        available_cols = [c for c in display_cols if c in df_top5.columns]
        df_display = df_top5[available_cols].copy()
        
        # 컬럼명 한글화
        col_names = {
            'screen_date': '날짜',
            'stock_code': '종목코드',
            'stock_name': '종목명',
            'rank': '순위',
            'screen_score': '점수',
            'grade': '등급',
            'change_rate': '등락률(%)',
            'cci': 'CCI',
            'trading_value': '거래대금(억)',
            'data_source': '소스',
        }
        df_display = df_display.rename(columns=col_names)
        
        # 날짜 정렬 (최신순)
        if '날짜' in df_display.columns:
            df_display = df_display.sort_values('날짜', ascending=False)
        
        # 숫자 포맷
        if '점수' in df_display.columns:
            df_display['점수'] = df_display['점수'].round(1)
        if '등락률(%)' in df_display.columns:
            df_display['등락률(%)'] = df_display['등락률(%)'].round(2)
        if 'CCI' in df_display.columns:
            df_display['CCI'] = df_display['CCI'].round(0)
        if '거래대금(억)' in df_display.columns:
            df_display['거래대금(억)'] = df_display['거래대금(억)'].round(0)
        
        st.dataframe(
            df_display,
            width='stretch',
            hide_index=True,
            height=min(400, 40 + len(df_display) * 35),
        )
        
        # 등급별 통계
        if 'grade' in df_top5.columns:
            st.markdown("**등급 분포:**")
            grade_counts = df_top5['grade'].value_counts().sort_index()
            cols = st.columns(len(grade_counts))
            for i, (grade, count) in enumerate(grade_counts.items()):
                with cols[i]:
                    emoji = {"S": "🏆", "A": "🥇", "B": "🥈", "C": "🥉", "D": "⚠️"}.get(grade, "")
                    st.write(f"{emoji} {grade}등급: **{count}회**")
    
    elif show_top5:
        st.info("🏆 TOP5 출현 이력이 없습니다.")
    
    # ============================================================
    # 유목민 히스토리 테이블
    # ============================================================
    if show_nomad and not df_nomad.empty:
        st.markdown("---")
        st.subheader("📚 유목민 출현 이력")
        
        # 컬럼 선택 및 포맷
        display_cols = ['study_date', 'stock_code', 'stock_name', 
                       'candidate_type', 'change_rate', 'score']
        
        available_cols = [c for c in display_cols if c in df_nomad.columns]
        df_display = df_nomad[available_cols].copy()
        
        # 컬럼명 한글화
        col_names = {
            'study_date': '날짜',
            'stock_code': '종목코드',
            'stock_name': '종목명',
            'candidate_type': '유형',
            'change_rate': '등락률(%)',
            'score': '점수',
        }
        df_display = df_display.rename(columns=col_names)
        
        # 날짜 정렬 (최신순)
        if '날짜' in df_display.columns:
            df_display = df_display.sort_values('날짜', ascending=False)
        
        # 유형 한글화
        if '유형' in df_display.columns:
            type_map = {
                'limit_up': '🔴 상한가',
                'volume_explosion': '🟡 거래량천만',
            }
            df_display['유형'] = df_display['유형'].map(type_map).fillna(df_display['유형'])
        
        st.dataframe(
            df_display,
            width='stretch',
            hide_index=True,
            height=min(400, 40 + len(df_display) * 35),
        )
        
        # 유형별 통계
        if 'candidate_type' in df_nomad.columns:
            st.markdown("**유형 분포:**")
            type_counts = df_nomad['candidate_type'].value_counts()
            cols = st.columns(len(type_counts))
            for i, (ctype, count) in enumerate(type_counts.items()):
                with cols[i]:
                    emoji = "🔴" if ctype == "limit_up" else "🟡"
                    label = "상한가" if ctype == "limit_up" else "거래량천만"
                    st.write(f"{emoji} {label}: **{count}회**")
    
    elif show_nomad:
        st.info("📚 유목민 출현 이력이 없습니다.")
    
    # ============================================================
    # 수익률 요약 (TOP5만, D+1~D+20 데이터가 있는 경우)
    # ============================================================
    if show_top5 and not df_top5.empty:
        st.markdown("---")
        st.subheader("📈 수익률 요약 (D+1 ~ D+20)")
        
        # D+1 수익률 조회 시도
        try:
            from src.infrastructure.repository import get_top5_prices_repository
            prices_repo = get_top5_prices_repository()
            
            # 각 TOP5 기록의 수익률 조회
            returns_data = []
            for _, row in df_top5.iterrows():
                if 'id' not in row:
                    continue
                    
                history_id = row['id']
                prices = prices_repo.get_by_history_id(history_id)
                
                if prices:
                    d1 = next((p for p in prices if p.get('day_number') == 1), None)
                    d5 = next((p for p in prices if p.get('day_number') == 5), None)
                    d20 = next((p for p in prices if p.get('day_number') == 20), None)
                    
                    returns_data.append({
                        'date': row.get('screen_date'),
                        'name': row.get('stock_name'),
                        'd1': d1.get('return_rate') if d1 else None,
                        'd5': d5.get('return_rate') if d5 else None,
                        'd20': d20.get('return_rate') if d20 else None,
                    })
            
            if returns_data:
                df_returns = pd.DataFrame(returns_data)
                
                # 평균 수익률 계산
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    d1_avg = df_returns['d1'].dropna().mean()
                    d1_win = (df_returns['d1'].dropna() > 0).mean() * 100
                    st.metric(
                        "D+1 평균", 
                        f"{d1_avg:.2f}%" if pd.notna(d1_avg) else "-",
                        f"승률 {d1_win:.0f}%" if pd.notna(d1_win) else None
                    )
                
                with col2:
                    d5_avg = df_returns['d5'].dropna().mean()
                    d5_win = (df_returns['d5'].dropna() > 0).mean() * 100
                    st.metric(
                        "D+5 평균", 
                        f"{d5_avg:.2f}%" if pd.notna(d5_avg) else "-",
                        f"승률 {d5_win:.0f}%" if pd.notna(d5_win) else None
                    )
                
                with col3:
                    d20_avg = df_returns['d20'].dropna().mean()
                    d20_win = (df_returns['d20'].dropna() > 0).mean() * 100
                    st.metric(
                        "D+20 평균", 
                        f"{d20_avg:.2f}%" if pd.notna(d20_avg) else "-",
                        f"승률 {d20_win:.0f}%" if pd.notna(d20_win) else None
                    )
                
                with col4:
                    total_samples = len(df_returns['d1'].dropna())
                    st.metric("샘플 수", f"{total_samples}건")
            else:
                st.info("수익률 데이터가 없습니다. (D+1~D+20 가격 데이터 수집 필요)")
                
        except Exception as e:
            st.info(f"수익률 데이터 조회 실패: {e}")
    
    # ============================================================
    # 차트 (OHLCV 기반)
    # ============================================================
    st.markdown("---")
    st.subheader("📊 차트")
    
    # 검색된 종목 중 첫 번째 종목 코드로 차트 표시
    chart_code = None
    chart_name = None
    highlight_dates = []
    
    if not df_top5.empty:
        chart_code = df_top5.iloc[0].get('stock_code')
        chart_name = df_top5.iloc[0].get('stock_name', chart_code)
        highlight_dates = pd.to_datetime(df_top5['screen_date']).tolist()
    elif not df_nomad.empty:
        chart_code = df_nomad.iloc[0].get('stock_code')
        chart_name = df_nomad.iloc[0].get('stock_name', chart_code)
        highlight_dates = pd.to_datetime(df_nomad['study_date']).tolist()
    
    if chart_code:
        ohlcv_df = load_ohlcv(chart_code, days=60)
        
        if ohlcv_df is not None and not ohlcv_df.empty:
            fig = create_candlestick_chart(ohlcv_df, chart_name, highlight_dates)
            if fig:
                st.plotly_chart(fig, width='stretch')
                st.caption("🟠 점선: TOP5/유목민 출현일")
            else:
                st.warning("차트 표시에 plotly가 필요합니다.")
        else:
            st.info(f"📁 OHLCV 데이터 없음: {chart_code}")
            st.caption(f"경로: {OHLCV_PATH / f'{chart_code}.csv'}")

else:
    # 검색어 미입력 시 안내
    st.info("👈 사이드바에서 **종목코드 또는 종목명**을 입력하세요 (2글자 이상)")
    
    # 최근 TOP5 요약
    st.markdown("---")
    st.subheader("📊 최근 TOP5 요약")
    
    try:
        recent_dates = repos['top5'].get_dates_with_data(days=5)
        
        if recent_dates:
            for d in recent_dates[:3]:
                top5 = repos['top5'].get_by_date(d)
                if top5:
                    names = [f"{t.get('stock_name', '?')} ({t.get('grade', '?')})" for t in top5[:5]]
                    st.write(f"**{d}**: {', '.join(names)}")
        else:
            st.info("TOP5 데이터가 없습니다.")
            
    except Exception as e:
        st.error(f"데이터 조회 실패: {e}")


# 푸터
st.markdown("---")
st.caption(FOOTER_SEARCH)
