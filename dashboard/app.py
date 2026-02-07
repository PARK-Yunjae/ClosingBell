"""
ClosingBell ?€?œë³´??====================

?“Š ê°ì‹œì¢…ëª© TOP5 20??ì¶”ì  + ? ëª©ë¯?ê³µë?ë²?
?¤í–‰ ë°©ë²•:
- cd dashboard && streamlit run app.py
- ?ëŠ” run_dashboard.bat ?¤í–‰
"""

import streamlit as st
import sys
import os
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

# ?„ì—­?ìˆ˜ import
try:
    from src.config.app_config import (
        APP_VERSION, APP_NAME, APP_FULL_VERSION, AI_ENGINE,
        FOOTER_DASHBOARD, SIDEBAR_TITLE,
    )
except ImportError:
    # fallback
    APP_VERSION = "v9.1"
    APP_NAME = "ClosingBell"
    APP_FULL_VERSION = f"{APP_NAME} {APP_VERSION}"
    AI_ENGINE = "Gemini 2.5 Flash"
    FOOTER_DASHBOARD = APP_FULL_VERSION
    SIDEBAR_TITLE = f"?”” {APP_NAME}"

# plotly import (Streamlit Cloud ?¸í™˜)
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    st.error("? ï¸ plotly ?¨í‚¤ì§€ë¥?ì°¾ì„ ???†ìŠµ?ˆë‹¤. requirements.txtë¥??•ì¸?˜ì„¸??")

# Streamlit Cloud ëª¨ë“œ (API ??ë¶ˆí•„??
os.environ["DASHBOARD_ONLY"] = "true"

# ?„ë¡œ?íŠ¸ ë£¨íŠ¸ ì¶”ê? (dashboard ?´ë”?ì„œ ?¤í–‰?´ë„ ?™ì‘)
current_dir = Path(__file__).parent
project_root = current_dir.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# NOTE: os.chdir() ?¸ì¶œ ?œê±° - Streamlit multipageê°€ pages/ ?´ë”ë¥?ì°¾ì? ëª»í•˜???ì¸
# settings.py??BASE_DIR???´ë? ?ˆë? ê²½ë¡œë¥??¬ìš©?˜ë?ë¡?ë¶ˆí•„??
st.set_page_config(
    page_title=APP_FULL_VERSION,
    page_icon="?””",
    layout="wide",
)

# ==================== ?¬ì´?œë°” ?¤ë¹„ê²Œì´??====================
with st.sidebar:
    from dashboard.components.sidebar import render_sidebar_nav
    render_sidebar_nav()
    st.markdown("---")

# ==================== Repository ?±ê???====================
@st.cache_resource
def get_cached_repositories():
    """Repository ?¸ìŠ¤?´ìŠ¤ ìºì‹œ (1???ì„±)"""
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
        st.error(f"Repository ì´ˆê¸°???¤íŒ¨: {e}")
        return None

# ==================== ?¤ë” ====================
st.title(f"?”” {APP_FULL_VERSION}")
st.markdown("**ê°ì‹œì¢…ëª© TOP5 ì¶”ì  + ? ëª©ë¯?ê³µë?ë²?* | _ì°¨íŠ¸ê°€ ëª¨ë“  ê²ƒì„ ë°˜ì˜?œë‹¤_ ?“ˆ")
st.markdown("---")


# ==================== ?°ì´??ë¡œë“œ ====================
@st.cache_data(ttl=300)
def load_all_results(days=60):
    """?µì¼ ê²°ê³¼ ?°ì´??ë¡œë“œ"""
    try:
        repos = get_cached_repositories()
        if not repos:
            return []
        
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        
        results = repos['main'].get_next_day_results(start_date=start_date, end_date=end_date)
        return results
    except Exception as e:
        st.error(f"?°ì´??ë¡œë“œ ?¤íŒ¨: {e}")
        return []


@st.cache_data(ttl=300)
def load_top5_summary():
    """TOP5 20??ì¶”ì  ?”ì•½"""
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
    """? ëª©ë¯?ê³µë?ë²??”ì•½"""
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
    """? ëª©ë¯??±ì¥ ?Ÿìˆ˜ ??‚¹ (ìµœê·¼ N??"""
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
    """? ëª©ë¯??±ì¥ ?Ÿìˆ˜ ê·¸ë£¹ë³??¹ë¥  ?¤ì‹œê°?ê³„ì‚°"""
    try:
        import sqlite3
        from pathlib import Path
        
        db_path = Path(__file__).parent.parent / "data" / "screener.db"
        ohlcv_path = Path(os.getenv("DATA_DIR", str(Path(__file__).parent.parent))) / "ohlcv_kiwoom"
        
        if not db_path.exists():
            return None
        
        conn = sqlite3.connect(db_path)
        
        # ? ëª©ë¯??°ì´??ë¡œë“œ
        df_nomad = pd.read_sql_query("""
            SELECT stock_code, study_date
            FROM nomad_candidates
            ORDER BY stock_code, study_date
        """, conn)
        conn.close()
        
        if df_nomad.empty:
            return None
        
        # ì¢…ëª©ë³?ì´??±ì¥ ?Ÿìˆ˜
        occurrence_count = df_nomad.groupby('stock_code').size().reset_index(name='total_count')
        df_nomad = df_nomad.merge(occurrence_count, on='stock_code')
        
        # D+5 ?˜ìµë¥?ê³„ì‚° (?˜í”Œë§?- ìµœë? 300ê±?
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
        
        # ê·¸ë£¹ë³??¹ë¥  ê³„ì‚°
        bins = [0, 3, 7, 12, 100]
        labels = ['1~3??, '4~7??, '8~12??, '13??']
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


# ==================== ?µê³„ ?¨ìˆ˜ ====================
def calc_stats(results):
    """?¹ë¥  ?µê³„ ê³„ì‚°"""
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
    """?„ì  ?˜ìµë¥?ì°¨íŠ¸"""
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
            name='?„ì  ?˜ìµë¥?,
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
            name='?¼ë³„ ê°?ˆ˜?µë¥ ',
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
        xaxis2_title="? ì§œ",
        yaxis_title="?„ì  ?˜ìµë¥?(%)",
        yaxis2_title="?¼ë³„ (%)",
    )
    
    return fig


def create_gauge(value, title):
    """?¹ë¥  ê²Œì´ì§€"""
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


# ==================== ê¸°ëŠ¥ ?”ì•½ ì¹´ë“œ ====================
st.subheader("?“Œ ì£¼ìš” ê¸°ëŠ¥")

col1, col2 = st.columns(2)

with col1:
    top5_summary = load_top5_summary()
    st.markdown("### ?“ˆ ê°ì‹œì¢…ëª© TOP5")
    if top5_summary['dates_count'] > 0:
        st.success(f"??{top5_summary['dates_count']}???°ì´??| ìµœì‹ : {top5_summary['latest_date']}")
    else:
        st.warning("? ï¸ ?°ì´???†ìŒ")
    st.caption("D+1 ~ D+20 ?˜ìµë¥?ì¶”ì , CCI ?˜ë“œ?„í„°(250+)")

with col2:
    nomad_summary = load_nomad_summary()
    st.markdown("### ?“š ? ëª©ë¯?ê³µë?ë²?)
    if nomad_summary['dates_count'] > 0:
        st.success(f"??{nomad_summary['dates_count']}???°ì´??| ìµœì‹ : {nomad_summary['latest_date']}")
    else:
        st.warning("? ï¸ ?°ì´???†ìŒ")
    st.caption("?í•œê°€/ê±°ë˜?‰ì²œë§?ì¢…ëª©, ?¤ì´ë²?ê¸°ì—…?•ë³´, AI ë¶„ì„")

st.info("?‘ˆ **?¬ì´?œë°”?ì„œ ?˜ì´ì§€ë¥?? íƒ?˜ì„¸??*")
st.markdown("---")


# ==================== ë©”ì¸ ì»¨í…ì¸?(D+1 ?±ê³¼) ====================
st.subheader("?“Š D+1 ?±ê³¼ ?”ì•½ (ìµœê·¼ 60??")

results = load_all_results(60)

if results:
    stats = calc_stats(results)
    
    # ?ë‹¨: ?”ì•½ ì¹´ë“œ
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("?“ˆ ì´?ê±°ë˜", f"{stats['total']}ê±?)
    col2.metric("???¹ë¦¬", f"{stats['wins']}ê±?)
    col3.metric("?“Š ?¹ë¥ ", f"{stats['win_rate']:.1f}%", 
                delta="Good" if stats['win_rate'] >= 60 else None)
    col4.metric("?’° ?‰ê·  ê°?, f"{stats['avg_gap']:+.1f}%")
    col5.metric("?“ˆ ?‰ê·  ê³ ê?", f"{stats['avg_high']:+.1f}%")
    
    st.markdown("---")
    
    # ì¤‘ë‹¨: ?¹ë¥  ê²Œì´ì§€ + ?„ì  ?˜ìµë¥?    col1, col2 = st.columns([1, 2])
    
    with col1:
        gauge_fig = create_gauge(stats['win_rate'], "?„ì²´ ?¹ë¥ ")
        if gauge_fig:
            st.plotly_chart(gauge_fig, width="stretch")
        else:
            st.metric("?„ì²´ ?¹ë¥ ", f"{stats['win_rate']:.1f}%")
        
        st.markdown("##### ?“‹ ?ì„¸ ?µê³„")
        st.write(f"???¹ë¦¬: {stats['wins']}ê±?/ {stats['total']}ê±?)
        st.write(f"???‰ê·  ê°?ˆ˜?µë¥ : {stats['avg_gap']:+.1f}%")
        st.write(f"???‰ê·  ê³ ê??˜ìµë¥? {stats['avg_high']:+.1f}%")
    
    with col2:
        fig = create_cumulative_chart(results, "?“ˆ ?„ì  ?˜ìµë¥?& ?¼ë³„ ê°?ˆ˜?µë¥ ")
        if fig:
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("?“Š ì°¨íŠ¸ë¥??œì‹œ?˜ë ¤ë©?plotlyê°€ ?„ìš”?©ë‹ˆ??")
    
    st.markdown("---")
    
    # ?˜ë‹¨: ìµœê·¼ ê²°ê³¼ ?Œì´ë¸?    st.subheader(f"?“‹ ìµœê·¼ ê²°ê³¼ ({min(stats['total'], 10)}ê±?")
    
    df = pd.DataFrame(results)
    df['screen_date'] = pd.to_datetime(df['screen_date'])
    df = df.sort_values('screen_date', ascending=False)
    
    display_df = df[['screen_date', 'stock_code', 'stock_name', 'gap_rate', 'high_change_rate']].head(10)
    display_df.columns = ['? ì§œ', 'ì¢…ëª©ì½”ë“œ', 'ì¢…ëª©ëª?, 'ê°?ˆ˜?µë¥ (%)', 'ê³ ê??˜ìµë¥?%)']
    display_df['? ì§œ'] = display_df['? ì§œ'].dt.strftime('%m/%d')
    display_df['ê°?ˆ˜?µë¥ (%)'] = display_df['ê°?ˆ˜?µë¥ (%)'].apply(lambda x: f"{x:+.1f}" if pd.notna(x) else "-")
    display_df['ê³ ê??˜ìµë¥?%)'] = display_df['ê³ ê??˜ìµë¥?%)'].apply(lambda x: f"{x:+.1f}" if pd.notna(x) else "-")
    
    st.dataframe(display_df, width="stretch", hide_index=True)

else:
    st.info("?“­ D+1 ?±ê³¼ ?°ì´?°ê? ?†ìŠµ?ˆë‹¤. ë°±í•„ ???°ì´?°ê? ?“ì´ë©??œì‹œ?©ë‹ˆ??")

# ==================== ? ëª©ë¯??±ì¥ ?Ÿìˆ˜ ??‚¹ ====================
st.markdown("---")
st.subheader("?”¥ ? ëª©ë¯??±ì¥ ?Ÿìˆ˜ TOP 15 (ìµœê·¼ 30??")
st.caption("ë§ì´ ?±ì¥? ìˆ˜ë¡?ëª¨ë©˜?€ ê°•ë ¥! ?¹ë¥ ?€ D+5 ê¸°ì? ?¤ì‹œê°?ê³„ì‚°")

ranking_df = load_nomad_occurrence_ranking(days=30, top_n=15)

if not ranking_df.empty and PLOTLY_AVAILABLE:
    # ??ˆœ ?•ë ¬ (?„ë˜?ì„œ ?„ë¡œ ì¦ê?)
    ranking_df = ranking_df.sort_values('count', ascending=True)
    
    # ?‰ìƒ ì§€??(?±ì¥ ?Ÿìˆ˜???°ë¼)
    colors = []
    for cnt in ranking_df['count']:
        if cnt >= 13:
            colors.append('#FF5722')  # ëª¨ë©˜?€ ê°•ë ¥
        elif cnt >= 8:
            colors.append('#FF9800')  # ì£¼ëª©
        elif cnt >= 4:
            colors.append('#4CAF50')  # ?ìŠ¹??        else:
            colors.append('#9E9E9E')  # ì´ˆê¸°
    
    fig = go.Figure(go.Bar(
        x=ranking_df['count'],
        y=ranking_df['stock_name'],
        orientation='h',
        marker_color=colors,
        text=ranking_df['count'].astype(str) + '??,
        textposition='outside',
    ))
    
    fig.update_layout(
        height=450,
        margin=dict(l=10, r=50, t=10, b=10),
        xaxis_title="?±ì¥ ?Ÿìˆ˜",
        yaxis_title="",
        showlegend=False,
    )
    
    st.plotly_chart(fig, width='stretch')
    
    # ?¤ì‹œê°??¹ë¥  ê³„ì‚°
    win_rates = calc_nomad_win_rates()
    
    if win_rates:
        col1, col2, col3, col4 = st.columns(4)
        
        wr_13 = win_rates.get('13??', {})
        wr_8 = win_rates.get('8~12??, {})
        wr_4 = win_rates.get('4~7??, {})
        wr_1 = win_rates.get('1~3??, {})
        
        col1.markdown(f"?”´ **13??**: ëª¨ë©˜?€ ê°•ë ¥ (?¹ë¥  {wr_13.get('win_rate', 0):.0f}%, n={wr_13.get('n', 0)})")
        col2.markdown(f"?Ÿ  **8~12??*: ì£¼ëª© (?¹ë¥  {wr_8.get('win_rate', 0):.0f}%, n={wr_8.get('n', 0)})")
        col3.markdown(f"?Ÿ¢ **4~7??*: ?ìŠ¹??(?¹ë¥  {wr_4.get('win_rate', 0):.0f}%, n={wr_4.get('n', 0)})")
        col4.markdown(f"??**1~3??*: ì´ˆê¸° (?¹ë¥  {wr_1.get('win_rate', 0):.0f}%, n={wr_1.get('n', 0)})")
    else:
        col1, col2, col3, col4 = st.columns(4)
        col1.markdown("?”´ **13??**: ëª¨ë©˜?€ ê°•ë ¥")
        col2.markdown("?Ÿ  **8~12??*: ì£¼ëª©")
        col3.markdown("?Ÿ¢ **4~7??*: ?ìŠ¹??)
        col4.markdown("??**1~3??*: ì´ˆê¸°")
    
elif not ranking_df.empty:
    # plotly ?†ì„ ???Œì´ë¸”ë¡œ ?œì‹œ
    st.dataframe(ranking_df, width='stretch', hide_index=True)
else:
    st.info("?“­ ? ëª©ë¯??°ì´?°ê? ?†ìŠµ?ˆë‹¤. ë°±í•„ ???œì‹œ?©ë‹ˆ??")


# ==================== ?¬ì´?œë°” ====================
st.sidebar.markdown("---")
st.sidebar.markdown(f"### {SIDEBAR_TITLE} {APP_VERSION}")

# v6.5: ì¢…ëª© ê²€??(ê²€???˜ì´ì§€ë¡??´ë™)
st.sidebar.markdown("---")
st.sidebar.markdown("### ?” ë¹ ë¥¸ ê²€??)
search_query = st.sidebar.text_input(
    "ì¢…ëª©ì½”ë“œ/ì¢…ëª©ëª?,
    placeholder="?? 005930 ?ëŠ” ?¼ì„±",
    help="?”í„° ??ê²€???˜ì´ì§€ë¡??´ë™",
    label_visibility="collapsed",  # ?ì–´ ?¼ë²¨ ?¨ê?
)

if search_query and len(search_query) >= 2:
    # ê²€???˜ì´ì§€ë¡??´ë™ (query parameter ?„ë‹¬)
    st.switch_page("pages/3_stock_search.py")

st.sidebar.markdown("---")
st.sidebar.markdown(f"""
**{APP_VERSION} ?…ë°?´íŠ¸:**
- ?ìˆ˜??êµ¬ê°„ ìµœì ??- CCI 160~180 ìµœì 
- ?±ë½ë¥?4~6% ìµœì 
- ?´ê²©??2~8% ìµœì 
- ?°ì†?‘ë´‰ 2~3??ìµœì 
- DART + ?¤ì´ë²?ê¸°ì—…?•ë³´

**?„ëµ:**
- ê°ì‹œì¢…ëª© TOP5 (?ìˆ˜??
- ?µì¼ ?œê? ë§¤ë„
""")


# ==================== ?¸í„° ====================
st.markdown("---")
st.caption(f"{FOOTER_DASHBOARD} | ?ìˆ˜??êµ¬ê°„ ìµœì ??+ AI ë¶„ì„")
