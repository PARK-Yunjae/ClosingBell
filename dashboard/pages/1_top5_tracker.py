"""
ê°ì‹œì¢…ëª© TOP5 20??ì¶”ì  ?€?œë³´??================================

OHLCV ?Œì¼ ê¸°ë°˜ ì°¨íŠ¸ + ê°€?…ì„± ê°œì„ 
- ?¬ë ¥ UI
- ?œê?ì´ì•¡ ?„í„° (?€ê¸°ì—…/ì¤‘í˜•ì£??Œí˜•ì£?
- ?…ì¢…(?¹í„°) ?œì‹œ
- D+20 ìº”ë“¤ì°¨íŠ¸ (OHLCV ?Œì¼ ê¸°ë°˜)
"""

import os
os.environ["DASHBOARD_ONLY"] = "true"  # Streamlit Cloud: API ??ê²€ì¦??¤í‚µ

import streamlit as st
import sys
from pathlib import Path
from datetime import date, timedelta, datetime
import pandas as pd

# plotly import (Streamlit Cloud ?¸í™˜)
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

# ?„ë¡œ?íŠ¸ ë£¨íŠ¸ ì¶”ê?
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# ?„ì—­?ìˆ˜ import
try:
    from src.config.app_config import (
        APP_VERSION, APP_FULL_VERSION, SIDEBAR_TITLE, FOOTER_TOP5,
    )
except ImportError:
    APP_VERSION = "v9.1"
    APP_FULL_VERSION = f"ClosingBell {APP_VERSION}"
    SIDEBAR_TITLE = "?”” ClosingBell"
    FOOTER_TOP5 = f"{APP_FULL_VERSION} | D+1 ~ D+20 ?˜ìµë¥?ë¶„ì„"

# ?…ì¢… ?•ë³´ ì¡°íšŒ
try:
    from src.services.company_service import get_sector_from_mapping
    SECTOR_AVAILABLE = True
except ImportError:
    SECTOR_AVAILABLE = False
    def get_sector_from_mapping(code):
        return None

# OHLCV ?Œì¼ ê²½ë¡œ (?˜ê²½ë³€???ëŠ” ê¸°ë³¸ê°?
OHLCV_PATH = Path(os.getenv("DATA_DIR", "C:/Coding/data")) / "ohlcv"

st.set_page_config(
    page_title="ê°ì‹œì¢…ëª© TOP5",
    page_icon="?“Š",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ==================== ?¬ì´?œë°” ?¤ë¹„ê²Œì´??====================
with st.sidebar:
    from dashboard.components.sidebar import render_sidebar_nav
    render_sidebar_nav()
    st.markdown("---")

st.title("?“Š ê°ì‹œì¢…ëª© TOP5 20??ì¶”ì ")
st.markdown(f"**D+1 ~ D+20 ?˜ìµë¥?ë¶„ì„** | _{APP_VERSION} êµ¬ê°„ ìµœì ???ìˆ˜??")
st.markdown("---")


# ==================== ?°ì´??ë¡œë“œ ====================
@st.cache_data(ttl=300)
def load_top5_dates(limit=60):
    """TOP5 ?°ì´?°ê? ?ˆëŠ” ? ì§œ ëª©ë¡"""
    try:
        from src.infrastructure.repository import get_top5_history_repository
        repo = get_top5_history_repository()
        return repo.get_dates_with_data(limit)
    except Exception as e:
        st.error(f"? ì§œ ë¡œë“œ ?¤íŒ¨: {e}")
        return []


@st.cache_data(ttl=300)
def load_top5_data(screen_date):
    """?¹ì • ? ì§œ??TOP5 + ?¼ë³„ ê°€ê²?""
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
        st.error(f"?°ì´??ë¡œë“œ ?¤íŒ¨: {e}")
        return []


@st.cache_data(ttl=300)
def load_market_cap_data():
    """?œê?ì´ì•¡ ?°ì´??ë¡œë“œ"""
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
    """OHLCV ?°ì´??ë¡œë“œ (FinanceDataReader ?°ì„ , ë¡œì»¬ ?Œì¼ ?´ë°±)"""
    
    # 1. FinanceDataReaderë¡??œë„ (Streamlit Cloud ?¸í™˜)
    try:
        import FinanceDataReader as fdr
        from datetime import timedelta
        
        start = pd.to_datetime(start_date)
        end = start + timedelta(days=days + 15)  # ?ì—…??ê³ ë ¤?´ì„œ ?¬ìœ ?ˆê²Œ
        
        df = fdr.DataReader(stock_code, start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
        
        if df is not None and not df.empty:
            df = df.reset_index()
            df = df.rename(columns={'index': 'Date', 'date': 'Date'})
            
            # ì»¬ëŸ¼ëª??œì???            df.columns = [col.title() if col.lower() in ['date', 'open', 'high', 'low', 'close', 'volume'] else col for col in df.columns]
            
            # ?„ìš”??ì»¬ëŸ¼ë§?? íƒ
            required_cols = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
            available_cols = [col for col in required_cols if col in df.columns]
            df = df[available_cols].head(days)
            
            if not df.empty:
                return df
    except Exception as e:
        pass  # FinanceDataReader ?¤íŒ¨??ë¡œì»¬ ?Œì¼ ?œë„
    
    # 2. ë¡œì»¬ ?Œì¼ ?´ë°± (ë¡œì»¬ ê°œë°œ??
    try:
        csv_path = OHLCV_PATH / f"{stock_code}.csv"
        if not csv_path.exists():
            return None
        
        df = pd.read_csv(csv_path)
        
        # ì»¬ëŸ¼ëª??Œë¬¸???µì¼
        df.columns = df.columns.str.lower()
        
        # date ì»¬ëŸ¼ ì°¾ê¸°
        if 'date' not in df.columns:
            first_col = df.columns[0]
            if first_col in ['', 'unnamed: 0']:
                df = df.rename(columns={first_col: 'date'})
        
        df['date'] = pd.to_datetime(df['date'])
        
        # start_date ?´í›„ days???°ì´??        start = pd.to_datetime(start_date)
        mask = df['date'] >= start
        df = df[mask].head(days)
        
        if df.empty:
            return None
        
        # ì»¬ëŸ¼ëª??€ë¬¸ìë¡?ë³€??(ì°¨íŠ¸ ?¸í™˜??
        df = df.rename(columns={
            'date': 'Date',
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'volume': 'Volume',
        })
        
        return df
    except Exception as e:
        return None


def create_candlestick_chart(stock_name, stock_code, screen_date, screen_price):
    """ìº”ë“¤?¤í‹± ì°¨íŠ¸ ?ì„± (OHLCV ê¸°ë°˜)"""
    if not PLOTLY_AVAILABLE:
        return None
    
    df = load_ohlcv_data(stock_code, screen_date, 25)
    
    if df is None or df.empty:
        return None
    
    # ?˜ìµë¥?ê³„ì‚°
    df['return_pct'] = (df['Close'] - screen_price) / screen_price * 100
    
    fig = make_subplots(
        rows=2, cols=1,
        row_heights=[0.7, 0.3],
        shared_xaxes=True,
        vertical_spacing=0.05,
    )
    
    # ìº”ë“¤?¤í‹±
    fig.add_trace(
        go.Candlestick(
            x=df['Date'],
            open=df['Open'],
            high=df['High'],
            low=df['Low'],
            close=df['Close'],
            name='OHLC',
            increasing_line_color='#F44336',  # ?œêµ­?? ?ìŠ¹=ë¹¨ê°•
            decreasing_line_color='#2196F3',  # ?˜ë½=?Œë‘
        ),
        row=1, col=1
    )
    
    # ?¤í¬ë¦¬ë‹ ê¸°ì?ê°€ ?¼ì¸
    fig.add_hline(
        y=screen_price, 
        line_dash="dash", 
        line_color="orange", 
        annotation_text=f"ê¸°ì?ê°€ {screen_price:,}??,
        row=1, col=1
    )
    
    # ê±°ë˜??    colors = ['#F44336' if c >= o else '#2196F3' for o, c in zip(df['Open'], df['Close'])]
    fig.add_trace(
        go.Bar(
            x=df['Date'],
            y=df['Volume'],
            name='ê±°ë˜??,
            marker_color=colors,
            opacity=0.7,
        ),
        row=2, col=1
    )
    
    fig.update_layout(
        title=dict(text=f"{stock_name} ({stock_code}) D+20 ì°¨íŠ¸", font=dict(size=14)),
        height=400,
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis_rangeslider_visible=False,
        showlegend=False,
        yaxis_title="ê°€ê²?(??",
        yaxis2_title="ê±°ë˜??,
    )
    
    return fig


def create_return_chart(stock_name, daily_prices, screen_price):
    """20???˜ìµë¥??¼ì¸ ì°¨íŠ¸"""
    if not daily_prices or not PLOTLY_AVAILABLE:
        return None
    
    df = pd.DataFrame(daily_prices)
    
    fig = go.Figure()
    
    # ì¢…ê? ?˜ìµë¥?    fig.add_trace(go.Scatter(
        x=df['days_after'],
        y=df['return_from_screen'],
        mode='lines+markers',
        name='ì¢…ê? ?˜ìµë¥?,
        line=dict(color='#2196F3', width=2),
        marker=dict(size=6),
    ))
    
    # ê³ ê? ?˜ìµë¥?    if 'high_return' in df.columns:
        fig.add_trace(go.Scatter(
            x=df['days_after'],
            y=df['high_return'],
            mode='lines',
            name='ê³ ê? ?˜ìµë¥?,
            line=dict(color='#4CAF50', width=1, dash='dot'),
        ))
    
    # ?€ê°€ ?˜ìµë¥?    if 'low_return' in df.columns:
        fig.add_trace(go.Scatter(
            x=df['days_after'],
            y=df['low_return'],
            mode='lines',
            name='?€ê°€ ?˜ìµë¥?,
            line=dict(color='#F44336', width=1, dash='dot'),
        ))
    
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    
    fig.update_layout(
        title=dict(text=f"{stock_name} 20???˜ìµë¥?, font=dict(size=14)),
        height=300,
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis_title="D+N",
        yaxis_title="?˜ìµë¥?(%)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    
    return fig


def grade_color(grade):
    """?±ê¸‰ ?‰ìƒ"""
    colors = {
        'S': '#FFD700',
        'A': '#4CAF50',
        'B': '#2196F3',
        'C': '#FFC107',
        'D': '#F44336',
    }
    return colors.get(grade, '#9E9E9E')


def format_market_cap(cap):
    """?œê?ì´ì•¡ ?¬ë§· (?Œìˆ˜??1?ë¦¬)"""
    if cap is None or cap <= 0:
        return "-"
    if cap >= 10000:
        return f"{cap/10000:.1f}ì¡?
    return f"{cap:,.0f}??


# ==================== ?¬ì´?œë°” ====================
dates = load_top5_dates(60)
market_caps = load_market_cap_data()

if not dates:
    st.warning("?“­ ?„ì§ ?˜ì§‘??TOP5 ?°ì´?°ê? ?†ìŠµ?ˆë‹¤.")
    st.markdown("""
    ### ?? ?°ì´???˜ì§‘ ë°©ë²•
    
    ```bash
    python main.py --backfill 20
    ```
    """)
    st.stop()

st.sidebar.markdown("### ?“… ? ì§œ ? íƒ")

# v6.3.2: query param?¼ë¡œ ? ì§œ ë°›ê¸° ì§€??query_date = st.query_params.get("date", None)
default_date = None

if query_date and query_date in dates:
    default_date = datetime.strptime(query_date, "%Y-%m-%d")
elif dates:
    default_date = datetime.strptime(dates[0], "%Y-%m-%d")
else:
    default_date = date.today()

selected_date = st.sidebar.date_input(
    "?¤í¬ë¦¬ë‹ ? ì§œ",
    value=default_date,
    min_value=datetime.strptime(dates[-1], "%Y-%m-%d") if dates else date.today() - timedelta(days=60),
    max_value=datetime.strptime(dates[0], "%Y-%m-%d") if dates else date.today(),
)
selected_date_str = selected_date.strftime("%Y-%m-%d")

if selected_date_str not in dates:
    available = [d for d in dates if d <= selected_date_str]
    if available:
        selected_date_str = available[0]
        st.sidebar.warning(f"??{selected_date_str}ë¡??œì‹œ")
    else:
        st.sidebar.error("?°ì´???†ìŒ")
        st.stop()

st.sidebar.markdown("---")

st.sidebar.markdown("### ?¢ ?œê?ì´ì•¡ ?„í„°")
cap_filter = st.sidebar.selectbox(
    "?œê?ì´ì•¡ ê¸°ì?",
    ["?„ì²´", "?€ê¸°ì—… (1ì¡?)", "ì¤‘í˜•ì£?(3ì²œì–µ~1ì¡?", "?Œí˜•ì£?(3ì²œì–µ ë¯¸ë§Œ)"],
    index=0
)

st.sidebar.markdown("### ?“Š ?ìˆ˜??)
st.sidebar.success(f"{APP_VERSION}: êµ¬ê°„ ìµœì ???ìˆ˜??)

st.sidebar.markdown("---")
st.sidebar.caption(f"? íƒ: {selected_date_str}")


# ==================== ë©”ì¸ ì»¨í…ì¸?====================
top5_data = load_top5_data(selected_date_str)

if not top5_data:
    st.warning(f"?“­ {selected_date_str} ? ì§œ??TOP5 ?°ì´?°ê? ?†ìŠµ?ˆë‹¤.")
    st.stop()

# ?œê?ì´ì•¡ ?•ë³´ ì¶”ê?
for item in top5_data:
    item['market_cap'] = market_caps.get(item['stock_code'], 0)

# ?œê?ì´ì•¡ ?„í„° ?ìš©
if cap_filter == "?€ê¸°ì—… (1ì¡?)":
    top5_data = [item for item in top5_data if item['market_cap'] >= 10000]
elif cap_filter == "ì¤‘í˜•ì£?(3ì²œì–µ~1ì¡?":
    top5_data = [item for item in top5_data if 3000 <= item['market_cap'] < 10000]
elif cap_filter == "?Œí˜•ì£?(3ì²œì–µ ë¯¸ë§Œ)":
    top5_data = [item for item in top5_data if item['market_cap'] < 3000]

if not top5_data:
    st.warning(f"?“­ {cap_filter} ì¡°ê±´??ë§ëŠ” ì¢…ëª©???†ìŠµ?ˆë‹¤.")
    st.stop()

# ?”ì•½ ì¹´ë“œ
st.subheader(f"?“ˆ {selected_date_str} TOP5")

cols = st.columns(min(5, len(top5_data)))
for i, item in enumerate(top5_data[:5]):
    with cols[i]:
        d1_gap = None
        if item.get('daily_prices'):
            d1 = next((p for p in item['daily_prices'] if p['days_after'] == 1), None)
            if d1:
                d1_gap = d1.get('gap_rate')
        
        cap_str = format_market_cap(item['market_cap'])
        cap_badge = "?¢" if item['market_cap'] >= 10000 else ""
        
        cci = item.get('cci') or 0
        cci_warning = "? ï¸" if cci > 220 else ""
        
        # v6.3.2: ê±°ë˜?€ê¸?ê±°ë˜??        trading_value = item.get('trading_value') or 0
        if trading_value >= 1000:
            tv_str = f"{trading_value/1000:.1f}ì¡?
        elif trading_value >= 1:
            tv_str = f"{trading_value:.0f}??
        else:
            tv_str = "-"
        
        # v6.4: AI ì¶”ì²œ/?„í—˜??ë°°ì? (ê°•ì¡°)
        ai_risk = item.get('ai_risk_level', '')
        ai_rec = item.get('ai_recommendation', '')
        risk_badge = {'??Œ': '??, 'ë³´í†µ': '? ï¸', '?’ìŒ': '?š«'}.get(ai_risk, '')
        rec_badge = {'ë§¤ìˆ˜': '?Ÿ¢', 'ê´€ë§?: '?Ÿ¡', 'ë§¤ë„': '?”´'}.get(ai_rec, '')
        rec_color = {'ë§¤ìˆ˜': '#4CAF50', 'ê´€ë§?: '#FF9800', 'ë§¤ë„': '#F44336'}.get(ai_rec, '#888')
        
        # v6.3: DB?ì„œ ?¹í„° ?•ë³´ (?†ìœ¼ë©?company_service?ì„œ ì¡°íšŒ)
        sector = item.get('sector') or get_sector_from_mapping(item['stock_code']) or "-"
        is_leading = item.get('is_leading_sector', 0)
        sector_rank = item.get('sector_rank', 99)
        
        # ì£¼ë„?¹í„° ë°°ì?
        if is_leading:
            sector_display = f"?”¥ {sector} (#{sector_rank})"
        else:
            sector_display = f"?­ {sector}"
        
        st.markdown(f"""
        <div style="
            background: linear-gradient(135deg, {grade_color(item['grade'])}22, {grade_color(item['grade'])}11);
            border-left: 5px solid {grade_color(item['grade'])};
            padding: 12px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        ">
            <div style="font-size: 12px; color: #888; margin-bottom: 4px;">#{item['rank']} {cap_badge}</div>
            <div style="font-size: 18px; font-weight: bold; margin-bottom: 4px;">{item['stock_name']}</div>
            <div style="font-size: 12px; color: {'#FF6B6B' if is_leading else '#666'}; margin-bottom: 6px;">{sector_display}</div>
            <div style="font-size: 16px; margin-bottom: 4px;">
                <span style="color: {grade_color(item['grade'])}; font-weight: bold;">{item['grade']}</span>
                <span style="color: #666;">({item['screen_score']:.1f}??</span>
            </div>
            <div style="font-size: 14px; color: #444; margin-bottom: 2px;">{item['screen_price']:,}??/div>
            <div style="font-size: 12px; color: #666; margin-bottom: 6px;">{cap_str} | ê±°ë˜ {tv_str}</div>
            <div style="font-size: 12px; color: #888; margin-bottom: 8px;">CCI: {cci:.0f} {cci_warning}</div>
            <div style="
                background: {rec_color}15;
                border-radius: 4px;
                padding: 6px;
                margin-bottom: 6px;
                text-align: center;
            ">
                <span style="font-size: 14px; font-weight: bold; color: {rec_color};">
                    {rec_badge} {ai_rec if ai_rec else '-'} | {risk_badge} {ai_risk if ai_risk else '-'}
                </span>
            </div>
            <div style="font-size: 16px; color: {'#4CAF50' if d1_gap and d1_gap > 0 else '#F44336'}; font-weight: bold; text-align: center;">
                D+1: {f"{d1_gap:+.1f}%" if d1_gap is not None else "-"}
            </div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("---")

# ì¢…ëª©ë³??ì„¸
st.subheader("?“‹ ì¢…ëª©ë³??ì„¸ ë¶„ì„")

for item in top5_data:
    cap_str = format_market_cap(item['market_cap'])
    cci = item.get('cci') or 0
    cci_badge = " ? ï¸ê³¼ì—´" if cci > 220 else ""
    
    # v6.3.1: ê±°ë˜?€ê¸??œì‹œ
    trading_value = item.get('trading_value') or 0
    if trading_value >= 1000:
        tv_str = f"{trading_value/1000:.1f}ì¡?
    elif trading_value >= 1:
        tv_str = f"{trading_value:.0f}??
    else:
        tv_str = "-"
    
    # v6.3: DB?ì„œ ?¹í„° ?•ë³´
    sector = item.get('sector') or get_sector_from_mapping(item['stock_code']) or ""
    is_leading = item.get('is_leading_sector', 0)
    sector_rank = item.get('sector_rank', 99)
    
    if sector:
        if is_leading:
            sector_str = f" | ?”¥ {sector} (#{sector_rank})"
        else:
            sector_str = f" | ?­ {sector}"
    else:
        sector_str = ""
    
    with st.expander(
        f"**#{item['rank']} {item['stock_name']}** - {item['grade']}?±ê¸‰ ({item['screen_score']:.1f}?? | {tv_str}{sector_str}{cci_badge}", 
        expanded=(item['rank'] == 1)
    ):
        # ì°¨íŠ¸ ? íƒ (ìº”ë“¤ì°¨íŠ¸ ê¸°ë³¸)
        chart_type = st.radio(
            "ì°¨íŠ¸ ì¢…ë¥˜",
            ["?•¯ï¸?ìº”ë“¤ì°¨íŠ¸ (OHLCV)", "?“ˆ ?˜ìµë¥??¼ì¸"],
            key=f"chart_{item['stock_code']}",
            horizontal=True
        )
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            if not PLOTLY_AVAILABLE:
                st.warning("?“Š ì°¨íŠ¸ë¥??œì‹œ?˜ë ¤ë©?plotlyê°€ ?„ìš”?©ë‹ˆ??")
            elif chart_type == "?•¯ï¸?ìº”ë“¤ì°¨íŠ¸ (OHLCV)":
                fig = create_candlestick_chart(
                    item['stock_name'], 
                    item['stock_code'], 
                    selected_date_str,
                    item['screen_price']
                )
                if fig:
                    st.plotly_chart(fig, width="stretch")
                else:
                    st.info(f"?“Š {item['stock_name']} OHLCV ?°ì´?°ë? ë¶ˆëŸ¬?????†ìŠµ?ˆë‹¤. ?˜ìµë¥??¼ì¸ ì°¨íŠ¸ë¥??´ìš©?´ì£¼?¸ìš”.")
            else:  # ?˜ìµë¥??¼ì¸
                if item.get('daily_prices'):
                    fig = create_return_chart(item['stock_name'], item['daily_prices'], item['screen_price'])
                    if fig:
                        st.plotly_chart(fig, width="stretch")
                else:
                    st.info("?„ì§ ?¼ë³„ ê°€ê²??°ì´?°ê? ?†ìŠµ?ˆë‹¤.")
        
        with col2:
            st.markdown("##### ?“Š ?¤í¬ë¦¬ë‹ ì§€??)
            
            # ?…ì¢… ?œì‹œ
            st.write(f"???…ì¢…: **{sector if sector else '-'}**")
            
            cci_display = f"{cci:.0f}"
            if cci > 250:
                cci_display += " ?š«"
            elif cci > 220:
                cci_display += " ? ï¸"
            elif 150 <= cci <= 170:
                cci_display += " ??
            
            st.write(f"??CCI: **{cci_display}**")
            st.write(f"??RSI: {item.get('rsi', '-'):.1f}" if item.get('rsi') else "??RSI: -")
            st.write(f"???±ë½ë¥? {item.get('change_rate', 0):.1f}%")
            st.write(f"???´ê²©??20): {item.get('disparity_20', '-'):.1f}%" if item.get('disparity_20') else "???´ê²©??20): -")
            st.write(f"???°ì†?‘ë´‰: {item.get('consecutive_up', 0)}??)
            st.write(f"??ê±°ë˜?€ê¸? **{tv_str}**")
            
            # v6.3.2: ê±°ë˜??(ë§Œì£¼ ?¨ìœ„)
            volume = item.get('volume') or 0
            if volume >= 100_000_000:
                vol_str = f"{volume/100_000_000:.1f}?µì£¼"
            elif volume >= 10_000:
                vol_str = f"{volume/10_000:.0f}ë§Œì£¼"
            else:
                vol_str = f"{volume:,}ì£? if volume else "-"
            st.write(f"??ê±°ë˜?? **{vol_str}**")
            
            st.markdown("---")
            
            if item.get('daily_prices'):
                st.markdown("##### ?“ˆ ?±ê³¼ ?”ì•½")
                
                prices = item['daily_prices']
                max_return = max((p.get('high_return') or 0 for p in prices), default=0)
                min_return = min((p.get('low_return') or 0 for p in prices), default=0)
                final_return = prices[-1]['return_from_screen'] if prices else 0
                
                col_a, col_b = st.columns(2)
                col_a.metric("ìµœë? ?˜ìµ", f"{max_return:+.1f}%")
                col_b.metric("ìµœë? ?ì‹¤", f"{min_return:+.1f}%")
                st.metric("ìµœì¢… ?˜ìµ", f"{final_return:+.1f}%")
        
        # v6.3.2: AI ë¶„ì„ ?¹ì…˜
        if item.get('ai_summary'):
            st.markdown("---")
            
            ai_risk = item.get('ai_risk_level', 'ë³´í†µ')
            ai_rec = item.get('ai_recommendation', 'ê´€ë§?)
            risk_color = {'??Œ': '#4CAF50', 'ë³´í†µ': '#FF9800', '?’ìŒ': '#F44336'}.get(ai_risk, '#888')
            risk_emoji = {'??Œ': '??, 'ë³´í†µ': '? ï¸', '?’ìŒ': '?š«'}.get(ai_risk, '')
            rec_emoji = {'ë§¤ìˆ˜': '?“ˆ', 'ê´€ë§?: '??', 'ë§¤ë„': '?“‰'}.get(ai_rec, '')
            
            st.markdown(f"""
            <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; border-left: 4px solid {risk_color};">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                    <span style="font-size: 16px; font-weight: bold;">?¤– AI ë¶„ì„</span>
                    <span style="color: {risk_color}; font-weight: bold;">
                        {rec_emoji} {ai_rec} | ?„í—˜?? {ai_risk} {risk_emoji}
                    </span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            try:
                import json
                ai_summary = item.get('ai_summary', '')
                
                # ë¹?ë¬¸ì?´ì´??None ì²´í¬
                if not ai_summary or ai_summary.strip() == '':
                    st.info("?¤– AI ë¶„ì„ ?°ì´??ì¤€ë¹?ì¤‘ì…?ˆë‹¤.")
                else:
                    # JSON ?Œì‹± ?œë„
                    try:
                        ai_data = json.loads(ai_summary) if isinstance(ai_summary, str) else ai_summary
                        
                        col_ai1, col_ai2 = st.columns(2)
                        
                        with col_ai1:
                            st.markdown("**â­??µì‹¬ ?”ì•½**")
                            st.info(ai_data.get('summary', '-'))
                            
                            st.markdown("**?“ˆ ì£¼ê? ?€ì§ì„ ?ì¸**")
                            st.write(ai_data.get('price_reason', '-'))
                            
                            if ai_data.get('investment_points'):
                                st.markdown("**???¬ì ?¬ì¸??*")
                                for point in ai_data['investment_points'][:3]:
                                    st.write(f"??{point}")
                        
                        with col_ai2:
                            if ai_data.get('risk_factors'):
                                st.markdown("**? ï¸ ë¦¬ìŠ¤???”ì¸**")
                                for risk in ai_data['risk_factors'][:3]:
                                    st.write(f"??{risk}")
                            
                            st.markdown("**?’° ë°¸ë¥˜?ì´??*")
                            st.write(ai_data.get('valuation_comment', '-'))
                            
                            st.markdown(f"**?¯ ì¶”ì²œ: {rec_emoji} {ai_rec}**")
                    
                    except json.JSONDecodeError:
                        # JSON ?„ë‹Œ ê²½ìš° ?¨ìˆœ ?ìŠ¤?¸ë¡œ ?œì‹œ
                        st.markdown("**â­?AI ë¶„ì„ ?”ì•½**")
                        st.info(ai_summary)
            
            except Exception as e:
                st.info("?¤– AI ë¶„ì„??ë¶ˆëŸ¬?????†ìŠµ?ˆë‹¤.")


# ==================== ?œìœ„ë³??µê³„ ====================
st.markdown("---")
st.subheader("?“Š ?œìœ„ë³??±ê³¼ ë¹„êµ")

try:
    import sqlite3
    db_path = project_root / 'data' / 'screener.db'
    conn = sqlite3.connect(str(db_path))
    
    rank_stats = pd.read_sql("""
        SELECT 
            h.rank as ?œìœ„,
            COUNT(*) as ?˜í”Œ??
            ROUND(AVG(p.return_from_screen), 1) as 'D+1 ì¢…ê??˜ìµë¥?,
            ROUND(AVG(p.gap_rate), 1) as 'D+1 ê°?¥ ',
            ROUND(AVG(p.high_return), 1) as 'D+1 ê³ ê??˜ìµë¥?
        FROM closing_top5_history h
        JOIN top5_daily_prices p ON h.id = p.top5_history_id
        WHERE p.days_after = 1
        GROUP BY h.rank
        ORDER BY h.rank
    """, conn)
    conn.close()
    
    if not rank_stats.empty:
        st.dataframe(rank_stats, width="stretch", hide_index=True)
        
        # TOP1 vs TOP2-3 ë¹„êµ
        top1 = rank_stats[rank_stats['?œìœ„'] == 1]
        top23 = rank_stats[rank_stats['?œìœ„'].isin([2, 3])]
        
        if not top1.empty and not top23.empty:
            col1, col2 = st.columns(2)
            with col1:
                st.metric("TOP1 ?‰ê·  ê°?¥ ", f"{top1['D+1 ê°?¥ '].values[0]:+.1f}%")
            with col2:
                avg_23 = top23['D+1 ê°?¥ '].mean()
                delta = avg_23 - top1['D+1 ê°?¥ '].values[0]
                st.metric("TOP2-3 ?‰ê·  ê°?¥ ", f"{avg_23:+.1f}%", delta=f"{delta:+.1f}% vs TOP1")
except Exception as e:
    st.warning(f"?œìœ„ë³??µê³„ ë¡œë“œ ?¤íŒ¨: {e}")


# ==================== ?¸í„° ====================
st.markdown("---")
st.caption(f"{FOOTER_TOP5} | êµ¬ê°„ ìµœì ???ìˆ˜??+ ì£¼ë„?¹í„° | OHLCV ì°¨íŠ¸")
