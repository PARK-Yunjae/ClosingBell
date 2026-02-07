"""
ClosingBell - ì¢…ëª© ê²€???˜ì´ì§€

ì¢…ëª©ì½”ë“œ/ì¢…ëª©ëª…ìœ¼ë¡?TOP5/? ëª©ë¯?ì¶œí˜„ ?´ë ¥ ê²€??- ?”ì•½ ì¹´ë“œ (?±ì¥ ?Ÿìˆ˜, ?‰ê·  ??¬, ìµœê·¼ ?±ì¥??
- ?„í„° (ê¸°ê°„, ?ŒìŠ¤, TOP5/? ëª©ë¯?
- ?ˆìŠ¤? ë¦¬ ?Œì´ë¸?(?•ë ¬ ê°€??
- ì°¨íŠ¸ (OHLCV ê¸°ë°˜)
"""

import streamlit as st
import pandas as pd
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

# ?„ë¡œ?íŠ¸ ë£¨íŠ¸ ì¶”ê?
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# ?„ì—­?ìˆ˜ import
try:
    from src.config.app_config import (
        APP_VERSION, APP_FULL_VERSION, SIDEBAR_TITLE, FOOTER_SEARCH,
    )
except ImportError:
    APP_VERSION = "v9.1"
    APP_FULL_VERSION = f"ClosingBell {APP_VERSION}"
    SIDEBAR_TITLE = "?”” ClosingBell"
    FOOTER_SEARCH = f"{APP_FULL_VERSION} | ì¢…ëª© ?ì„¸ ë¶„ì„"

st.set_page_config(
    page_title=f"ì¢…ëª© ê²€??| {APP_FULL_VERSION}",
    page_icon="?”",
    layout="wide",
)

# ==================== ?¬ì´?œë°” ?¤ë¹„ê²Œì´??====================
with st.sidebar:
    from dashboard.components.sidebar import render_sidebar_nav
    render_sidebar_nav()
    st.markdown("---")

st.title("?” ì¢…ëª© ê²€??)
st.markdown("ì¢…ëª©ì½”ë“œ ?ëŠ” ì¢…ëª©ëª…ìœ¼ë¡?**TOP5/? ëª©ë¯?* ì¶œí˜„ ?´ë ¥??ê²€?‰í•©?ˆë‹¤.")


# Repository ë¡œë“œ
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


# OHLCV ì°¨íŠ¸ ë¡œë“œ (?¤ì? ê¸°ë°˜, ë¡œì»¬ ?Œì¼ ?´ë°±)
OHLCV_PATH = Path(os.getenv("DATA_DIR", "C:/Coding/data")) / "ohlcv_kiwoom"

@st.cache_data(ttl=3600)
def load_ohlcv(stock_code: str, days: int = 60):
    """OHLCV ?°ì´??ë¡œë“œ (FinanceDataReader ?°ì„ , ë¡œì»¬ ?Œì¼ ?´ë°±)"""
    
    # 1. FinanceDataReaderë¡??œë„ (Streamlit Cloud ?¸í™˜)
    try:
        import FinanceDataReader as fdr
        from datetime import timedelta
        
        end = datetime.now()
        start = end - timedelta(days=days + 30)  # ?ì—…??ê³ ë ¤
        
        df = fdr.DataReader(stock_code, start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
        
        if df is not None and not df.empty:
            df = df.reset_index()
            df.columns = df.columns.str.lower()
            
            # ì»¬ëŸ¼ëª??œì???            if 'index' in df.columns:
                df = df.rename(columns={'index': 'date'})
            
            df = df.tail(days)  # ìµœê·¼ N??            
            if not df.empty:
                return df
    except Exception:
        pass  # FDR ?¤íŒ¨??ë¡œì»¬ ?Œì¼ ?œë„
    
    # 2. ë¡œì»¬ ?Œì¼ ?´ë°± (ë¡œì»¬ ê°œë°œ??
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
    """ìº”ë“¤?¤í‹± ì°¨íŠ¸ ?ì„± (?œêµ­?? ?ìŠ¹=ë¹¨ê°•, ?˜ë½=?Œë‘)"""
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        
        fig = make_subplots(
            rows=2, cols=1,
            row_heights=[0.7, 0.3],
            shared_xaxes=True,
            vertical_spacing=0.05,
        )
        
        # ìº”ë“¤?¤í‹± (?œêµ­?? ?ìŠ¹=ë¹¨ê°•, ?˜ë½=?Œë‘)
        fig.add_trace(
            go.Candlestick(
                x=df['date'],
                open=df['open'],
                high=df['high'],
                low=df['low'],
                close=df['close'],
                name='ê°€ê²?,
                increasing_line_color='#F44336',  # ?ìŠ¹=ë¹¨ê°•
                increasing_fillcolor='#F44336',
                decreasing_line_color='#2196F3',  # ?˜ë½=?Œë‘
                decreasing_fillcolor='#2196F3',
            ),
            row=1, col=1
        )
        
        # TOP5/? ëª©ë¯?ì¶œí˜„???œì‹œ
        if highlight_dates:
            for d in highlight_dates:
                fig.add_vline(
                    x=d,
                    line_dash="dash",
                    line_color="orange",
                    opacity=0.7,
                    row=1, col=1
                )
        
        # ê±°ë˜??(?œêµ­?? ?‘ë´‰=ë¹¨ê°•, ?Œë´‰=?Œë‘)
        colors = ['#F44336' if c >= o else '#2196F3' 
                  for c, o in zip(df['close'], df['open'])]
        fig.add_trace(
            go.Bar(x=df['date'], y=df['volume'], name='ê±°ë˜??, marker_color=colors),
            row=2, col=1
        )
        
        fig.update_layout(
            title=f"?“ˆ {stock_name} ì°¨íŠ¸ (ìµœê·¼ 60??",
            height=500,
            xaxis_rangeslider_visible=False,
            showlegend=False,
        )
        
        return fig
    except ImportError:
        return None


# ============================================================
# ?¬ì´?œë°”: ê²€??ì¡°ê±´
# ============================================================
st.sidebar.header("?” ê²€??ì¡°ê±´")

# ê²€?‰ì–´ ?…ë ¥
search_query = st.sidebar.text_input(
    "ì¢…ëª©ì½”ë“œ ?ëŠ” ì¢…ëª©ëª?,
    placeholder="?? 005930 ?ëŠ” ?¼ì„±",
    help="2ê¸€???´ìƒ ?…ë ¥?˜ì„¸??
)

# ê¸°ê°„ ?„í„°
period_options = {
    "ìµœê·¼ 7??: 7,
    "ìµœê·¼ 30??: 30,
    "ìµœê·¼ 90??: 90,
    "ìµœê·¼ 1??: 365,
    "?„ì²´": 9999,
}
selected_period = st.sidebar.selectbox("ê¸°ê°„", list(period_options.keys()), index=1)
days_back = period_options[selected_period]

# ?°ì´???ŒìŠ¤ ?„í„°
source_options = ["?„ì²´", "realtime", "backfill"]
selected_source = st.sidebar.selectbox("?°ì´???ŒìŠ¤", source_options)

# êµ¬ë¶„ ?„í„°
show_top5 = st.sidebar.checkbox("TOP5", value=True)
show_nomad = st.sidebar.checkbox("? ëª©ë¯?, value=True)


# ============================================================
# ê²€???¨ìˆ˜ (ìºì‹œ)
# ============================================================
@st.cache_data(ttl=60)
def search_top5(query: str, limit: int = 200):
    """TOP5 ?ˆìŠ¤? ë¦¬ ê²€??""
    return repos['top5'].search_occurrences(query, limit=limit)


@st.cache_data(ttl=60)
def search_nomad(query: str, limit: int = 200):
    """? ëª©ë¯??ˆìŠ¤? ë¦¬ ê²€??""
    return repos['nomad'].search_occurrences(query, limit=limit)


def filter_by_period(df: pd.DataFrame, days: int, date_col: str = 'screen_date') -> pd.DataFrame:
    """ê¸°ê°„ ?„í„°"""
    if days >= 9999 or df.empty:
        return df
    
    cutoff = (datetime.now() - timedelta(days=days)).date()
    
    # ? ì§œ ì»¬ëŸ¼ ì²˜ë¦¬
    df_copy = df.copy()
    if date_col in df_copy.columns:
        df_copy[date_col] = pd.to_datetime(df_copy[date_col]).dt.date
        return df_copy[df_copy[date_col] >= cutoff]
    
    return df_copy


def filter_by_source(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """?ŒìŠ¤ ?„í„°"""
    if source == "?„ì²´" or 'data_source' not in df.columns:
        return df
    return df[df['data_source'] == source]


# ============================================================
# ë©”ì¸ ê²€??ë¡œì§
# ============================================================
if search_query and len(search_query) >= 2:
    
    # ê²€???¤í–‰
    top5_results = []
    nomad_results = []
    
    if show_top5:
        top5_results = search_top5(search_query)
    
    if show_nomad:
        nomad_results = search_nomad(search_query)
    
    # DataFrame ë³€??    df_top5 = pd.DataFrame(top5_results) if top5_results else pd.DataFrame()
    df_nomad = pd.DataFrame(nomad_results) if nomad_results else pd.DataFrame()
    
    # ?„í„° ?ìš©
    if not df_top5.empty:
        df_top5 = filter_by_period(df_top5, days_back, 'screen_date')
        df_top5 = filter_by_source(df_top5, selected_source)
    
    if not df_nomad.empty:
        df_nomad = filter_by_period(df_nomad, days_back, 'study_date')
        # nomad??data_source ì»¬ëŸ¼???†ì„ ???ˆìŒ
    
    # ============================================================
    # ?”ì•½ ì¹´ë“œ
    # ============================================================
    st.markdown("---")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        top5_count = len(df_top5)
        st.metric("?† TOP5 ?±ì¥", f"{top5_count}??)
    
    with col2:
        nomad_count = len(df_nomad)
        st.metric("?“š ? ëª©ë¯??±ì¥", f"{nomad_count}??)
    
    with col3:
        # ìµœê·¼ ?±ì¥??        latest_date = None
        if not df_top5.empty:
            latest_top5 = pd.to_datetime(df_top5['screen_date']).max()
            latest_date = latest_top5
        if not df_nomad.empty:
            latest_nomad = pd.to_datetime(df_nomad['study_date']).max()
            if latest_date is None or latest_nomad > latest_date:
                latest_date = latest_nomad
        
        if latest_date:
            st.metric("?“… ìµœê·¼ ?±ì¥", latest_date.strftime("%Y-%m-%d"))
        else:
            st.metric("?“… ìµœê·¼ ?±ì¥", "-")
    
    with col4:
        # ?‰ê·  ??¬ (TOP5ë§?
        if not df_top5.empty and 'rank' in df_top5.columns:
            avg_rank = df_top5['rank'].mean()
            st.metric("?“Š ?‰ê·  ??¬", f"{avg_rank:.1f}")
        else:
            st.metric("?“Š ?‰ê·  ??¬", "-")
    
    # ============================================================
    # TOP5 ?ˆìŠ¤? ë¦¬ ?Œì´ë¸?    # ============================================================
    if show_top5 and not df_top5.empty:
        st.markdown("---")
        st.subheader("?† TOP5 ì¶œí˜„ ?´ë ¥")
        
        # ì»¬ëŸ¼ ? íƒ ë°??¬ë§·
        display_cols = ['screen_date', 'stock_code', 'stock_name', 'rank', 
                       'screen_score', 'grade', 'change_rate', 'cci', 
                       'trading_value', 'data_source']
        
        available_cols = [c for c in display_cols if c in df_top5.columns]
        df_display = df_top5[available_cols].copy()
        
        # ì»¬ëŸ¼ëª??œê???        col_names = {
            'screen_date': '? ì§œ',
            'stock_code': 'ì¢…ëª©ì½”ë“œ',
            'stock_name': 'ì¢…ëª©ëª?,
            'rank': '?œìœ„',
            'screen_score': '?ìˆ˜',
            'grade': '?±ê¸‰',
            'change_rate': '?±ë½ë¥?%)',
            'cci': 'CCI',
            'trading_value': 'ê±°ë˜?€ê¸???',
            'data_source': '?ŒìŠ¤',
        }
        df_display = df_display.rename(columns=col_names)
        
        # ? ì§œ ?•ë ¬ (ìµœì‹ ??
        if '? ì§œ' in df_display.columns:
            df_display = df_display.sort_values('? ì§œ', ascending=False)
        
        # ?«ì ?¬ë§·
        if '?ìˆ˜' in df_display.columns:
            df_display['?ìˆ˜'] = df_display['?ìˆ˜'].round(1)
        if '?±ë½ë¥?%)' in df_display.columns:
            df_display['?±ë½ë¥?%)'] = df_display['?±ë½ë¥?%)'].round(2)
        if 'CCI' in df_display.columns:
            df_display['CCI'] = df_display['CCI'].round(0)
        if 'ê±°ë˜?€ê¸???' in df_display.columns:
            df_display['ê±°ë˜?€ê¸???'] = df_display['ê±°ë˜?€ê¸???'].round(0)
        
        st.dataframe(
            df_display,
            width='stretch',
            hide_index=True,
            height=min(400, 40 + len(df_display) * 35),
        )
        
        # ?±ê¸‰ë³??µê³„
        if 'grade' in df_top5.columns:
            st.markdown("**?±ê¸‰ ë¶„í¬:**")
            grade_counts = df_top5['grade'].value_counts().sort_index()
            cols = st.columns(len(grade_counts))
            for i, (grade, count) in enumerate(grade_counts.items()):
                with cols[i]:
                    emoji = {"S": "?†", "A": "?¥‡", "B": "?¥ˆ", "C": "?¥‰", "D": "? ï¸"}.get(grade, "")
                    st.write(f"{emoji} {grade}?±ê¸‰: **{count}??*")
    
    elif show_top5:
        st.info("?† TOP5 ì¶œí˜„ ?´ë ¥???†ìŠµ?ˆë‹¤.")
    
    # ============================================================
    # ? ëª©ë¯??ˆìŠ¤? ë¦¬ ?Œì´ë¸?    # ============================================================
    if show_nomad and not df_nomad.empty:
        st.markdown("---")
        st.subheader("?“š ? ëª©ë¯?ì¶œí˜„ ?´ë ¥")
        
        # ì»¬ëŸ¼ ? íƒ ë°??¬ë§·
        display_cols = ['study_date', 'stock_code', 'stock_name', 
                       'candidate_type', 'change_rate', 'score']
        
        available_cols = [c for c in display_cols if c in df_nomad.columns]
        df_display = df_nomad[available_cols].copy()
        
        # ì»¬ëŸ¼ëª??œê???        col_names = {
            'study_date': '? ì§œ',
            'stock_code': 'ì¢…ëª©ì½”ë“œ',
            'stock_name': 'ì¢…ëª©ëª?,
            'candidate_type': '? í˜•',
            'change_rate': '?±ë½ë¥?%)',
            'score': '?ìˆ˜',
        }
        df_display = df_display.rename(columns=col_names)
        
        # ? ì§œ ?•ë ¬ (ìµœì‹ ??
        if '? ì§œ' in df_display.columns:
            df_display = df_display.sort_values('? ì§œ', ascending=False)
        
        # ? í˜• ?œê???        if '? í˜•' in df_display.columns:
            type_map = {
                'limit_up': '?”´ ?í•œê°€',
                'volume_explosion': '?Ÿ¡ ê±°ë˜?‰ì²œë§?,
            }
            df_display['? í˜•'] = df_display['? í˜•'].map(type_map).fillna(df_display['? í˜•'])
        
        st.dataframe(
            df_display,
            width='stretch',
            hide_index=True,
            height=min(400, 40 + len(df_display) * 35),
        )
        
        # ? í˜•ë³??µê³„
        if 'candidate_type' in df_nomad.columns:
            st.markdown("**? í˜• ë¶„í¬:**")
            type_counts = df_nomad['candidate_type'].value_counts()
            cols = st.columns(len(type_counts))
            for i, (ctype, count) in enumerate(type_counts.items()):
                with cols[i]:
                    emoji = "?”´" if ctype == "limit_up" else "?Ÿ¡"
                    label = "?í•œê°€" if ctype == "limit_up" else "ê±°ë˜?‰ì²œë§?
                    st.write(f"{emoji} {label}: **{count}??*")
    
    elif show_nomad:
        st.info("?“š ? ëª©ë¯?ì¶œí˜„ ?´ë ¥???†ìŠµ?ˆë‹¤.")
    
    # ============================================================
    # ?˜ìµë¥??”ì•½ (TOP5ë§? D+1~D+20 ?°ì´?°ê? ?ˆëŠ” ê²½ìš°)
    # ============================================================
    if show_top5 and not df_top5.empty:
        st.markdown("---")
        st.subheader("?“ˆ ?˜ìµë¥??”ì•½ (D+1 ~ D+20)")
        
        # D+1 ?˜ìµë¥?ì¡°íšŒ ?œë„
        try:
            from src.infrastructure.repository import get_top5_prices_repository
            prices_repo = get_top5_prices_repository()
            
            # ê°?TOP5 ê¸°ë¡???˜ìµë¥?ì¡°íšŒ
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
                
                # ?‰ê·  ?˜ìµë¥?ê³„ì‚°
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    d1_avg = df_returns['d1'].dropna().mean()
                    d1_win = (df_returns['d1'].dropna() > 0).mean() * 100
                    st.metric(
                        "D+1 ?‰ê· ", 
                        f"{d1_avg:.2f}%" if pd.notna(d1_avg) else "-",
                        f"?¹ë¥  {d1_win:.0f}%" if pd.notna(d1_win) else None
                    )
                
                with col2:
                    d5_avg = df_returns['d5'].dropna().mean()
                    d5_win = (df_returns['d5'].dropna() > 0).mean() * 100
                    st.metric(
                        "D+5 ?‰ê· ", 
                        f"{d5_avg:.2f}%" if pd.notna(d5_avg) else "-",
                        f"?¹ë¥  {d5_win:.0f}%" if pd.notna(d5_win) else None
                    )
                
                with col3:
                    d20_avg = df_returns['d20'].dropna().mean()
                    d20_win = (df_returns['d20'].dropna() > 0).mean() * 100
                    st.metric(
                        "D+20 ?‰ê· ", 
                        f"{d20_avg:.2f}%" if pd.notna(d20_avg) else "-",
                        f"?¹ë¥  {d20_win:.0f}%" if pd.notna(d20_win) else None
                    )
                
                with col4:
                    total_samples = len(df_returns['d1'].dropna())
                    st.metric("?˜í”Œ ??, f"{total_samples}ê±?)
            else:
                st.info("?˜ìµë¥??°ì´?°ê? ?†ìŠµ?ˆë‹¤. (D+1~D+20 ê°€ê²??°ì´???˜ì§‘ ?„ìš”)")
                
        except Exception as e:
            st.info(f"?˜ìµë¥??°ì´??ì¡°íšŒ ?¤íŒ¨: {e}")
    
    # ============================================================
    # ì°¨íŠ¸ (OHLCV ê¸°ë°˜)
    # ============================================================
    st.markdown("---")
    st.subheader("?“Š ì°¨íŠ¸")
    
    # ê²€?‰ëœ ì¢…ëª© ì¤?ì²?ë²ˆì§¸ ì¢…ëª© ì½”ë“œë¡?ì°¨íŠ¸ ?œì‹œ
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
                st.caption("?Ÿ  ?ì„ : TOP5/? ëª©ë¯?ì¶œí˜„??)
            else:
                st.warning("ì°¨íŠ¸ ?œì‹œ??plotlyê°€ ?„ìš”?©ë‹ˆ??")
        else:
            st.info(f"?“ OHLCV ?°ì´???†ìŒ: {chart_code}")
            st.caption(f"ê²½ë¡œ: {OHLCV_PATH / f'{chart_code}.csv'}")

else:
    # ê²€?‰ì–´ ë¯¸ì…?????ˆë‚´
    st.info("?‘ˆ ?¬ì´?œë°”?ì„œ **ì¢…ëª©ì½”ë“œ ?ëŠ” ì¢…ëª©ëª?*???…ë ¥?˜ì„¸??(2ê¸€???´ìƒ)")
    
    # ìµœê·¼ TOP5 ?”ì•½
    st.markdown("---")
    st.subheader("?“Š ìµœê·¼ TOP5 ?”ì•½")
    
    try:
        recent_dates = repos['top5'].get_dates_with_data(days=5)
        
        if recent_dates:
            for d in recent_dates[:3]:
                top5 = repos['top5'].get_by_date(d)
                if top5:
                    names = [f"{t.get('stock_name', '?')} ({t.get('grade', '?')})" for t in top5[:5]]
                    st.write(f"**{d}**: {', '.join(names)}")
        else:
            st.info("TOP5 ?°ì´?°ê? ?†ìŠµ?ˆë‹¤.")
            
    except Exception as e:
        st.error(f"?°ì´??ì¡°íšŒ ?¤íŒ¨: {e}")


# ?¸í„°
st.markdown("---")
st.caption(FOOTER_SEARCH)
