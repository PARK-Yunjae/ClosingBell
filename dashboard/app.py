"""
ClosingBell 대시보드
====================

📊 감시종목 TOP5 20일 추적 + 유목민 공부법

실행 방법:
- cd dashboard && streamlit run app.py
- 또는 run_dashboard.bat 실행
"""

import streamlit as st
import sys
import os
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

# 전역상수 import
try:
    from src.config.app_config import (
        APP_VERSION, APP_NAME, APP_FULL_VERSION, AI_ENGINE,
        FOOTER_DASHBOARD, SIDEBAR_TITLE,
    )
except ImportError:
    # fallback
    APP_VERSION = "v8.0"
    APP_NAME = "ClosingBell"
    APP_FULL_VERSION = f"{APP_NAME} {APP_VERSION}"
    AI_ENGINE = "Gemini 2.5 Flash"
    FOOTER_DASHBOARD = APP_FULL_VERSION
    SIDEBAR_TITLE = f"🔔 {APP_NAME}"

# plotly import (Streamlit Cloud 호환)
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    st.error("⚠️ plotly 패키지를 찾을 수 없습니다. requirements.txt를 확인하세요.")

# Streamlit Cloud 모드 (API 키 불필요)
os.environ["DASHBOARD_ONLY"] = "true"

# 프로젝트 루트 추가 (dashboard 폴더에서 실행해도 동작)
current_dir = Path(__file__).parent
project_root = current_dir.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# NOTE: os.chdir() 호출 제거 - Streamlit multipage가 pages/ 폴더를 찾지 못하는 원인
# settings.py의 BASE_DIR이 이미 절대 경로를 사용하므로 불필요

st.set_page_config(
    page_title=APP_FULL_VERSION,
    page_icon="🔔",
    layout="wide",
)

# ==================== 사이드바 네비게이션 ====================
with st.sidebar:
    st.markdown(f"## {SIDEBAR_TITLE}")
    st.page_link("app.py", label="홈")
    st.page_link("pages/1_top5_tracker.py", label="감시종목 TOP5")
    st.page_link("pages/2_nomad_study.py", label="유목민 공부법")
    st.page_link("pages/3_stock_search.py", label="종목 검색")
    st.page_link("pages/4_broker_flow.py", label="거래원 수급")
    st.page_link("pages/5_stock_analysis.py", label="종목 심층 분석")
    st.markdown("---")

# ==================== Repository 싱글톤 ====================
@st.cache_resource
def get_cached_repositories():
    """Repository 인스턴스 캐시 (1회 생성)"""
    try:
        from src.infrastructure.repository import (
            get_repository,
            get_top5_history_repository,
            get_nomad_candidates_repository,
        )
        return {
            'main': get_repository(),
            'top5': get_top5_history_repository(),
            'nomad': get_nomad_candidates_repository(),
        }
    except Exception as e:
        st.error(f"Repository 초기화 실패: {e}")
        return None

# ==================== 헤더 ====================
st.title(f"🔔 {APP_FULL_VERSION}")
st.markdown("**감시종목 TOP5 추적 + 유목민 공부법** | _차트가 모든 것을 반영한다_ 📈")
st.markdown("---")


# ==================== 데이터 로드 ====================
@st.cache_data(ttl=300)
def load_all_results(days=60):
    """익일 결과 데이터 로드"""
    try:
        repos = get_cached_repositories()
        if not repos:
            return []
        
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        
        results = repos['main'].get_next_day_results(start_date=start_date, end_date=end_date)
        return results
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return []


@st.cache_data(ttl=300)
def load_top5_summary():
    """TOP5 20일 추적 요약"""
    try:
        repos = get_cached_repositories()
        if not repos:
            return {'dates_count': 0, 'latest_date': None}
        
        dates = repos['top5'].get_dates_with_data(30)
        return {'dates_count': len(dates), 'latest_date': dates[0] if dates else None}
    except Exception:
        return {'dates_count': 0, 'latest_date': None}


@st.cache_data(ttl=300)
def load_nomad_summary():
    """유목민 공부법 요약"""
    try:
        repos = get_cached_repositories()
        if not repos:
            return {'dates_count': 0, 'latest_date': None}
        
        dates = repos['nomad'].get_dates_with_data(30)
        return {'dates_count': len(dates), 'latest_date': dates[0] if dates else None}
    except Exception:
        return {'dates_count': 0, 'latest_date': None}


@st.cache_data(ttl=300)
def load_nomad_occurrence_ranking(days=30, top_n=15):
    """유목민 등장 횟수 랭킹 (최근 N일)"""
    try:
        import sqlite3
        from pathlib import Path
        
        db_path = Path(__file__).parent.parent / "data" / "screener.db"
        if not db_path.exists():
            return pd.DataFrame()
        
        conn = sqlite3.connect(db_path)
        
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        
        df = pd.read_sql_query(f"""
            SELECT 
                stock_code,
                stock_name,
                COUNT(*) as count,
                MAX(change_rate) as max_change,
                MAX(study_date) as last_date
            FROM nomad_candidates
            WHERE study_date >= '{cutoff}'
            GROUP BY stock_code, stock_name
            ORDER BY count DESC
            LIMIT {top_n}
        """, conn)
        
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def calc_nomad_win_rates():
    """유목민 등장 횟수 그룹별 승률 실시간 계산"""
    try:
        import sqlite3
        from pathlib import Path
        
        db_path = Path(__file__).parent.parent / "data" / "screener.db"
        ohlcv_path = Path(os.getenv("DATA_DIR", str(Path(__file__).parent.parent))) / "ohlcv_kiwoom"
        
        if not db_path.exists():
            return None
        
        conn = sqlite3.connect(db_path)
        
        # 유목민 데이터 로드
        df_nomad = pd.read_sql_query("""
            SELECT stock_code, study_date
            FROM nomad_candidates
            ORDER BY stock_code, study_date
        """, conn)
        conn.close()
        
        if df_nomad.empty:
            return None
        
        # 종목별 총 등장 횟수
        occurrence_count = df_nomad.groupby('stock_code').size().reset_index(name='total_count')
        df_nomad = df_nomad.merge(occurrence_count, on='stock_code')
        
        # D+5 수익률 계산 (샘플링 - 최대 300건)
        sample = df_nomad.sample(n=min(300, len(df_nomad)), random_state=42)
        
        results = []
        for _, row in sample.iterrows():
            try:
                csv_path = ohlcv_path / f"{row['stock_code']}.csv"
                if not csv_path.exists():
                    continue
                
                ohlcv = pd.read_csv(csv_path)
                ohlcv['date'] = pd.to_datetime(ohlcv['date'])
                ohlcv = ohlcv.sort_values('date')
                
                base_date = pd.to_datetime(row['study_date'])
                future = ohlcv[ohlcv['date'] > base_date]
                
                if len(future) >= 5:
                    base_row = ohlcv[ohlcv['date'] <= base_date].iloc[-1]
                    d5_close = future.iloc[4]['close']
                    d5_return = (d5_close / base_row['close'] - 1) * 100
                    
                    results.append({
                        'total_count': row['total_count'],
                        'd5_return': d5_return
                    })
            except:
                pass
        
        if not results:
            return None
        
        df_results = pd.DataFrame(results)
        
        # 그룹별 승률 계산
        bins = [0, 3, 7, 12, 100]
        labels = ['1~3회', '4~7회', '8~12회', '13회+']
        df_results['group'] = pd.cut(df_results['total_count'], bins=bins, labels=labels)
        
        win_rates = {}
        for group in labels:
            subset = df_results[df_results['group'] == group]['d5_return']
            if len(subset) >= 3:
                win_rates[group] = {
                    'win_rate': (subset > 0).mean() * 100,
                    'n': len(subset)
                }
        
        return win_rates
    except Exception:
        return None


# ==================== 통계 함수 ====================
def calc_stats(results):
    """승률 통계 계산"""
    if not results:
        return {'total': 0, 'wins': 0, 'win_rate': 0, 'avg_gap': 0, 'avg_high': 0}
    
    total = len(results)
    wins = sum(1 for r in results if (r.get('gap_rate') or 0) > 0)
    avg_gap = sum(r.get('gap_rate') or 0 for r in results) / total
    avg_high = sum(r.get('high_change_rate') or 0 for r in results) / total
    
    return {
        'total': total,
        'wins': wins,
        'win_rate': (wins / total * 100) if total > 0 else 0,
        'avg_gap': avg_gap,
        'avg_high': avg_high,
    }


def create_cumulative_chart(results, title):
    """누적 수익률 차트"""
    if not results or not PLOTLY_AVAILABLE:
        return None
    
    df = pd.DataFrame(results)
    df['screen_date'] = pd.to_datetime(df['screen_date'])
    
    daily = df.groupby('screen_date')['gap_rate'].mean().reset_index()
    daily = daily.sort_values('screen_date')
    daily['gap_rate'] = daily['gap_rate'].fillna(0)
    daily['cumulative'] = (1 + daily['gap_rate'] / 100).cumprod() - 1
    daily['cumulative_pct'] = daily['cumulative'] * 100
    
    colors = ['#4CAF50' if x > 0 else '#F44336' for x in daily['gap_rate']]
    
    fig = make_subplots(
        rows=2, cols=1,
        row_heights=[0.7, 0.3],
        shared_xaxes=True,
        vertical_spacing=0.05,
    )
    
    fig.add_trace(
        go.Scatter(
            x=daily['screen_date'],
            y=daily['cumulative_pct'],
            mode='lines+markers',
            name='누적 수익률',
            line=dict(color='#2196F3', width=2),
            marker=dict(size=5),
            fill='tozeroy',
            fillcolor='rgba(33, 150, 243, 0.1)',
        ),
        row=1, col=1
    )
    
    fig.add_trace(
        go.Bar(
            x=daily['screen_date'],
            y=daily['gap_rate'],
            name='일별 갭수익률',
            marker_color=colors,
        ),
        row=2, col=1
    )
    
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5, row=1, col=1)
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5, row=2, col=1)
    
    fig.update_layout(
        title=dict(text=title, font=dict(size=16)),
        height=400,
        margin=dict(l=10, r=10, t=40, b=10),
        showlegend=False,
        xaxis2_title="날짜",
        yaxis_title="누적 수익률 (%)",
        yaxis2_title="일별 (%)",
    )
    
    return fig


def create_gauge(value, title):
    """승률 게이지"""
    if not PLOTLY_AVAILABLE:
        return None
    
    color = "#4CAF50" if value >= 60 else "#FFC107" if value >= 50 else "#F44336"
    
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        number={'suffix': '%', 'font': {'size': 36}, 'valueformat': '.1f'},
        gauge={
            'axis': {'range': [0, 100], 'tickwidth': 1},
            'bar': {'color': color},
            'steps': [
                {'range': [0, 50], 'color': 'rgba(244, 67, 54, 0.1)'},
                {'range': [50, 60], 'color': 'rgba(255, 193, 7, 0.1)'},
                {'range': [60, 100], 'color': 'rgba(76, 175, 80, 0.1)'},
            ],
        },
        title={'text': title, 'font': {'size': 14}},
    ))
    
    fig.update_layout(height=180, margin=dict(l=20, r=20, t=40, b=10))
    return fig


# ==================== 기능 요약 카드 ====================
st.subheader("📌 주요 기능")

col1, col2 = st.columns(2)

with col1:
    top5_summary = load_top5_summary()
    st.markdown("### 📈 감시종목 TOP5")
    if top5_summary['dates_count'] > 0:
        st.success(f"✅ {top5_summary['dates_count']}일 데이터 | 최신: {top5_summary['latest_date']}")
    else:
        st.warning("⚠️ 데이터 없음")
    st.caption("D+1 ~ D+20 수익률 추적, CCI 하드필터(250+)")

with col2:
    nomad_summary = load_nomad_summary()
    st.markdown("### 📚 유목민 공부법")
    if nomad_summary['dates_count'] > 0:
        st.success(f"✅ {nomad_summary['dates_count']}일 데이터 | 최신: {nomad_summary['latest_date']}")
    else:
        st.warning("⚠️ 데이터 없음")
    st.caption("상한가/거래량천만 종목, 네이버 기업정보, AI 분석")

st.info("👈 **사이드바에서 페이지를 선택하세요**")
st.markdown("---")


# ==================== 메인 컨텐츠 (D+1 성과) ====================
st.subheader("📊 D+1 성과 요약 (최근 60일)")

results = load_all_results(60)

if results:
    stats = calc_stats(results)
    
    # 상단: 요약 카드
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("📈 총 거래", f"{stats['total']}건")
    col2.metric("✅ 승리", f"{stats['wins']}건")
    col3.metric("📊 승률", f"{stats['win_rate']:.1f}%", 
                delta="Good" if stats['win_rate'] >= 60 else None)
    col4.metric("💰 평균 갭", f"{stats['avg_gap']:+.1f}%")
    col5.metric("📈 평균 고가", f"{stats['avg_high']:+.1f}%")
    
    st.markdown("---")
    
    # 중단: 승률 게이지 + 누적 수익률
    col1, col2 = st.columns([1, 2])
    
    with col1:
        gauge_fig = create_gauge(stats['win_rate'], "전체 승률")
        if gauge_fig:
            st.plotly_chart(gauge_fig, width="stretch")
        else:
            st.metric("전체 승률", f"{stats['win_rate']:.1f}%")
        
        st.markdown("##### 📋 상세 통계")
        st.write(f"• 승리: {stats['wins']}건 / {stats['total']}건")
        st.write(f"• 평균 갭수익률: {stats['avg_gap']:+.1f}%")
        st.write(f"• 평균 고가수익률: {stats['avg_high']:+.1f}%")
    
    with col2:
        fig = create_cumulative_chart(results, "📈 누적 수익률 & 일별 갭수익률")
        if fig:
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("📊 차트를 표시하려면 plotly가 필요합니다.")
    
    st.markdown("---")
    
    # 하단: 최근 결과 테이블
    st.subheader(f"📋 최근 결과 ({min(stats['total'], 10)}건)")
    
    df = pd.DataFrame(results)
    df['screen_date'] = pd.to_datetime(df['screen_date'])
    df = df.sort_values('screen_date', ascending=False)
    
    display_df = df[['screen_date', 'stock_code', 'stock_name', 'gap_rate', 'high_change_rate']].head(10)
    display_df.columns = ['날짜', '종목코드', '종목명', '갭수익률(%)', '고가수익률(%)']
    display_df['날짜'] = display_df['날짜'].dt.strftime('%m/%d')
    display_df['갭수익률(%)'] = display_df['갭수익률(%)'].apply(lambda x: f"{x:+.1f}" if pd.notna(x) else "-")
    display_df['고가수익률(%)'] = display_df['고가수익률(%)'].apply(lambda x: f"{x:+.1f}" if pd.notna(x) else "-")
    
    st.dataframe(display_df, width="stretch", hide_index=True)

else:
    st.info("📭 D+1 성과 데이터가 없습니다. 백필 후 데이터가 쌓이면 표시됩니다.")

# ==================== 유목민 등장 횟수 랭킹 ====================
st.markdown("---")
st.subheader("🔥 유목민 등장 횟수 TOP 15 (최근 30일)")
st.caption("많이 등장할수록 모멘텀 강력! 승률은 D+5 기준 실시간 계산")

ranking_df = load_nomad_occurrence_ranking(days=30, top_n=15)

if not ranking_df.empty and PLOTLY_AVAILABLE:
    # 역순 정렬 (아래에서 위로 증가)
    ranking_df = ranking_df.sort_values('count', ascending=True)
    
    # 색상 지정 (등장 횟수에 따라)
    colors = []
    for cnt in ranking_df['count']:
        if cnt >= 13:
            colors.append('#FF5722')  # 모멘텀 강력
        elif cnt >= 8:
            colors.append('#FF9800')  # 주목
        elif cnt >= 4:
            colors.append('#4CAF50')  # 상승세
        else:
            colors.append('#9E9E9E')  # 초기
    
    fig = go.Figure(go.Bar(
        x=ranking_df['count'],
        y=ranking_df['stock_name'],
        orientation='h',
        marker_color=colors,
        text=ranking_df['count'].astype(str) + '회',
        textposition='outside',
    ))
    
    fig.update_layout(
        height=450,
        margin=dict(l=10, r=50, t=10, b=10),
        xaxis_title="등장 횟수",
        yaxis_title="",
        showlegend=False,
    )
    
    st.plotly_chart(fig, width='stretch')
    
    # 실시간 승률 계산
    win_rates = calc_nomad_win_rates()
    
    if win_rates:
        col1, col2, col3, col4 = st.columns(4)
        
        wr_13 = win_rates.get('13회+', {})
        wr_8 = win_rates.get('8~12회', {})
        wr_4 = win_rates.get('4~7회', {})
        wr_1 = win_rates.get('1~3회', {})
        
        col1.markdown(f"🔴 **13회+**: 모멘텀 강력 (승률 {wr_13.get('win_rate', 0):.0f}%, n={wr_13.get('n', 0)})")
        col2.markdown(f"🟠 **8~12회**: 주목 (승률 {wr_8.get('win_rate', 0):.0f}%, n={wr_8.get('n', 0)})")
        col3.markdown(f"🟢 **4~7회**: 상승세 (승률 {wr_4.get('win_rate', 0):.0f}%, n={wr_4.get('n', 0)})")
        col4.markdown(f"⚪ **1~3회**: 초기 (승률 {wr_1.get('win_rate', 0):.0f}%, n={wr_1.get('n', 0)})")
    else:
        col1, col2, col3, col4 = st.columns(4)
        col1.markdown("🔴 **13회+**: 모멘텀 강력")
        col2.markdown("🟠 **8~12회**: 주목")
        col3.markdown("🟢 **4~7회**: 상승세")
        col4.markdown("⚪ **1~3회**: 초기")
    
elif not ranking_df.empty:
    # plotly 없을 때 테이블로 표시
    st.dataframe(ranking_df, width='stretch', hide_index=True)
else:
    st.info("📭 유목민 데이터가 없습니다. 백필 후 표시됩니다.")


# ==================== 사이드바 ====================
st.sidebar.markdown("---")
st.sidebar.markdown(f"### {SIDEBAR_TITLE} {APP_VERSION}")

# v6.5: 종목 검색 (검색 페이지로 이동)
st.sidebar.markdown("---")
st.sidebar.markdown("### 🔎 빠른 검색")
search_query = st.sidebar.text_input(
    "종목코드/종목명",
    placeholder="예: 005930 또는 삼성",
    help="엔터 시 검색 페이지로 이동",
    label_visibility="collapsed",  # 영어 라벨 숨김
)

if search_query and len(search_query) >= 2:
    # 검색 페이지로 이동 (query parameter 전달)
    st.switch_page("pages/3_stock_search.py")

st.sidebar.markdown("---")
st.sidebar.markdown(f"""
**{APP_VERSION} 업데이트:**
- 점수제 구간 최적화
- CCI 160~180 최적
- 등락률 4~6% 최적
- 이격도 2~8% 최적
- 연속양봉 2~3일 최적
- DART + 네이버 기업정보

**전략:**
- 감시종목 TOP5 (점수제)
- 익일 시가 매도
""")


# ==================== 푸터 ====================
st.markdown("---")
st.caption(f"{FOOTER_DASHBOARD} | 점수제 구간 최적화 + AI 분석")
