"""
유목민 공부법 대시보드
======================

상한가/거래량천만 종목 분석
- 네이버 금융 + DART 기업정보
- Gemini 2.5 Flash AI 분석
- 숫자 표현: 소수점 1자리
"""

import os
os.environ["DASHBOARD_ONLY"] = "true"  # Streamlit Cloud: API 키 검증 스킵

import streamlit as st
import sys
from pathlib import Path
from datetime import date, timedelta
import pandas as pd
import json

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# 전역상수 import
try:
    from src.config.app_config import (
        APP_VERSION, APP_FULL_VERSION, AI_ENGINE, SIDEBAR_TITLE, FOOTER_NOMAD,
        MSG_COMPANY_INFO_AUTO,
    )
except ImportError:
    APP_VERSION = "v6.5"
    APP_FULL_VERSION = f"ClosingBell {APP_VERSION}"
    AI_ENGINE = "Gemini 2.5 Flash"
    SIDEBAR_TITLE = "🔔 ClosingBell"
    FOOTER_NOMAD = f"{APP_FULL_VERSION} | 유목민 공부법"
    MSG_COMPANY_INFO_AUTO = "기업정보는 매일 자동 수집됩니다."

st.set_page_config(
    page_title="유목민 공부법",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ==================== 사이드바 네비게이션 ====================
with st.sidebar:
    st.markdown(f"## {SIDEBAR_TITLE}")
    st.page_link("app.py", label="홈")
    st.page_link("pages/1_top5_tracker.py", label="종가매매 TOP5")
    st.page_link("pages/2_nomad_study.py", label="유목민 공부법")
    st.page_link("pages/3_stock_search.py", label="종목 검색")
    st.markdown("---")

st.title("📚 유목민 공부법")
st.markdown(f"**상한가/거래량천만 종목 분석** | _네이버 금융 + DART + {AI_ENGINE}_")
st.markdown("---")


# ==================== 데이터 로드 ====================
@st.cache_data(ttl=300)
def load_nomad_dates(limit=60):
    try:
        from src.infrastructure.repository import get_nomad_candidates_repository
        repo = get_nomad_candidates_repository()
        return repo.get_dates_with_data(limit)
    except Exception as e:
        st.error(f"날짜 로드 실패: {e}")
        return []


@st.cache_data(ttl=300)
def load_nomad_candidates(study_date, reason_filter=None):
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
    try:
        from src.infrastructure.repository import get_nomad_news_repository
        repo = get_nomad_news_repository()
        return repo.get_by_candidate(study_date, stock_code)
    except Exception:
        return []


@st.cache_data(ttl=300)
def get_occurrence_count(stock_code, days=30):
    """최근 N일간 유목민 등장 횟수 조회"""
    try:
        from src.infrastructure.repository import get_nomad_candidates_repository
        repo = get_nomad_candidates_repository()
        results = repo.search_occurrences(stock_code, limit=100)
        
        if not results:
            return 0, []
        
        # 최근 N일 필터
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=days)).date()
        
        recent = []
        for r in results:
            try:
                d = r.get('study_date')
                if isinstance(d, str):
                    d = datetime.strptime(d, '%Y-%m-%d').date()
                if d >= cutoff:
                    recent.append(r)
            except:
                pass
        
        return len(recent), recent
    except Exception:
        return 0, []


def occurrence_badge(count):
    """등장 횟수에 따른 배지 색상"""
    if count >= 13:
        return "🔥", "#FF5722", "모멘텀 강력"
    elif count >= 8:
        return "⭐", "#FF9800", "주목"
    elif count >= 4:
        return "📈", "#4CAF50", "상승세"
    else:
        return "🔹", "#9E9E9E", "초기"


def reason_emoji(reason):
    if '상한가' in reason and '거래량' in reason:
        return '🔥'
    elif '상한가' in reason:
        return '🚀'
    else:
        return '📈'


def reason_color(reason):
    if '상한가' in reason and '거래량' in reason:
        return '#FF5722'
    elif '상한가' in reason:
        return '#F44336'
    else:
        return '#2196F3'


def format_market_cap(cap):
    """시가총액 포맷 (소수점 1자리)"""
    if cap is None or cap <= 0:
        return "-"
    if cap >= 10000:
        return f"{cap/10000:.1f}조"
    return f"{cap:,.0f}억"


def evaluate_per(per):
    if per is None or per <= 0:
        return "-", "gray"
    if per < 10:
        return "저평가", "#4CAF50"
    elif per < 20:
        return "적정", "#FFC107"
    else:
        return "고평가", "#F44336"


def evaluate_pbr(pbr):
    if pbr is None or pbr <= 0:
        return "-", "gray"
    if pbr < 1:
        return "저평가", "#4CAF50"
    elif pbr < 2:
        return "적정", "#FFC107"
    else:
        return "고평가", "#F44336"


# ==================== AI 분석 함수 ====================
def generate_ai_analysis(candidate, news_list):
    """Gemini 2.0 Flash로 AI 분석 생성"""
    try:
        from google import genai
        
        # dotenv는 선택적 (Streamlit Cloud에서는 secrets 사용 가능)
        try:
            from dotenv import load_dotenv
            load_dotenv(project_root / '.env')
        except ImportError:
            pass  # Streamlit Cloud에서는 dotenv 없이 환경변수 사용
        
        api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
        
        if not api_key:
            return None, "Gemini API 키가 설정되지 않았습니다. .env 파일에 GEMINI_API_KEY를 추가하세요."
        
        # 새 API 클라이언트
        client = genai.Client(api_key=api_key)
        
        company_info = f"""
종목: {candidate['stock_name']} ({candidate['stock_code']})
등락률: {candidate['change_rate']:+.1f}%
사유: {candidate['reason_flag']}
시장: {candidate.get('market', '-')}
업종: {candidate.get('sector', '-')}
시가총액: {format_market_cap(candidate.get('market_cap'))}
PER: {candidate.get('per', '-')}
PBR: {candidate.get('pbr', '-')}
ROE: {candidate.get('roe', '-')}%
외국인보유율: {candidate.get('foreign_rate', '-')}%
사업내용: {candidate.get('business_summary', '-')[:300] if candidate.get('business_summary') else '-'}
"""
        
        news_text = ""
        if news_list:
            news_text = "\n관련 뉴스:\n"
            for news in news_list[:5]:
                news_text += f"- [{news.get('sentiment', '중립')}] {news.get('news_title', '')}\n"
        
        prompt = f"""
다음 종목에 대해 간결하게 분석해주세요. 각 항목은 1-2문장으로 작성하세요.

{company_info}
{news_text}

다음 형식으로 JSON으로 응답하세요:
{{
    "summary": "핵심 요약 (1문장)",
    "price_reason": "오늘 주가 움직임 원인 추정",
    "investment_points": ["투자 포인트 1", "투자 포인트 2"],
    "risk_factors": ["리스크 1", "리스크 2"],
    "valuation_comment": "밸류에이션 의견",
    "short_term_outlook": "단기 전망 (1-2주)",
    "recommendation": "매수/관망/매도 중 하나"
}}
"""
        
        # 새 API 호출
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        result_text = response.text
        
        if '```json' in result_text:
            result_text = result_text.split('```json')[1].split('```')[0]
        elif '```' in result_text:
            result_text = result_text.split('```')[1].split('```')[0]
        
        result = json.loads(result_text.strip())
        return result, None
        
    except ImportError:
        return None, "google-genai 패키지가 설치되지 않았습니다. pip install google-genai"
    except json.JSONDecodeError as e:
        return None, f"AI 응답 파싱 실패: {e}"
    except Exception as e:
        return None, f"AI 분석 실패: {e}"


def collect_single_company_info(stock_code):
    """단일 종목 기업정보 수집"""
    try:
        from src.services.company_service import fetch_naver_finance
        from src.infrastructure.repository import get_nomad_candidates_repository
        
        info = fetch_naver_finance(stock_code)
        if info:
            repo = get_nomad_candidates_repository()
            repo.update_company_info_by_code(stock_code, info)
            return True, info
        return False, None
    except Exception as e:
        return False, str(e)


# ==================== 사이드바 ====================
dates = load_nomad_dates(60)

if not dates:
    st.warning("📭 아직 수집된 유목민 데이터가 없습니다.")
    st.markdown("""
    ```bash
    python main.py --backfill 20
    ```
    """)
    st.stop()

st.sidebar.markdown("### 📅 날짜 선택")

# v6.5.2: date_input으로 변경 (종가매매 TOP5와 동일한 UX)
query_date = st.query_params.get("date", None)

# 기본 날짜 설정
if query_date and query_date in dates:
    default_date = date.fromisoformat(query_date)
else:
    default_date = date.fromisoformat(dates[0]) if dates else date.today()

selected_date_input = st.sidebar.date_input("공부 날짜", value=default_date)
selected_date = selected_date_input.isoformat()

# 데이터 있는 가장 가까운 날짜로 이동 버튼
if selected_date not in dates:
    # 선택한 날짜보다 이전 날짜 중 가장 가까운 날짜 찾기
    earlier_dates = [d for d in dates if d <= selected_date]
    if earlier_dates:
        closest_date = earlier_dates[0]
        if st.sidebar.button(f"→ {closest_date}로 표시"):
            selected_date = closest_date
            st.rerun()
    st.sidebar.warning(f"⚠️ {selected_date} 데이터 없음")

st.sidebar.markdown("### 🏷️ 필터")
reason_options = ["전체", "상한가", "거래량천만", "상한가+거래량"]
selected_reason = st.sidebar.radio("사유 필터", reason_options)

st.sidebar.markdown("---")
st.sidebar.caption(f"선택: {selected_date}")


# ==================== 메인 컨텐츠 ====================
candidates = load_nomad_candidates(selected_date, selected_reason if selected_reason != "전체" else None)

if not candidates:
    st.warning(f"📭 {selected_date} 날짜에 해당하는 종목이 없습니다.")
    st.stop()

# 요약 통계
st.subheader(f"📊 {selected_date} 요약")

reason_counts = {}
for c in candidates:
    r = c['reason_flag']
    reason_counts[r] = reason_counts.get(r, 0) + 1

company_collected = sum(1 for c in candidates if c.get('company_info_collected'))
ai_analyzed = sum(1 for c in candidates if c.get('ai_summary'))

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("📋 총 종목", f"{len(candidates)}개")
col2.metric("🚀 상한가", f"{reason_counts.get('상한가', 0)}개")
col3.metric("📈 거래량천만", f"{reason_counts.get('거래량천만', 0)}개")
col4.metric("🏢 기업정보", f"{company_collected}/{len(candidates)}")
col5.metric("🤖 AI분석", f"{ai_analyzed}/{len(candidates)}")

st.markdown("---")

# 종목 카드 그리드
st.subheader("📋 종목 목록")

# 카드 스타일 CSS (반응형 - 최대 5열)
st.markdown("""
<style>
/* Streamlit columns를 반응형 flexbox로 변경 */
[data-testid="stHorizontalBlock"] {
    flex-wrap: wrap !important;
    gap: 12px !important;
}
[data-testid="stColumn"] {
    flex: 1 1 200px !important;
    min-width: 200px !important;
    max-width: calc(20% - 10px) !important;
    width: auto !important;
}
/* 반응형 breakpoints */
@media (max-width: 1400px) {
    [data-testid="stColumn"] {
        max-width: calc(25% - 10px) !important;
    }
}
@media (max-width: 1100px) {
    [data-testid="stColumn"] {
        max-width: calc(33.33% - 10px) !important;
    }
}
@media (max-width: 800px) {
    [data-testid="stColumn"] {
        max-width: calc(50% - 10px) !important;
    }
}
@media (max-width: 500px) {
    [data-testid="stColumn"] {
        max-width: 100% !important;
        min-width: 100% !important;
    }
}
.nomad-card {
    background: linear-gradient(135deg, rgba(0,0,0,0.02), rgba(0,0,0,0.01));
    border-radius: 8px;
    padding: 12px;
    border-left: 4px solid #ccc;
    min-height: 100px;
    transition: box-shadow 0.2s;
}
.nomad-card:hover {
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}
.nomad-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 4px;
}
.nomad-name {
    font-size: 16px;
    font-weight: bold;
    margin-bottom: 2px;
}
.nomad-code {
    font-size: 11px;
    color: #888;
}
.nomad-change {
    font-size: 18px;
    font-weight: bold;
}
.nomad-badge {
    font-size: 10px;
    padding: 2px 6px;
    border-radius: 4px;
    display: inline-block;
}
</style>
""", unsafe_allow_html=True)

# 5열 레이아웃 (CSS가 반응형으로 조절)
num_cols = 5
cols = st.columns(num_cols)
for i, candidate in enumerate(candidates):
    with cols[i % num_cols]:
        # 상태 아이콘
        status_icons = ""
        if candidate.get('company_info_collected'):
            status_icons += "🏢"
        if candidate.get('ai_summary'):
            status_icons += "🤖"
        
        # 최근 30일 등장 횟수
        occ_count, _ = get_occurrence_count(candidate['stock_code'], days=30)
        occ_emoji, occ_color, occ_label = occurrence_badge(occ_count)
        
        # 거래대금 표시
        tv = candidate.get('trading_value', 0)
        if tv >= 10000:
            tv_str = f"{tv/10000:.1f}조"
        elif tv >= 1:
            tv_str = f"{tv:.0f}억"
        else:
            tv_str = "-"
        
        # 등락률 색상
        change_color = '#4CAF50' if candidate['change_rate'] > 0 else '#F44336'
        border_color = reason_color(candidate['reason_flag'])
        
        st.markdown(f"""
        <div class="nomad-card" style="border-left-color: {border_color};">
            <div class="nomad-header">
                <span style="font-size: 11px; color: #888;">
                    {reason_emoji(candidate['reason_flag'])} {candidate['reason_flag']}
                </span>
                <span>{status_icons}</span>
            </div>
            <div class="nomad-name">{candidate['stock_name']}</div>
            <div class="nomad-code">{candidate['stock_code']} | 거래대금: {tv_str}</div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 6px;">
                <span class="nomad-change" style="color: {change_color};">{candidate['change_rate']:+.1f}%</span>
                <span class="nomad-badge" style="background: {occ_color}20; color: {occ_color};">
                    {occ_emoji} {occ_count}회 ({occ_label})
                </span>
            </div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("---")

# 종목 상세 선택
st.subheader("🔍 종목 상세 분석")

stock_options = [f"{c['stock_name']} ({c['stock_code']})" for c in candidates]
selected_stock_str = st.selectbox("종목 선택", stock_options)

if selected_stock_str:
    selected_idx = stock_options.index(selected_stock_str)
    selected_candidate = candidates[selected_idx]
    
    # 등장 횟수 정보
    detail_occ_count, detail_occ_history = get_occurrence_count(selected_candidate['stock_code'], days=30)
    detail_emoji, detail_color, detail_label = occurrence_badge(detail_occ_count)
    
    # 등장 횟수 요약 박스
    st.markdown(f"""
    <div style="
        background: linear-gradient(135deg, {detail_color}22, {detail_color}11);
        border-left: 4px solid {detail_color};
        padding: 15px;
        border-radius: 5px;
        margin-bottom: 15px;
    ">
        <span style="font-size: 18px; font-weight: bold; color: {detail_color};">
            {detail_emoji} 최근 30일 {detail_occ_count}회 등장 - {detail_label}
        </span>
        <span style="font-size: 12px; color: #666; margin-left: 10px;">
            (4~7회: 상승세, 8~12회: 주목, 13회+: 모멘텀 강력)
        </span>
    </div>
    """, unsafe_allow_html=True)
    
    tab1, tab2, tab3 = st.tabs(["🏢 기업정보", "📰 뉴스", "🤖 AI 분석"])
    
    with tab1:
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.markdown("##### 📊 기본 정보")
            st.write(f"• **종목명**: {selected_candidate['stock_name']}")
            st.write(f"• **종목코드**: {selected_candidate['stock_code']}")
            st.write(f"• **사유**: {reason_emoji(selected_candidate['reason_flag'])} {selected_candidate['reason_flag']}")
            st.write(f"• **시장**: {selected_candidate.get('market', '-')}")
            st.write(f"• **업종**: {selected_candidate.get('sector', '-')}")
            
            st.markdown("---")
            st.markdown("##### 💰 가격 정보")
            st.write(f"• **종가**: {selected_candidate['close_price']:,}원")
            st.write(f"• **등락률**: {selected_candidate['change_rate']:+.1f}%")
            st.write(f"• **거래량**: {selected_candidate['volume']:,}주")
            st.write(f"• **거래대금**: {selected_candidate['trading_value']:.0f}억원")
            
            if selected_candidate.get('high_52w'):
                st.markdown("---")
                st.markdown("##### 📈 52주 범위")
                high_52w = selected_candidate.get('high_52w', 0)
                low_52w = selected_candidate.get('low_52w', 0)
                current = selected_candidate['close_price']
                
                if high_52w > low_52w:
                    position = (current - low_52w) / (high_52w - low_52w) * 100
                    st.progress(int(position) / 100)
                    st.caption(f"최저 {low_52w:,}원 ↔ 최고 {high_52w:,}원 | 현재 위치: {position:.1f}%")
        
        with col2:
            st.markdown("##### 📊 밸류에이션")
            
            per = selected_candidate.get('per')
            pbr = selected_candidate.get('pbr')
            roe = selected_candidate.get('roe')
            
            per_eval, _ = evaluate_per(per)
            pbr_eval, _ = evaluate_pbr(pbr)
            
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("PER", f"{per:.1f}" if per else "-", per_eval)
            col_b.metric("PBR", f"{pbr:.1f}" if pbr else "-", pbr_eval)
            col_c.metric("ROE", f"{roe:.1f}%" if roe else "-")
            
            st.markdown("---")
            st.markdown("##### 🏦 시가총액")
            st.write(f"• **시가총액**: {format_market_cap(selected_candidate.get('market_cap'))}")
            if selected_candidate.get('market_cap_rank'):
                st.write(f"• **순위**: {selected_candidate.get('market_cap_rank')}위")
            
            st.markdown("---")
            st.markdown("##### 🌍 외국인/투자의견")
            foreign_rate = selected_candidate.get('foreign_rate')
            st.write(f"• **외국인 보유율**: {foreign_rate:.1f}%" if foreign_rate else "• **외국인 보유율**: -")
            st.write(f"• **투자의견**: {selected_candidate.get('analyst_recommend', '-')}")
            target = selected_candidate.get('target_price')
            st.write(f"• **목표주가**: {target:,}원" if target else "• **목표주가**: -")
        
        if selected_candidate.get('business_summary'):
            st.markdown("---")
            st.markdown("##### 📝 사업 내용")
            st.info(selected_candidate['business_summary'])
        
        # v6.5: 재수집 버튼 제거 (배포 환경 에러 방지)
        st.markdown("---")
        st.caption(f"ℹ️ {MSG_COMPANY_INFO_AUTO}")
    
    with tab2:
        news_list = load_nomad_news(selected_date, selected_candidate['stock_code'])
        
        if news_list:
            for news in news_list:
                sentiment = news.get('sentiment', '중립')
                if sentiment in ['positive', '호재']:
                    sentiment_color = '#4CAF50'
                    sentiment_icon = '🟢'
                elif sentiment in ['negative', '악재']:
                    sentiment_color = '#F44336'
                    sentiment_icon = '🔴'
                else:
                    sentiment_color = '#9E9E9E'
                    sentiment_icon = '⚪'
                
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
                        {news.get('news_source', '')} | {news.get('news_date', '')[:10] if news.get('news_date') else ''}
                    </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("📭 수집된 뉴스가 없습니다.")
    
    with tab3:
        if selected_candidate.get('ai_summary'):
            try:
                summary = json.loads(selected_candidate['ai_summary'])
                
                col1, col2 = st.columns(2)
                
                with col1:
                    if summary.get('summary'):
                        st.markdown("##### 📌 핵심 요약")
                        st.info(summary['summary'])
                    
                    if summary.get('price_reason'):
                        st.markdown("##### 📈 주가 움직임 원인")
                        st.write(summary['price_reason'])
                    
                    if summary.get('investment_points'):
                        st.markdown("##### ✅ 투자 포인트")
                        for point in summary['investment_points']:
                            st.write(f"• {point}")
                
                with col2:
                    if summary.get('risk_factors'):
                        st.markdown("##### ⚠️ 리스크 요인")
                        for risk in summary['risk_factors']:
                            st.write(f"• {risk}")
                    
                    if summary.get('valuation_comment'):
                        st.markdown("##### 💰 밸류에이션 의견")
                        st.write(summary['valuation_comment'])
                    
                    if summary.get('recommendation'):
                        st.markdown("##### 🎯 추천")
                        rec = summary['recommendation']
                        if '매수' in rec:
                            st.success(f"📈 {rec}")
                        elif '매도' in rec:
                            st.error(f"📉 {rec}")
                        else:
                            st.warning(f"⏸️ {rec}")
                            
            except json.JSONDecodeError:
                st.write(selected_candidate['ai_summary'])
        else:
            st.info("🤖 AI 분석이 아직 생성되지 않았습니다. 로컬에서 백필을 실행해주세요.")


# ==================== 푸터 ====================
st.markdown("---")
st.caption(FOOTER_NOMAD)