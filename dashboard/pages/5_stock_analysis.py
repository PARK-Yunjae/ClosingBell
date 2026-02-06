"""
🧾 종목 심층 분석 대시보드 v9.0
"""

import os
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
    APP_FULL_VERSION = "ClosingBell v9.0"
    FOOTER_DASHBOARD = APP_FULL_VERSION
    SIDEBAR_TITLE = "ClosingBell"
    OHLCV_DIR = None
    OHLCV_FULL_DIR = None


def _sidebar_nav():
    st.page_link("app.py", label="홈")
    st.page_link("pages/1_top5_tracker.py", label="감시종목 TOP5")
    st.page_link("pages/2_nomad_study.py", label="유목민 공부법")
    st.page_link("pages/3_stock_search.py", label="종목 검색")
    st.page_link("pages/4_broker_flow.py", label="거래원 수급")
    st.page_link("pages/5_stock_analysis.py", label="종목 심층 분석")


def _apply_styles(hide_sidebar: bool = False) -> None:
    base = """
    <style>
    .cb-card { padding:12px;border:1px solid #e8e8e8;border-radius:12px;margin:6px 0;background:#fafafa; }
    .cb-title { font-size:18px;font-weight:700;margin:8px 0; }
    </style>
    """
    if hide_sidebar:
        base += """
        <style>
        [data-testid="stSidebar"] { display: none !important; }
        [data-testid="stSidebarNav"] { display: none !important; }
        </style>
        """
    st.markdown(base, unsafe_allow_html=True)


def _fix_text(text: str) -> str:
    if not text:
        return ""
    mapping = {
        "?곸듅?щ젰": "상승여력",
        "???꼍": "저항",
        "以묐┰": "중립",
        "?곗씠?곕?議?": "데이터부족",
        "?뺤긽": "정상",
        "?ㅻ쪟": "오류",
        "AI ?섍껄": "AI 의견",
    }
    fixed = text
    for k, v in mapping.items():
        fixed = fixed.replace(k, v)
    return fixed


SECTION_TITLE_MAP = {
    "Holdings Snapshot": "보유/관찰 현황",
    "OHLCV Summary": "가격/거래 요약",
    "Volume Profile": "매물대 요약",
    "Technical Analysis": "기술 지표",
    "Broker Flow": "거래원 수급",
    "News & Disclosures": "뉴스/공시",
    "DART Company Profile": "기업정보(DART)",
    "Entry/Exit Plan": "진입/이탈 계획",
    "Easy Summary": "쉬운 요약",
    "AI Summary": "AI 요약",
    "Summary": "최종 요약",
}


def _section_title(key: str) -> str:
    return SECTION_TITLE_MAP.get(key, key)


def _badge(text: str, color: str) -> str:
    return f"""<span style='display:inline-block;padding:2px 8px;border-radius:999px;background:{color};color:#111;font-size:12px;margin-right:6px;'>{text}</span>"""


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
    sections: Dict[str, List[str]] = {}
    if not report_path or not report_path.exists():
        return sections
    lines = report_path.read_text(encoding="utf-8").splitlines()
    current = "Summary"
    sections[current] = []
    for line in lines:
        if line.startswith("## "):
            current = line.replace("## ", "").strip()
            sections[current] = []
            continue
        sections[current].append(line)
    return sections


def _resolve_ohlcv_path(code: str) -> Optional[Path]:
    candidates: List[Path] = []
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
        candidates.append(Path(base) / f"{code}.csv")
        candidates.append(Path(base) / f"A{code}.csv")

    for path in candidates:
        if path.exists():
            return path
    return None


@st.cache_data(ttl=1800)
def _load_ohlcv_df(code: str) -> Tuple[Optional["pd.DataFrame"], str]:
    if pd is None:
        return None, "pandas not available"

    path = _resolve_ohlcv_path(code)
    if path:
        try:
            from src.services.backfill.data_loader import load_single_ohlcv
            df = load_single_ohlcv(path)
            if df is not None and not df.empty:
                return df, "local"
        except Exception:
            pass

    # Online fallback (FDR)
    try:
        import FinanceDataReader as fdr
        end = datetime.now().date()
        start = end - timedelta(days=365 * 2)
        df = fdr.DataReader(code, start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
        if df is not None and not df.empty:
            df = df.reset_index()
            df.columns = [c.lower() for c in df.columns]
            if "date" not in df.columns and "index" in df.columns:
                df = df.rename(columns={"index": "date"})
            return df, "fdr"
    except Exception:
        pass

    return None, "not found"


def _lines_to_markdown(lines: List[str]) -> str:
    if not lines:
        return "-"
    out = []
    for line in lines:
        text = _fix_text(line)
        if not text.strip():
            continue
        if text.strip().startswith("- "):
            out.append(text.strip())
        elif text.strip().startswith("• "):
            out.append("- " + text.strip()[2:])
        elif text.strip().startswith("  - "):
            out.append("- " + text.strip()[4:])
        else:
            out.append(text.strip())
    return "\n".join(out)


def _parse_news_disclosures(lines: List[str]) -> Tuple[List[str], List[str]]:
    news, disclosures = [], []
    mode = None
    for line in lines:
        text = _fix_text(line.strip())
        if text.startswith("- News") or text.startswith("News:"):
            mode = "news"
            continue
        if text.startswith("- Disclosures") or text.startswith("Disclosures:"):
            mode = "disclosures"
            continue
        if text.startswith("- Note:"):
            continue
        if text.startswith("- ") or text.startswith("• ") or text.startswith("  - "):
            item = text.lstrip("- ").lstrip("• ").strip()
            if mode == "news":
                news.append(item)
            elif mode == "disclosures":
                disclosures.append(item)
    return news, disclosures


def _parse_technical(lines: List[str]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for line in lines:
        text = _fix_text(line.strip())
        if text.startswith("- CCI("):
            result["CCI"] = text.split(":", 1)[-1].strip()
        elif text.startswith("- RSI("):
            result["RSI"] = text.split(":", 1)[-1].strip()
        elif text.startswith("- MACD"):
            result["MACD"] = text.split(":", 1)[-1].strip()
        elif text.startswith("- MA:"):
            result["MA"] = text.split(":", 1)[-1].strip()
        elif text.startswith("- Bollinger"):
            result["BOLL"] = text.split(":", 1)[-1].strip()
    return result


def _parse_holdings(lines: List[str]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for line in lines:
        text = _fix_text(line.strip())
        if text.startswith("- Status:"):
            result["status"] = text.split(":", 1)[-1].strip()
        elif text.startswith("- Qty:"):
            result["qty"] = text.split(":", 1)[-1].strip()
        elif text.startswith("- First Seen:"):
            result["first_seen"] = text.split(":", 1)[-1].strip()
        elif text.startswith("- Last Seen:"):
            result["last_seen"] = text.split(":", 1)[-1].strip()
    return result


def _interpret_cci(value: Optional[float]) -> str:
    if value is None:
        return "-"
    if value >= 100:
        return "과열 경향"
    if value <= -100:
        return "과매도 경향"
    return "중립 구간"


def _interpret_rsi(value: Optional[float]) -> str:
    if value is None:
        return "-"
    if value >= 70:
        return "과열 경향"
    if value <= 30:
        return "과매도 경향"
    return "중립 구간"


def _classify_news(items: List[str]) -> List[Dict[str, str]]:
    positive = ["호재", "수주", "계약", "공급", "실적", "흑자", "턴어라운드", "신제품", "기술", "특허", "승인", "상승"]
    negative = ["적자", "손실", "경고", "조사", "거래정지", "상장폐지", "소송", "리콜", "하락", "유상증자", "전환사채"]
    out: List[Dict[str, str]] = []
    for item in items:
        tag = "중립"
        color = "#e0e0e0"
        for key in positive:
            if key in item:
                tag, color = "긍정", "#81c784"
                break
        for key in negative:
            if key in item:
                tag, color = "주의", "#ffb74d"
                break
        out.append({"text": item, "tag": tag, "color": color})
    return out


def _highlight_disclosures(disclosures: List[str]) -> List[Dict[str, str]]:
    rules = [
        ("유상증자", "주의", "#ffb74d"),
        ("전환사채", "주의", "#ffb74d"),
        ("CB", "주의", "#ffb74d"),
        ("BW", "주의", "#ffb74d"),
        ("신주인수권", "주의", "#ffb74d"),
        ("자기주식취득", "호재", "#81c784"),
        ("자기주식처분", "주의", "#ffb74d"),
        ("대량보유", "지분변동", "#90caf9"),
        ("임원", "지분변동", "#90caf9"),
        ("주요주주", "지분변동", "#90caf9"),
        ("최대주주", "지분변동", "#90caf9"),
    ]
    out = []
    for item in disclosures:
        tag = "일반"
        color = "#e0e0e0"
        for key, t, c in rules:
            if key in item:
                tag, color = t, c
                break
        out.append({"text": item, "tag": tag, "color": color})
    return out


def _render_cards(items: List[str], title: str):
    if not items:
        st.caption(f"{title}: 없음")
        return
    st.markdown(f"**{title}**")
    for item in items:
        st.markdown(
            f"""
            <div class="cb-card">
              {item}
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_badge_cards(items: List[Dict[str, str]], title: str):
    if not items:
        st.caption(f"{title}: 없음")
        return
    st.markdown(f"**{title}**")
    for item in items:
        st.markdown(
            f"""
            <div class="cb-card" style="background:#fff;">
              {_badge(item['tag'], item['color'])} {item['text']}
            </div>
            """,
            unsafe_allow_html=True,
        )


@st.cache_data(ttl=3600)
def _fetch_financials(code: str) -> Dict[str, Optional[float]]:
    if not os.getenv("DART_API_KEY"):
        return {}
    try:
        from src.services.dart_service import get_dart_service
        dart = get_dart_service()
        year = str(datetime.now().year - 1)
        prev_year = str(int(year) - 1)
        cur = dart.get_financial_summary(code, year=year)
        prev = dart.get_financial_summary(code, year=prev_year)
        result = {
            "year": year,
            "revenue": cur.get("revenue") if cur else None,
            "operating_profit": cur.get("operating_profit") if cur else None,
            "net_income": cur.get("net_income") if cur else None,
            "total_equity": cur.get("total_equity") if cur else None,
            "total_assets": cur.get("total_assets") if cur else None,
            "prev_revenue": prev.get("revenue") if prev else None,
            "prev_operating_profit": prev.get("operating_profit") if prev else None,
            "prev_net_income": prev.get("net_income") if prev else None,
        }
        return result
    except Exception:
        return {}


@st.cache_data(ttl=3600)
def _fetch_broker_series(code: str, limit: int = 60) -> Optional["pd.DataFrame"]:
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


@st.cache_data(ttl=3600)
def _ai_summary(text: str) -> Optional[str]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        prompt = f"""
당신은 투자 리서치 어시스턴트입니다.
아래 리포트 내용을 기반으로 한국어로 간결하게 요약하세요.
형식:
1) 한 줄 요약
2) 리스크 3개 (불릿)
3) 관찰 포인트 3개 (불릿)

리포트:
{text[:6000]}
"""
        resp = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=prompt,
            config={"max_output_tokens": 512, "temperature": 0.2},
        )
        return getattr(resp, "text", None)
    except Exception:
        return None


st.set_page_config(
    page_title="종목 심층 분석",
    page_icon="🧾",
    layout="wide",
)

st.sidebar.title(SIDEBAR_TITLE)
_sidebar_nav()

st.title("🧾 종목 심층 분석 (v9.0)")
st.caption(APP_FULL_VERSION)
hide_sidebar = st.toggle("메뉴 숨기기", value=False)
_apply_styles(hide_sidebar)

dashboard_only = os.getenv("DASHBOARD_ONLY", "").lower() == "true"
missing_kiwoom = not os.getenv("KIWOOM_APPKEY") or not os.getenv("KIWOOM_SECRETKEY")
read_only = dashboard_only or missing_kiwoom
if dashboard_only:
    st.info("보기 전용 모드입니다. 스케줄러가 만든 리포트만 보여줍니다.")
if missing_kiwoom:
    st.warning("키움 API 키가 없어 온라인 리포트 생성은 꺼져 있습니다.")

col1, col2 = st.columns([2, 1])
with col1:
    try:
        from src.services.account_service import get_holdings_watchlist
        holdings = [
            row for row in get_holdings_watchlist()
            if row.get("status") in ("holding", "sold", "manual")
        ]
    except Exception:
        holdings = []

    holdings_map = {h.get("stock_code"): h for h in holdings if h.get("stock_code")}
    holding_codes = [
        f"{h.get('stock_code')} {h.get('stock_name','')}".strip() for h in holdings
    ]
    holding_codes = [c for c in holding_codes if c]

    if holding_codes:
        selected = st.selectbox("보유/관찰 종목", options=["최근 리포트"] + holding_codes, index=0)
        if selected != "최근 리포트":
            code = selected.split()[0]
        else:
            code = ""
    else:
        code = st.text_input("종목코드", value="", placeholder="예: 090710")

with col2:
    full = st.checkbox("상세 모드 (최근 거래원 5건)", value=False)

run = st.button(
    "분석 리포트 생성",
    type="primary",
    use_container_width=True,
    disabled=read_only,
)

if run and not read_only:
    if not code or not code.isdigit():
        st.error("종목코드를 숫자 6자리로 입력해주세요.")
    else:
        try:
            from src.services.analysis_report import generate_analysis_report
            result = generate_analysis_report(code, full=full)
            st.success(f"리포트 생성 완료: {result.report_path}")
            st.caption(f"요약: {result.summary}")
        except Exception as e:
            st.error(f"리포트 생성 실패: {e}")

# Dashboard view
report_path = None
if code and code.isdigit():
    report_path = _find_latest_report(code)
else:
    reports = _list_reports()
    report_path = reports[0] if reports else None

if report_path and report_path.exists():
    st.subheader(f"리포트: {report_path.name}")
    sections = _load_report_sections(report_path)

    tabs = st.tabs(["요약", "차트", "리포트"])

    with tabs[0]:
        if "AI Summary" in sections:
            st.markdown(f"### {_section_title('AI Summary')}")
            st.markdown(_lines_to_markdown(sections["AI Summary"]))

        if "Easy Summary" in sections:
            st.markdown(f"### {_section_title('Easy Summary')}")
            st.markdown(_lines_to_markdown(sections["Easy Summary"]))
            st.caption("쉬운 요약은 숫자 지표를 일상 언어로 풀어쓴 내용입니다.")

        if code and code in holdings_map:
            h = holdings_map[code]
            st.markdown("### 보유 정보")
            qty = int(h.get("last_qty") or 0)
            avg_price = float(h.get("last_price") or 0.0)
            df_hold, _ = _load_ohlcv_df(code)
            last_price = None
            if df_hold is not None and not df_hold.empty:
                last_price = float(df_hold.sort_values("date").iloc[-1]["close"])
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("보유수량", f"{qty:,}")
            c2.metric("평균단가", f"{avg_price:,.0f}" if avg_price else "-")
            c3.metric("현재가(종가)", f"{last_price:,.0f}" if last_price else "-")
            if qty and avg_price and last_price:
                profit = (last_price - avg_price) * qty
                rate = (last_price / avg_price - 1) * 100
                c4.metric("평가손익", f"{profit:,.0f}", f"{rate:+.1f}%")
            else:
                c4.metric("평가손익", "-")

        for key in ["Holdings Snapshot", "OHLCV Summary", "Volume Profile", "Broker Flow"]:
            if key in sections:
                st.markdown(f"### {_section_title(key)}")
                st.markdown(_lines_to_markdown(sections[key]))
                if key == "Volume Profile":
                    st.caption("매물대는 거래가 많이 쌓인 가격대를 뜻합니다.")

        if "Technical Analysis" in sections:
            tech = _parse_technical(sections["Technical Analysis"])
            if tech:
                st.markdown(f"### {_section_title('Technical Analysis')}")
                cols = st.columns(3)
                cci_val = tech.get("CCI", "-")
                rsi_val = tech.get("RSI", "-")
                cols[0].metric("CCI(14)", cci_val)
                cols[1].metric("RSI(14)", rsi_val)
                cols[2].metric("MACD", tech.get("MACD", "-"))
                try:
                    cci_num = float(str(cci_val).strip())
                    st.caption(f"CCI 해석: {_interpret_cci(cci_num)}")
                except Exception:
                    pass
                try:
                    rsi_num = float(str(rsi_val).strip())
                    st.caption(f"RSI 해석: {_interpret_rsi(rsi_num)}")
                except Exception:
                    pass
                st.caption(f"이동평균선: {tech.get('MA', '-')}")
                st.caption(f"볼린저밴드: {tech.get('BOLL', '-')}")

        fin = _fetch_financials(code) if code else {}
        if fin:
            st.markdown("### 재무 요약")
            c1, c2, c3 = st.columns(3)
            rev = fin.get("revenue")
            rev_prev = fin.get("prev_revenue")
            op = fin.get("operating_profit")
            op_prev = fin.get("prev_operating_profit")
            net = fin.get("net_income")
            net_prev = fin.get("prev_net_income")
            if rev is not None:
                delta = None
                if rev_prev:
                    delta = f"{((rev - rev_prev) / rev_prev * 100):+.1f}%"
                c1.metric("매출액(억원)", f"{rev:,.0f}", delta)
            if op is not None:
                delta = None
                if op_prev:
                    delta = f"{((op - op_prev) / op_prev * 100):+.1f}%"
                c2.metric("영업이익(억원)", f"{op:,.0f}", delta)
            if net is not None:
                delta = None
                if net_prev:
                    delta = f"{((net - net_prev) / net_prev * 100):+.1f}%"
                c3.metric("순이익(억원)", f"{net:,.0f}", delta)
            if rev and op is not None:
                st.caption(f"영업이익률: {(op/rev*100):.1f}%")
            if rev and net is not None:
                st.caption(f"순이익률: {(net/rev*100):.1f}%")

        if "News & Disclosures" in sections:
            st.markdown(f"### {_section_title('News & Disclosures')}")
            news, disclosures = _parse_news_disclosures(sections["News & Disclosures"])
            _render_cards(news[:12], "뉴스")
            news_badges = _classify_news(news[:12])
            _render_badge_cards(news_badges[:12], "뉴스 분류")
            badges = _highlight_disclosures(disclosures)
            _render_badge_cards(badges[:12], "공시 하이라이트")
            _render_cards(disclosures[:12], "공시 전체")

        if "DART Company Profile" in sections:
            with st.expander("기업정보 / 재무 / 최대주주 / 감사의견", expanded=False):
                st.markdown(_lines_to_markdown(sections["DART Company Profile"]))

        for key in ["Entry/Exit Plan", "Summary"]:
            if key in sections:
                st.markdown(f"### {_section_title(key)}")
                st.markdown(_lines_to_markdown(sections[key]))

    with tabs[1]:
        if code and code.isdigit():
            df, source = _load_ohlcv_df(code)
            if df is None or df.empty:
                st.warning(f"차트 데이터를 불러오지 못했습니다. ({source})")
            else:
                df = df.sort_values("date").reset_index(drop=True)
                last = df.iloc[-1]
                prev = df.iloc[-2] if len(df) > 1 else None
                change_pct = 0.0
                if prev is not None and float(prev["close"]) > 0:
                    change_pct = (float(last["close"]) - float(prev["close"])) / float(prev["close"]) * 100.0

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("종가", f"{int(last['close']):,}", f"{change_pct:+.2f}%")
                c2.metric("고가", f"{int(last['high']):,}")
                c3.metric("저가", f"{int(last['low']):,}")
                c4.metric("거래량", f"{int(last['volume']):,}")

                st.caption(f"차트 데이터 소스: {source}")

                if go is None or make_subplots is None or pd is None:
                    view = df.tail(200).set_index("date")
                    st.markdown("#### 종가 추이")
                    st.line_chart(view["close"])
                    st.markdown("#### 거래량")
                    st.bar_chart(view["volume"])
                else:
                    view = df.tail(200)
                    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.02)
                    fig.add_trace(
                        go.Candlestick(
                            x=view["date"],
                            open=view["open"],
                            high=view["high"],
                            low=view["low"],
                            close=view["close"],
                            name="OHLC",
                        ),
                        row=1,
                        col=1,
                    )
                    fig.add_trace(
                        go.Bar(x=view["date"], y=view["volume"], name="Volume"),
                        row=2,
                        col=1,
                    )
                    fig.update_layout(height=600, xaxis_rangeslider_visible=False, showlegend=False)

                    # Volume Profile lines
                    try:
                        from src.domain.volume_profile import calc_volume_profile
                        vp = calc_volume_profile(df, current_price=float(last["close"]), n_days=60, n_bands=10)
                        if vp.poc_price:
                            fig.add_hline(y=vp.poc_price, line_color="#ff6b6b", line_dash="dot", annotation_text="POC", annotation_position="top left")
                        support = None
                        resistance = None
                        if vp.bands:
                            below = [b for b in vp.bands if b.price_high <= float(last["close"])]
                            above = [b for b in vp.bands if b.price_low >= float(last["close"])]
                            if below:
                                support = max(below, key=lambda b: b.pct).price_high
                            if above:
                                resistance = max(above, key=lambda b: b.pct).price_low
                        if support:
                            fig.add_hline(y=support, line_color="#2ecc71", line_dash="dot", annotation_text="지지", annotation_position="top left")
                        if resistance:
                            fig.add_hline(y=resistance, line_color="#e74c3c", line_dash="dot", annotation_text="저항", annotation_position="top left")

                        # Highlight top volume bands on chart
                        if vp.bands:
                            top_bands = sorted(vp.bands, key=lambda b: b.pct, reverse=True)[:3]
                            colors = ["rgba(255, 193, 7, 0.18)", "rgba(33, 150, 243, 0.12)", "rgba(76, 175, 80, 0.10)"]
                            for idx, band in enumerate(top_bands):
                                fig.add_hrect(
                                    y0=band.price_low,
                                    y1=band.price_high,
                                    fillcolor=colors[idx % len(colors)],
                                    line_width=0,
                                    annotation_text=f"매물대 {band.pct:.1f}%",
                                    annotation_position="top left",
                                )
                    except Exception:
                        pass

                    st.plotly_chart(fig, use_container_width=True)

                    # Volume Profile distribution
                    try:
                        from src.domain.volume_profile import calc_volume_profile
                        vp = calc_volume_profile(df, current_price=float(last["close"]), n_days=60, n_bands=10)
                        bands = vp.bands
                        if bands:
                            vp_df = pd.DataFrame({
                                "band": [f"{b.price_low:,.0f}-{b.price_high:,.0f}" for b in bands],
                                "pct": [b.pct for b in bands],
                                "is_current": [b.is_current for b in bands],
                            })
                            vp_df = vp_df.sort_values("pct")
                            colors = ["#ff6b6b" if c else "#6c8ef5" for c in vp_df["is_current"]]
                            vp_fig = go.Figure(
                                data=[go.Bar(
                                    x=vp_df["pct"],
                                    y=vp_df["band"],
                                    orientation="h",
                                    marker_color=colors,
                                )]
                            )
                            vp_fig.update_layout(
                                title="매물대 분포(Volume Profile)",
                                xaxis_title="비중(%)",
                                yaxis_title="가격대",
                                height=500,
                            )
                            st.plotly_chart(vp_fig, use_container_width=True)
                            top_text = ", ".join(vp_df.tail(3)["band"].tolist())
                            if top_text:
                                st.caption(f"상위 매물대 구간: {top_text}")
                    except Exception:
                        st.caption("매물대 차트 계산 실패")

                # Broker flow heatmap
                broker_df = _fetch_broker_series(code)
                if broker_df is not None and not broker_df.empty:
                    st.markdown("#### 거래원 이상 점수 추이")
                    chart_df = broker_df[["screen_date", "anomaly_score"]].dropna()
                    chart_df = chart_df.set_index("screen_date")
                    st.line_chart(chart_df)
                else:
                    st.caption("거래원 시계열 데이터 없음")

    with tabs[2]:
        st.markdown(report_path.read_text(encoding="utf-8"))
        with report_path.open("rb") as f:
            st.download_button(
                label="리포트 다운로드",
                data=f,
                file_name=report_path.name,
                mime="text/markdown",
            )
else:
    st.warning("리포트가 없습니다. 스케줄러 실행 후 확인하세요.")

st.markdown("---")
st.caption(FOOTER_DASHBOARD)
