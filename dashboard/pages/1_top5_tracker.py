"""
감시종목 TOP5 20일 추적 대시보드
================================

OHLCV 파일 기반 차트 + 가시성 개선
- 달력 UI
- 시가총액 필터 (대기업/중형주/소형주)
- 업종(섹터) 표시
- D+20 캔들차트 (OHLCV 파일 기반)
"""

import os
os.environ["DASHBOARD_ONLY"] = "true"  # Streamlit Cloud: API 등 검증 스킵

import streamlit as st
import sys
from pathlib import Path
from datetime import date, timedelta, datetime
import pandas as pd

# plotly import (Streamlit Cloud 호환)
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# 전역변수 import
try:
    from src.config.app_config import (
        APP_VERSION, APP_FULL_VERSION, SIDEBAR_TITLE, FOOTER_TOP5,
    )
except ImportError:
    APP_VERSION = "v10.1"
    APP_FULL_VERSION = f"ClosingBell {APP_VERSION}"
    SIDEBAR_TITLE = "🔔 ClosingBell"
    FOOTER_TOP5 = f"{APP_FULL_VERSION} | D+1 ~ D+20 수익률 분석"

# 업종 정보 조회
try:
    from src.services.company_service import get_sector_from_mapping
    SECTOR_AVAILABLE = True
except ImportError:
    SECTOR_AVAILABLE = False
    def get_sector_from_mapping(code):
        return None

# OHLCV 파일 경로 (환경변수 또는 기본값)
OHLCV_PATH = Path(os.getenv("DATA_DIR", "C:/Coding/data")) / "ohlcv"

st.set_page_config(
    page_title="감시종목 TOP5",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ==================== 사이드바 네비게이션 ====================
with st.sidebar:
    from dashboard.components.sidebar import render_sidebar_nav
    render_sidebar_nav()
    st.markdown("---")

st.title("📈 감시종목 TOP5 20일 추적")
st.markdown(f"**D+1 ~ D+20 수익률 분석** | _{APP_VERSION} 구간 최적화 점수제_")
st.markdown("---")


# ==================== 데이터 로드 ====================
@st.cache_data(ttl=300)
def load_top5_dates(limit=60):
    """TOP5 데이터가 있는 날짜 목록"""
    try:
        from src.infrastructure.repository import get_top5_history_repository
        repo = get_top5_history_repository()
        return repo.get_dates_with_data(limit)
    except Exception as e:
        st.error(f"날짜 로드 실패: {e}")
        return []


@st.cache_data(ttl=300)
def load_top5_data(screen_date):
    """특정 날짜의 TOP5 + 일별 가격"""
    try:
        from src.infrastructure.repository import (
            get_top5_history_repository,
            get_top5_prices_repository
        )
        
        history_repo = get_top5_history_repository()
        prices_repo = get_top5_prices_repository()
        
        top5 = history_repo.get_by_date(screen_date)
        
        for item in top5:
            item['daily_prices'] = prices_repo.get_by_history(item['id'])
        
        return top5
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return []


@st.cache_data(ttl=300)
def load_market_cap_data():
    """시가총액 데이터 로드"""
    try:
        import sqlite3
        db_path = project_root / 'data' / 'screener.db'
        conn = sqlite3.connect(str(db_path))
        df = pd.read_sql("""
            SELECT stock_code, market_cap 
            FROM nomad_candidates 
            WHERE market_cap > 0
        """, conn)
        conn.close()
        return dict(zip(df['stock_code'], df['market_cap']))
    except:
        return {}


@st.cache_data(ttl=3600)
def load_ohlcv_data(stock_code, start_date, days=25):
    """OHLCV 데이터 로드 (FinanceDataReader 우선, 로컬 파일 폴백)"""
    
    def _to_title(df):
        """컬럼명 Title case 통일"""
        df.columns = df.columns.str.lower().str.strip()
        # 날짜 컬럼 통일
        for col in ['index', 'unnamed: 0', '']:
            if col in df.columns:
                df = df.rename(columns={col: 'date'})
                break
        # Title case 변환
        df = df.rename(columns={
            'date': 'Date', 'open': 'Open', 'high': 'High',
            'low': 'Low', 'close': 'Close', 'volume': 'Volume',
        })
        required = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
        if not all(c in df.columns for c in required):
            return None
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df = df.dropna(subset=['Date'])
        return df[required]
    
    # 1. FinanceDataReader로 시도 (Streamlit Cloud 호환)
    try:
        import FinanceDataReader as fdr
        from datetime import timedelta
        
        start = pd.to_datetime(start_date)
        end = start + timedelta(days=days + 15)
        
        df = fdr.DataReader(stock_code, start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
        
        if df is not None and not df.empty:
            df = df.reset_index()
            df = _to_title(df)
            if df is not None and not df.empty:
                return df.head(days)
    except Exception:
        pass
    
    # 2. 로컬 파일 폴백 (로컬 개발용)
    try:
        csv_path = OHLCV_PATH / f"{stock_code}.csv"
        if not csv_path.exists():
            return None
        
        df = pd.read_csv(csv_path)
        df = _to_title(df)
        if df is None or df.empty:
            return None
        
        start = pd.to_datetime(start_date)
        df = df[df['Date'] >= start].head(days)
        
        return df if not df.empty else None
    except Exception:
        return None


def create_candlestick_chart(stock_name, stock_code, screen_date, screen_price):
    """캔들스틱 차트 생성 (OHLCV 기반)"""
    if not PLOTLY_AVAILABLE:
        return None
    
    df = load_ohlcv_data(stock_code, screen_date, 25)
    
    if df is None or df.empty:
        return None
    
    # 수익률 계산
    df['return_pct'] = (df['Close'] - screen_price) / screen_price * 100
    
    fig = make_subplots(
        rows=2, cols=1,
        row_heights=[0.7, 0.3],
        shared_xaxes=True,
        vertical_spacing=0.05,
    )
    
    # 캔들스틱
    fig.add_trace(
        go.Candlestick(
            x=df['Date'],
            open=df['Open'],
            high=df['High'],
            low=df['Low'],
            close=df['Close'],
            name='OHLC',
            increasing_line_color='#F44336',  # 한국식: 상승=빨강
            decreasing_line_color='#2196F3',  # 하락=파랑
        ),
        row=1, col=1
    )
    
    # 스크리닝 기준가 라인
    fig.add_hline(
        y=screen_price, 
        line_dash="dash", 
        line_color="orange", 
        annotation_text=f"기준가 {screen_price:,}원",
        row=1, col=1
    )
    
    # 거래량
    colors = ['#F44336' if c >= o else '#2196F3' for o, c in zip(df['Open'], df['Close'])]
    fig.add_trace(
        go.Bar(
            x=df['Date'],
            y=df['Volume'],
            name='거래량',
            marker_color=colors,
            opacity=0.7,
        ),
        row=2, col=1
    )
    
    fig.update_layout(
        title=dict(text=f"{stock_name} ({stock_code}) D+20 차트", font=dict(size=14)),
        height=400,
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis_rangeslider_visible=False,
        showlegend=False,
        yaxis_title="가격(원)",
        yaxis2_title="거래량",
    )
    
    return fig


def create_return_chart(stock_name, daily_prices, screen_price):
    """20일 수익률 라인 차트"""
    if not daily_prices or not PLOTLY_AVAILABLE:
        return None
    
    df = pd.DataFrame(daily_prices)
    
    fig = go.Figure()
    
    # 종가 수익률
    fig.add_trace(go.Scatter(
        x=df['days_after'],
        y=df['return_from_screen'],
        mode='lines+markers',
        name='종가 수익률',
        line=dict(color='#2196F3', width=2),
        marker=dict(size=6),
    ))
    
    # 고점 수익률
    if 'high_return' in df.columns:
        fig.add_trace(go.Scatter(
            x=df['days_after'],
            y=df['high_return'],
            mode='lines',
            name='고점 수익률',
            line=dict(color='#4CAF50', width=1, dash='dot'),
        ))
    
    # 저가 수익률
    if 'low_return' in df.columns:
        fig.add_trace(go.Scatter(
            x=df['days_after'],
            y=df['low_return'],
            mode='lines',
            name='저가 수익률',
            line=dict(color='#F44336', width=1, dash='dot'),
        ))
    
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    
    fig.update_layout(
        title=dict(text=f"{stock_name} 20일 수익률", font=dict(size=14)),
        height=300,
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis_title="D+N",
        yaxis_title="수익률 (%)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    
    return fig


def grade_color(grade):
    """등급 색상"""
    colors = {
        'S': '#FFD700',
        'A': '#4CAF50',
        'B': '#2196F3',
        'C': '#FFC107',
        'D': '#F44336',
    }
    return colors.get(grade, '#9E9E9E')


def format_market_cap(cap):
    """시가총액 포맷 (소수점 1자리)"""
    if cap is None or cap <= 0:
        return "-"
    if cap >= 10000:
        return f"{cap/10000:.1f}조"
    return f"{cap:,.0f}억"


# ==================== 사이드바 ====================
dates = load_top5_dates(60)
market_caps = load_market_cap_data()

if not dates:
    st.warning("📊 아직 수집된 TOP5 데이터가 없습니다.")
    st.markdown("""
    ### ✅ 데이터 수집 방법
    
    ```bash
    python main.py --backfill 20
    ```
    """)
    st.stop()

st.sidebar.markdown("### 📅 날짜 선택")

# v6.3.2: query param으로 날짜 받기 지원
query_date = st.query_params.get("date", None)
default_date = None

if query_date and query_date in dates:
    default_date = datetime.strptime(query_date, "%Y-%m-%d")
elif dates:
    default_date = datetime.strptime(dates[0], "%Y-%m-%d")
else:
    default_date = date.today()

selected_date = st.sidebar.date_input(
    "스크리닝 날짜",
    value=default_date,
    min_value=datetime.strptime(dates[-1], "%Y-%m-%d") if dates else date.today() - timedelta(days=60),
    max_value=datetime.strptime(dates[0], "%Y-%m-%d") if dates else date.today(),
)

# 휴장일 경고
try:
    from src.utils.market_calendar import is_market_open
    if not is_market_open(selected_date):
        weekday_kr = ['월','화','수','목','금','토','일'][selected_date.weekday()]
        st.sidebar.caption(f"⚠️ {selected_date.strftime('%m/%d')}({weekday_kr})은 휴장일입니다")
except ImportError:
    pass

selected_date_str = selected_date.strftime("%Y-%m-%d")

if selected_date_str not in dates:
    available = [d for d in dates if d <= selected_date_str]
    if available:
        selected_date_str = available[0]
        st.sidebar.warning(f"➡ {selected_date_str}로 표시")
    else:
        st.sidebar.error("데이터 없음")
        st.stop()

st.sidebar.markdown("---")

st.sidebar.markdown("### 💰 시가총액 필터")
cap_filter = st.sidebar.selectbox(
    "시가총액 기준",
    ["전체", "대기업 (1조+)", "중형주(3천억~1조)", "소형주(3천억 미만)"],
    index=0
)

st.sidebar.markdown("### 📊 점수제")
st.sidebar.success(f"{APP_VERSION}: 구간 최적화 점수제")

st.sidebar.markdown("---")
st.sidebar.caption(f"선택: {selected_date_str}")


# ==================== 메인 컨텐츠 ====================
top5_data = load_top5_data(selected_date_str)

if not top5_data:
    st.warning(f"📊 {selected_date_str} 날짜의 TOP5 데이터가 없습니다.")
    st.stop()

# 시가총액 정보 추가
for item in top5_data:
    item['market_cap'] = market_caps.get(item['stock_code'], 0)

# 시가총액 필터 적용
if cap_filter == "대기업 (1조+)":
    top5_data = [item for item in top5_data if item['market_cap'] >= 10000]
elif cap_filter == "중형주(3천억~1조)":
    top5_data = [item for item in top5_data if 3000 <= item['market_cap'] < 10000]
elif cap_filter == "소형주(3천억 미만)":
    top5_data = [item for item in top5_data if item['market_cap'] < 3000]

if not top5_data:
    st.warning(f"📊 {cap_filter} 조건에 맞는 종목이 없습니다.")
    st.stop()

# 요약 카드
st.subheader(f"📊 {selected_date_str} TOP5")

cols = st.columns(min(5, len(top5_data)))
for i, item in enumerate(top5_data[:5]):
    with cols[i]:
        d1_gap = None
        if item.get('daily_prices'):
            d1 = next((p for p in item['daily_prices'] if p['days_after'] == 1), None)
            if d1:
                d1_gap = d1.get('gap_rate')
        
        cap_str = format_market_cap(item['market_cap'])
        cap_badge = "🏢" if item['market_cap'] >= 10000 else ""
        
        cci = item.get('cci') or 0
        cci_warning = "⚠️" if cci > 220 else ""
        
        # v6.3.2: 거래대금/거래량
        trading_value = item.get('trading_value') or 0
        if trading_value >= 1000:
            tv_str = f"{trading_value/1000:.1f}조"
        elif trading_value >= 1:
            tv_str = f"{trading_value:.0f}억"
        else:
            tv_str = "-"
        
        # v6.4: AI 추천/위험도 배지 (강조)
        ai_risk = item.get('ai_risk_level', '')
        ai_rec = item.get('ai_recommendation', '')
        risk_badge = {'높음': '🔴', '보통': '🟡', '낮음': '🟢'}.get(ai_risk, '')
        rec_badge = {'매수': '🟢', '관망': '🟡', '매도': '🔴'}.get(ai_rec, '')
        rec_color = {'매수': '#4CAF50', '관망': '#FF9800', '매도': '#F44336'}.get(ai_rec, '#888888')
        
        # v6.3: DB에서 섹터 정보 (없으면 company_service에서 조회)
        sector = item.get('sector') or get_sector_from_mapping(item['stock_code']) or "-"
        is_leading = item.get('is_leading_sector', 0)
        sector_rank = item.get('sector_rank', 99)
        
        # 주도섹터 배지
        if is_leading:
            sector_display = f"🔥 {sector} (#{sector_rank})"
        else:
            sector_display = f"📌 {sector}"
        
        # pre-compute (f-string 안에서 조건문/중첩 피하기)
        _grade_bg = grade_color(item['grade'])
        _sector_color = '#FF6B6B' if is_leading else '#666'
        _short_html = ""
        _sr = item.get('short_ratio', 0) or 0
        if _sr >= 2:
            _short_html = f"<div style='font-size: 11px; color: #E53E3E; margin-bottom: 4px;'>📉 공매도 {_sr:.1f}%</div>"
        _d1_color = '#4CAF50' if d1_gap and d1_gap > 0 else '#F44336'
        _d1_text = f"{d1_gap:+.1f}%" if d1_gap is not None else "-"
        _ai_rec_text = ai_rec if ai_rec else '-'
        _ai_risk_text = ai_risk if ai_risk else '-'
        
        # HTML 들여쓰기 제거 및 구조 단순화 (Streamlit 렌더링 이슈 방지)
        card_html = f"""
<div style="background: linear-gradient(135deg, {_grade_bg}22, {_grade_bg}11); border-left: 5px solid {_grade_bg}; padding: 12px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
    <div style="font-size: 12px; color: #888; margin-bottom: 4px;">#{item['rank']} {cap_badge}</div>
    <div style="font-size: 18px; font-weight: bold; margin-bottom: 4px;">{item['stock_name']}</div>
    <div style="font-size: 12px; color: {_sector_color}; margin-bottom: 6px;">{sector_display}</div>
    <div style="font-size: 16px; margin-bottom: 4px;">
        <span style="color: {_grade_bg}; font-weight: bold;">{item['grade']}</span>
        <span style="color: #666;">({item['screen_score']:.1f}점)</span>
    </div>
    <div style="font-size: 14px; color: #444; margin-bottom: 2px;">{item['screen_price']:,}원</div>
    <div style="font-size: 12px; color: #666; margin-bottom: 6px;">{cap_str} | 거래 {tv_str}</div>
    <div style="font-size: 12px; color: #888; margin-bottom: 8px;">CCI: {cci:.0f} {cci_warning}</div>
    {_short_html}
    <div style="background: {rec_color}15; border-radius: 4px; padding: 6px; margin-bottom: 6px; text-align: center;">
        <span style="font-size: 14px; font-weight: bold; color: {rec_color};">
            {rec_badge} {_ai_rec_text} | {risk_badge} {_ai_risk_text}
        </span>
    </div>
    <div style="font-size: 16px; color: {_d1_color}; font-weight: bold; text-align: center;">
        D+1: {_d1_text}
    </div>
</div>
"""
        st.markdown(card_html, unsafe_allow_html=True)

st.markdown("---")

# 종목별 상세
st.subheader("📋 종목별 상세 분석")

for item in top5_data:
    cap_str = format_market_cap(item['market_cap'])
    cci = item.get('cci') or 0
    cci_badge = " ⚠️과열" if cci > 220 else ""
    
    # v6.3.1: 거래대금 표시
    trading_value = item.get('trading_value') or 0
    if trading_value >= 1000:
        tv_str = f"{trading_value/1000:.1f}조"
    elif trading_value >= 1:
        tv_str = f"{trading_value:.0f}억"
    else:
        tv_str = "-"
    
    # v6.3: DB에서 섹터 정보
    sector = item.get('sector') or get_sector_from_mapping(item['stock_code']) or ""
    is_leading = item.get('is_leading_sector', 0)
    sector_rank = item.get('sector_rank', 99)
    
    if sector:
        if is_leading:
            sector_str = f" | 🔥 {sector} (#{sector_rank})"
        else:
            sector_str = f" | 📌 {sector}"
    else:
        sector_str = ""
    
    with st.expander(
        f"**#{item['rank']} {item['stock_name']}** - {item['grade']}등급 ({item['screen_score']:.1f}점) | {tv_str}{sector_str}{cci_badge}", 
        expanded=(item['rank'] == 1)
    ):
        # 차트 선택 (캔들차트 기본)
        chart_type = st.radio(
            "차트 종류",
            ["📊 캔들차트 (OHLCV)", "📈 수익률 라인"],
            key=f"chart_{item['stock_code']}",
            horizontal=True
        )
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            if not PLOTLY_AVAILABLE:
                st.warning("📈 차트를 표시하려면 plotly가 필요합니다.")
            elif chart_type == "📊 캔들차트 (OHLCV)":
                fig = create_candlestick_chart(
                    item['stock_name'], 
                    item['stock_code'], 
                    selected_date_str,
                    item['screen_price']
                )
                if fig:
                    st.plotly_chart(fig, width="stretch")
                else:
                    st.info(f"📈 {item['stock_name']} OHLCV 데이터를 불러올 수 없습니다. 수익률 라인 차트를 사용해주세요.")
            else:  # 수익률 라인
                if item.get('daily_prices'):
                    fig = create_return_chart(item['stock_name'], item['daily_prices'], item['screen_price'])
                    if fig:
                        st.plotly_chart(fig, width="stretch")
                else:
                    st.info("아직 일별 가격 데이터가 없습니다.")
        
        with col2:
            st.markdown("##### 📋 스크리닝 지표")
            
            # 업종 표시
            st.write(f"📌 업종: **{sector if sector else '-'}**")
            
            cci_display = f"{cci:.0f}"
            if cci > 250:
                cci_display += " 🔴"
            elif cci > 220:
                cci_display += " ⚠️"
            elif 150 <= cci <= 170:
                cci_display += " ✅"
            
            st.write(f"📊 CCI: **{cci_display}**")
            st.write(f"📊 RSI: {item.get('rsi', '-'):.1f}" if item.get('rsi') else "📊 RSI: -")
            st.write(f"📊 등락률: {item.get('change_rate', 0):.1f}%")
            st.write(f"📊 이격도(20): {item.get('disparity_20', '-'):.1f}%" if item.get('disparity_20') else "📊 이격도(20): -")
            st.write(f"📊 연속양봉: {item.get('consecutive_up', 0)}일")
            st.write(f"💰 거래대금: **{tv_str}**")
            
            # v6.3.2: 거래량(만주 단위)
            volume = item.get('volume') or 0
            if volume >= 100_000_000:
                vol_str = f"{volume/100_000_000:.1f}억주"
            elif volume >= 10_000:
                vol_str = f"{volume/10_000:.0f}만주"
            else:
                vol_str = f"{volume:,}주" if volume else "-"
            st.write(f"📊 거래량: **{vol_str}**")
            
            # v10.1: 공매도 + 지지/저항
            short_ratio = item.get('short_ratio', 0)
            short_score_val = item.get('short_score', 0)
            sr_support = item.get('sr_nearest_support', 0)
            sr_resist = item.get('sr_nearest_resistance', 0)
            sr_tags = item.get('sr_tags', '')
            short_tags = item.get('short_tags', '')
            
            if short_ratio or sr_support:
                st.markdown("---")
                st.markdown("##### 📉 공매도 / 지지·저항")
            
            if short_ratio:
                short_emoji = "🔴" if short_ratio >= 5 else ("🟡" if short_ratio >= 2 else "🟢")
                st.write(f"📉 공매도 비중: **{short_ratio:.1f}%** {short_emoji}")
                if short_tags:
                    st.caption(f"  {short_tags}")
            
            if sr_support:
                price = item.get('screen_price', 0)
                if price > 0:
                    support_dist = (price - sr_support) / price * 100
                    resist_dist = (sr_resist - price) / price * 100 if sr_resist else 0
                    st.write(f"🟢 지지선: **{sr_support:,.0f}원** ({support_dist:.1f}% 하방)")
                    if sr_resist:
                        st.write(f"🔴 저항선: **{sr_resist:,.0f}원** ({resist_dist:.1f}% 상방)")
                    if sr_tags:
                        st.caption(f"  {sr_tags}")
            
            st.markdown("---")
            
            if item.get('daily_prices'):
                st.markdown("##### 📊 성과 요약")
                
                prices = item['daily_prices']
                max_return = max((p.get('high_return') or 0 for p in prices), default=0)
                min_return = min((p.get('low_return') or 0 for p in prices), default=0)
                final_return = prices[-1]['return_from_screen'] if prices else 0
                
                col_a, col_b = st.columns(2)
                col_a.metric("최대 수익", f"{max_return:+.1f}%")
                col_b.metric("최대 손실", f"{min_return:+.1f}%")
                st.metric("최종 수익", f"{final_return:+.1f}%")
        
        # v6.3.2: AI 분석 섹션
        if item.get('ai_summary'):
            st.markdown("---")
            
            ai_risk = item.get('ai_risk_level', '보통')
            ai_rec = item.get('ai_recommendation', '관망')
            risk_color = {'높음': '#4CAF50', '보통': '#FF9800', '낮음': '#F44336'}.get(ai_risk, '#888888')
            risk_emoji = {'높음': '🔴', '보통': '🟡', '낮음': '🟢'}.get(ai_risk, '')
            rec_emoji = {'매수': '🟢', '관망': '🟡', '매도': '🔴'}.get(ai_rec, '')
            
            st.markdown(f"""
            <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; border-left: 4px solid {risk_color};">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                    <span style="font-size: 16px; font-weight: bold;">🤖 AI 분석</span>
                    <span style="color: {risk_color}; font-weight: bold;">
                        {rec_emoji} {ai_rec} | 위험도: {ai_risk} {risk_emoji}
                    </span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            try:
                import json
                ai_summary = item.get('ai_summary', '')
                
                # 빈 문자열이나 None 체크
                if not ai_summary or ai_summary.strip() == '':
                    st.info("🤖 AI 분석 데이터 준비중입니다.")
                else:
                    # JSON 파싱 시도
                    try:
                        ai_data = json.loads(ai_summary) if isinstance(ai_summary, str) else ai_summary
                        
                        col_ai1, col_ai2 = st.columns(2)
                        
                        with col_ai1:
                            st.markdown("**📝 핵심 요약**")
                            st.info(ai_data.get('summary', '-'))
                            
                            st.markdown("**📈 주가 움직임 원인**")
                            st.write(ai_data.get('price_reason', '-'))
                            
                            if ai_data.get('investment_points'):
                                st.markdown("**✅ 투자 포인트**")
                                for point in ai_data['investment_points'][:3]:
                                    st.write(f"- {point}")
                        
                        with col_ai2:
                            if ai_data.get('risk_factors'):
                                st.markdown("**⚠️ 리스크 요인**")
                                for risk in ai_data['risk_factors'][:3]:
                                    st.write(f"- {risk}")
                            
                            st.markdown("**💰 밸류에이션**")
                            st.write(ai_data.get('valuation_comment', '-'))
                            
                            st.markdown(f"**📊 추천: {rec_emoji} {ai_rec}**")
                    
                    except json.JSONDecodeError:
                        # JSON 아닌 경우 단순 텍스트로 표시
                        st.markdown("**📝 AI 분석 요약**")
                        st.info(ai_summary)
            
            except Exception as e:
                st.info("🤖 AI 분석을 불러올 수 없습니다.")


# ==================== 순위별 통계 ====================
st.markdown("---")
st.subheader("📊 순위별 성과 비교")

try:
    import sqlite3
    db_path = project_root / 'data' / 'screener.db'
    conn = sqlite3.connect(str(db_path))
    
    rank_stats = pd.read_sql("""
        SELECT 
            h.rank as 순위,
            COUNT(*) as 샘플수,
            ROUND(AVG(p.return_from_screen), 1) as 'D+1 종가수익률',
            ROUND(AVG(p.gap_rate), 1) as 'D+1 갭률',
            ROUND(AVG(p.high_return), 1) as 'D+1 고점수익률'
        FROM closing_top5_history h
        JOIN top5_daily_prices p ON h.id = p.top5_history_id
        WHERE p.days_after = 1
        GROUP BY h.rank
        ORDER BY h.rank
    """, conn)
    conn.close()
    
    if not rank_stats.empty:
        st.dataframe(rank_stats, width="stretch", hide_index=True)
        
        # TOP1 vs TOP2-3 비교
        top1 = rank_stats[rank_stats['순위'] == 1]
        top23 = rank_stats[rank_stats['순위'].isin([2, 3])]
        
        if not top1.empty and not top23.empty:
            col1, col2 = st.columns(2)
            with col1:
                st.metric("TOP1 평균 갭률", f"{top1['D+1 갭률'].values[0]:+.1f}%")
            with col2:
                avg_23 = top23['D+1 갭률'].mean()
                delta = avg_23 - top1['D+1 갭률'].values[0]
                st.metric("TOP2-3 평균 갭률", f"{avg_23:+.1f}%", delta=f"{delta:+.1f}% vs TOP1")
except Exception as e:
    st.warning(f"순위별 통계 로드 실패: {e}")


# ==================== 푸터 ====================
st.markdown("---")
st.caption(f"{FOOTER_TOP5} | 구간 최적화 점수제 + 주도섹터 | OHLCV 차트")
