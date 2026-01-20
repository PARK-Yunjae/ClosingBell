"""
유목민 공부법 대시보드
======================

v6.0: 상한가/거래량천만 종목 뉴스 분석
"""

import streamlit as st
import sys
import os
from pathlib import Path
from datetime import date, timedelta
import pandas as pd
import json

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

st.set_page_config(
    page_title="유목민 공부법",
    page_icon="📚",
    layout="wide",
)

st.title("📚 유목민 공부법")
st.markdown("**상한가/거래량천만 종목 뉴스 분석** | _왜 올랐는지 알아야 한다_")
st.markdown("---")


# ==================== 데이터 로드 ====================
@st.cache_data(ttl=300)
def load_nomad_dates(limit=60):
    """유목민 데이터가 있는 날짜 목록"""
    try:
        from src.infrastructure.repository import get_nomad_candidates_repository
        repo = get_nomad_candidates_repository()
        return repo.get_dates_with_data(limit)
    except Exception as e:
        st.error(f"날짜 로드 실패: {e}")
        return []


@st.cache_data(ttl=300)
def load_nomad_candidates(study_date, reason_filter=None):
    """특정 날짜의 후보 종목"""
    try:
        from src.infrastructure.repository import get_nomad_candidates_repository
        repo = get_nomad_candidates_repository()
        
        if reason_filter and reason_filter != "전체":
            return repo.get_by_date_and_reason(study_date, reason_filter)
        else:
            return repo.get_by_date(study_date)
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return []


@st.cache_data(ttl=300)
def load_nomad_news(study_date, stock_code):
    """종목 뉴스"""
    try:
        from src.infrastructure.repository import get_nomad_news_repository
        repo = get_nomad_news_repository()
        return repo.get_by_candidate(study_date, stock_code)
    except Exception as e:
        return []


def reason_emoji(reason):
    """사유 이모지"""
    if '상한가' in reason and '거래량' in reason:
        return '🔥'
    elif '상한가' in reason:
        return '🚀'
    else:  # 거래량천만
        return '📈'


def reason_color(reason):
    """사유 색상"""
    if '상한가' in reason and '거래량' in reason:
        return '#FF5722'  # 주황
    elif '상한가' in reason:
        return '#F44336'  # 빨강
    else:
        return '#2196F3'  # 파랑


# ==================== 사이드바: 날짜 선택 ====================
dates = load_nomad_dates(60)

if not dates:
    st.warning("📭 아직 수집된 유목민 데이터가 없습니다.")
    st.markdown("""
    ### 🚀 데이터 수집 방법
    
    ```bash
    # 과거 데이터 백필 (최초 1회)
    python main.py --backfill 20
    
    # 또는 오늘의 유목민 공부
    python main.py --run-nomad
    ```
    """)
    st.stop()

st.sidebar.markdown("### 📅 날짜 선택")
selected_date = st.sidebar.selectbox(
    "공부 날짜",
    dates,
    format_func=lambda x: x
)

st.sidebar.markdown("### 🏷️ 필터")
reason_options = ["전체", "상한가", "거래량천만", "상한가+거래량"]
selected_reason = st.sidebar.radio("사유 필터", reason_options)

st.sidebar.markdown("---")
st.sidebar.markdown(f"**선택된 날짜**: {selected_date}")
st.sidebar.markdown(f"**전체 데이터**: {len(dates)}일")


# ==================== 메인 컨텐츠 ====================
candidates = load_nomad_candidates(selected_date, selected_reason if selected_reason != "전체" else None)

if not candidates:
    st.warning(f"📭 {selected_date} 날짜에 해당하는 종목이 없습니다.")
    st.stop()

# 요약 통계
st.subheader(f"📊 {selected_date} 요약")

# 사유별 카운트
reason_counts = {}
for c in candidates:
    r = c['reason_flag']
    reason_counts[r] = reason_counts.get(r, 0) + 1

# 뉴스 수집 상태
news_collected = sum(1 for c in candidates if c.get('news_status') == 'collected')

col1, col2, col3, col4 = st.columns(4)
col1.metric("📋 총 종목", f"{len(candidates)}개")
col2.metric("🚀 상한가", f"{reason_counts.get('상한가', 0)}개")
col3.metric("📈 거래량천만", f"{reason_counts.get('거래량천만', 0)}개")
col4.metric("📰 뉴스 수집", f"{news_collected}/{len(candidates)}")

st.markdown("---")

# 종목 선택
st.subheader("📋 종목 목록")

# 종목 카드 그리드
cols = st.columns(3)
for i, candidate in enumerate(candidates):
    with cols[i % 3]:
        st.markdown(f"""
        <div style="
            background: linear-gradient(135deg, {reason_color(candidate['reason_flag'])}22, {reason_color(candidate['reason_flag'])}11);
            border-left: 4px solid {reason_color(candidate['reason_flag'])};
            padding: 12px;
            border-radius: 5px;
            margin-bottom: 10px;
        ">
            <div style="font-size: 11px; color: #888;">{reason_emoji(candidate['reason_flag'])} {candidate['reason_flag']}</div>
            <div style="font-size: 16px; font-weight: bold;">{candidate['stock_name']}</div>
            <div style="font-size: 13px; color: #666;">{candidate['stock_code']}</div>
            <div style="font-size: 14px; color: {'#4CAF50' if candidate['change_rate'] > 0 else '#F44336'};">
                {candidate['change_rate']:+.2f}%
            </div>
            <div style="font-size: 12px; color: #888;">
                거래대금: {candidate['trading_value']:.1f}억
            </div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("---")

# 종목 상세 선택
st.subheader("🔍 종목 상세 분석")

stock_options = [f"{c['stock_name']} ({c['stock_code']})" for c in candidates]
selected_stock_str = st.selectbox("종목 선택", stock_options)

if selected_stock_str:
    # 선택된 종목 찾기
    selected_idx = stock_options.index(selected_stock_str)
    selected_candidate = candidates[selected_idx]
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.markdown("##### 📊 기업 정보")
        
        # 기본 정보
        st.write(f"• **종목명**: {selected_candidate['stock_name']}")
        st.write(f"• **종목코드**: {selected_candidate['stock_code']}")
        st.write(f"• **사유**: {reason_emoji(selected_candidate['reason_flag'])} {selected_candidate['reason_flag']}")
        
        st.markdown("---")
        
        # 가격 정보
        st.markdown("##### 💰 가격 정보")
        st.write(f"• **종가**: {selected_candidate['close_price']:,}원")
        st.write(f"• **등락률**: {selected_candidate['change_rate']:+.2f}%")
        st.write(f"• **거래량**: {selected_candidate['volume']:,}주")
        st.write(f"• **거래대금**: {selected_candidate['trading_value']:.1f}억원")
        
        st.markdown("---")
        
        # 기업 상세 (수집된 경우)
        if selected_candidate.get('market'):
            st.markdown("##### 🏢 기업 상세")
            st.write(f"• **시장**: {selected_candidate.get('market', '-')}")
            
            # 섹터 (숫자가 아닌 경우만 표시)
            sector = selected_candidate.get('sector', '-')
            if sector and not str(sector).replace(',', '').replace('.', '').isdigit():
                st.write(f"• **섹터**: {sector}")
            else:
                st.write("• **섹터**: -")
            
            # 시가총액
            market_cap = selected_candidate.get('market_cap')
            if market_cap and market_cap > 0:
                st.write(f"• **시가총액**: {market_cap/100000000:.0f}억원")
            else:
                st.write("• **시가총액**: -")
            
            # PER/PBR/ROE (비정상 값 필터링: 종목코드가 들어간 경우 1000 이상)
            per = selected_candidate.get('per')
            pbr = selected_candidate.get('pbr')
            roe = selected_candidate.get('roe')
            st.write(f"• **PER**: {per:.1f}" if per and per < 1000 else "• **PER**: -")
            st.write(f"• **PBR**: {pbr:.1f}" if pbr and pbr < 100 else "• **PBR**: -")
            st.write(f"• **ROE**: {roe:.1f}%" if roe and abs(roe) < 1000 else "• **ROE**: -")
            
            if selected_candidate.get('business_summary'):
                st.markdown("---")
                st.markdown("##### 📝 사업 내용")
                st.write(selected_candidate['business_summary'])
    
    with col2:
        st.markdown("##### 📰 관련 뉴스")
        
        news_list = load_nomad_news(selected_date, selected_candidate['stock_code'])
        
        if news_list:
            for news in news_list:
                # 감성 색상 (한글)
                sentiment = news.get('sentiment', '중립')
                if sentiment in ['positive', '호재']:
                    sentiment_color = '#4CAF50'
                    sentiment_icon = '🟢'
                    sentiment_text = '호재'
                elif sentiment in ['negative', '악재']:
                    sentiment_color = '#F44336'
                    sentiment_icon = '🔴'
                    sentiment_text = '악재'
                else:
                    sentiment_color = '#9E9E9E'
                    sentiment_icon = '⚪'
                    sentiment_text = '중립'
                
                # 카테고리
                category = news.get('category', '')
                category_text = f" [{category}]" if category else ""
                
                st.markdown(f"""
                <div style="
                    background: #f8f9fa;
                    border-left: 3px solid {sentiment_color};
                    padding: 10px;
                    margin-bottom: 10px;
                    border-radius: 3px;
                ">
                    <div style="font-size: 14px; font-weight: bold;">
                        {sentiment_icon} <a href="{news.get('news_url', '#')}" target="_blank" style="text-decoration: none; color: #333;">
                            {news.get('news_title', '제목 없음')}
                        </a>
                    </div>
                    <div style="font-size: 12px; color: #666; margin-top: 5px;">
                        {news.get('news_source', '')} | {news.get('news_date', '')[:10] if news.get('news_date') else ''}{category_text}
                    </div>
                    <div style="font-size: 13px; color: #555; margin-top: 5px;">
                        {news.get('summary', '')[:150]}...
                    </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            if selected_candidate.get('news_collected'):
                st.info("📭 수집된 뉴스가 없습니다.")
            else:
                st.info("📭 뉴스 수집 대기 중...")
                st.caption("터미널에서 실행: `python main.py --run-news`")
        
        # AI 요약 (있는 경우)
        if selected_candidate.get('ai_summary'):
            st.markdown("---")
            st.markdown("##### 🤖 AI 분석")
            
            try:
                summary = json.loads(selected_candidate['ai_summary'])
                
                if summary.get('summary'):
                    st.write(f"**요약**: {summary['summary']}")
                
                if summary.get('investment_points'):
                    st.write("**투자 포인트**:")
                    for point in summary['investment_points']:
                        st.write(f"• {point}")
                
                if summary.get('risk_factors'):
                    st.write("**리스크 요인**:")
                    for risk in summary['risk_factors']:
                        st.write(f"• {risk}")
                        
            except json.JSONDecodeError:
                st.write(selected_candidate['ai_summary'])


# ==================== 푸터 ====================
st.markdown("---")
st.caption("ClosingBell v6.0 | 유목민 공부법")
