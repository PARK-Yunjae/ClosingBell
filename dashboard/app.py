import json
import os
import html
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

os.environ.setdefault("DASHBOARD_ONLY", "true")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage import get_buy_picks, iter_buy_pick_outcomes, iter_notification_events, iter_screen_results, list_buy_pick_dates, list_watchlists as list_watchlists_db, load_backtest_dataset
from config import WATCHLIST_MAX_DAYS
from trading_calendar import trading_days_since

LOG_DIR = ROOT / "data" / "logs"
WATCHLIST_DIR = ROOT / "data" / "watchlist"
PERF_DIR = ROOT / "data" / "performance"
OHLCV_DIR = Path(os.getenv("DATA_DIR", "C:/Coding/data")) / "ohlcv"
NAV = ["Overview", "Pick Vault", "Dispatch Log", "Watchlist Lab", "Performance Lab", "Screening Log", "Theme Radar"]
COLORS = {"navy": "#143A52", "teal": "#1E6F74", "mint": "#2A9D8F", "coral": "#E76F51", "gold": "#E9C46A", "bg": "#FFF9F1", "ink": "#16202A"}
MATCH_GAP_WARN_DAYS = 3
MATCH_GAP_CRITICAL_DAYS = 10
PAGE_LABELS = {
    "Overview": "개요",
    "Pick Vault": "추천 보관함",
    "Dispatch Log": "발송 기록",
    "Watchlist Lab": "감시 목록",
    "Performance Lab": "성과 분석",
    "Screening Log": "스크리닝 로그",
    "Theme Radar": "테마 레이더",
}
STATUS_LABELS = {"sent": "성공", "failed": "실패", "disabled": "비활성", "error": "오류"}
EVENT_TYPE_LABELS = {
    "screen_skip": "스크리닝 건너뜀",
    "screen_recommendation": "장마감 스크리닝",
    "daily_picks": "일일 추천",
    "shutdown": "종료 알림",
    "pullback_signals": "눌림목 신호",
    "error": "오류 알림",
}
COMPARE_SOURCE_LABELS = {
    "live_exact": "실전 일치",
    "archive_exact": "백테스트 일치",
    "archive_recent": "백테스트 최근",
    "unknown": "미확인",
}
GAP_FLAG_LABELS = {"ok": "정상", "warning": "주의", "critical": "심각"}
WATCHLIST_STATUS_LABELS = {"active": "활성", "expired": "만료"}

st.set_page_config(page_title="클로징벨 대시보드", page_icon="CB", layout="wide", initial_sidebar_state="expanded")
st.markdown(
    f"""
    <style>
    .stApp {{background: radial-gradient(circle at top left, rgba(233,196,106,.18), transparent 22%), linear-gradient(180deg, #fffdf9, #f4ebdd);}}
    section[data-testid="stSidebar"] {{background: linear-gradient(180deg, #102A43, #143A52 60%, #1E6F74);}}
    section[data-testid="stSidebar"] * {{color: #f7f5ef !important;}}
    section[data-testid="stSidebar"] div[data-baseweb="select"] > div {{background: rgba(255,255,255,.96) !important; border-radius: 14px !important;}}
    section[data-testid="stSidebar"] div[data-baseweb="select"] * {{color: #16202A !important;}}
    section[data-testid="stSidebar"] [data-testid="stTextInput"] input,
    section[data-testid="stSidebar"] [data-testid="stNumberInput"] input,
    section[data-testid="stSidebar"] [data-testid="stDateInput"] input,
    section[data-testid="stSidebar"] textarea {{
        color: #16202A !important;
        background: rgba(255,255,255,.96) !important;
        -webkit-text-fill-color: #16202A !important;
        border-radius: 14px !important;
    }}
    section[data-testid="stSidebar"] [data-baseweb="tag"],
    section[data-testid="stSidebar"] [data-baseweb="tag"] span,
    section[data-testid="stSidebar"] [data-baseweb="tag"] div {{
        color: #16202A !important;
        background: rgba(255,255,255,.92) !important;
    }}
    section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] code {{color: #F8F4ED !important;}}
    .block-container {{padding-top:1.5rem;padding-bottom:2.5rem;padding-left:1.2rem;padding-right:1.2rem;max-width:1480px;}}
    .hero {{padding:1.35rem 1.5rem;border-radius:24px;background:linear-gradient(135deg, rgba(20,58,82,.98), rgba(30,111,116,.92));color:#f8f4ed;box-shadow:0 20px 50px rgba(20,58,82,.16);margin-bottom:1rem;}}
    .hero h1 {{margin:0;font-size:2rem;}}
    .hero p {{margin:.55rem 0 0 0;color:rgba(248,244,237,.82);}}
    .pill {{display:inline-block;padding:.35rem .7rem;margin:.8rem .35rem 0 0;border-radius:999px;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.12);font-size:.84rem;}}
    .kicker {{display:inline-block;margin-bottom:.6rem;padding:.28rem .6rem;border-radius:999px;background:rgba(20,58,82,.08);color:{COLORS["navy"]};font-size:.78rem;font-weight:700;text-transform:uppercase;}}
    div[data-testid="stMetric"] {{background:rgba(255,255,255,.82);border:1px solid rgba(20,58,82,.08);border-radius:20px;padding:.7rem .9rem;box-shadow:0 10px 30px rgba(20,58,82,.06);}}
    .pick {{padding:1rem 1.1rem;background:rgba(255,255,255,.84);border:1px solid rgba(20,58,82,.08);border-radius:20px;box-shadow:0 8px 24px rgba(20,58,82,.06);margin-bottom:.8rem;display:flex;flex-direction:column;min-height:170px;}}
    .pick h4 {{margin:0 0 .35rem 0;color:{COLORS["ink"]};}}
    .pick .meta {{color:#5E6A75;font-size:.92rem;margin-bottom:.35rem;}}
    .pick .note {{color:{COLORS["ink"]};font-size:.95rem;line-height:1.45;margin-top:auto;}}
    .pick .chips {{display:flex;flex-wrap:wrap;gap:.35rem;margin:.35rem 0 .25rem 0;align-items:flex-start;}}
    div[data-testid="stHorizontalBlock"] {{gap:.9rem;}}
    @media (max-width: 1024px) {{
        .block-container {{padding-left:1rem;padding-right:1rem;}}
        .hero {{padding:1.1rem 1.15rem;border-radius:22px;}}
        .hero h1 {{font-size:1.72rem;line-height:1.12;}}
        .hero p {{font-size:.95rem;}}
        .pill {{font-size:.78rem;}}
        .pick {{min-height:150px;padding:.95rem 1rem;}}
        .pick h4 {{font-size:1rem;line-height:1.32;}}
        .pick .meta {{font-size:.88rem;}}
        .pick .note {{font-size:.92rem;line-height:1.42;}}
    }}
    @media (max-width: 640px) {{
        .block-container {{padding-top:1rem;padding-bottom:2rem;padding-left:.8rem;padding-right:.8rem;}}
        .hero {{padding:1rem .95rem 1.05rem;border-radius:18px;}}
        .hero h1 {{font-size:1.42rem;}}
        .hero p {{font-size:.9rem;line-height:1.4;}}
        .pill {{font-size:.72rem;padding:.3rem .55rem;margin:.55rem .28rem 0 0;}}
        .kicker {{font-size:.69rem;margin-bottom:.45rem;}}
        div[data-testid="stMetric"] {{padding:.62rem .72rem;border-radius:16px;}}
        .pick {{min-height:auto;padding:.85rem .9rem;border-radius:16px;}}
        .pick h4 {{font-size:.96rem;}}
        .pick .meta {{font-size:.84rem;}}
        .pick .note {{font-size:.88rem;line-height:1.38;}}
        .pick .chips {{gap:.28rem;}}
        div[data-testid="stHorizontalBlock"] {{gap:.65rem;}}
        div[data-testid="column"] {{min-width:100% !important;flex:1 1 100% !important;}}
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


def hero(title: str, subtitle: str, pills: list[str]) -> None:
    pills_html = "".join(f"<span class='pill'>{p}</span>" for p in pills)
    st.markdown(f"<div class='hero'><h1>{title}</h1><p>{subtitle}</p>{pills_html}</div>", unsafe_allow_html=True)


def kicker(text: str) -> None:
    st.markdown(f"<div class='kicker'>{text}</div>", unsafe_allow_html=True)


def fmt_date(v) -> str:
    if isinstance(v, pd.Timestamp):
        return "-" if pd.isna(v) else v.strftime("%Y-%m-%d")
    return str(v)[:10] if v is not None else "-"


def fmt_dt(v) -> str:
    if isinstance(v, pd.Timestamp):
        return "-" if pd.isna(v) else v.strftime("%Y-%m-%d %H:%M")
    return str(v)[:16] if v is not None else "-"


def fmt_pct(v) -> str:
    try:
        return f"{float(v):+.2f}%"
    except Exception:
        return "-"


def is_blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    return str(value).strip().lower() in {"", "-", "nan", "none", "null"}


def text_list(value) -> list[str]:
    if is_blank(value):
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if not is_blank(item)]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if not is_blank(item)]
            except Exception:
                pass
        return [item.strip() for item in stripped.split(",") if item.strip()]
    return [str(value).strip()]


def compact_text(value, limit: int = 120, fallback: str = "-") -> str:
    if is_blank(value):
        return fallback
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."


def safe_int(value, fallback: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return fallback


def pretty_label(mapping: dict[str, str], value) -> str:
    key = str(value)
    return mapping.get(key, key)


def pretty_event_type(value) -> str:
    key = str(value)
    if key in EVENT_TYPE_LABELS:
        return EVENT_TYPE_LABELS[key]
    if key == "event":
        return "이벤트"
    if key == "dispatch":
        return "발송"
    if not key or key in {"None", "nan"}:
        return "-"
    return key.replace("_", " ")


def pretty_ref_date(value) -> str:
    key = str(value)
    if key in {"unassigned", "None", "nan", "", "-"}:
        return "미지정"
    return key


def compare_tone(label: str, value) -> str:
    text = str(value).strip().lower()
    if is_blank(value):
        return "muted"
    if label in {"등락률"}:
        try:
            num = float(value)
            if num > 0:
                return "good"
            if num < 0:
                return "bad"
            return "neutral"
        except Exception:
            return "muted"
    if label in {"기간 수익"}:
        try:
            num = float(value)
            if num > 0:
                return "good"
            if num < 0:
                return "bad"
            return "neutral"
        except Exception:
            return "muted"
    if label in {"과열"}:
        if any(token in text for token in ("예", "true", "1", "과열")):
            return "bad"
        if any(token in text for token in ("아니오", "false", "0", "정상")):
            return "good"
        return "muted"
    if label in {"테마 강도"}:
        if any(token in text for token in ("강세", "우위", "확산")):
            return "good"
        if any(token in text for token in ("약세", "축소")):
            return "bad"
        return "warn"
    if label in {"트리거"}:
        if any(token in text for token in ("완료", "예", "true", "triggered", "감지")):
            return "good"
        if any(token in text for token in ("대기", "아니오", "false", "미감지")):
            return "muted"
        return "warn"
    if label in {"등급"}:
        if text == "a":
            return "good"
        if text == "b":
            return "warn"
        if text == "c":
            return "neutral"
        return "muted"
    if label in {"Gap", "간격"}:
        if any(token in text for token in ("ok", "exact", "aligned", "matched")):
            return "good"
        if any(token in text for token in ("warning", "caution", "older", "warn")):
            return "warn"
        if any(token in text for token in ("critical", "severe", "stale", "bad")):
            return "bad"
    if label in {"Combo", "조합"}:
        if any(token in text for token in ("selected", "active", "선택", "적용")):
            return "good"
        if any(token in text for token in ("all", "none", "전체", "없음")):
            return "muted"
    if label in {"Source", "소스", "비교 소스"}:
        if "live_exact" in text or text.startswith("live"):
            return "good"
        if "archive_exact" in text:
            return "neutral"
        if "archive_recent" in text or "archive" in text:
            return "warn"
        if any(token in text for token in ("unknown", "missing", "none")):
            return "bad"
    if label in {"Sent", "성공"}:
        return "good" if safe_int(value, 0) > 0 else "muted"
    if label in {"Failed", "실패"}:
        return "bad" if safe_int(value, 0) > 0 else "muted"
    if label in {"Disabled", "비활성"}:
        return "warn" if safe_int(value, 0) > 0 else "muted"
    if label in {"DART", "NEWS", "AI Risk", "뉴스", "AI 위험"}:
        if any(token in text for token in ("normal", "low", "stable", "clean", "ok", "safe", "정상", "낮음", "안정")):
            return "good"
        if any(token in text for token in ("caution", "watch", "medium", "neutral", "주의", "보통", "중립", "관망")):
            return "warn"
        if any(token in text for token in ("high", "risk", "warning", "alert", "bad", "negative", "높음", "위험", "경고", "부정")):
            return "bad"
    if label in {"AI", "Broker", "수급"}:
        if any(token in text for token in ("buy", "bull", "positive", "accumulate", "strong", "매수", "관심", "긍정", "외국계 관심")):
            return "good"
        if any(token in text for token in ("watch", "hold", "wait", "neutral", "관망", "중립", "보통")):
            return "warn"
        if any(token in text for token in ("avoid", "sell", "bear", "negative", "risk", "회피", "매도", "부정", "위험")):
            return "bad"
    return "neutral"


def compare_chip_html(label: str, value) -> str:
    palette = {
        "good": ("rgba(42,157,143,.14)", COLORS["mint"]),
        "warn": ("rgba(233,196,106,.20)", COLORS["navy"]),
        "bad": ("rgba(231,111,81,.16)", COLORS["coral"]),
        "neutral": ("rgba(20,58,82,.10)", COLORS["navy"]),
        "muted": ("rgba(20,58,82,.06)", "#6B7280"),
    }
    bg, fg = palette[compare_tone(label, value)]
    return (
        f"<span style='display:inline-block;margin:0 .35rem .35rem 0;padding:.26rem .55rem;"
        f"border-radius:999px;background:{bg};color:{fg};font-size:.8rem;font-weight:700;'>"
        f"{html.escape(label)} {html.escape(compact_text(value, 28, '미확인'))}</span>"
    )


def gap_severity(gap_days: int) -> str:
    if gap_days >= MATCH_GAP_CRITICAL_DAYS:
        return "critical"
    if gap_days >= MATCH_GAP_WARN_DAYS:
        return "warning"
    return "ok"


def enrich_pick_compare_fields(day_rows: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    if day_rows.empty or signals.empty:
        return day_rows
    join_cols = ["join_code", "join_watchlist", "join_date", "rank"]
    saved = day_rows.copy()
    ref = signals.copy()
    saved["pick_dt"] = pd.to_datetime(saved.get("pick_date"), errors="coerce")
    ref["check_dt"] = pd.to_datetime(ref.get("check_date"), errors="coerce")
    saved["join_code"] = saved["code"].astype(str).str.zfill(6)
    ref["join_code"] = ref["code"].astype(str).str.zfill(6)
    saved["join_watchlist"] = pd.to_datetime(saved.get("watchlist_date"), errors="coerce").dt.strftime("%Y-%m-%d")
    ref["join_watchlist"] = pd.to_datetime(ref.get("watchlist_date"), errors="coerce").dt.strftime("%Y-%m-%d")
    saved["join_date"] = pd.to_datetime(saved.get("pick_date"), errors="coerce").dt.strftime("%Y-%m-%d")
    ref["join_date"] = pd.to_datetime(ref.get("check_date"), errors="coerce").dt.strftime("%Y-%m-%d")
    extra_cols = [col for col in ("ai_action", "ai_risk", "broker_signal") if col in ref.columns]
    if not extra_cols:
        return day_rows
    ref = ref[join_cols + extra_cols].drop_duplicates(join_cols)
    merged = saved.merge(ref, how="left", on=join_cols, suffixes=("", "_signal"))
    for col in extra_cols:
        signal_col = f"{col}_signal"
        if signal_col not in merged.columns:
            continue
        if col not in merged.columns:
            merged[col] = merged[signal_col]
        else:
            merged[col] = merged[col].where(~merged[col].apply(is_blank), merged[signal_col])
        merged = merged.drop(columns=[signal_col])
    still_missing = pd.Series(False, index=merged.index)
    for col in extra_cols:
        if col in merged.columns:
            still_missing = still_missing | merged[col].apply(is_blank)
    if still_missing.any():
        ref_lookup = signals.copy()
        ref_lookup["join_code"] = ref_lookup["code"].astype(str).str.zfill(6)
        ref_lookup["join_watchlist"] = pd.to_datetime(ref_lookup.get("watchlist_date"), errors="coerce").dt.strftime("%Y-%m-%d")
        ref_lookup["check_dt"] = pd.to_datetime(ref_lookup.get("check_date"), errors="coerce")
        ref_lookup = ref_lookup.sort_values("check_dt")
        for idx in merged[still_missing].index:
            row = merged.loc[idx]
            candidates = ref_lookup[
                (ref_lookup["join_code"] == row["join_code"]) &
                (ref_lookup["rank"] == row["rank"]) &
                (ref_lookup["join_watchlist"] == row["join_watchlist"]) &
                ref_lookup["check_dt"].notna() &
                (ref_lookup["check_dt"] <= row["pick_dt"])
            ]
            if candidates.empty:
                continue
            best = candidates.iloc[-1]
            for col in extra_cols:
                if col not in merged.columns or merged.at[idx, col] is None or is_blank(merged.at[idx, col]):
                    merged.at[idx, col] = best.get(col)
    return merged.drop(columns=["join_code", "join_watchlist", "join_date", "pick_dt"], errors="ignore")


def render_pick_compare_cards(day_rows: pd.DataFrame) -> None:
    if day_rows.empty:
        st.info("비교할 종목이 없습니다.")
        return
    rows = list(day_rows.iterrows())
    cards_per_row = min(3, max(1, len(rows)))
    for start in range(0, len(rows), cards_per_row):
        cols = st.columns(cards_per_row)
        for col, (_, row) in zip(cols, rows[start : start + cards_per_row]):
            name = row.get("name", row.get("code", ""))
            grade = str(row.get("conviction", "C"))
            rank = row.get("rank", "-")
            score = safe_int(row.get("conviction_score", 0), 0)
            price = safe_int(row.get("current_price", row.get("buy_price", 0) or 0), 0)
            flags = text_list(row.get("risk_flags"))
            flags_html = "".join(compare_chip_html(flag, "risk") for flag in flags[:5]) if flags else compare_chip_html("리스크", "없음")
            note_lines = []
            if not is_blank(row.get("dart_note")):
                note_lines.append(f"<div class='meta'>DART 메모: {html.escape(compact_text(row.get('dart_note'), 140))}</div>")
            if not is_blank(row.get("news_summary")):
                note_lines.append(f"<div class='meta'>뉴스: {html.escape(compact_text(row.get('news_summary'), 140))}</div>")
            elif "news_summary" in day_rows.columns:
                note_lines.append("<div class='meta'>뉴스: 이 행에는 저장되지 않았습니다.</div>")
            note_lines.append(f"<div class='meta'>리스크 플래그: {', '.join(html.escape(flag) for flag in flags) if flags else '없음'}</div>")
            card_html = (
                f"<div class='pick'>"
                f"<h4>{html.escape(str(name))} <span style='color:{grade_color(grade)}'>[{html.escape(grade)}]</span> #{html.escape(str(rank))}</h4>"
                f"<div class='meta'>확신점수 {score} | D+{int(row.get('days_elapsed', 0) or 0)} | 현재가 {price:,}</div>"
                f"<div class='chips'>"
                f"{compare_chip_html('DART', row.get('dart_risk', '미확인'))}"
                f"{compare_chip_html('뉴스', row.get('news_risk', '미저장'))}"
                f"{compare_chip_html('AI', row.get('ai_action', '미연결'))}"
                f"{compare_chip_html('AI 위험', row.get('ai_risk', '미확인'))}"
                f"{compare_chip_html('수급', row.get('broker_signal', '미확인'))}"
                f"</div>"
                f"<div class='chips'>{flags_html}</div>"
                f"{''.join(note_lines)}"
                f"</div>"
            )
            with col:
                st.markdown(card_html, unsafe_allow_html=True)


def render_pick_cards(day_rows: pd.DataFrame, mode: str) -> None:
    if day_rows.empty:
        st.info("선택한 날짜 데이터가 없습니다.")
        return
    rows = list(day_rows.iterrows())
    cards_per_row = min(2, max(1, len(rows)))
    for start in range(0, len(rows), cards_per_row):
        cols = st.columns(cards_per_row)
        for col, (_, row) in zip(cols, rows[start : start + cards_per_row]):
            grade = str(row.get("conviction", "C"))
            signal_type = row.get("signal_type", "") or "기본 신호"
            price = safe_int(row.get("current_price", row.get("buy_price", 0) or 0), 0)
            risk = text_list(row.get("risk_flags"))
            risk_html = "".join(compare_chip_html(flag, "위험") for flag in risk[:4]) if risk else compare_chip_html("리스크", "없음")
            chips = (
                f"{compare_chip_html('등급', grade)}"
                f"{compare_chip_html('DART', row.get('dart_risk', '미확인'))}"
                f"{compare_chip_html('뉴스', row.get('news_risk', '미저장'))}"
                f"{compare_chip_html('AI', row.get('ai_action', '미확인'))}"
                f"{compare_chip_html('수급', row.get('broker_signal', '미확인'))}"
            )
            note_lines = [
                html.escape(compact_text(signal_type, 54, "기본 신호")),
                f"확신점수 {safe_int(row.get('conviction_score', 0), 0)} | D+{int(row.get('days_elapsed', 0) or 0)} | 현재가 {price:,}",
            ]
            if risk:
                note_lines.append(f"리스크: {html.escape(compact_text(', '.join(risk[:4]), 42, '없음'))}")
            if not is_blank(row.get("news_summary")):
                note_lines.append(f"뉴스: {html.escape(compact_text(row.get('news_summary'), 54))}")
            card_html = (
                f"<div class='pick'>"
                f"<h4>{html.escape(str(row.get('name', row.get('code', ''))))} <span style='color:{grade_color(grade)}'>[{grade}]</span> #{html.escape(str(row.get('rank', '-')))}</h4>"
                f"<div class='chips'>{chips}</div>"
                f"<div class='chips'>{risk_html}</div>"
                f"<div class='note'>{'<br/>'.join(note_lines)}</div>"
                f"</div>"
            )
            with col:
                st.markdown(card_html, unsafe_allow_html=True)


def render_watchlist_stock_cards(sdf: pd.DataFrame) -> None:
    if sdf.empty:
        return
    rows = list(sdf.iterrows())
    cards_per_row = min(2, max(1, len(rows)))
    for start in range(0, len(rows), cards_per_row):
        cols = st.columns(cards_per_row)
        for col, (_, row) in zip(cols, rows[start : start + cards_per_row]):
            grade = str(row.get("conviction", "C"))
            triggered = bool(row.get("triggered"))
            trigger_text = "완료" if triggered else "대기"
            sweet_spot = f"D+{safe_int(row.get('sweet_spot_day', 0), 0)}" if not is_blank(row.get("sweet_spot_day")) else "미설정"
            window_text = f"D+{safe_int(row.get('window_start', 0), 0)} ~ D+{safe_int(row.get('window_end', 0), 0)}"
            score = safe_int(row.get("score", 0), 0)
            entry_price = safe_int(row.get("entry_price", 0), 0)
            chips = (
                f"{compare_chip_html('등급', grade)}"
                f"{compare_chip_html('트리거', trigger_text)}"
                f"{compare_chip_html('스위트스팟', sweet_spot)}"
                f"{compare_chip_html('감시 구간', window_text)}"
            )
            note_lines = [
                f"스크리닝 점수 {score} | 기준가 {entry_price:,}",
                f"트리거일 {fmt_date(row.get('trigger_date')) if triggered else '미감지'}",
            ]
            if not is_blank(row.get("rank_note")):
                note_lines.append(html.escape(compact_text(row.get("rank_note"), 54)))
            card_html = (
                f"<div class='pick'>"
                f"<h4>#{safe_int(row.get('rank', 0), 0)} {html.escape(str(row.get('name', row.get('code', ''))))} <span style='color:{grade_color(grade)}'>[{grade}]</span></h4>"
                f"<div class='chips'>{chips}</div>"
                f"<div class='note'>{'<br/>'.join(note_lines)}</div>"
                f"</div>"
            )
            with col:
                st.markdown(card_html, unsafe_allow_html=True)


def dispatch_combo_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    work = df.copy()
    work["ref_date"] = work["ref_date"].fillna("unassigned").astype(str)
    work["event_type"] = work["event_type"].fillna("event").astype(str)
    work["sent_flag"] = (work["status"].astype(str) == "sent").astype(int)
    work["failed_flag"] = (work["status"].astype(str) == "failed").astype(int)
    work["disabled_flag"] = (work["status"].astype(str) == "disabled").astype(int)
    summary = (
        work.groupby(["ref_date", "event_type"], dropna=False)
        .agg(
            total=("event_id", "count"),
            sent=("sent_flag", "sum"),
            failed=("failed_flag", "sum"),
            disabled=("disabled_flag", "sum"),
            latest_sent=("sent_at", "max"),
        )
        .reset_index()
    )
    summary["success_rate"] = (summary["sent"] / summary["total"] * 100).round(1)
    summary["ref_date_sort"] = pd.to_datetime(summary["ref_date"], errors="coerce")
    summary = summary.sort_values(["ref_date_sort", "latest_sent", "total"], ascending=[False, False, False]).drop(columns=["ref_date_sort"])
    return summary


def sort_dispatch_combo_summary(summary: pd.DataFrame, sort_by: str, ascending: bool = False) -> pd.DataFrame:
    if summary.empty:
        return summary
    work = summary.copy()
    work["ref_date_sort"] = pd.to_datetime(work["ref_date"], errors="coerce")
    sort_map = {
        "Newest Ref Date": ["ref_date_sort", "latest_sent", "total"],
        "Latest Sent": ["latest_sent", "ref_date_sort", "total"],
        "Total Events": ["total", "latest_sent", "ref_date_sort"],
        "Failed": ["failed", "latest_sent", "ref_date_sort"],
        "Success Rate": ["success_rate", "sent", "total"],
        "Sent": ["sent", "success_rate", "latest_sent"],
    }
    cols = sort_map.get(sort_by, sort_map["Newest Ref Date"])
    if len(cols) == 3:
        asc = [ascending, ascending, ascending]
    else:
        asc = ascending
    work = work.sort_values(cols, ascending=asc, na_position="last")
    return work.drop(columns=["ref_date_sort"], errors="ignore")


def prioritize_dispatch_combo_summary(summary: pd.DataFrame, selected_events: list[str] | None = None, selected_ref_date: str = "All") -> pd.DataFrame:
    if summary.empty:
        return summary
    work = summary.copy()
    selected_values = [str(item) for item in (selected_events or [])]
    selected_event = selected_values[0] if len(selected_values) == 1 else None
    selected_ref = str(selected_ref_date)
    event_active = selected_event is not None
    ref_active = selected_ref != "All"
    if not event_active and not ref_active:
        return work
    event_match = work["event_type"].astype(str).eq(selected_event) if event_active else pd.Series(True, index=work.index)
    if ref_active:
        if selected_ref == "unassigned":
            ref_match = work["ref_date"].isna() | work["ref_date"].astype(str).isin(["", "nan", "None", "unassigned"])
        else:
            ref_match = work["ref_date"].astype(str).eq(selected_ref)
    else:
        ref_match = pd.Series(True, index=work.index)
    if event_active and ref_active:
        selected_mask = event_match & ref_match
    elif event_active:
        selected_mask = event_match
    else:
        selected_mask = ref_match
    work["_selected_combo"] = selected_mask.astype(int)
    work = work.sort_values("_selected_combo", ascending=False, kind="stable")
    return work.drop(columns=["_selected_combo"], errors="ignore")


def render_dispatch_combo_banner(selected_events: list[str], event_options: list[str], selected_ref_date: str) -> None:
    event_values = [str(item) for item in selected_events]
    all_events = [str(item) for item in event_options]
    event_active = bool(all_events) and sorted(event_values) != sorted(all_events)
    ref_active = selected_ref_date != "All"
    combo_active = event_active or ref_active
    if not all_events:
        return

    if not event_values:
        event_label = "없음"
    elif len(event_values) == 1:
        event_label = pretty_event_type(event_values[0])
    elif len(event_values) == len(all_events):
        event_label = "전체"
    else:
        event_label = f"{len(event_values)}개 선택"
    ref_label = pretty_ref_date(selected_ref_date) if ref_active else "전체"

    left, right = st.columns([1.2, 0.45])
    with left:
        chips = (
            f"{compare_chip_html('이벤트', event_label)}"
            f"{compare_chip_html('기준일', ref_label)}"
            f"{compare_chip_html('조합', '적용' if combo_active else '전체')}"
        )
        banner_html = (
            "<div class='pick'>"
            "<div class='meta'>현재 조합</div>"
            f"<div style='margin:.35rem 0 .15rem 0;'>{chips}</div>"
            "<div class='meta'>초기화는 조합 필터만 해제합니다. 상태, 응답 코드, 검색, 날짜 범위는 유지됩니다.</div>"
            "</div>"
        )
        st.markdown(banner_html, unsafe_allow_html=True)
    with right:
        if st.button("조합 초기화", key="dispatch_combo_reset", use_container_width=True, disabled=not combo_active):
            st.session_state["dispatch_event_types"] = all_events
            st.session_state["dispatch_ref_date"] = "All"
            st.session_state["dispatch_event"] = 0
            st.rerun()


def render_dispatch_combo_cards(
    summary: pd.DataFrame,
    limit: int = 9,
    selected_events: list[str] | None = None,
    selected_ref_date: str = "All",
) -> None:
    if summary.empty:
        st.info("표시할 조합 요약이 없습니다.")
        return
    selected_values = [str(item) for item in (selected_events or [])]
    selected_event = selected_values[0] if len(selected_values) == 1 else None
    selected_ref = str(selected_ref_date)
    prioritized = prioritize_dispatch_combo_summary(summary, selected_events=selected_events, selected_ref_date=selected_ref_date)
    rows = list(prioritized.head(limit).iterrows())
    for start in range(0, len(rows), 3):
        cols = st.columns(3)
        for col, (_, row) in zip(cols, rows[start : start + 3]):
            event_type = row.get("event_type", "event")
            ref_date = row.get("ref_date", "unassigned")
            event_label = pretty_event_type(event_type)
            ref_label = pretty_ref_date(ref_date)
            total = safe_int(row.get("total"), 0)
            sent = safe_int(row.get("sent"), 0)
            failed = safe_int(row.get("failed"), 0)
            disabled = safe_int(row.get("disabled"), 0)
            success_rate = row.get("success_rate", 0)
            latest_sent = fmt_dt(row.get("latest_sent"))
            event_match = selected_event is not None and str(event_type) == selected_event
            ref_match = selected_ref != "All" and str(ref_date) == selected_ref
            is_selected = (selected_event is not None or selected_ref != "All") and (
                (event_match and selected_ref == "All")
                or (ref_match and selected_event is None)
                or (event_match and ref_match)
            )
            status_chips = (
                f"{compare_chip_html('성공', sent)}"
                f"{compare_chip_html('실패', failed)}"
                f"{compare_chip_html('비활성', disabled)}"
            )
            selection_chip = compare_chip_html("조합", "선택") if is_selected else ""
            card_style = (
                "border:2px solid rgba(42,157,143,.65);"
                "box-shadow:0 14px 36px rgba(42,157,143,.14);"
                "background:linear-gradient(180deg, rgba(255,255,255,.96), rgba(232,248,245,.92));"
                if is_selected
                else ""
            )
            card_html = (
                f"<div class='pick' style='{card_style}'>"
                f"<h4>{html.escape(str(event_label))}</h4>"
                f"<div class='meta'>기준일 {html.escape(str(ref_label))} | 건수 {total} | 성공률 {success_rate:.1f}%</div>"
                f"<div style='margin:.2rem 0 0 0;'>{selection_chip}</div>"
                f"<div style='margin:.3rem 0 .15rem 0;'>{status_chips}</div>"
                f"<div class='meta'>최근 발송 {html.escape(latest_sent)}</div>"
                f"</div>"
            )
            with col:
                st.markdown(card_html, unsafe_allow_html=True)
                if st.button("이 조합 보기", key=f"dispatch_combo_{event_type}_{ref_date}_{start}", use_container_width=True):
                    st.session_state["dispatch_event_types"] = [str(event_type)]
                    st.session_state["dispatch_ref_date"] = str(ref_date)
                    st.session_state["dispatch_event"] = 0
                    st.rerun()


def grade_color(g: str) -> str:
    return {"A": COLORS["coral"], "B": COLORS["gold"], "C": COLORS["mint"]}.get(str(g), COLORS["teal"])


@st.cache_data(show_spinner=False)
def load_logs() -> dict[str, dict]:
    logs = {}
    for item in iter_screen_results():
        if item and item.get("date"):
            logs[item["date"]] = item
    if logs:
        return logs
    for path in sorted(LOG_DIR.glob("*.json")):
        try:
            logs[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return logs


@st.cache_data(show_spinner=False)
def load_watchlists() -> list[dict]:
    rows = list_watchlists_db(desc=True)
    if rows:
        return rows
    out = []
    for path in sorted(WATCHLIST_DIR.glob("*.json"), reverse=True):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            pass
    return out


@st.cache_data(show_spinner=False)
def load_df(name: str, date_cols: tuple[str, ...]) -> pd.DataFrame:
    if name == "tracking":
        path = PERF_DIR / "tracking.json"
        data = json.loads(path.read_text(encoding="utf-8")).get("records", []) if path.exists() else []
    else:
        data = load_backtest_dataset(name) or []
    df = pd.DataFrame(data)
    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


@st.cache_data(show_spinner=False)
def load_saved_picks() -> pd.DataFrame:
    rows = []
    for pick_date in list_buy_pick_dates(desc=False):
        payload = get_buy_picks(pick_date) or {}
        for order, item in enumerate(payload.get("picks", []), start=1):
            rows.append({"pick_date": pick_date, "pick_order": order, **item})
    df = pd.DataFrame(rows)
    if "pick_date" in df.columns:
        df["pick_date"] = pd.to_datetime(df["pick_date"], errors="coerce")
    return df


@st.cache_data(show_spinner=False)
def load_live_pick_perf() -> pd.DataFrame:
    df = pd.DataFrame(iter_buy_pick_outcomes(desc=False))
    for col in ("pick_date", "signal_date", "track_date", "watchlist_date"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


@st.cache_data(show_spinner=False)
def load_notifications() -> pd.DataFrame:
    rows = []
    for item in iter_notification_events(desc=True):
        payload = item.get("payload", {}) or {}
        embeds = payload.get("embeds", []) or []
        first = embeds[0] if embeds else {}
        rows.append(
            {
                "event_id": item.get("event_id"),
                "event_type": item.get("event_type"),
                "ref_date": item.get("ref_date"),
                "sent_at": pd.to_datetime(item.get("sent_at"), errors="coerce"),
                "status": item.get("status"),
                "response_code": item.get("response_code"),
                "embed_count": len(embeds),
                "title": first.get("title", ""),
                "description": first.get("description", payload.get("content", "")),
                "content": payload.get("content", ""),
                "payload": payload,
            }
        )
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def load_ohlcv(code: str) -> pd.DataFrame:
    path = OHLCV_DIR / f"{str(code).zfill(6)}.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df.columns = [c.lower().strip() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)



def active_watchlists(watchlists: list[dict]) -> tuple[list[dict], pd.DataFrame]:
    today = datetime.now().strftime("%Y-%m-%d")
    active, rows = [], []
    for wl in watchlists:
        stocks = wl.get("stocks", [])
        status = "active" if wl.get("expires", "") >= today else "expired"
        rows.append({"created": wl.get("created"), "expires": wl.get("expires"), "days_elapsed": trading_days_since(wl.get("created")), "stock_count": len(stocks), "triggered_count": sum(1 for x in stocks if x.get("triggered")), "status": status})
        if status == "active":
            active.append(wl)
    return active, pd.DataFrame(rows)


def watchlist_lifecycle_chart(wl_summary: pd.DataFrame) -> go.Figure | None:
    if wl_summary.empty:
        return None
    chart_df = wl_summary.copy()
    chart_df["created_dt"] = pd.to_datetime(chart_df["created"], errors="coerce")
    chart_df = chart_df.dropna(subset=["created_dt"]).sort_values("created_dt", ascending=False).head(30)
    if chart_df.empty:
        return None

    chart_df["progress"] = chart_df["days_elapsed"].clip(lower=0, upper=WATCHLIST_MAX_DAYS)
    chart_df["remaining"] = (WATCHLIST_MAX_DAYS - chart_df["progress"]).clip(lower=0)
    chart_df["label"] = chart_df["created"].astype(str)
    progress_colors = chart_df.apply(
        lambda row: COLORS["teal"] if row["status"] == "active" else COLORS["navy"],
        axis=1,
    ).tolist()
    hover_text = chart_df.apply(
        lambda row: (
            f"생성일 {row['created']}<br>"
            f"만료일 {row['expires']}<br>"
            f"진행 D+{int(row['days_elapsed'])}/{WATCHLIST_MAX_DAYS}<br>"
            f"종목 수 {int(row['stock_count'])} · 트리거 {int(row['triggered_count'])}<br>"
            f"상태 {pretty_label(WATCHLIST_STATUS_LABELS, row['status'])}"
        ),
        axis=1,
    )

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=chart_df["progress"],
            y=chart_df["label"],
            orientation="h",
            name="경과",
            marker_color=progress_colors,
            text=[f"D+{int(v)}" for v in chart_df["days_elapsed"]],
            textposition="inside",
            insidetextanchor="middle",
            customdata=hover_text,
            hovertemplate="%{customdata}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=chart_df["remaining"],
            y=chart_df["label"],
            orientation="h",
            name="잔여",
            marker_color="rgba(20,58,82,.12)",
            customdata=hover_text,
            hovertemplate="%{customdata}<extra></extra>",
        )
    )
    fig.update_layout(
        height=max(320, len(chart_df) * 22),
        barmode="stack",
        margin=dict(l=8, r=8, t=16, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,.72)",
        font=dict(color=COLORS["ink"]),
        legend=dict(orientation="h", y=1.02, x=0),
    )
    fig.update_xaxes(
        title="거래일 진행",
        tickmode="array",
        tickvals=list(range(0, WATCHLIST_MAX_DAYS + 1)),
        ticktext=[f"D+{x}" for x in range(0, WATCHLIST_MAX_DAYS + 1)],
        gridcolor="rgba(20,58,82,.08)",
    )
    fig.update_yaxes(autorange="reversed", showgrid=False)
    return fig


def watchlist_stock_timeline(payload: dict) -> go.Figure | None:
    stocks = payload.get("stocks", []) or []
    if not stocks:
        return None

    created = payload.get("created")
    current_day = min(trading_days_since(created), WATCHLIST_MAX_DAYS)
    rows = []
    for stock in stocks:
        trigger_day = None
        if stock.get("triggered") and stock.get("trigger_date"):
            try:
                trigger_day = min(
                    trading_days_since(created, stock.get("trigger_date")),
                    WATCHLIST_MAX_DAYS,
                )
            except Exception:
                trigger_day = None
        rows.append(
            {
                "label": f"#{int(stock.get('rank', 0) or 0)} {stock.get('name', stock.get('code', ''))}",
                "window_start": int(stock.get("window_start", 1) or 1),
                "window_end": int(stock.get("window_end", WATCHLIST_MAX_DAYS) or WATCHLIST_MAX_DAYS),
                "sweet_spot_day": int(stock.get("sweet_spot_day", 0) or 0),
                "trigger_day": trigger_day,
                "triggered": bool(stock.get("triggered")),
                "trigger_date": stock.get("trigger_date"),
                "conviction": stock.get("conviction") or "-",
                "rank": int(stock.get("rank", 0) or 0),
            }
        )

    chart_df = pd.DataFrame(rows).sort_values(["rank", "label"]).reset_index(drop=True)
    chart_df["window_width"] = (chart_df["window_end"] - chart_df["window_start"]).clip(lower=0) + 1
    hover_text = chart_df.apply(
        lambda row: (
            f"{row['label']}<br>"
            f"감시 구간 D+{int(row['window_start'])}~D+{int(row['window_end'])}<br>"
            f"스위트스팟 D+{int(row['sweet_spot_day'])}<br>"
            f"트리거 {'예' if row['triggered'] else '아니오'}<br>"
            f"트리거 날짜 {row['trigger_date'] or '-'}<br>"
            f"등급 {row['conviction']}"
        ),
        axis=1,
    )
    window_colors = [
        COLORS["coral"] if triggered else COLORS["gold"] if row["sweet_spot_day"] <= current_day else COLORS["mint"]
        for triggered, (_, row) in zip(chart_df["triggered"], chart_df.iterrows())
    ]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=chart_df["window_width"],
            y=chart_df["label"],
            base=chart_df["window_start"],
            orientation="h",
            name="감시 구간",
            marker_color=window_colors,
            text=[f"D+{int(s)}~D+{int(e)}" for s, e in zip(chart_df["window_start"], chart_df["window_end"])],
            textposition="inside",
            customdata=hover_text,
            hovertemplate="%{customdata}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=chart_df["sweet_spot_day"],
            y=chart_df["label"],
            mode="markers",
            name="스위트스팟",
            marker=dict(symbol="diamond", size=11, color=COLORS["navy"], line=dict(color="#fff", width=1)),
            customdata=hover_text,
            hovertemplate="%{customdata}<extra></extra>",
        )
    )

    triggered_df = chart_df[chart_df["trigger_day"].notna()].copy()
    if not triggered_df.empty:
        fig.add_trace(
            go.Scatter(
                x=triggered_df["trigger_day"],
                y=triggered_df["label"],
                mode="markers",
                name="트리거",
                marker=dict(symbol="star", size=13, color=COLORS["coral"], line=dict(color="#fff", width=1)),
                customdata=triggered_df.apply(
                    lambda row: f"{row['label']}<br>트리거 D+{int(row['trigger_day'])}<br>날짜 {row['trigger_date']}<br>등급 {row['conviction']}",
                    axis=1,
                ),
                hovertemplate="%{customdata}<extra></extra>",
            )
        )

    fig.add_vline(
        x=current_day,
        line_width=2,
        line_dash="dot",
        line_color=COLORS["teal"],
        annotation_text=f"오늘 D+{current_day}",
        annotation_position="top",
    )
    fig.update_layout(
        height=max(280, len(chart_df) * 42),
        margin=dict(l=8, r=8, t=24, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,.72)",
        font=dict(color=COLORS["ink"]),
        legend=dict(orientation="h", y=1.02, x=0),
    )
    fig.update_xaxes(
        title="거래일 감시 구간",
        range=[0, WATCHLIST_MAX_DAYS + 1],
        tickmode="array",
        tickvals=list(range(0, WATCHLIST_MAX_DAYS + 1)),
        ticktext=[f"D+{x}" for x in range(0, WATCHLIST_MAX_DAYS + 1)],
        gridcolor="rgba(20,58,82,.08)",
    )
    fig.update_yaxes(autorange="reversed", showgrid=False)
    return fig


def day_profile_chart(df: pd.DataFrame, label: str = "매수 신호", bar_color: str = COLORS["navy"], line_color: str = COLORS["coral"]) -> go.Figure | None:
    if df.empty:
        return None
    grp = df.groupby("track_day").agg(win_rate=("win", "mean"), avg_ret=("return_pct", "mean")).reset_index()
    grp["win_rate"] *= 100
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=grp["track_day"], y=grp["win_rate"], name=f"{label} 승률", marker_color=bar_color, hovertemplate="D+%{x}<br>승률 %{y:.1f}%<extra></extra>"), secondary_y=False)
    fig.add_trace(go.Scatter(x=grp["track_day"], y=grp["avg_ret"], name=f"{label} 평균 수익", line=dict(color=line_color, width=3), hovertemplate="D+%{x}<br>평균 수익 %{y:.2f}%<extra></extra>"), secondary_y=True)
    fig.update_layout(height=340, margin=dict(l=8, r=8, t=16, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,.72)", font=dict(color=COLORS["ink"]), legend=dict(orientation="h", y=1.02, x=0))
    fig.update_xaxes(tickmode="array", tickvals=grp["track_day"], ticktext=[f"D+{int(x)}" for x in grp["track_day"]], showgrid=False)
    fig.update_yaxes(title_text="승률(%)", secondary_y=False, gridcolor="rgba(20,58,82,.08)")
    fig.update_yaxes(title_text="수익률(%)", secondary_y=True, showgrid=False)
    return fig


def rolling_chart(df: pd.DataFrame, window: int = 20) -> go.Figure | None:
    day1 = df[df["track_day"] == 1].copy()
    if day1.empty:
        return None
    daily = day1.groupby("signal_date").agg(win_rate=("win", "mean"), avg_ret=("return_pct", "mean")).reset_index().sort_values("signal_date")
    daily["rolling_wr"] = daily["win_rate"].rolling(window, min_periods=5).mean() * 100
    daily["rolling_ret"] = daily["avg_ret"].rolling(window, min_periods=5).mean()
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=daily["signal_date"], y=daily["rolling_wr"], name=f"{window}일 D+1 승률", line=dict(color=COLORS["navy"], width=3), hovertemplate="%{x|%Y-%m-%d}<br>승률 %{y:.1f}%<extra></extra>"), secondary_y=False)
    fig.add_trace(go.Scatter(x=daily["signal_date"], y=daily["rolling_ret"], name=f"{window}일 D+1 평균 수익", line=dict(color=COLORS["coral"], width=2), hovertemplate="%{x|%Y-%m-%d}<br>평균 수익 %{y:.2f}%<extra></extra>"), secondary_y=True)
    fig.update_layout(height=340, margin=dict(l=8, r=8, t=16, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,.72)", font=dict(color=COLORS["ink"]), legend=dict(orientation="h", y=1.02, x=0))
    fig.update_yaxes(title_text="승률(%)", secondary_y=False, gridcolor="rgba(20,58,82,.08)")
    fig.update_yaxes(title_text="수익률(%)", secondary_y=True, showgrid=False)
    return fig


def heatmap(df: pd.DataFrame) -> go.Figure | None:
    if df.empty:
        return None
    pivot = df.pivot_table(index="rank", columns="track_day", values="return_pct", aggfunc="mean").sort_index()
    if pivot.empty:
        return None
    fig = go.Figure(go.Heatmap(z=pivot.values, x=[f"D+{int(x)}" for x in pivot.columns], y=[f"#{int(x)}" for x in pivot.index], colorscale=[[0, "#0B3C49"], [.45, "#F6F4EF"], [1, "#E76F51"]], zmid=0, colorbar=dict(title="평균 수익률"), hovertemplate="순위 %{y}<br>%{x}<br>평균 수익 %{z:.2f}%<extra></extra>"))
    fig.update_layout(height=340, margin=dict(l=8, r=8, t=16, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,.72)", font=dict(color=COLORS["ink"]))
    return fig


def conviction_scatter(signals: pd.DataFrame, perf: pd.DataFrame) -> go.Figure | None:
    day1 = perf[perf["track_day"] == 1].copy()
    if signals.empty or day1.empty:
        return None
    left = signals.copy()
    date_col = next((col for col in ("check_date", "pick_date", "signal_date") if col in left.columns), None)
    if not date_col:
        return None
    left["check_key"] = left[date_col].dt.strftime("%Y-%m-%d")
    signal_col = "pick_date" if "pick_date" in day1.columns else "signal_date"
    day1["signal_key"] = day1[signal_col].dt.strftime("%Y-%m-%d")
    merged = day1.merge(left[["code", "rank", "check_key", "conviction", "conviction_score", "signal_type"]], left_on=["code", "rank", "signal_key"], right_on=["code", "rank", "check_key"], how="left")
    if merged.empty:
        return None
    fig = go.Figure()
    for grade in ("A", "B", "C"):
        sub = merged[merged["conviction"] == grade]
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(x=sub["conviction_score"], y=sub["high_ret"] if "high_ret" in sub.columns else sub["return_pct"], mode="markers", name=f"{grade} 등급", marker=dict(size=9, color=grade_color(grade), opacity=.75, line=dict(color="#fff", width=.8)), text=sub["signal_type"].fillna("기본"), hovertemplate="확신 점수 %{x}<br>수익률 %{y:.2f}%<br>신호 %{text}<extra></extra>"))
    fig.update_layout(height=360, margin=dict(l=8, r=8, t=16, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,.72)", font=dict(color=COLORS["ink"]), legend=dict(orientation="h", y=1.02, x=0))
    fig.update_xaxes(title="확신 점수", gridcolor="rgba(20,58,82,.08)")
    fig.update_yaxes(title="D+1 고가 수익률" if "high_ret" in merged.columns else "D+1 종가 수익률", gridcolor="rgba(20,58,82,.08)")
    return fig


def price_chart(code: str, signal_date, watchlist_date=None) -> go.Figure | None:
    df = load_ohlcv(code)
    anchor = pd.to_datetime(signal_date, errors="coerce")
    if df.empty or pd.isna(anchor):
        return None
    idxs = df.index[df["date"] <= anchor]
    if len(idxs) == 0:
        return None
    i = int(idxs[-1]); win = df.iloc[max(0, i - 35): min(len(df), i + 11)].copy()
    fig = go.Figure(go.Candlestick(x=win["date"], open=win["open"], high=win["high"], low=win["low"], close=win["close"], increasing_line_color=COLORS["coral"], decreasing_line_color=COLORS["teal"], increasing_fillcolor=COLORS["coral"], decreasing_fillcolor=COLORS["teal"], name="주가"))
    for d, name, color in ((watchlist_date, "감시 시작", COLORS["gold"]), (signal_date, "신호일", COLORS["navy"])):
        dt = pd.to_datetime(d, errors="coerce")
        row = win.loc[win["date"] == dt]
        if pd.isna(dt) or row.empty:
            continue
        fig.add_trace(go.Scatter(x=row["date"], y=row["close"], mode="markers+text", text=[name], textposition="top center", marker=dict(size=11, color=color, line=dict(color="#fff", width=1.5)), name=name))
    fig.update_layout(height=420, margin=dict(l=8, r=8, t=24, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,.75)", font=dict(color=COLORS["ink"]), xaxis_rangeslider_visible=False, legend=dict(orientation="h", y=1.02, x=0))
    fig.update_xaxes(showgrid=False); fig.update_yaxes(gridcolor="rgba(20,58,82,.08)")
    return fig


def pick_timeline_chart(df: pd.DataFrame) -> go.Figure | None:
    if df.empty:
        return None
    work = df.sort_values("track_day").copy()
    fig = go.Figure()
    if "open_ret" in work.columns:
        fig.add_trace(go.Scatter(x=work["track_day"], y=work["open_ret"], mode="lines+markers", name="시가", line=dict(color=COLORS["gold"], width=2), hovertemplate="D+%{x}<br>시가 수익률 %{y:.2f}%<extra></extra>"))
    if "high_ret" in work.columns:
        fig.add_trace(go.Scatter(x=work["track_day"], y=work["high_ret"], mode="lines+markers", name="고가", line=dict(color=COLORS["mint"], width=2), hovertemplate="D+%{x}<br>고가 수익률 %{y:.2f}%<extra></extra>"))
    fig.add_trace(go.Scatter(x=work["track_day"], y=work["return_pct"], mode="lines+markers", name="종가", line=dict(color=COLORS["coral"], width=3), hovertemplate="D+%{x}<br>종가 수익률 %{y:.2f}%<extra></extra>"))
    fig.add_hline(y=0, line_color="rgba(20,58,82,.25)", line_dash="dash")
    fig.update_layout(height=260, margin=dict(l=8, r=8, t=16, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,.72)", font=dict(color=COLORS["ink"]), legend=dict(orientation="h", y=1.02, x=0))
    fig.update_xaxes(tickmode="array", tickvals=work["track_day"], ticktext=[f"D+{int(x)}" for x in work["track_day"]], gridcolor="rgba(20,58,82,.08)")
    fig.update_yaxes(title="수익률(%)", gridcolor="rgba(20,58,82,.08)")
    return fig


def build_pick_compare_perf(day_rows: pd.DataFrame, source: str, live_pick_perf: pd.DataFrame, buy_perf: pd.DataFrame) -> pd.DataFrame:
    if day_rows.empty:
        return pd.DataFrame()
    base = day_rows.copy()
    base["code_key"] = base["code"].astype(str).str.zfill(6)
    base["rank_key"] = pd.to_numeric(base["rank"], errors="coerce") if "rank" in base.columns else pd.Series(pd.NA, index=base.index)
    base_date_col = "pick_date" if source == "saved" and "pick_date" in base.columns else "check_date"
    base["base_event_date"] = pd.to_datetime(base[base_date_col], errors="coerce") if base_date_col in base.columns else pd.NaT

    live = live_pick_perf.copy()
    if not live.empty and "code" in live.columns:
        live["code_key"] = live["code"].astype(str).str.zfill(6)
        live["rank_key"] = pd.to_numeric(live["rank"], errors="coerce") if "rank" in live.columns else pd.Series(pd.NA, index=live.index)
        live["perf_event_date"] = pd.to_datetime(live["pick_date"], errors="coerce") if "pick_date" in live.columns else pd.NaT

    archive = buy_perf.copy()
    if not archive.empty and "code" in archive.columns:
        archive["code_key"] = archive["code"].astype(str).str.zfill(6)
        archive["rank_key"] = pd.to_numeric(archive["rank"], errors="coerce") if "rank" in archive.columns else pd.Series(pd.NA, index=archive.index)
        archive["perf_event_date"] = pd.to_datetime(archive["signal_date"], errors="coerce") if "signal_date" in archive.columns else pd.NaT

    matched_frames = []
    for _, row in base.iterrows():
        code_key = row.get("code_key")
        rank_key = row.get("rank_key")
        event_date = row.get("base_event_date")
        if is_blank(code_key) or pd.isna(event_date):
            continue

        matched = pd.DataFrame()
        compare_source = None
        if source == "saved" and not live.empty and "perf_event_date" in live.columns:
            matched = live[(live["code_key"] == code_key) & (live["perf_event_date"] == event_date)].copy()
            if "rank_key" in matched.columns and not pd.isna(rank_key):
                rank_exact = matched[matched["rank_key"] == rank_key].copy()
                if not rank_exact.empty:
                    matched = rank_exact
            if not matched.empty:
                compare_source = "live_exact"

        if matched.empty and not archive.empty and "perf_event_date" in archive.columns:
            exact = archive[(archive["code_key"] == code_key) & (archive["perf_event_date"] == event_date)].copy()
            if "rank_key" in exact.columns and not pd.isna(rank_key):
                rank_exact = exact[exact["rank_key"] == rank_key].copy()
                if not rank_exact.empty:
                    exact = rank_exact
            if not exact.empty:
                matched = exact
                compare_source = "archive_exact"
            else:
                recent = archive[(archive["code_key"] == code_key) & archive["perf_event_date"].notna() & (archive["perf_event_date"] <= event_date)].copy()
                if "rank_key" in recent.columns and not pd.isna(rank_key):
                    rank_recent = recent[recent["rank_key"] == rank_key].copy()
                    if not rank_recent.empty:
                        recent = rank_recent
                if not recent.empty:
                    latest_perf_date = recent["perf_event_date"].max()
                    matched = recent[recent["perf_event_date"] == latest_perf_date].copy()
                    compare_source = "archive_recent"

        if matched.empty:
            continue

        rank_label = "-" if pd.isna(rank_key) else str(safe_int(rank_key, 0))
        matched["label"] = f"#{rank_label} {row.get('name', row.get('code', ''))}"
        matched["base_name"] = row.get("name", row.get("code", ""))
        matched["base_rank"] = rank_key
        matched["base_event_date"] = event_date
        matched_date = matched["perf_event_date"].iloc[0] if "perf_event_date" in matched.columns and not matched.empty else pd.NaT
        gap_days = trading_days_since(fmt_date(matched_date), fmt_date(event_date)) if not pd.isna(matched_date) and not pd.isna(event_date) else 0
        matched["match_gap_days"] = gap_days
        matched["compare_source"] = compare_source or "unknown"
        matched_frames.append(matched)

    if not matched_frames:
        return pd.DataFrame()
    return pd.concat(matched_frames, ignore_index=True)


def pick_compare_chart(df: pd.DataFrame, metric_col: str) -> go.Figure | None:
    if df.empty or metric_col not in df.columns:
        return None
    work = df.dropna(subset=[metric_col, "track_day"]).copy()
    if work.empty:
        return None
    order = work.sort_values(["base_rank", "label"]).drop_duplicates("label")["label"].tolist()
    palette = [COLORS["coral"], COLORS["navy"], COLORS["mint"], COLORS["gold"], COLORS["teal"], "#7C5CFC", "#4C956C", "#C06C84"]
    fig = go.Figure()
    for idx, label in enumerate(order):
        sub = work[work["label"] == label].sort_values("track_day")
        hover_data = sub.apply(lambda row: [pretty_label(COMPARE_SOURCE_LABELS, row["compare_source"]), fmt_date(row.get("perf_event_date"))], axis=1).tolist()
        fig.add_trace(
            go.Scatter(
                x=sub["track_day"],
                y=sub[metric_col],
                mode="lines+markers",
                name=label,
                line=dict(color=palette[idx % len(palette)], width=3),
                marker=dict(size=8),
                customdata=hover_data,
                hovertemplate="%{fullData.name}<br>D+%{x}<br>수익률 %{y:.2f}%<br>비교 소스 %{customdata[0]}<br>매칭일 %{customdata[1]}<extra></extra>",
            )
        )
    fig.add_hline(y=0, line_color="rgba(20,58,82,.25)", line_dash="dash")
    fig.update_layout(height=320, margin=dict(l=8, r=8, t=16, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,.72)", font=dict(color=COLORS["ink"]), legend=dict(orientation="h", y=1.02, x=0))
    fig.update_xaxes(tickmode="array", tickvals=sorted(work["track_day"].dropna().unique().tolist()), ticktext=[f"D+{int(x)}" for x in sorted(work["track_day"].dropna().unique().tolist())], gridcolor="rgba(20,58,82,.08)")
    fig.update_yaxes(title="수익률(%)", gridcolor="rgba(20,58,82,.08)")
    return fig


def pick_compare_heatmap(df: pd.DataFrame, metric_col: str) -> go.Figure | None:
    if df.empty or metric_col not in df.columns:
        return None
    work = df.dropna(subset=[metric_col, "track_day"]).copy()
    if work.empty:
        return None
    order = work.sort_values(["base_rank", "label"]).drop_duplicates("label")["label"].tolist()
    pivot = work.pivot_table(index="label", columns="track_day", values=metric_col, aggfunc="mean")
    pivot = pivot.reindex(order).sort_index(axis=1)
    if pivot.empty:
        return None
    fig = go.Figure(
        go.Heatmap(
            z=pivot.values,
            x=[f"D+{int(x)}" for x in pivot.columns],
            y=pivot.index.tolist(),
            colorscale=[[0, "#0B3C49"], [.45, "#F6F4EF"], [1, "#E76F51"]],
            zmid=0,
            colorbar=dict(title="수익률(%)"),
            hovertemplate="%{y}<br>%{x}<br>수익률 %{z:.2f}%<extra></extra>",
        )
    )
    fig.update_layout(height=max(240, len(pivot.index) * 42), margin=dict(l=8, r=8, t=16, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,.72)", font=dict(color=COLORS["ink"]))
    return fig


def pick_compare_summary(df: pd.DataFrame, metric_col: str) -> pd.DataFrame:
    if df.empty or metric_col not in df.columns:
        return pd.DataFrame()
    work = df.dropna(subset=[metric_col, "track_day"]).copy()
    if work.empty:
        return pd.DataFrame()
    rows = []
    for label, sub in work.sort_values("track_day").groupby("label", sort=False):
        sub = sub.sort_values("track_day")
        day1 = sub[sub["track_day"] == 1]
        gap_days = safe_int(sub["match_gap_days"].iloc[0], 0) if "match_gap_days" in sub.columns else 0
        rows.append(
            {
                "Symbol": label,
                "Base Date": fmt_date(sub["base_event_date"].iloc[0]),
                "Matched Date": fmt_date(sub["perf_event_date"].iloc[0]),
                "Source": sub["compare_source"].iloc[0],
                "Gap TD": gap_days,
                "Gap Flag": gap_severity(gap_days),
                "D+1": day1[metric_col].iloc[0] if not day1.empty else None,
                "Best": sub[metric_col].max(),
                "Latest": sub[metric_col].iloc[-1],
                "Tracked Days": safe_int(sub["track_day"].max(), 0),
            }
        )
    return pd.DataFrame(rows)


def filter_pick_compare_summary(summary: pd.DataFrame, quick_filter: str) -> pd.DataFrame:
    if summary.empty:
        return summary
    work = summary.copy()
    gap_col = pd.to_numeric(work.get("Gap TD"), errors="coerce").fillna(0)
    source_col = work.get("Source", pd.Series("", index=work.index)).astype(str)
    if quick_filter == "Exact Match":
        work = work[gap_col == 0]
    elif quick_filter == "Near Match":
        work = work[(gap_col > 0) & (gap_col < MATCH_GAP_WARN_DAYS)]
    elif quick_filter == "Warning Gap":
        work = work[(gap_col >= MATCH_GAP_WARN_DAYS) & (gap_col < MATCH_GAP_CRITICAL_DAYS)]
    elif quick_filter == "Critical Gap":
        work = work[gap_col >= MATCH_GAP_CRITICAL_DAYS]
    elif quick_filter == "Archive Only":
        work = work[source_col.str.startswith("archive")]
    elif quick_filter == "Live Exact Only":
        work = work[source_col == "live_exact"]
    return work


def sort_pick_compare_summary(summary: pd.DataFrame, sort_by: str, ascending: bool = False) -> pd.DataFrame:
    if summary.empty:
        return summary
    work = summary.copy()
    work["matched_date_sort"] = pd.to_datetime(work.get("Matched Date"), errors="coerce")
    work["base_date_sort"] = pd.to_datetime(work.get("Base Date"), errors="coerce")
    sort_map = {
        "Gap TD": ["Gap TD", "Matched Date", "Symbol"],
        "Matched Date": ["matched_date_sort", "Gap TD", "Symbol"],
        "Base Date": ["base_date_sort", "Gap TD", "Symbol"],
        "D+1": ["D+1", "Best", "Gap TD"],
        "Best": ["Best", "D+1", "Gap TD"],
        "Latest": ["Latest", "Best", "Gap TD"],
        "Tracked Days": ["Tracked Days", "Gap TD", "Symbol"],
        "Symbol": ["Symbol", "Gap TD", "Matched Date"],
    }
    cols = sort_map.get(sort_by, sort_map["Gap TD"])
    asc = [ascending, ascending, ascending]
    work = work.sort_values(cols, ascending=asc, na_position="last")
    return work.drop(columns=["matched_date_sort", "base_date_sort"], errors="ignore")


def style_pick_compare_table(df: pd.DataFrame):
    if df.empty:
        return df
    palette = {
        "good": ("rgba(42,157,143,.18)", COLORS["mint"]),
        "warn": ("rgba(233,196,106,.24)", COLORS["navy"]),
        "bad": ("rgba(231,111,81,.18)", COLORS["coral"]),
        "neutral": ("rgba(20,58,82,.10)", COLORS["navy"]),
        "muted": ("rgba(20,58,82,.06)", "#6B7280"),
    }

    def gap_flag_css(value) -> str:
        bg, fg = palette[compare_tone("Gap", value)]
        return (
            f"background-color: {bg};"
            f"color: {fg};"
            "font-weight: 700;"
            "text-transform: uppercase;"
            "text-align: center;"
        )

    def source_css(value) -> str:
        bg, fg = palette[compare_tone("Source", value)]
        return (
            f"background-color: {bg};"
            f"color: {fg};"
            "font-weight: 700;"
            "text-align: center;"
        )

    styler = df.style
    gap_col = next((col for col in ("Gap Flag", "간격 상태") if col in df.columns), None)
    source_col = next((col for col in ("Source", "비교 소스") if col in df.columns), None)
    if gap_col:
        styler = styler.applymap(gap_flag_css, subset=[gap_col])
    if source_col:
        styler = styler.applymap(source_css, subset=[source_col])
    format_map = {}
    if gap_col:
        format_map[gap_col] = lambda v: pretty_label(GAP_FLAG_LABELS, v)
    if source_col:
        format_map[source_col] = lambda v: pretty_label(COMPARE_SOURCE_LABELS, v)
    for col in ("D+1", "Best", "Latest"):
        if col in df.columns:
            format_map[col] = "{:.2f}"
    for col in ("Gap TD", "Tracked Days"):
        if col in df.columns:
            format_map[col] = "{:.0f}"
    if format_map:
        styler = styler.format(format_map, na_rep="-")
    return styler


logs = load_logs()
if not logs:
    st.warning("스크리닝 로그가 없습니다. 먼저 장 종료 스크리닝을 실행해 주세요.")
    st.stop()
watchlists = load_watchlists()
signals = load_df("buy_signals", ("watchlist_date", "check_date"))
buy_perf = load_df("buy_performance_v2", ("signal_date", "track_date"))
if buy_perf.empty:
    buy_perf = load_df("buy_performance", ("signal_date", "track_date"))
screen_perf = load_df("tracking", ("rec_date", "track_date"))
saved_picks = load_saved_picks()
live_pick_perf = load_live_pick_perf()
notifications = load_notifications()
active_wls, wl_summary = active_watchlists(watchlists)
latest_date = max(logs)
latest_log = logs[latest_date]
source = "saved" if not saved_picks.empty else ("archive" if not signals.empty else "empty")
available_dates = sorted((saved_picks["pick_date"].dropna().dt.strftime("%Y-%m-%d").unique() if source == "saved" else signals["check_date"].dropna().dt.strftime("%Y-%m-%d").unique()), reverse=True) if source != "empty" else []
perf_view = live_pick_perf if not live_pick_perf.empty else buy_perf
perf_mode = "실전 저장 추천" if not live_pick_perf.empty else "백테스트 신호 아카이브"

st.sidebar.title("클로징벨")
st.sidebar.caption("실전 추천과 신호 아카이브")
page = st.sidebar.radio("메뉴", NAV, index=0, format_func=lambda item: PAGE_LABELS.get(item, item))
st.sidebar.markdown("---")
st.sidebar.markdown(f"**최신 스크리닝:** `{latest_date}`")
st.sidebar.markdown(f"**활성 감시목록:** `{len(active_wls)}`")
st.sidebar.markdown(f"**신호 날짜 수:** `{len(available_dates)}`")
st.sidebar.markdown(f"**저장 추천 날짜 수:** `{saved_picks['pick_date'].nunique() if not saved_picks.empty else 0}`")
st.sidebar.markdown(f"**발송 이벤트:** `{len(notifications):,}`")

if page == "Overview":
    d1 = perf_view[perf_view["track_day"] == 1] if not perf_view.empty else pd.DataFrame()
    d3 = perf_view[perf_view["track_day"] == 3] if not perf_view.empty else pd.DataFrame()
    hero("개요", "스크리닝, 감시목록, 매수 추천 성과를 한 화면에서 확인합니다.", [f"최신 로그 {latest_date}", f"활성 감시목록 {len(active_wls)}", f"신호 아카이브 {len(signals)}", perf_mode])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("활성 감시목록", len(active_wls))
    c2.metric("백테스트 신호", f"{len(signals):,}")
    c3.metric("D+1 종가 승률", f"{d1['win'].mean() * 100:.1f}%" if not d1.empty else "-", delta=f"{d1['return_pct'].mean():+.2f}%" if not d1.empty else None)
    c4.metric("D+3 평균 수익", f"{d3['return_pct'].mean():+.2f}%" if not d3.empty else "-", delta=f"{len(live_pick_perf):,} 실전 행" if not live_pick_perf.empty else (f"{len(saved_picks):,} 저장 행" if not saved_picks.empty else "저장 추천 대기"))
    l, r = st.columns([1.15, 1])
    with l:
        kicker("일별 흐름")
        fig = day_profile_chart(perf_view)
        if fig:
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    with r:
        kicker("D+1 추이")
        fig = rolling_chart(perf_view, 20)
        if fig:
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    l2, r2 = st.columns(2)
    with l2:
        kicker("최근 상위 종목")
        top_df = pd.DataFrame(latest_log.get("top", []))
        if not top_df.empty:
            cols = [c for c in ["rank", "name", "sector", "price", "change_rate", "score", "cci", "rsi"] if c in top_df.columns]
            st.dataframe(
                top_df[cols].rename(
                    columns={
                        "rank": "순위",
                        "name": "종목명",
                        "sector": "업종",
                        "price": "현재가",
                        "change_rate": "등락률",
                        "score": "점수",
                        "cci": "CCI",
                        "rsi": "RSI",
                    }
                ),
                width="stretch",
                hide_index=True,
            )
    with r2:
        kicker("확신도 분포")
        counts = signals["conviction"].value_counts() if not signals.empty else pd.Series(dtype=int)
        if not counts.empty:
            fig = go.Figure(go.Bar(x=counts.index.tolist(), y=counts.values.tolist(), marker_color=[grade_color(x) for x in counts.index.tolist()]))
            fig.update_layout(height=320, margin=dict(l=8, r=8, t=16, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,.72)", font=dict(color=COLORS["ink"]))
            fig.update_yaxes(gridcolor="rgba(20,58,82,.08)")
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

elif page == "Pick Vault":
    mode = "저장 추천" if source == "saved" else "백테스트 신호 아카이브"
    hero("추천 보관함", "저장된 추천을 우선 보여주고, 없으면 백테스트 신호 아카이브를 대신 표시합니다.", [mode, f"선택 가능 날짜 {len(available_dates)}", "아카이브 사용 중" if source != "saved" else "저장 추천 사용 중"])
    if source == "empty":
        st.info("추천 데이터가 없습니다.")
    else:
        selected = st.sidebar.selectbox("추천 날짜", available_dates, key="pick_date")
        if source == "saved":
            day_rows = saved_picks[saved_picks["pick_date"].dt.strftime("%Y-%m-%d") == selected].sort_values(["pick_order", "conviction_score"], ascending=[True, False]).copy()
            day_rows = enrich_pick_compare_fields(day_rows, signals)
        else:
            day_rows = signals[(signals["check_date"].dt.strftime("%Y-%m-%d") == selected) & (signals["conviction"].isin(["A", "B"]))].sort_values(["conviction_score", "rank", "days_elapsed"], ascending=[False, True, True]).head(8).copy()
        left, right = st.columns([.95, 1.05])
        with left:
            kicker("당일 추천 카드")
            if source != "saved":
                st.warning("저장된 추천 이력이 없어 신호 아카이브를 대신 표시합니다.")
            render_pick_cards(day_rows, mode)
        with right:
            kicker("상세 차트")
            if day_rows.empty:
                st.info("상세 차트가 없습니다.")
            else:
                labels = day_rows.apply(lambda row: f"{row.get('name', row.get('code', ''))} | #{row.get('rank', '-')} | {row.get('conviction', '-')} | {int(row.get('conviction_score', 0) or 0)}점", axis=1).tolist()
                idx = st.selectbox("상세 종목", range(len(labels)), format_func=lambda i: labels[i], key="detail_idx")
                row = day_rows.iloc[int(idx)]
                fig = price_chart(str(row.get("code", "")), row.get("check_date", row.get("pick_date")), row.get("watchlist_date"))
                if fig:
                    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
                perf_rows = pd.DataFrame()
                key_date = fmt_date(row.get("check_date") or row.get("signal_date") or row.get("pick_date"))
                code = str(row.get("code", "")).zfill(6)
                if source == "saved" and not live_pick_perf.empty:
                    perf_rows = live_pick_perf[(live_pick_perf["pick_date"].dt.strftime("%Y-%m-%d") == key_date) & (live_pick_perf["code"].astype(str).str.zfill(6) == code)].sort_values("track_day").copy()
                elif not buy_perf.empty:
                    perf_rows = buy_perf[(buy_perf["signal_date"].dt.strftime("%Y-%m-%d") == key_date) & (buy_perf["code"].astype(str).str.zfill(6) == code)].sort_values("track_day").copy()
                if not perf_rows.empty:
                    timeline = pick_timeline_chart(perf_rows)
                    if timeline is not None:
                        st.plotly_chart(timeline, width="stretch", config={"displayModeBar": False})
                    perf_rows["Bucket"] = perf_rows["track_day"].apply(lambda x: f"D+{int(x)}")
                    cols = ["Bucket", "track_date", "return_pct"] + [c for c in ("open_ret", "high_ret", "low_ret") if c in perf_rows.columns]
                    st.dataframe(
                        perf_rows[cols].rename(
                            columns={
                                "Bucket": "추적 구간",
                                "track_date": "추적일",
                                "return_pct": "종가 수익률",
                                "open_ret": "시가 수익률",
                                "high_ret": "고가 수익률",
                                "low_ret": "저가 수익률",
                            }
                        ),
                        width="stretch",
                        hide_index=True,
                    )
                elif source == "saved":
                    st.info("장 마감 후 OHLCV 추적이 실행되면 실전 성과가 표시됩니다.")
                if source == "saved" and not notifications.empty:
                    matched = notifications[notifications["ref_date"] == key_date].head(3).copy()
                    if not matched.empty:
                        kicker("발송 스냅샷")
                        for _, event in matched.iterrows():
                            desc = str(event.get("description", "") or event.get("content", "") or "").replace("\n", "<br/>")
                            event_label = pretty_event_type(event.get("event_type", "event"))
                            status_label = pretty_label(STATUS_LABELS, event.get("status", "-"))
                            card_html = (
                                f"<div class='pick'>"
                                f"<h4>{event.get('title', event_label or '발송 이벤트')}</h4>"
                                f"<div class='meta'>{event_label} | {status_label}"
                                f" | {fmt_dt(event.get('sent_at'))}</div>"
                                f"<div class='note'>{desc[:480]}</div>"
                                f"</div>"
                            )
                            st.markdown(card_html, unsafe_allow_html=True)
        kicker("리스크 비교")
        render_pick_compare_cards(day_rows)
        kicker("성과 비교")
        compare_perf = build_pick_compare_perf(day_rows, source, live_pick_perf, buy_perf)
        if compare_perf.empty:
            st.info("선택한 날짜에 연결된 성과 데이터가 아직 없습니다.")
        else:
            source_mix = ", ".join(f"{pretty_label(COMPARE_SOURCE_LABELS, name)} {count}" for name, count in compare_perf["compare_source"].value_counts().items())
            st.caption(f"비교 소스 구성: {source_mix}")
            source_options = compare_perf["compare_source"].dropna().astype(str).value_counts().index.tolist()
            metric_map = [("고가 수익률", "high_ret"), ("종가 수익률", "return_pct"), ("시가 수익률", "open_ret"), ("저가 수익률", "low_ret")]
            f1, f2 = st.columns([1.1, 1.2])
            with f1:
                selected_sources = st.multiselect(
                    "비교 소스",
                    source_options,
                    default=source_options,
                    format_func=lambda x: pretty_label(COMPARE_SOURCE_LABELS, x),
                    key="pick_compare_sources",
                )
            filtered_compare = compare_perf[compare_perf["compare_source"].astype(str).isin(selected_sources)].copy() if selected_sources else compare_perf.iloc[0:0].copy()
            with f2:
                metric_options = [(label, col) for label, col in metric_map if col in filtered_compare.columns and filtered_compare[col].notna().any()]
                if metric_options:
                    metric_labels = [label for label, _ in metric_options]
                    default_idx = next((idx for idx, (_, col) in enumerate(metric_options) if col == "high_ret"), 0)
                    selected_metric_label = st.selectbox("비교 기준", metric_labels, index=default_idx, key="pick_compare_metric")
                    metric_col = dict(metric_options)[selected_metric_label]
                else:
                    metric_col = None
                    st.selectbox("비교 기준", ["사용 가능한 지표 없음"], index=0, key="pick_compare_metric_empty", disabled=True)
            st.caption(f"필터 후 행 수: {len(filtered_compare):,} | 종목 수: {filtered_compare['label'].nunique() if not filtered_compare.empty else 0}")
            if filtered_compare.empty or not metric_col:
                st.info("소스 필터 후 남은 비교 데이터가 없습니다.")
            else:
                preview_summary = pick_compare_summary(filtered_compare, metric_col)
                gap_warn = (
                    preview_summary[preview_summary["Gap TD"] >= MATCH_GAP_WARN_DAYS]
                    .sort_values(["Gap TD", "Symbol"], ascending=[False, True])
                    .copy()
                    if not preview_summary.empty and "Gap TD" in preview_summary.columns
                    else pd.DataFrame()
                )
                if not gap_warn.empty:
                    critical_gap = gap_warn[gap_warn["Gap Flag"] == "critical"].copy()
                    warning_gap = gap_warn[gap_warn["Gap Flag"] == "warning"].copy()
                    worst_gap = int(gap_warn["Gap TD"].max())
                    if not critical_gap.empty:
                        st.error(
                            f"오래된 아카이브 날짜에 연결된 종목이 {len(critical_gap)}개 있습니다. "
                            f"심각 기준은 D+{MATCH_GAP_CRITICAL_DAYS}, 최대 간격은 {worst_gap} 거래일입니다."
                        )
                    if not warning_gap.empty:
                        st.warning(
                            f"이전 날짜 아카이브에 연결된 종목이 {len(warning_gap)}개 있습니다. "
                            f"주의 기준은 D+{MATCH_GAP_WARN_DAYS}부터입니다."
                        )
                    gap_warn_view = gap_warn[["Symbol", "Base Date", "Matched Date", "Gap TD", "Gap Flag", "Source"]].rename(
                        columns={
                            "Symbol": "종목",
                            "Base Date": "기준일",
                            "Matched Date": "매칭일",
                            "Gap TD": "간격 거래일",
                            "Gap Flag": "간격 상태",
                            "Source": "비교 소스",
                        }
                    )
                    st.dataframe(
                        style_pick_compare_table(gap_warn_view),
                        width="stretch",
                        hide_index=True,
                    )
                c1, c2 = st.columns([1.15, .85])
                with c1:
                    fig = pick_compare_chart(filtered_compare, metric_col)
                    if fig is not None:
                        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
                with c2:
                    fig = pick_compare_heatmap(filtered_compare, metric_col)
                    if fig is not None:
                        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
                t1, t2, t3 = st.columns([1.1, .95, .7])
                with t1:
                    summary_quick_filter = st.selectbox(
                        "매칭 필터",
                        ["전체", "완전 일치", "근접 일치", "주의 간격", "심각 간격", "아카이브만", "실전 일치만"],
                        index=0,
                        key="pick_compare_summary_filter",
                    )
                with t2:
                    summary_sort = st.selectbox(
                        "표 정렬",
                        ["간격 거래일", "매칭 날짜", "기준 날짜", "D+1", "최고값", "최근값", "추적 일수", "종목"],
                        index=0,
                        key="pick_compare_summary_sort",
                    )
                with t3:
                    summary_order = st.selectbox(
                        "정렬 방향",
                        ["내림차순", "오름차순"],
                        index=0,
                        key="pick_compare_summary_order",
                    )
                summary_filter_map = {
                    "전체": "All",
                    "완전 일치": "Exact Match",
                    "근접 일치": "Near Match",
                    "주의 간격": "Warning Gap",
                    "심각 간격": "Critical Gap",
                    "아카이브만": "Archive Only",
                    "실전 일치만": "Live Exact Only",
                }
                summary_sort_map = {
                    "간격 거래일": "Gap TD",
                    "매칭 날짜": "Matched Date",
                    "기준 날짜": "Base Date",
                    "D+1": "D+1",
                    "최고값": "Best",
                    "최근값": "Latest",
                    "추적 일수": "Tracked Days",
                    "종목": "Symbol",
                }
                summary_df = filter_pick_compare_summary(preview_summary, summary_filter_map[summary_quick_filter])
                summary_df = sort_pick_compare_summary(summary_df, summary_sort_map[summary_sort], ascending=(summary_order == "오름차순"))
                st.caption(f"표 행 수: {len(summary_df):,}")
                if not summary_df.empty:
                    summary_view = summary_df.rename(
                        columns={
                            "Symbol": "종목",
                            "Base Date": "기준일",
                            "Matched Date": "매칭일",
                            "Source": "비교 소스",
                            "Gap TD": "간격 거래일",
                            "Gap Flag": "간격 상태",
                            "Tracked Days": "추적 일수",
                            "Best": "최고값",
                            "Latest": "최근값",
                        }
                    )
                    st.dataframe(style_pick_compare_table(summary_view), width="stretch", hide_index=True)
                else:
                    st.info("표 필터 후 남은 비교 데이터가 없습니다.")
        kicker("이력 표")
        if not day_rows.empty:
            date_col = "pick_date" if source == "saved" else "check_date"
            day_rows[date_col] = day_rows[date_col].apply(fmt_date)
            cols = [c for c in [date_col, "name", "code", "rank", "conviction", "conviction_score", "days_elapsed", "signal_type", "dart_risk", "news_risk", "ai_action", "ai_risk", "broker_signal", "current_price", "buy_price"] if c in day_rows.columns]
            st.dataframe(day_rows[cols].rename(columns={date_col: "날짜", "name": "종목명", "code": "코드", "rank": "순위", "conviction": "등급", "conviction_score": "확신 점수", "days_elapsed": "경과 D+", "signal_type": "신호", "dart_risk": "DART", "news_risk": "뉴스", "ai_action": "AI", "ai_risk": "AI 위험", "broker_signal": "수급", "current_price": "현재가", "buy_price": "기준가"}), width="stretch", hide_index=True)

elif page == "Dispatch Log":
    hero("발송 기록", "디스코드 웹훅 발송 이력과 실제 전송 내용을 확인합니다.", [f"이벤트 {len(notifications):,}", "SQLite 저장", "성공 / 실패 / 비활성"])
    if notifications.empty:
        st.info("발송 이력이 아직 없습니다.")
    else:
        show = notifications.copy()
        event_options = sorted(show["event_type"].dropna().astype(str).unique().tolist()) if "event_type" in show.columns else []
        status_options = sorted(show["status"].dropna().astype(str).unique().tolist()) if "status" in show.columns else []
        ref_date_options = (
            sorted(
                [
                    value
                    for value in show["ref_date"].dropna().astype(str).unique().tolist()
                    if value and value != "nan"
                ],
                reverse=True,
            )
            if "ref_date" in show.columns
            else []
        )
        if "ref_date" in show.columns and show["ref_date"].isna().any():
            ref_date_options = ["unassigned"] + ref_date_options
        http_code_options = (
            sorted(pd.to_numeric(show["response_code"], errors="coerce").dropna().astype(int).unique().tolist())
            if "response_code" in show.columns
            else []
        )
        sent_days = show["sent_at"].dropna().dt.date if "sent_at" in show.columns else pd.Series(dtype="object")

        f1, f2, f3, f4 = st.columns([1.05, .95, .85, .95])
        with f1:
            selected_events = st.multiselect("이벤트 유형", event_options, default=event_options, format_func=pretty_event_type, key="dispatch_event_types")
        with f2:
            selected_status = st.multiselect("상태", status_options, default=status_options, format_func=lambda x: pretty_label(STATUS_LABELS, x), key="dispatch_statuses")
        with f3:
            http_filter = st.selectbox(
                "응답 코드 필터",
                ["All", "2xx", "3xx", "4xx", "5xx", "No HTTP", "Specific"],
                index=0,
                format_func=lambda x: {"All": "전체", "No HTTP": "응답 코드 없음", "Specific": "직접 선택"}.get(x, x),
                key="dispatch_http_filter",
            )
        with f4:
            search_text = st.text_input("검색", value="", placeholder="제목 / 설명 / 날짜", key="dispatch_search").strip().lower()

        selected_ref_date = "All"
        if ref_date_options:
            selected_ref_date = st.selectbox(
                "기준일 이동",
                ["All"] + ref_date_options,
                index=0,
                format_func=lambda x: "전체" if x == "All" else pretty_ref_date(x),
                key="dispatch_ref_date",
            )

        selected_http_codes = []
        if http_filter == "Specific":
            selected_http_codes = st.multiselect(
                "응답 코드",
                http_code_options,
                default=http_code_options,
                key="dispatch_http_codes",
            )

        if not sent_days.empty:
            default_range = (sent_days.min(), sent_days.max())
            selected_range = st.date_input(
                "발송 날짜 범위",
                value=default_range,
                min_value=default_range[0],
                max_value=default_range[1],
                key="dispatch_date_range",
            )
            if isinstance(selected_range, tuple) and len(selected_range) == 2:
                start_day, end_day = selected_range
            else:
                start_day = end_day = selected_range
            show = show[show["sent_at"].notna()]
            show = show[
                (show["sent_at"].dt.date >= start_day) &
                (show["sent_at"].dt.date <= end_day)
            ]

        render_dispatch_combo_banner(selected_events, event_options, selected_ref_date)

        if status_options:
            if selected_status:
                show = show[show["status"].astype(str).isin(selected_status)]
            else:
                show = show.iloc[0:0]
        if "response_code" in show.columns:
            http_codes = pd.to_numeric(show["response_code"], errors="coerce")
            if http_filter == "2xx":
                show = show[(http_codes >= 200) & (http_codes < 300)]
            elif http_filter == "3xx":
                show = show[(http_codes >= 300) & (http_codes < 400)]
            elif http_filter == "4xx":
                show = show[(http_codes >= 400) & (http_codes < 500)]
            elif http_filter == "5xx":
                show = show[(http_codes >= 500) & (http_codes < 600)]
            elif http_filter == "No HTTP":
                show = show[http_codes.isna()]
            elif http_filter == "Specific":
                if selected_http_codes:
                    show = show[http_codes.isin(selected_http_codes)]
                else:
                    show = show.iloc[0:0]
        if search_text:
            haystack = (
                show["event_type"].fillna("").astype(str) + " " +
                show["ref_date"].fillna("").astype(str) + " " +
                show["status"].fillna("").astype(str) + " " +
                show["title"].fillna("").astype(str) + " " +
                show["description"].fillna("").astype(str) + " " +
                show["content"].fillna("").astype(str)
            ).str.lower()
            show = show[haystack.str.contains(search_text, na=False)]

        summary_source = show.copy()

        if event_options:
            if selected_events:
                show = show[show["event_type"].astype(str).isin(selected_events)]
            else:
                show = show.iloc[0:0]
        if selected_ref_date != "All" and "ref_date" in show.columns:
            if selected_ref_date == "unassigned":
                show = show[show["ref_date"].isna() | show["ref_date"].astype(str).isin(["", "nan", "None"])]
            else:
                show = show[show["ref_date"].astype(str) == selected_ref_date]

        sent_count = int((show["status"] == "sent").sum()) if "status" in show.columns else 0
        failed_count = int((show["status"] == "failed").sum()) if "status" in show.columns else 0
        disabled_count = int((show["status"] == "disabled").sum()) if "status" in show.columns else 0
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("필터된 이벤트", f"{len(show):,}")
        m2.metric("성공", sent_count)
        m3.metric("실패", failed_count)
        m4.metric("비활성", disabled_count)

        if not summary_source.empty:
            kicker("이벤트 요약")
            combo_summary = dispatch_combo_summary(summary_source)
            s1, s2, s3 = st.columns([1.1, .8, .75])
            with s1:
                summary_sort = st.selectbox(
                    "요약 정렬",
                    ["최신 기준일", "최근 발송", "이벤트 수", "실패 수", "성공률", "성공 수"],
                    index=0,
                    key="dispatch_summary_sort",
                )
            with s2:
                summary_order = st.selectbox(
                    "정렬 방향",
                    ["내림차순", "오름차순"],
                    index=0,
                    key="dispatch_summary_order",
                )
            with s3:
                summary_limit = st.selectbox(
                    "카드 수",
                    [3, 6, 9, 12, 18],
                    index=2,
                    key="dispatch_summary_limit",
                )
            summary_sort_map = {
                "최신 기준일": "Newest Ref Date",
                "최근 발송": "Latest Sent",
                "이벤트 수": "Total Events",
                "실패 수": "Failed",
                "성공률": "Success Rate",
                "성공 수": "Sent",
            }
            combo_summary = sort_dispatch_combo_summary(combo_summary, summary_sort_map[summary_sort], ascending=(summary_order == "오름차순"))
            st.caption(
                f"조합 수: {len(combo_summary):,}. "
                "요약은 상태, 응답 코드, 검색, 날짜 필터를 반영하며 현재 조합은 맨 위에 고정됩니다."
            )
            render_dispatch_combo_cards(
                combo_summary,
                limit=summary_limit,
                selected_events=selected_events,
                selected_ref_date=selected_ref_date,
            )
        else:
            st.info("현재 비조합 필터에 맞는 이벤트가 없습니다.")

        if show.empty:
            st.info("선택한 조합 필터에 맞는 이벤트가 없습니다.")
        else:
            left, right = st.columns([.88, 1.12])
            with left:
                kicker("최근 이벤트")
                table_rows = show.copy()
                table_rows["sent_at"] = table_rows["sent_at"].apply(fmt_dt)
                if "event_type" in table_rows.columns:
                    table_rows["event_type"] = table_rows["event_type"].apply(pretty_event_type)
                if "ref_date" in table_rows.columns:
                    table_rows["ref_date"] = table_rows["ref_date"].apply(pretty_ref_date)
                if "status" in table_rows.columns:
                    table_rows["status"] = table_rows["status"].apply(lambda x: pretty_label(STATUS_LABELS, x))
                cols = [c for c in ["sent_at", "event_type", "ref_date", "status", "response_code", "embed_count", "title"] if c in table_rows.columns]
                st.dataframe(table_rows[cols].rename(columns={"sent_at": "발송 시각", "event_type": "이벤트", "ref_date": "기준일", "status": "상태", "response_code": "응답 코드", "embed_count": "임베드 수", "title": "제목"}), width="stretch", hide_index=True)
            with right:
                kicker("이벤트 상세")
                labels = show.apply(lambda row: f"{fmt_dt(row.get('sent_at'))} | {pretty_event_type(row.get('event_type', 'event'))} | {pretty_label(STATUS_LABELS, row.get('status', '-'))}", axis=1).tolist()
                idx = st.selectbox("발송 이벤트", range(len(labels)), format_func=lambda i: labels[i], key="dispatch_event")
                event = show.iloc[int(idx)]
                payload = event.get("payload", {}) or {}
                embeds = payload.get("embeds", []) or []
                st.markdown(f"**상태:** `{pretty_label(STATUS_LABELS, event.get('status', '-'))}`")
                st.markdown(f"**이벤트 유형:** `{pretty_event_type(event.get('event_type', '-'))}`")
                st.markdown(f"**기준일:** `{pretty_ref_date(event.get('ref_date', '-'))}`")
                st.markdown(f"**응답 코드:** `{event.get('response_code', '-')}`")
                if payload.get("content"):
                    st.code(payload.get("content", ""), language="markdown")
                for embed in embeds[:5]:
                    title = embed.get("title", "임베드")
                    desc = embed.get("description", "")
                    st.markdown(f"### {title}")
                    if desc:
                        st.markdown(desc)
                    fields = embed.get("fields", []) or []
                    if fields:
                        field_rows = [{"항목": f.get("name", ""), "값": f.get("value", ""), "인라인": f.get("inline", False)} for f in fields]
                        st.dataframe(pd.DataFrame(field_rows), width="stretch", hide_index=True)

elif page == "Watchlist Lab":
    avg_text = f"평균 종목 수 {wl_summary['stock_count'].mean():.1f}" if not wl_summary.empty else "평균 종목 수 -"
    hero("감시 목록", "감시목록의 진행 상태, 종목 수, 트리거 여부를 확인합니다.", [f"전체 감시목록 {len(watchlists)}", f"활성 {len(active_wls)}", avg_text])
    if wl_summary.empty:
        st.info("감시목록이 없습니다.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("활성", int((wl_summary["status"] == "active").sum()))
        c2.metric("만료", int((wl_summary["status"] == "expired").sum()))
        c3.metric("트리거", int(wl_summary["triggered_count"].sum()))
        c4.metric("평균 기간", f"{wl_summary['days_elapsed'].mean():.1f}일")
        kicker("진행 현황")
        lifecycle_fig = watchlist_lifecycle_chart(wl_summary)
        if lifecycle_fig:
            st.plotly_chart(lifecycle_fig, width="stretch", config={"displayModeBar": False})
        l, r = st.columns([.92, 1.08])
        with l:
            kicker("목록 요약")
            show = wl_summary.sort_values("created", ascending=False).head(40).copy()
            if "status" in show.columns:
                show["status"] = show["status"].apply(lambda x: pretty_label(WATCHLIST_STATUS_LABELS, x))
            show = show.rename(columns={"created": "생성일", "expires": "만료일", "days_elapsed": "경과일", "stock_count": "종목 수", "triggered_count": "트리거 수", "status": "상태"})
            st.dataframe(show, width="stretch", hide_index=True)
        with r:
            kicker("상세 보기")
            dates = [wl.get("created", "") for wl in watchlists if wl.get("created")]
            selected = st.selectbox("감시목록 날짜", dates, key="wl_date")
            payload = next((wl for wl in watchlists if wl.get("created") == selected), None)
            if payload:
                sdf = pd.DataFrame(payload.get("stocks", []))
                if not sdf.empty:
                    kicker("종목 카드")
                    render_watchlist_stock_cards(sdf)
                    cols = [c for c in ["rank", "name", "score", "entry_price", "sweet_spot_day", "window_start", "window_end", "triggered", "trigger_date", "conviction"] if c in sdf.columns]
                    st.dataframe(sdf[cols].rename(columns={"rank": "순위", "name": "종목명", "score": "스크리닝 점수", "entry_price": "기준가", "sweet_spot_day": "스위트스팟", "window_start": "시작", "window_end": "종료", "triggered": "트리거", "trigger_date": "트리거 날짜", "conviction": "등급"}), width="stretch", hide_index=True)
                    kicker("종목 타임라인")
                    timeline_fig = watchlist_stock_timeline(payload)
                    if timeline_fig:
                        st.plotly_chart(timeline_fig, width="stretch", config={"displayModeBar": False})

elif page == "Performance Lab":
    perf_text = f"{perf_mode} 행 {len(perf_view):,}" if not perf_view.empty else f"{perf_mode} 행 0"
    screen_text = f"스크리닝 행 {len(screen_perf):,}" if not screen_perf.empty else "스크리닝 행 0"
    hero("성과 분석", "실전 저장 추천 성과를 우선 보여주고, 없으면 백테스트를 기준으로 표시합니다.", [perf_text, screen_text, "D+1 ~ D+5 시가/종가/고가"])
    if perf_view.empty:
        st.info("매수 신호 성과 데이터가 없습니다.")
    else:
        d1 = perf_view[perf_view["track_day"] == 1]
        d3 = perf_view[perf_view["track_day"] == 3]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("D+1 종가 승률", f"{d1['win'].mean() * 100:.1f}%")
        c2.metric("D+1 시가 평균", fmt_pct(d1["open_ret"].mean()) if "open_ret" in d1.columns else "-")
        c3.metric("D+1 고가 평균", fmt_pct(d1["high_ret"].mean()) if "high_ret" in d1.columns else "-")
        c4.metric("D+3 종가 평균", fmt_pct(d3["return_pct"].mean()) if not d3.empty else "-")
        l, r = st.columns([1.05, .95])
        with l:
            kicker("일자별 프로필")
            fig = day_profile_chart(perf_view)
            if fig:
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        with r:
            kicker("순위 히트맵")
            fig = heatmap(perf_view)
            if fig:
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        l2, r2 = st.columns([1.05, .95])
        with l2:
            kicker("D+1 추이")
            fig = rolling_chart(perf_view, 20)
            if fig:
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        with r2:
            kicker("스크리닝 참고")
            fig = day_profile_chart(screen_perf, "스크리닝", COLORS["gold"], COLORS["navy"])
            if fig:
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        kicker("확신도 산점도")
        scatter_base = saved_picks if not live_pick_perf.empty and not saved_picks.empty else signals
        fig = conviction_scatter(scatter_base, perf_view)
        if fig:
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

elif page == "Screening Log":
    hero("스크리닝 로그", "날짜별 시장 상태와 점수 결과를 확인합니다. 로그는 SQLite를 우선 사용합니다.", [f"최신 {latest_date}", f"유니버스 {latest_log.get('universe_count', 0)}", f"상위 종목 {len(latest_log.get('top', []))}"])
    selected = st.sidebar.selectbox("로그 날짜", sorted(logs.keys(), reverse=True), key="screen_log")
    payload = logs[selected]
    market = payload.get("market", {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("코스피", f"{market.get('kospi', 0):,.0f}", delta=f"{market.get('kospi_change', 0):+.2f}%")
    c2.metric("코스닥", f"{market.get('kosdaq', 0):,.0f}", delta=f"{market.get('kosdaq_change', 0):+.2f}%")
    c3.metric("나스닥", f"{market.get('nasdaq', 0):,.0f}", delta=f"{market.get('nasdaq_change', 0):+.2f}%")
    c4.metric("유니버스", f"{payload.get('universe_count', 0)}", delta=f"과열 {payload.get('overheat_count', 0)}")
    if payload.get("skipped"):
        st.warning(payload.get("reason", "건너뛴 로그입니다."))
    else:
        l, r = st.columns([.94, 1.06])
        with l:
            kicker("상위 종목")
            for _, row in pd.DataFrame(payload.get("top", [])).iterrows():
                sector = compact_text(row.get("sector", "업종 미확인"), 24, "업종 미확인")
                score = safe_int(row.get("score", 0), 0)
                price = safe_int(row.get("price", 0), 0)
                change_rate = row.get("change_rate", 0)
                cci = row.get("cci", 0)
                rsi = row.get("rsi", 0)
                ma20_gap = row.get("ma20_gap", 0)
                vol_ratio = row.get("vol_ratio", 0)
                ai_action = row.get("ai_action", "미확인")
                dart_risk = row.get("dart_risk", "미확인")
                vp_tag = row.get("vp_tag", "미확인")
                overheat_text = "과열" if row.get("overheat") else "정상"
                chips = (
                    f"{compare_chip_html('업종', sector)}"
                    f"{compare_chip_html('등락률', fmt_pct(change_rate))}"
                    f"{compare_chip_html('DART', dart_risk)}"
                    f"{compare_chip_html('AI', ai_action)}"
                    f"{compare_chip_html('거래대금', vp_tag)}"
                    f"{compare_chip_html('과열', overheat_text)}"
                )
                note_lines = [
                    f"CCI {cci:.0f} · RSI {rsi:.0f} · MA20 괴리 {ma20_gap:+.1f}%",
                    f"거래량 배수 {vol_ratio:.1f}x · 점수 {score}",
                ]
                if not is_blank(row.get("dart_note")):
                    note_lines.append(f"DART 메모: {html.escape(compact_text(row.get('dart_note'), 120))}")
                if not is_blank(row.get("ai_summary")):
                    note_lines.append(f"AI 요약: {html.escape(compact_text(row.get('ai_summary'), 120))}")
                card = (
                    f"<div class='pick'>"
                    f"<h4>#{int(row.get('rank', 0))} {html.escape(str(row.get('name', row.get('code', ''))))}</h4>"
                    f"<div class='meta'>현재가 {price:,} | 점수 {score} | 등락률 {fmt_pct(change_rate)}</div>"
                    f"<div class='chips'>{chips}</div>"
                    f"<div class='note'>{'<br/>'.join(note_lines)}</div>"
                    f"</div>"
                )
                st.markdown(card, unsafe_allow_html=True)
        with r:
            kicker("유니버스 표")
            udf = pd.DataFrame(payload.get("all_scored", []))
            if not udf.empty:
                cols = [c for c in ["rank", "name", "sector", "price", "change_rate", "score", "cci", "rsi", "ma20_gap", "vol_ratio", "vp_tag", "dart_risk", "ai_action"] if c in udf.columns]
                st.dataframe(
                    udf[cols].rename(
                        columns={
                            "rank": "순위",
                            "name": "종목명",
                            "sector": "업종",
                            "price": "현재가",
                            "change_rate": "등락률",
                            "score": "점수",
                            "cci": "CCI",
                            "rsi": "RSI",
                            "ma20_gap": "MA20 괴리",
                            "vol_ratio": "거래량 배수",
                            "vp_tag": "거래대금 신호",
                            "dart_risk": "DART",
                            "ai_action": "AI",
                        }
                    ),
                    width="stretch",
                    hide_index=True,
                )

elif page == "Theme Radar":
    hero("테마 레이더", "날짜별 테마 스냅샷과 관련 종목을 확인합니다.", [f"테마 날짜 수 {len(logs)}", "테마 요약 기준"])
    selected = st.sidebar.selectbox("테마 날짜", sorted(logs.keys(), reverse=True), key="theme_date")
    themes = logs[selected].get("theme_summary", [])
    if not themes:
        st.info("선택한 날짜의 테마 데이터가 없습니다.")
    else:
        df = pd.DataFrame(themes)
        avg_change = pd.to_numeric(df.get("change_rate"), errors="coerce").mean() if "change_rate" in df.columns else None
        rising_theme_count = int((pd.to_numeric(df.get("change_rate"), errors="coerce") > 0).sum()) if "change_rate" in df.columns else 0
        avg_stock_count = pd.to_numeric(df.get("stock_count"), errors="coerce").mean() if "stock_count" in df.columns else None
        leader = df.sort_values(["change_rate", "period_return"], ascending=[False, False], na_position="last").iloc[0] if not df.empty else None
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("상승 테마", rising_theme_count)
        t2.metric("평균 등락률", fmt_pct(avg_change) if avg_change == avg_change else "-")
        t3.metric("대표 테마", str(leader.get("name", "-")) if leader is not None else "-", delta=fmt_pct(leader.get("change_rate")) if leader is not None else None)
        t4.metric("평균 편입 종목", f"{avg_stock_count:.1f}개" if avg_stock_count == avg_stock_count else "-")
        l, r = st.columns([1.05, .95])
        with l:
            kicker("테마 카드")
            theme_rows = list(df.sort_values(["change_rate", "period_return"], ascending=[False, False], na_position="last").iterrows())
            for start in range(0, len(theme_rows), 2):
                cols = st.columns(2)
                for col, (_, row) in zip(cols, theme_rows[start : start + 2]):
                    name = html.escape(str(row.get("name", row.get("code", "테마"))))
                    change_rate = row.get("change_rate", 0)
                    period_return = row.get("period_return", 0)
                    stock_count = safe_int(row.get("stock_count", 0), 0)
                    rising_count = safe_int(row.get("rising_count", 0), 0)
                    falling_count = safe_int(row.get("falling_count", 0), 0)
                    main_stock = compact_text(row.get("main_stock", "대장주 미확인"), 48, "대장주 미확인")
                    if rising_count > falling_count:
                        breadth_text = "강세"
                    elif rising_count < falling_count:
                        breadth_text = "약세"
                    else:
                        breadth_text = "혼조"
                    chips = (
                        f"{compare_chip_html('등락률', fmt_pct(change_rate))}"
                        f"{compare_chip_html('기간 수익', fmt_pct(period_return))}"
                        f"{compare_chip_html('테마 강도', breadth_text)}"
                        f"{compare_chip_html('편입 종목', stock_count)}"
                    )
                    note_lines = [
                        f"상승 {rising_count}개 · 하락 {falling_count}개",
                        f"대장주 {html.escape(main_stock)}",
                    ]
                    card = (
                        f"<div class='pick'>"
                        f"<h4>{name}</h4>"
                        f"<div class='meta'>테마 코드 {html.escape(str(row.get('code', '-')))} | 편입 {stock_count}개 | 등락률 {fmt_pct(change_rate)}</div>"
                    f"<div class='chips'>{chips}</div>"
                    f"<div class='note'>{'<br/>'.join(note_lines)}</div>"
                    f"</div>"
                )
                    with col:
                        st.markdown(card, unsafe_allow_html=True)
            kicker("테마 표")
            cols = [c for c in ["name", "change_rate", "period_return", "stock_count", "rising_count", "falling_count", "main_stock"] if c in df.columns]
            st.dataframe(
                df[cols].rename(
                    columns={
                        "name": "테마명",
                        "change_rate": "등락률",
                        "period_return": "기간 수익",
                        "stock_count": "종목 수",
                        "rising_count": "상승 종목",
                        "falling_count": "하락 종목",
                        "main_stock": "대장주",
                    }
                ),
                width="stretch",
                hide_index=True,
            )
        with r:
            kicker("테마 모멘텀")
            changes = df["change_rate"] if "change_rate" in df.columns else pd.Series([0] * len(df))
            names = df["name"] if "name" in df.columns else pd.Series([""] * len(df))
            fig = go.Figure(go.Bar(x=changes, y=names, orientation="h", marker_color=[COLORS["coral"] if x >= 0 else COLORS["teal"] for x in changes]))
            fig.update_layout(height=360, margin=dict(l=8, r=8, t=16, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,.72)", font=dict(color=COLORS["ink"]))
            fig.update_xaxes(title="등락률(%)", gridcolor="rgba(20,58,82,.08)")
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

st.sidebar.markdown("---")
st.sidebar.caption("대시보드는 런타임 SQLite 기준으로 갱신됩니다.")


