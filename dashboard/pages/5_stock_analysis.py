"""
🧾 종목 심층 분석 대시보드 v9.1
- 모든 설명을 쉬운 한국어로
- 풍부한 차트와 시각화
- 신호등 시스템
"""

import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import streamlit as st

try:
    import pandas as pd
except Exception:
    pd = None

if os.getenv("STREAMLIT_SERVER_HEADLESS", "").lower() == "true":
    os.environ.setdefault("DASHBOARD_ONLY", "true")

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except Exception:
    go = None
    make_subplots = None

try:
    from src.config.app_config import (
        APP_FULL_VERSION,
        FOOTER_DASHBOARD,
        SIDEBAR_TITLE,
        OHLCV_DIR,
        OHLCV_FULL_DIR,
    )
except ImportError:
    APP_FULL_VERSION = "ClosingBell v10.1"
    FOOTER_DASHBOARD = APP_FULL_VERSION
    SIDEBAR_TITLE = "🔔 ClosingBell"
    OHLCV_DIR = None
    OHLCV_FULL_DIR = None

try:
    from dashboard.components.sidebar import render_sidebar_nav
except ImportError:
    def render_sidebar_nav():
        st.page_link("app.py", label="🏠 홈")
        st.page_link("pages/1_top5_tracker.py", label="📊 감시종목 TOP5")
        st.page_link("pages/2_nomad_study.py", label="📚 유목민 공부법")
        st.page_link("pages/3_stock_search.py", label="🔍 종목 검색")
        st.page_link("pages/4_broker_flow.py", label="💰 거래원 수급")
        st.page_link("pages/5_stock_analysis.py", label="🧾 종목 심층 분석")
        st.page_link("pages/6_holdings_watch.py", label="📌 보유종목 관찰")


# ────────────────────────────────────────────────────
# 설정 & 유틸
# ────────────────────────────────────────────────────

# 신호등 색상 (Streamlit 호환)
SIG_COLORS = {
    "good":    {"bg": "#d4edda", "border": "#28a745", "icon": "🟢", "label": "양호"},
    "neutral": {"bg": "#fff3cd", "border": "#ffc107", "icon": "🟡", "label": "보통"},
    "warning": {"bg": "#f8d7da", "border": "#dc3545", "icon": "🔴", "label": "주의"},
}


def _signal_card(title: str, value: str, level: str) -> str:
    """신호등 카드 HTML"""
    c = SIG_COLORS.get(level, SIG_COLORS["neutral"])
    return f"""
    <div style="text-align:center; padding:12px 8px; border-radius:12px;
                background:{c['bg']}; border:2px solid {c['border']};
                margin:4px 2px; min-height:90px;">
        <div style="font-size:22px;">{c['icon']}</div>
        <div style="font-size:11px; color:#666; margin:2px 0;">{title}</div>
        <div style="font-size:13px; font-weight:700; color:#222;">{value}</div>
    </div>"""


def _info_card(title: str, content: str, emoji: str = "📌") -> None:
    """설명 카드 렌더링"""
    st.markdown(f"""
    <div style="padding:16px; border-radius:12px; background:#f8f9fa;
                border-left:4px solid #6c8ef5; margin:8px 0;">
        <div style="font-size:15px; font-weight:700; margin-bottom:8px;">
            {emoji} {title}
        </div>
        <div style="font-size:13px; color:#444; line-height:1.7;">
            {content}
        </div>
    </div>""", unsafe_allow_html=True)


def _gauge_chart(value: float, title: str,
                 ranges: List[Tuple[float, float, str, str]],
                 suffix: str = "") -> Optional[object]:
    """게이지 차트 생성 (CCI, RSI 등)"""
    if go is None:
        return None
    min_v = min(r[0] for r in ranges)
    max_v = max(r[1] for r in ranges)
    steps = [dict(range=[r[0], r[1]], color=r[3]) for r in ranges]
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        title={"text": title, "font": {"size": 14}},
        number={"suffix": suffix, "font": {"size": 20}},
        gauge={
            "axis": {"range": [min_v, max_v], "tickfont": {"size": 10}},
            "bar": {"color": "#333", "thickness": 0.25},
            "steps": steps,
            "threshold": {
                "line": {"color": "#333", "width": 3},
                "thickness": 0.8,
                "value": value,
            },
        },
    ))
    fig.update_layout(height=200, margin=dict(l=20, r=20, t=40, b=10))
    return fig


# ────────────────────────────────────────────────────
# 데이터 로딩 함수
# ────────────────────────────────────────────────────

def _resolve_ohlcv_path(code: str) -> Optional[Path]:
    bases: List[Path] = []
    for base in [OHLCV_FULL_DIR, OHLCV_DIR]:
        if base and base not in bases:
            bases.append(base)
    try:
        from src.config.backfill_config import get_backfill_config
        cfg = get_backfill_config()
        base = cfg.get_active_ohlcv_dir()
        if base and base not in bases:
            bases.append(base)
    except Exception:
        pass
    for base in bases:
        for name in [f"{code}.csv", f"A{code}.csv"]:
            p = Path(base) / name
            if p.exists():
                return p
    return None


@st.cache_data(ttl=1800)
def _load_ohlcv_df(code: str) -> Tuple[Optional[object], str]:
    if pd is None:
        return None, "pandas 없음"
    path = _resolve_ohlcv_path(code)
    if path:
        try:
            from src.services.backfill.data_loader import load_single_ohlcv
            df = load_single_ohlcv(path)
            if df is not None and not df.empty:
                return df, "로컬"
        except Exception:
            pass
    try:
        import FinanceDataReader as fdr
        end = datetime.now().date()
        start = end - timedelta(days=365 * 2)
        df = fdr.DataReader(code, start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
        if df is not None and not df.empty:
            df = df.reset_index()
            df.columns = [c.lower().strip() for c in df.columns]
            # 날짜 컬럼 통일
            for col in ['index', 'unnamed: 0', '']:
                if col in df.columns and col != 'date':
                    df = df.rename(columns={col: 'date'})
                    break
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'], errors='coerce')
                df = df.dropna(subset=['date'])
            return df, "온라인"
    except Exception:
        pass
    return None, "없음"


@st.cache_data(ttl=3600)
def _fetch_financials(code: str) -> Dict:
    if not os.getenv("DART_API_KEY"):
        return {}
    try:
        from src.services.dart_service import get_dart_service
        dart = get_dart_service()
        year = str(datetime.now().year - 1)
        prev_year = str(int(year) - 1)
        cur = dart.get_financial_summary(code, year=year)
        prev = dart.get_financial_summary(code, year=prev_year)
        return {
            "year": year,
            "revenue": cur.get("revenue") if cur else None,
            "operating_profit": cur.get("operating_profit") if cur else None,
            "net_income": cur.get("net_income") if cur else None,
            "prev_revenue": prev.get("revenue") if prev else None,
            "prev_operating_profit": prev.get("operating_profit") if prev else None,
            "prev_net_income": prev.get("net_income") if prev else None,
        }
    except Exception:
        return {}


@st.cache_data(ttl=3600)
def _fetch_broker_series(code: str, limit: int = 60) -> Optional[object]:
    if pd is None:
        return None
    try:
        from src.infrastructure.repository import get_broker_signal_repository
        repo = get_broker_signal_repository()
        rows = repo.get_signals_by_code(code, limit=limit)
        if not rows:
            return None
        df = pd.DataFrame(rows)
        if "screen_date" in df.columns:
            df["screen_date"] = pd.to_datetime(df["screen_date"], errors="coerce")
            df = df.sort_values("screen_date")
        return df
    except Exception:
        return None


# ────────────────────────────────────────────────────
# 리포트 파싱
# ────────────────────────────────────────────────────

def _find_latest_report(code_value: str) -> Optional[Path]:
    if not code_value:
        return None
    report_dir = Path("reports")
    if not report_dir.exists():
        return None
    files = sorted(report_dir.glob(f"*_{code_value}.md"))
    return files[-1] if files else None


def _list_reports() -> List[Path]:
    report_dir = Path("reports")
    if not report_dir.exists():
        return []
    return sorted(report_dir.glob("*_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)


def _load_report_sections(report_path: Path) -> Dict[str, List[str]]:
    """리포트를 ## 기준으로 섹션 분리 (영문 섹션명도 한글로 변환)"""
    # 이전 버전 영문 섹션명 → 현재 한글 매핑
    SECTION_ALIAS = {
        "Holdings Snapshot": "보유 관찰 현황",
        "OHLCV Summary": "가격 거래 요약",
        "Volume Profile": "매물대 분석",
        "Technical Analysis": "기술 지표 분석",
        "Broker Flow": "거래원 수급 분석",
        "News & Disclosures": "뉴스 공시",
        "Easy Summary": "쉬운 요약",
        "DART Company Profile": "기업 정보",
        "AI Summary": "AI 분석 의견",
        "Entry/Exit Plan": "매매 계획",
        "Summary": "종합 판단",
        "보유/관찰 현황": "보유 관찰 현황",
        "가격/거래 요약": "가격 거래 요약",
        "매물대 요약": "매물대 분석",
        "기술 지표": "기술 지표 분석",
        "거래원 수급": "거래원 수급 분석",
        "뉴스/공시": "뉴스 공시",
        "기업정보(DART)": "기업 정보",
        "AI 요약": "AI 분석 의견",
        "진입/이탈 계획": "매매 계획",
        "최종 요약": "종합 판단",
    }
    sections: Dict[str, List[str]] = {}
    if not report_path or not report_path.exists():
        return sections
    lines = report_path.read_text(encoding="utf-8").splitlines()
    current = "_header"
    sections[current] = []
    for line in lines:
        if line.startswith("## "):
            raw_title = line[3:].strip()
            current = SECTION_ALIAS.get(raw_title, raw_title)
            if current not in sections:
                sections[current] = []
            continue
        sections.setdefault(current, []).append(line)
    return sections


def _parse_easy_subsections(lines: List[str]) -> List[Tuple[str, str]]:
    """쉬운 요약의 ### 서브섹션 분리"""
    result: List[Tuple[str, str]] = []
    current_title = ""
    current_lines: List[str] = []

    for line in lines:
        if line.startswith("### "):
            if current_title:
                result.append((current_title, "\n".join(current_lines)))
            current_title = line[4:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_title:
        result.append((current_title, "\n".join(current_lines)))
    return result


# ────────────────────────────────────────────────────
# 기술 지표 파싱 헬퍼
# ────────────────────────────────────────────────────

def _extract_number(text: str, keyword: str) -> Optional[float]:
    """텍스트에서 특정 키워드 뒤의 숫자 추출"""
    for line in text.split("\n"):
        if keyword in line:
            nums = re.findall(r"[-+]?\d*\.?\d+", line.split(keyword)[-1])
            if nums:
                return float(nums[0])
    return None


def _extract_section_data(sections: Dict, key: str) -> str:
    """섹션 내용을 텍스트로 결합"""
    if key not in sections:
        return ""
    return "\n".join(sections[key])


# ────────────────────────────────────────────────────
# 메인 페이지
# ────────────────────────────────────────────────────

st.set_page_config(
    page_title="종목 심층 분석",
    page_icon="🧾",
    layout="wide",
)

with st.sidebar:
    render_sidebar_nav()

st.title("🧾 종목 심층 분석")
st.caption(APP_FULL_VERSION)

# 모드 확인
dashboard_only = os.getenv("DASHBOARD_ONLY", "").lower() == "true"
missing_kiwoom = not os.getenv("KIWOOM_APPKEY") or not os.getenv("KIWOOM_SECRETKEY")
read_only = dashboard_only or missing_kiwoom

if read_only:
    st.info("📖 보기 전용 모드 — 스케줄러가 만든 리포트를 분석해서 보여드려요.")

# ── 종목 선택 ──
col1, col2 = st.columns([3, 1])
with col1:
    try:
        from src.services.account_service import get_holdings_watchlist, add_manual_watch
        holdings = [
            row for row in get_holdings_watchlist()
            if row.get("status") in ("holding", "sold", "manual")
        ]
    except Exception:
        holdings = []

    holdings_map = {h.get("stock_code"): h for h in holdings if h.get("stock_code")}

    # 리포트 목록 + 종목명/날짜 조합
    all_reports = _list_reports()
    report_options = []
    report_lookup = {}  # display_label → (code, report_path)

    for rp in all_reports:
        parts = rp.stem.split("_")  # 예: 20260206_090710
        if len(parts) >= 2 and parts[-1].isdigit():
            rp_code = parts[-1]
            rp_date = parts[0] if len(parts[0]) == 8 else ""
            # 날짜 포맷
            date_str = f"{rp_date[:4]}-{rp_date[4:6]}-{rp_date[6:]}" if len(rp_date) == 8 else ""
            # 종목명 조회
            h = holdings_map.get(rp_code)
            name = h.get("stock_name", "") if h else ""
            if not name:
                try:
                    from src.config.app_config import MAPPING_FILE
                    if MAPPING_FILE and MAPPING_FILE.exists():
                        import csv
                        with open(MAPPING_FILE, "r", encoding="utf-8") as f:
                            reader = csv.DictReader(f)
                            for row in reader:
                                if str(row.get("code", "")).zfill(6) == rp_code:
                                    name = row.get("name", "")
                                    break
                except Exception:
                    pass

            label = f"{date_str}  {rp_code} {name}".strip()
            report_options.append(label)
            report_lookup[label] = (rp_code, rp)

    if report_options:
        selected = st.selectbox(
            "분석할 종목 선택",
            options=["최근 리포트 자동 선택"] + report_options,
            index=0,
        )
        if selected != "최근 리포트 자동 선택" and selected in report_lookup:
            code, _ = report_lookup[selected]
        else:
            code = ""
    else:
        selected = "최근 리포트 자동 선택"
        code = st.text_input("종목코드 입력 (6자리 숫자)", value="", placeholder="예: 090710")

with col2:
    full = st.checkbox("상세 모드 (거래원 5일치)", value=False)

# 리포트 생성 버튼
if not read_only:
    run = st.button("🔍 분석 리포트 생성", type="primary", use_container_width=True)
    if run:
        if not code or not code.isdigit():
            st.error("종목코드를 숫자 6자리로 입력해주세요.")
        else:
            try:
                from src.services.analysis_report import generate_analysis_report
                result = generate_analysis_report(code, full=full)
                st.success(f"리포트 생성 완료: {result.report_path.name}")
            except Exception as e:
                st.error(f"리포트 생성 실패: {e}")

# ── 리포트 로딩 ──
report_path = None
if code and code.isdigit():
    # 드롭다운에서 선택한 경우 해당 리포트 직접 사용
    if selected != "최근 리포트 자동 선택" and selected in report_lookup:
        _, report_path = report_lookup[selected]
    else:
        report_path = _find_latest_report(code)
else:
    reports = _list_reports()
    if reports:
        report_path = reports[0]
        name = report_path.stem
        parts = name.split("_")
        if len(parts) >= 2 and parts[-1].isdigit():
            code = parts[-1]

if not report_path or not report_path.exists():
    st.warning("아직 리포트가 없어요. 스케줄러 실행 후 다시 확인해보세요.")
    
    # 보유종목 목록이 있으면 안내
    if holdings:
        holding_names = [f"{h.get('stock_name', '')} ({h.get('stock_code', '')})" 
                        for h in holdings if h.get('status') == 'holding']
        if holding_names:
            st.info(f"📋 현재 보유종목: {', '.join(holding_names)}")
            st.caption(
                "💡 리포트 생성: 매일 16:50 자동 실행 또는 수동 생성 버튼 사용\n\n"
                "⚠️ 휴장일에는 리포트가 생성되지 않습니다"
            )
    st.stop()

# 선택된 종목 정보 표시
_selected_name = ""
if code:
    h = holdings_map.get(code)
    _selected_name = h.get("stock_name", "") if h else ""
    rp_date = report_path.stem.split("_")[0] if report_path else ""
    date_display = f"{rp_date[:4]}-{rp_date[4:6]}-{rp_date[6:]}" if len(rp_date) == 8 else ""
    st.markdown(
        f"**📄 리포트**: `{report_path.name}`"
        + (f" | **{_selected_name}** ({code})" if _selected_name else f" | {code}")
        + (f" | 📅 {date_display}" if date_display else "")
    )

# ── 리포트 파싱 ──
sections = _load_report_sections(report_path)

# ════════════════════════════════════════════════════
# 탭 구성
# ════════════════════════════════════════════════════

tab1, tab2, tab3 = st.tabs(["📖 쉬운 분석", "📊 차트 모음", "📄 원본 리포트"])

# ────────────────────────────────────────────────────
# 탭 1: 쉬운 분석 (핵심)
# ────────────────────────────────────────────────────

with tab1:

    # ── 1-1. 신호등 대시보드 ──
    easy_text = _extract_section_data(sections, "쉬운 요약")
    summary_text = _extract_section_data(sections, "종합 판단")

    # 이전 형식 리포트 폴백: 쉬운 요약이 없으면 기술 지표/매물대에서 직접 추출
    has_easy = bool(easy_text.strip())

    if not has_easy:
        # 기본 데이터로 간이 신호등 구성
        tech_raw = _extract_section_data(sections, "기술 지표 분석")
        vp_raw = _extract_section_data(sections, "매물대 분석")
        price_raw = _extract_section_data(sections, "가격 거래 요약")

        st.info("📌 이 리포트는 이전 형식이에요. 새로 '분석 리포트 생성'을 하면 더 자세한 분석을 볼 수 있어요.")

    # 신호등 데이터 파싱
    def _parse_signal(text, keyword):
        """텍스트에서 🟢🟡🔴 신호등 파싱"""
        for line in text.split("\n"):
            if keyword in line:
                if "🟢" in line:
                    return "good", line.split("**")[-2] if "**" in line else ""
                elif "🔴" in line:
                    return "warning", line.split("**")[-2] if "**" in line else ""
                else:
                    return "neutral", line.split("**")[-2] if "**" in line else ""
        return "neutral", "-"

    sig_price = _parse_signal(easy_text, "**주가**")
    sig_vp = _parse_signal(easy_text, "**매물대**")
    sig_cci = _parse_signal(easy_text, "**CCI**")
    sig_rsi = _parse_signal(easy_text, "**RSI**")
    sig_broker = _parse_signal(easy_text, "**거래원**")
    sig_total = _parse_signal(easy_text, "**종합**")

    # 신호등 카드 6개
    st.markdown("### 🚦 한눈에 보는 종목 상태")
    cols = st.columns(6)
    cards = [
        ("주가 흐름", sig_price[1], sig_price[0]),
        ("매물대", sig_vp[1], sig_vp[0]),
        ("CCI 지표", sig_cci[1], sig_cci[0]),
        ("RSI 지표", sig_rsi[1], sig_rsi[0]),
        ("거래원", sig_broker[1], sig_broker[0]),
        ("종합 점수", sig_total[1], sig_total[0]),
    ]
    for col, (title, value, level) in zip(cols, cards):
        col.markdown(_signal_card(title, value, level), unsafe_allow_html=True)

    st.markdown("")

    # ── 1-2. 한줄 결론 ──
    for line in easy_text.split("\n"):
        if "한줄 결론" in line:
            continue
        if line.strip().startswith("이 종목은"):
            st.markdown(f"""
            <div style="padding:16px 20px; border-radius:12px; background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        color:white; font-size:16px; font-weight:600; margin:8px 0 16px 0; text-align:center;">
                {line.strip()}
            </div>""", unsafe_allow_html=True)
            break

    # ── 1-3. 쉬운 요약 서브섹션 렌더링 ──
    easy_sections = _parse_easy_subsections(sections.get("쉬운 요약", []))

    SECTION_EMOJIS = {
        "한줄 결론": "🎯",
        "신호등 요약": "🚦",
        "내 보유 정보": "💰",
        "오늘 주가 흐름": "📈",
        "기간별 수익률": "📊",
        "52주 고저 위치": "📏",
        "거래량 추세": "🔊",
        "캔들 패턴": "🕯️",
        "매물대": "🧱",
        "기술 지표": "🌡️",
        "이동평균 크로스": "✂️",
        "변동성 분석": "🌊",
        "거래원 흐름": "💸",
        "뉴스 공시 요약": "📰",
        "종합 점수 분해": "🏆",
    }

    for title, content in easy_sections:
        # 신호등 요약은 위에서 이미 카드로 표시했으므로 스킵
        if "신호등" in title:
            continue
        if "한줄 결론" in title:
            continue  # 위에서 배너로 표시

        emoji = "📌"
        for k, v in SECTION_EMOJIS.items():
            if k in title:
                emoji = v
                break

        with st.expander(f"{emoji} {title}", expanded=True):
            # 마크다운 렌더링
            st.markdown(content)

    # 이전 형식 리포트: 쉬운 요약이 없으면 기존 섹션들을 직접 표시
    if not has_easy:
        FALLBACK_SECTIONS = [
            ("가격 거래 요약", "📈", "오늘 주가 정보"),
            ("기간별 수익률", "📊", "1주/1개월/3개월/6개월/1년 수익률"),
            ("52주 고저 분석", "📏", "1년간 최고/최저 가격 대비 위치"),
            ("매물대 분석", "🧱", "매물대란 과거에 많이 거래된 가격대예요"),
            ("기술 지표 분석", "🌡️", "주가의 과열/과냉각 상태를 보여줘요"),
            ("거래량 추세 분석", "🔊", "거래량 변화로 관심도를 파악해요"),
            ("캔들 패턴 분석", "🕯️", "봉 모양으로 매수/매도 심리를 읽어요"),
            ("이동평균 크로스", "✂️", "추세 전환 신호를 감지해요"),
            ("변동성 분석", "🌊", "이 종목이 얼마나 출렁이는지 보여줘요"),
            ("점수 항목별 분해", "🏆", "CB 점수의 7개 항목별 점수예요"),
            ("거래원 수급 분석", "💸", "어느 증권사에서 많이 거래했는지 보여줘요"),
            ("뉴스 공시", "📰", "최근 뉴스와 공시 목록이에요"),
        ]
        for sec_key, sec_emoji, sec_help in FALLBACK_SECTIONS:
            sec_text = _extract_section_data(sections, sec_key)
            if sec_text.strip():
                with st.expander(f"{sec_emoji} {sec_key}", expanded=True):
                    st.caption(sec_help)
                    st.markdown(sec_text)

    # ── 1-4. 기술 지표 게이지 차트 ──
    tech_text = _extract_section_data(sections, "기술 지표 분석")
    cci_val = _extract_number(tech_text, "CCI")
    rsi_val = _extract_number(tech_text, "RSI")

    if cci_val is not None or rsi_val is not None:
        st.markdown("### 🌡️ 기술 지표 시각화")
        st.caption("게이지가 초록 영역에 있으면 양호, 빨간 영역이면 주의가 필요해요.")

        if go is not None:
            gcols = st.columns(2)

            if cci_val is not None:
                with gcols[0]:
                    fig = _gauge_chart(
                        value=cci_val,
                        title="CCI (추세 강도)",
                        ranges=[
                            (-300, -100, "과냉각 (반등 기대)", "#b8d4ff"),
                            (-100, 0,    "약세 (관망)", "#d4edda"),
                            (0, 100,     "양호 (안정)", "#d4edda"),
                            (100, 200,   "강세 (주의)", "#fff3cd"),
                            (200, 300,   "과열 (고점 주의)", "#f8d7da"),
                        ],
                    )
                    if fig:
                        st.plotly_chart(fig, use_container_width=True)
                    _info_card(
                        "CCI란?",
                        "CCI는 '지금 주가가 평균에서 얼마나 벗어났는지' 보여주는 도구예요.<br>"
                        "• <b>-100~+100</b>: 정상 범위<br>"
                        "• <b>+100 이상</b>: 과열 (많이 올랐으니 쉬어갈 수도)<br>"
                        "• <b>-100 이하</b>: 과냉각 (많이 떨어졌으니 반등할 수도)",
                        "📏",
                    )

            if rsi_val is not None:
                with gcols[1]:
                    fig = _gauge_chart(
                        value=rsi_val,
                        title="RSI (과열/과냉각)",
                        ranges=[
                            (0, 30,  "과냉각 (반등 기대)", "#b8d4ff"),
                            (30, 45, "약세", "#d4edda"),
                            (45, 55, "중립", "#d4edda"),
                            (55, 70, "약간 강세", "#d4edda"),
                            (70, 100, "과열 (조정 가능)", "#f8d7da"),
                        ],
                    )
                    if fig:
                        st.plotly_chart(fig, use_container_width=True)
                    _info_card(
                        "RSI란?",
                        "RSI는 '최근 14일 동안 오른 날이 많았나 내린 날이 많았나'를 보여줘요.<br>"
                        "• <b>70 이상</b>: 과열 (많이 올라서 쉬어갈 수도)<br>"
                        "• <b>30 이하</b>: 과냉각 (많이 내려서 반등할 수도)<br>"
                        "• <b>40~60</b>: 중립 (편안한 상태)",
                        "🌡️",
                    )

    # ── 1-5. 재무 요약 ──
    if code and code.isdigit():
        fin = _fetch_financials(code)
        if fin and fin.get("revenue"):
            st.markdown("### 🏢 회사 재무 상태")
            st.caption("작년 기준 매출, 영업이익, 순이익을 보여드려요. 전년 대비 증감도 함께 확인하세요.")

            fc1, fc2, fc3 = st.columns(3)
            rev = fin.get("revenue")
            rev_prev = fin.get("prev_revenue")
            op = fin.get("operating_profit")
            op_prev = fin.get("prev_operating_profit")
            net = fin.get("net_income")
            net_prev = fin.get("prev_net_income")

            if rev is not None:
                delta = f"{((rev - rev_prev) / rev_prev * 100):+.1f}%" if rev_prev else None
                fc1.metric("💵 매출액 (억원)", f"{rev:,.0f}", delta)
            if op is not None:
                delta = f"{((op - op_prev) / op_prev * 100):+.1f}%" if op_prev else None
                fc2.metric("📊 영업이익 (억원)", f"{op:,.0f}", delta)
            if net is not None:
                delta = f"{((net - net_prev) / net_prev * 100):+.1f}%" if net_prev else None
                fc3.metric("💰 순이익 (억원)", f"{net:,.0f}", delta)

            if rev and op is not None:
                margin = op / rev * 100
                _info_card("영업이익률이란?",
                           f"매출 대비 영업이익의 비율이에요. 현재 <b>{margin:.1f}%</b>로, "
                           f"{'높은 편이에요 (효율적인 사업 구조)' if margin > 10 else '보통 수준이에요' if margin > 5 else '낮은 편이에요 (비용 구조 확인 필요)'}.",
                           "📐")

    # ── 1-6. 매매 계획 ──
    plan_text = _extract_section_data(sections, "매매 계획")
    if plan_text.strip() and "데이터 부족" not in plan_text:
        st.markdown("### 🎯 매매 계획 (참고용)")
        st.caption("이 계획은 기술적 분석 기반의 참고 정보일 뿐, 투자 결정은 본인 판단으로 해주세요.")
        st.markdown(plan_text)

    # ── 1-7. AI 분석 의견 ──
    ai_text = _extract_section_data(sections, "AI 분석 의견")
    if ai_text.strip() and "없음" not in ai_text:
        st.markdown("### 🤖 AI 분석 의견")
        st.caption("AI가 리포트를 읽고 요약한 의견이에요. 참고 자료로만 활용해주세요.")
        st.markdown(ai_text)

    # ── 1-8. 기업 정보 ──
    corp_text = _extract_section_data(sections, "기업 정보")
    if corp_text.strip() and "없음" not in corp_text:
        with st.expander("🏛️ 기업 정보 (사업 내용, 재무, 대주주 등)", expanded=False):
            st.markdown(corp_text)


# ────────────────────────────────────────────────────
# 탭 2: 차트 모음
# ────────────────────────────────────────────────────

with tab2:
    if not code or not code.isdigit():
        st.warning("종목코드가 없어서 차트를 그릴 수 없어요.")
    else:
        df, source = _load_ohlcv_df(code)

        if df is None or df.empty:
            st.warning(f"가격 데이터를 불러오지 못했어요. (소스: {source})")
        else:
            df = df.sort_values("date").reset_index(drop=True)
            last = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else None
            change_pct = 0.0
            if prev is not None and float(prev["close"]) > 0:
                change_pct = (float(last["close"]) - float(prev["close"])) / float(prev["close"]) * 100

            # 가격 요약 카드
            st.markdown("### 📊 오늘 시세")
            pc1, pc2, pc3, pc4, pc5 = st.columns(5)
            pc1.metric("종가", f"{int(last['close']):,}원", f"{change_pct:+.1f}%")
            pc2.metric("시가", f"{int(last['open']):,}원")
            pc3.metric("고가", f"{int(last['high']):,}원")
            pc4.metric("저가", f"{int(last['low']):,}원")
            pc5.metric("거래량", f"{int(last['volume']):,}")

            st.caption(f"데이터 소스: {source}")

            # ── 캔들스틱 차트 ──
            st.markdown("### 🕯️ 가격 차트 (최근 200일)")

            if go is not None and make_subplots is not None and pd is not None:
                view = df.tail(200).copy()

                # 거래정지/비정상 봉 감지: 당일 변동폭이 전일종가의 30% 이상
                if len(view) > 1:
                    prev_close = view["close"].shift(1)
                    spread = (view["high"] - view["low"]).abs()
                    abnormal = (spread / prev_close.clip(lower=1)) > 0.30
                    # 비정상 봉은 종가 기준 가로선("_")으로 표시
                    view.loc[abnormal, "open"] = view.loc[abnormal, "close"]
                    view.loc[abnormal, "high"] = view.loc[abnormal, "close"]
                    view.loc[abnormal, "low"] = view.loc[abnormal, "close"]

                fig = make_subplots(
                    rows=2, cols=1,
                    shared_xaxes=True,
                    row_heights=[0.7, 0.3],
                    vertical_spacing=0.06,
                    subplot_titles=("주가 (캔들차트)", "거래량"),
                )

                # 캔들스틱
                fig.add_trace(go.Candlestick(
                    x=view["date"], open=view["open"],
                    high=view["high"], low=view["low"], close=view["close"],
                    name="주가",
                    increasing_line_color="#e74c3c",  # 한국식: 빨강=상승
                    decreasing_line_color="#3498db",  # 파랑=하락
                ), row=1, col=1)

                # 이동평균선
                for days, color, name in [(5, "#ff9800", "5일선"), (20, "#2196f3", "20일선"), (60, "#4caf50", "60일선")]:
                    if len(view) >= days:
                        ma = view["close"].rolling(days).mean()
                        fig.add_trace(go.Scatter(
                            x=view["date"], y=ma,
                            mode="lines", name=name,
                            line=dict(color=color, width=1),
                        ), row=1, col=1)

                # 거래량
                colors = ["#e74c3c" if c >= o else "#3498db"
                          for c, o in zip(view["close"], view["open"])]
                fig.add_trace(go.Bar(
                    x=view["date"], y=view["volume"],
                    name="거래량", marker_color=colors,
                ), row=2, col=1)

                # 볼린저밴드 (있으면)
                if len(view) >= 20:
                    bb_mid = view["close"].rolling(20).mean()
                    bb_std = view["close"].rolling(20).std()
                    bb_upper = bb_mid + 2 * bb_std
                    bb_lower = bb_mid - 2 * bb_std
                    fig.add_trace(go.Scatter(
                        x=view["date"], y=bb_upper,
                        mode="lines", name="볼린저 상단",
                        line=dict(color="rgba(150,150,150,0.3)", dash="dot"),
                    ), row=1, col=1)
                    fig.add_trace(go.Scatter(
                        x=view["date"], y=bb_lower,
                        mode="lines", name="볼린저 하단",
                        line=dict(color="rgba(150,150,150,0.3)", dash="dot"),
                        fill="tonexty", fillcolor="rgba(200,200,200,0.08)",
                    ), row=1, col=1)

                # VP 지지/저항선
                vp = None
                vp_error = ""
                try:
                    from src.domain.volume_profile import calc_volume_profile
                    # FDR 데이터 호환: NaN/0값 제거
                    vp_df = df.copy()
                    for _vc in ["open", "high", "low", "close", "volume"]:
                        if _vc in vp_df.columns:
                            vp_df[_vc] = pd.to_numeric(vp_df[_vc], errors="coerce")
                    vp_df = vp_df.dropna(subset=["high", "low", "close", "volume"])
                    vp_df = vp_df[vp_df["low"] > 0]
                    vp = calc_volume_profile(vp_df, current_price=float(last["close"]), n_days=60, n_bands=10)
                    if vp and vp.poc_price:
                        fig.add_hline(y=vp.poc_price, line_color="#ff6b6b", line_dash="dot",
                                      annotation_text=f"최다 거래가 {vp.poc_price:,.0f}", row=1, col=1)
                    if vp and vp.bands:
                        below = [b for b in vp.bands if b.price_high <= float(last["close"])]
                        above = [b for b in vp.bands if b.price_low >= float(last["close"])]
                        support = max(below, key=lambda b: b.pct).price_high if below else None
                        resistance = max(above, key=lambda b: b.pct).price_low if above else None
                        if support:
                            fig.add_hline(y=support, line_color="#2ecc71", line_dash="dot",
                                          annotation_text=f"지지 {support:,.0f}", row=1, col=1)
                        if resistance:
                            fig.add_hline(y=resistance, line_color="#e74c3c", line_dash="dot",
                                          annotation_text=f"저항 {resistance:,.0f}", row=1, col=1)
                except Exception as _vp_err:
                    vp_error = str(_vp_err)

                fig.update_layout(
                    height=650,
                    xaxis_rangeslider_visible=False,
                    showlegend=True,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    margin=dict(l=10, r=10, t=30, b=30),
                )

                # 주말/공휴일 빈 공간 제거
                fig.update_xaxes(
                    type="date",
                    rangebreaks=[dict(bounds=["sat", "mon"])],
                )
                # 거래량 하단에 날짜 레이블 표시
                fig.update_xaxes(
                    showticklabels=True,
                    dtick="M1", tickformat="%y/%m",
                    row=2, col=1,
                )
                st.plotly_chart(fig, use_container_width=True)

                # ── 매물대 분포 차트 ──
                st.markdown("### 🧱 매물대 분포 (많이 거래된 가격대)")
                st.caption("막대가 긴 가격대에서 거래가 많이 쌓였어요. 주가가 이 가격대 근처에서 멈추거나 튕길 수 있어요.")

                if vp and vp.bands:
                    vp_df = pd.DataFrame({
                        "가격대": [f"{b.price_low:,.0f}~{b.price_high:,.0f}" for b in vp.bands],
                        "비중": [b.pct for b in vp.bands],
                        "현재가포함": [b.is_current for b in vp.bands],
                        "price_low": [b.price_low for b in vp.bands],
                    })
                    vp_df = vp_df.sort_values("price_low")  # 낮은 가격이 아래

                    vp_colors = ["#ff6b6b" if c else "#6c8ef5" for c in vp_df["현재가포함"]]
                    vp_fig = go.Figure(data=[go.Bar(
                        x=vp_df["비중"], y=vp_df["가격대"],
                        orientation="h", marker_color=vp_colors,
                        text=[f"{v:.1f}%" for v in vp_df["비중"]],
                        textposition="outside",
                    )])
                    vp_fig.update_layout(
                        height=max(300, len(vp.bands) * 35),
                        xaxis_title="거래 비중 (%)",
                        yaxis_title="가격대 (원)",
                        margin=dict(l=10, r=10, t=10, b=10),
                    )
                    st.plotly_chart(vp_fig, use_container_width=True)
                    st.caption("🔴 빨간 막대 = 현재가가 이 가격대 안에 있음 / 🔵 파란 막대 = 다른 가격대")
                else:
                    if vp_error:
                        st.caption(f"매물대 계산 실패: {vp_error}")
                    elif vp and hasattr(vp, 'tag') and vp.tag:
                        st.caption(f"매물대: {vp.tag} (데이터 소스: {source})")
                    else:
                        st.caption("매물대 데이터가 없어요.")

            else:
                # plotly 없을 때 폴백
                view = df.tail(200).set_index("date")
                st.markdown("#### 종가 추이")
                st.line_chart(view["close"])
                st.markdown("#### 거래량")
                st.bar_chart(view["volume"])

            # ── CCI / RSI 추이 차트 ──
            if go is not None and pd is not None and len(df) >= 20:
                st.markdown("### 📉 기술 지표 추이 (최근 100일)")
                st.caption("CCI와 RSI가 시간에 따라 어떻게 변했는지 보여줘요. 과열/과냉각 구간에 색을 칠했어요.")

                view100 = df.tail(100).copy()

                # CCI 계산
                tp = (view100["high"] + view100["low"] + view100["close"]) / 3
                sma = tp.rolling(14).mean()
                mad = tp.rolling(14).apply(lambda x: abs(x - x.mean()).mean(), raw=True)
                view100["cci"] = (tp - sma) / (0.015 * mad)

                # RSI 계산
                delta = view100["close"].diff()
                gain = delta.where(delta > 0, 0.0).rolling(14).mean()
                loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
                rs = gain / loss.replace(0, float("nan"))
                view100["rsi"] = 100 - (100 / (1 + rs))

                cci_rsi_fig = make_subplots(
                    rows=2, cols=1,
                    shared_xaxes=True,
                    row_heights=[0.5, 0.5],
                    vertical_spacing=0.08,
                    subplot_titles=("CCI (추세 강도 지표)", "RSI (과열·과냉각 지표)"),
                )

                # CCI
                cci_rsi_fig.add_trace(go.Scatter(
                    x=view100["date"], y=view100["cci"],
                    mode="lines", name="CCI",
                    line=dict(color="#6c8ef5", width=2),
                ), row=1, col=1)
                cci_rsi_fig.add_hrect(y0=100, y1=300, fillcolor="rgba(255,0,0,0.07)",
                                       line_width=0, row=1, col=1)
                cci_rsi_fig.add_hrect(y0=-300, y1=-100, fillcolor="rgba(0,100,255,0.07)",
                                       line_width=0, row=1, col=1)
                cci_rsi_fig.add_hline(y=100, line_dash="dot", line_color="red",
                                       annotation_text="과열 기준 (+100)", row=1, col=1)
                cci_rsi_fig.add_hline(y=-100, line_dash="dot", line_color="blue",
                                       annotation_text="과냉각 기준 (-100)", row=1, col=1)

                # RSI
                cci_rsi_fig.add_trace(go.Scatter(
                    x=view100["date"], y=view100["rsi"],
                    mode="lines", name="RSI",
                    line=dict(color="#ff9800", width=2),
                ), row=2, col=1)
                cci_rsi_fig.add_hrect(y0=70, y1=100, fillcolor="rgba(255,0,0,0.07)",
                                       line_width=0, row=2, col=1)
                cci_rsi_fig.add_hrect(y0=0, y1=30, fillcolor="rgba(0,100,255,0.07)",
                                       line_width=0, row=2, col=1)
                cci_rsi_fig.add_hline(y=70, line_dash="dot", line_color="red",
                                       annotation_text="과열 (70)", row=2, col=1)
                cci_rsi_fig.add_hline(y=30, line_dash="dot", line_color="blue",
                                       annotation_text="과냉각 (30)", row=2, col=1)

                cci_rsi_fig.update_layout(
                    height=500,
                    showlegend=False,
                    margin=dict(l=10, r=10, t=30, b=10),
                )
                st.plotly_chart(cci_rsi_fig, use_container_width=True)

            # ── 거래원 추이 차트 ──
            broker_df = _fetch_broker_series(code)
            if broker_df is not None and not broker_df.empty and "anomaly_score" in broker_df.columns:
                st.markdown("### 💸 거래원 이상 점수 추이")
                st.caption("이상 점수가 높을수록 특정 증권사에서 비정상적으로 많은 거래가 있었다는 뜻이에요. "
                           "급등 전에 이 점수가 올라가는 경우가 있어요.")

                chart_df = broker_df[["screen_date", "anomaly_score"]].dropna()
                if not chart_df.empty and go is not None:
                    bk_fig = go.Figure()
                    bk_fig.add_trace(go.Scatter(
                        x=chart_df["screen_date"],
                        y=chart_df["anomaly_score"],
                        mode="lines+markers",
                        name="이상 점수",
                        line=dict(color="#e74c3c", width=2),
                        marker=dict(size=5),
                        fill="tozeroy",
                        fillcolor="rgba(231,76,60,0.1)",
                    ))
                    bk_fig.update_layout(
                        height=300,
                        xaxis_title="날짜",
                        yaxis_title="이상 점수",
                        margin=dict(l=10, r=10, t=10, b=10),
                    )
                    st.plotly_chart(bk_fig, use_container_width=True)
                else:
                    chart_df = chart_df.set_index("screen_date")
                    st.line_chart(chart_df)
            else:
                st.caption("거래원 시계열 데이터가 없어요.")

            # ── 거래량 변화 추이 ──
            if pd is not None and len(df) >= 20:
                st.markdown("### 📊 거래량 변화 추이 (20일 평균 대비)")
                st.caption("거래량이 평균보다 크게 늘면 '무언가 일어나고 있다'는 신호일 수 있어요.")

                v60 = df.tail(60).copy()
                v60["거래량_20일평균"] = v60["volume"].rolling(20).mean()
                v60["거래량비율"] = v60["volume"] / v60["거래량_20일평균"]
                v60 = v60.dropna()

                if not v60.empty and go is not None:
                    vol_fig = go.Figure()
                    vol_colors = ["#e74c3c" if r >= 2 else ("#ff9800" if r >= 1.5 else "#6c8ef5")
                                  for r in v60["거래량비율"]]
                    vol_fig.add_trace(go.Bar(
                        x=v60["date"], y=v60["거래량비율"],
                        marker_color=vol_colors,
                        name="거래량비율",
                        text=[f"{r:.1f}배" for r in v60["거래량비율"]],
                        textposition="outside",
                        textfont=dict(size=9),
                    ))
                    vol_fig.add_hline(y=1.0, line_dash="dot", line_color="#999",
                                      annotation_text="20일 평균 (1.0배)")
                    vol_fig.add_hline(y=2.0, line_dash="dot", line_color="#e74c3c",
                                      annotation_text="주의 (2배 이상)")
                    vol_fig.update_layout(
                        height=300,
                        yaxis_title="20일 평균 대비 배율",
                        margin=dict(l=10, r=10, t=10, b=10),
                    )
                    st.plotly_chart(vol_fig, use_container_width=True)
                    st.caption("🔴 빨강 = 평균의 2배 이상 / 🟠 주황 = 1.5배 이상 / 🔵 파랑 = 정상")


# ────────────────────────────────────────────────────
# 탭 3: 원본 리포트
# ────────────────────────────────────────────────────

with tab3:
    raw_text = report_path.read_text(encoding="utf-8")
    st.markdown(raw_text)
    with report_path.open("rb") as f:
        st.download_button(
            label="📥 리포트 다운로드 (.md)",
            data=f,
            file_name=report_path.name,
            mime="text/markdown",
        )

# ── 푸터 ──
st.markdown("---")
st.caption(FOOTER_DASHBOARD)