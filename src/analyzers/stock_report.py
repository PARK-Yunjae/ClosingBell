"""
종목 심층 분석 리포트 생성 (v9.1)
한글 전용, 쉬운 설명 중심.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime
import os
from pathlib import Path
from typing import List, Optional, Tuple
import pandas as pd
from src.config.app_config import OHLCV_FULL_DIR, OHLCV_DIR
from src.config.backfill_config import get_backfill_config
from src.domain.models import DailyPrice, StockData
from src.domain.score_calculator import ScoreCalculatorV5
from src.services.backfill.data_loader import load_single_ohlcv
from src.services.account_service import get_holdings_watchlist
from src.services.dart_service import get_dart_service
from src.analyzers.volume_profile import analyze_volume_profile, VolumeProfileSummary
from src.analyzers.technical_analyzer import analyze_technical
from src.analyzers.broker_tracker import analyze_broker_flow
from src.analyzers.news_timeline import analyze_news_timeline
from src.analyzers.entry_exit_calculator import calculate_entry_exit

# ── 상수 정의 (하드코딩 제거) ──
CCI_OVERBOUGHT_EXTREME = 200
CCI_OVERBOUGHT = 100
CCI_OVERSOLD = -100
CCI_OVERSOLD_EXTREME = -200

RSI_OVERBOUGHT_EXTREME = 80
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
RSI_OVERSOLD_EXTREME = 20

GRADE_S = 85
GRADE_A = 75
GRADE_B_PLUS = 65
GRADE_B = 55
GRADE_C_PLUS = 45
GRADE_C = 35

@dataclass
class StockReportResult:
    lines: List[str]
    summary: str


def _resolve_ohlcv_path(code: str) -> Optional[Path]:
    bases: List[Path] = []
    for base in [OHLCV_FULL_DIR, OHLCV_DIR]:
        if base and base not in bases:
            bases.append(base)
    try:
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


def _load_ohlcv_df(code: str) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    path = _resolve_ohlcv_path(code)
    if path:
        df = load_single_ohlcv(path)
        if df is not None and not df.empty:
            return df, str(path)
    try:
        import FinanceDataReader as fdr
        end = datetime.now().date()
        start = end - pd.Timedelta(days=365 * 2)
        df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if df is not None and not df.empty:
            df = df.reset_index()
            df.columns = [c.lower() for c in df.columns]
            if "date" not in df.columns and "index" in df.columns:
                df = df.rename(columns={"index": "date"})
            return df, "FDR"
    except Exception:
        pass
    return None, None


def _to_daily_prices(df: pd.DataFrame) -> List[DailyPrice]:
    prices: List[DailyPrice] = []
    for _, row in df.iterrows():
        prices.append(DailyPrice(
            date=row["date"].date(), open=int(row["open"]),
            high=int(row["high"]), low=int(row["low"]),
            close=int(row["close"]), volume=int(row["volume"]),
            trading_value=float(row.get("trading_value", 0.0)),
        ))
    return prices


def _calc_tv(last_row: pd.Series) -> float:
    tv = float(last_row.get("trading_value", 0.0))
    return tv if tv > 0 else (float(last_row["close"]) * float(last_row["volume"])) / 1e8


def _get_holding(code: str) -> Optional[dict]:
    try:
        for row in get_holdings_watchlist():
            if row.get("stock_code") == code:
                return row
    except Exception:
        pass
    return None


def _fmt_src(p: Optional[str]) -> str:
    if not p: return "없음"
    if p.upper() == "FDR": return "온라인(FDR)"
    try: return f"로컬({Path(p).name})"
    except Exception: return str(p)


# ── 해석 헬퍼 ──

def _cci_text(v):
    if v is None: return "데이터 없음"
    if v >= CCI_OVERBOUGHT_EXTREME: return "매우 과열 (고점 주의)"
    if v >= CCI_OVERBOUGHT: return "과열 경향"
    if v >= 50: return "약간 높음 (양호)"
    if v >= -50: return "보통 (안정적)"
    if v >= CCI_OVERSOLD: return "약간 낮음 (관망)"
    if v >= CCI_OVERSOLD_EXTREME: return "과냉각 (반등 가능)"
    return "매우 과냉각 (바닥 근처)"

def _rsi_text(v):
    if v is None: return "데이터 없음"
    if v >= RSI_OVERBOUGHT_EXTREME: return "매우 과열 (조정 가능)"
    if v >= RSI_OVERBOUGHT: return "과열"
    if v >= 55: return "약간 강세 (적당)"
    if v >= 45: return "중립"
    if v >= RSI_OVERSOLD: return "약세"
    if v >= RSI_OVERSOLD_EXTREME: return "과냉각 (반등 기대)"
    return "매우 과냉각"

def _change_word(pct):
    if pct is None: return "정보 없음"
    if pct >= 15: return "급등"
    if pct >= 5:  return "강한 상승"
    if pct >= 1:  return "소폭 상승"
    if pct >= -1: return "보합"
    if pct >= -5: return "소폭 하락"
    if pct >= -15: return "강한 하락"
    return "급락"

def _sig(level): return {"good":"🟢","neutral":"🟡","warning":"🔴"}.get(level,"⚪")
def _chg_sig(p): return "good" if p and p>=1 else ("warning" if p and p<=-1 else "neutral")
def _cci_sig(v): return "good" if v is not None and CCI_OVERSOLD<=v<=CCI_OVERBOUGHT and v>=0 else ("warning" if v is not None and (v>CCI_OVERBOUGHT or v<CCI_OVERSOLD) else "neutral")
def _rsi_sig(v): return "good" if v is not None and RSI_OVERSOLD<=v<=RSI_OVERBOUGHT else ("warning" if v is not None and (v>RSI_OVERBOUGHT or v<RSI_OVERSOLD) else "neutral")
def _vp_sig(t):  return "good" if "상승" in t else ("warning" if "저항" in t else "neutral")
def _bk_sig(t):  return "good" if t in ("정상","") else ("warning" if "주의" in t or "이상" in t else "neutral")

def _grade(s):
    if s>=GRADE_S: return "A+"
    if s>=GRADE_A: return "A"
    if s>=GRADE_B_PLUS: return "B+"
    if s>=GRADE_B: return "B"
    if s>=GRADE_C_PLUS: return "C+"
    if s>=GRADE_C: return "C"
    return "D"

def _ma_align(ma5, ma20, ma60, ma120, cur):
    vals = [v for v in [ma5, ma20, ma60, ma120] if v is not None]
    if len(vals) < 2: return "데이터 부족"
    if all(vals[i] >= vals[i+1] for i in range(len(vals)-1)):
        return "정배열 (단기 > 장기, 상승 추세)"
    if all(vals[i] <= vals[i+1] for i in range(len(vals)-1)):
        return "역배열 (단기 < 장기, 하락 추세)"
    return "혼조세 (추세 전환 중일 수 있음)"


DISC_EXPLAIN = {
    "대량보유상황보고서": "큰 주주의 지분이 변했어요",
    "임원": "회사 임원이 주식을 사거나 팔았어요",
    "주요주주": "주요 주주의 보유 현황이 변했어요",
    "최대주주": "최대주주 지분 변동 (중요!)",
    "주권관련사채권": "전환사채(CB) 관련 — 주식수 늘어날 수 있음",
    "유상증자": "새 주식 발행 — 기존 주주 불리할 수 있음",
    "무상증자": "무상 주식 배분 — 보통 호재",
    "자기주식취득": "회사가 자사주 매입 — 보통 호재",
    "자기주식처분": "자사주 매도 — 물량 부담",
    "감사보고서": "회계감사 결과 — '적정' 아니면 주의",
    "거래정지": "거래 정지 중 — 재개 조건 확인",
}

def _disc_explain(title):
    for k, v in DISC_EXPLAIN.items():
        if k in title: return v
    return ""


# ── AI 요약 ──
def _ai_summary(text: str) -> Optional[str]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key: return None
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=f"""투자 리서치 요약가로서 아래 리포트를 쉬운 한국어로 요약하세요.
전문 용어는 괄호로 설명. 과장 금지. 15줄 이내.
형식: 1)한줄요약 2)좋은점 3개 3)위험 3개 4)관찰포인트 3개

리포트:
{text[:6000]}""",
            config={"max_output_tokens": 700, "temperature": 0.2},
        )
        return getattr(resp, "text", None)
    except Exception:
        return None


# ────── 추가 분석 함수 (v9.1) ──────

def _calc_period_returns(df: pd.DataFrame, close: float) -> dict:
    """기간별 수익률: 1주/1개월/3개월/6개월/1년"""
    result = {}
    if df is None or df.empty or close is None or close <= 0:
        return result
    df = df.sort_values("date").reset_index(drop=True)
    periods = [("1주", 5), ("1개월", 20), ("3개월", 60), ("6개월", 120), ("1년", 240)]
    for label, days in periods:
        if len(df) > days:
            past = float(df.iloc[-(days + 1)]["close"])
            if past > 0:
                result[label] = (close - past) / past * 100
    return result


def _calc_52week(df: pd.DataFrame, close: float) -> dict:
    """52주 고저 대비 위치"""
    if df is None or df.empty or close is None:
        return {}
    df = df.sort_values("date").reset_index(drop=True)
    recent = df.tail(240) if len(df) >= 240 else df
    h52 = float(recent["high"].max())
    l52 = float(recent["low"].min())
    if h52 <= l52:
        return {"high": h52, "low": l52, "pct": 50.0}
    pct = (close - l52) / (h52 - l52) * 100
    return {"high": h52, "low": l52, "pct": pct}


def _calc_volume_trend(df: pd.DataFrame) -> dict:
    """거래량 추세: 5일/20일 평균, 급증일 감지"""
    if df is None or df.empty or len(df) < 20:
        return {}
    df = df.sort_values("date").reset_index(drop=True)
    vol = df["volume"].astype(float)
    today_vol = float(vol.iloc[-1])
    avg5 = float(vol.tail(5).mean())
    avg20 = float(vol.tail(20).mean())
    avg60 = float(vol.tail(60).mean()) if len(df) >= 60 else avg20

    ratio_5 = today_vol / avg5 if avg5 > 0 else 0
    ratio_20 = today_vol / avg20 if avg20 > 0 else 0

    # 최근 10일 중 거래량 급증일 (20일 평균의 2배 이상)
    surge_days = 0
    if len(df) >= 30:
        recent10 = df.tail(10)
        for _, row in recent10.iterrows():
            if float(row["volume"]) >= avg20 * 2:
                surge_days += 1

    # 거래량 추세 (5일 평균 vs 20일 평균)
    if avg5 > 0 and avg20 > 0:
        vol_trend = (avg5 - avg20) / avg20 * 100
    else:
        vol_trend = 0

    return {
        "today": today_vol, "avg5": avg5, "avg20": avg20, "avg60": avg60,
        "ratio_5": ratio_5, "ratio_20": ratio_20,
        "surge_days": surge_days, "vol_trend": vol_trend,
    }


def _calc_candle_pattern(df: pd.DataFrame) -> dict:
    """최근 5일 캔들 패턴 분석"""
    if df is None or df.empty or len(df) < 5:
        return {}
    df = df.sort_values("date").reset_index(drop=True)
    recent = df.tail(5)
    patterns = []
    bullish = 0
    bearish = 0
    for _, row in recent.iterrows():
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        body = abs(c - o)
        full_range = h - l if h > l else 1
        body_ratio = body / full_range * 100

        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        upper_pct = upper_wick / full_range * 100
        lower_pct = lower_wick / full_range * 100

        is_bull = c >= o
        if is_bull:
            bullish += 1
        else:
            bearish += 1

        pattern = "양봉" if is_bull else "음봉"
        if body_ratio < 10:
            pattern = "십자형(도지)"
        elif lower_pct > 60:
            pattern = "망치형(반등 신호)" if is_bull else "교수형(하락 신호)"
        elif upper_pct > 60:
            pattern = "유성형(고점 신호)"
        elif body_ratio > 70 and is_bull:
            pattern = "장대양봉(강한 상승)"
        elif body_ratio > 70 and not is_bull:
            pattern = "장대음봉(강한 하락)"

        patterns.append({
            "date": str(row["date"].date()) if hasattr(row["date"], "date") else str(row["date"]),
            "pattern": pattern, "body_ratio": body_ratio,
            "upper_pct": upper_pct, "lower_pct": lower_pct,
        })

    # 연속성
    last3 = df.tail(3)
    consecutive_bull = all(float(r["close"]) >= float(r["open"]) for _, r in last3.iterrows())
    consecutive_bear = all(float(r["close"]) < float(r["open"]) for _, r in last3.iterrows())

    return {
        "patterns": patterns, "bullish": bullish, "bearish": bearish,
        "consecutive_bull": consecutive_bull, "consecutive_bear": consecutive_bear,
    }


def _calc_ma_cross(df: pd.DataFrame) -> dict:
    """이동평균 크로스 감지 (최근 10일)"""
    if df is None or df.empty or len(df) < 60:
        return {}
    df = df.sort_values("date").reset_index(drop=True)
    c = df["close"].astype(float)
    ma5 = c.rolling(5).mean()
    ma20 = c.rolling(20).mean()
    ma60 = c.rolling(60).mean()

    crosses = []
    for i in range(max(len(df) - 10, 1), len(df)):
        dt = str(df.iloc[i]["date"].date()) if hasattr(df.iloc[i]["date"], "date") else str(df.iloc[i]["date"])
        # 5일선 ↔ 20일선
        if i > 0 and pd.notna(ma5.iloc[i]) and pd.notna(ma20.iloc[i]):
            prev_diff = ma5.iloc[i-1] - ma20.iloc[i-1] if pd.notna(ma5.iloc[i-1]) and pd.notna(ma20.iloc[i-1]) else 0
            curr_diff = ma5.iloc[i] - ma20.iloc[i]
            if prev_diff <= 0 < curr_diff:
                crosses.append(f"{dt}: 5일선이 20일선을 위로 돌파 (골든크로스, 상승 신호)")
            elif prev_diff >= 0 > curr_diff:
                crosses.append(f"{dt}: 5일선이 20일선을 아래로 돌파 (데드크로스, 하락 신호)")
        # 20일선 ↔ 60일선
        if i > 0 and pd.notna(ma20.iloc[i]) and pd.notna(ma60.iloc[i]):
            prev_diff = ma20.iloc[i-1] - ma60.iloc[i-1] if pd.notna(ma20.iloc[i-1]) and pd.notna(ma60.iloc[i-1]) else 0
            curr_diff = ma20.iloc[i] - ma60.iloc[i]
            if prev_diff <= 0 < curr_diff:
                crosses.append(f"{dt}: 20일선이 60일선을 위로 돌파 (중기 골든크로스)")
            elif prev_diff >= 0 > curr_diff:
                crosses.append(f"{dt}: 20일선이 60일선을 아래로 돌파 (중기 데드크로스)")

    return {"crosses": crosses}


def _calc_volatility(df: pd.DataFrame) -> dict:
    """변동성 분석: ATR, 일간 변동폭"""
    if df is None or df.empty or len(df) < 14:
        return {}
    df = df.sort_values("date").reset_index(drop=True)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df["close"].astype(float)
    prev_c = c.shift(1)

    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    atr14 = float(tr.tail(14).mean())
    atr5 = float(tr.tail(5).mean())
    last_close = float(c.iloc[-1])
    atr_pct = atr14 / last_close * 100 if last_close > 0 else 0

    # 최근 20일 일간 변동폭 평균
    daily_range = (h - l) / c * 100
    avg_range_20 = float(daily_range.tail(20).mean())
    avg_range_5 = float(daily_range.tail(5).mean())

    return {
        "atr14": atr14, "atr5": atr5, "atr_pct": atr_pct,
        "avg_range_20": avg_range_20, "avg_range_5": avg_range_5,
    }


def _score_breakdown(score_obj) -> List[str]:
    """CB 점수 7항목 분해 (쉬운 설명 포함)"""
    L = []
    if score_obj is None:
        return ["- 점수 분해 불가"]
    d = score_obj.score_detail
    items = [
        ("CCI (추세 강도)", d.cci_score, 13, "추세가 적당한 범위에 있을수록 높아요"),
        ("등락률 (하루 변동)", d.change_score, 13, "4~6% 상승이 가장 이상적이에요"),
        ("이격도 (평균과의 거리)", d.distance_score, 13, "20일 평균에서 2~8% 위에 있으면 좋아요"),
        ("연속 양봉 (상승 지속)", d.consec_score, 13, "2~3일 연속 상승이 가장 좋아요"),
        ("거래량비 (관심도)", d.volume_score, 13, "평소보다 거래량이 1~5배면 좋아요"),
        ("캔들 품질 (봉 모양)", d.candle_score, 13, "양봉 + 아래꼬리가 있으면 좋아요"),
        ("거래원 (큰손 움직임)", d.broker_score, 13, "특정 증권사 집중 매수가 있으면 높아요"),
    ]
    total = 0
    for name, val, mx, desc in items:
        total += val
        bar_len = int(val / mx * 10)
        bar = "█" * bar_len + "░" * (10 - bar_len)
        emoji = "🟢" if val >= mx * 0.6 else ("🟡" if val >= mx * 0.3 else "🔴")
        L.append(f"- {emoji} **{name}**: {val:.1f}/{mx} [{bar}]")
        L.append(f"  {desc}")
    L.append(f"- **합계**: {total:.1f}/91 (보너스 제외)")
    return L


# ────── 쉬운 요약 (핵심) ──────

def _build_easy_summary(chg_pct, close, opn, high, low, vol, tv,
                        vp, tech, broker, news, score, holding,
                        returns=None, w52=None, vol_trend=None, candle=None,
                        ma_cross=None, volatility=None, score_obj=None) -> List[str]:
    L = []
    # 한줄 결론
    L.append("### 한줄 결론")
    if chg_pct is not None and close is not None:
        L.append(f"이 종목은 오늘 **{_change_word(chg_pct)}({chg_pct:+.1f}%)**했고, 종가는 **{int(close):,}원**이에요.")
    else:
        L.append("가격 데이터가 부족해서 오늘의 흐름을 판단하기 어려워요.")
    L.append("")

    # 신호등
    L.append("### 신호등 요약")
    if chg_pct is not None:
        s = _chg_sig(chg_pct)
        L.append(f"- {_sig(s)} **주가**: {_change_word(chg_pct)} ({chg_pct:+.1f}%)")
    if vp:
        s = _vp_sig(vp.tag)
        L.append(f"- {_sig(s)} **매물대**: {vp.tag}")
    if tech and tech.cci is not None:
        s = _cci_sig(tech.cci)
        L.append(f"- {_sig(s)} **CCI**: {tech.cci:.0f} ({_cci_text(tech.cci)})")
    if tech and tech.rsi is not None:
        s = _rsi_sig(tech.rsi)
        L.append(f"- {_sig(s)} **RSI**: {tech.rsi:.0f} ({_rsi_text(tech.rsi)})")
    if broker:
        tag = broker.tag if broker.status == "ok" else "데이터 없음"
        L.append(f"- {_sig(_bk_sig(tag))} **거래원**: {tag}")
    if score is not None:
        g = "good" if score >= GRADE_B_PLUS else ("neutral" if score >= GRADE_C_PLUS else "warning")
        L.append(f"- {_sig(g)} **종합**: {score:.0f}점 (등급 {_grade(score)})")
    L.append("")

    # 보유 정보
    if holding:
        L.append("### 내 보유 정보")
        qty = int(holding.get("last_qty") or 0)
        avg = float(holding.get("last_price") or 0)
        L.append(f"- 보유: {qty:,}주 / 평균 매수가: {avg:,.0f}원")
        if qty and avg and close:
            pnl = (close - avg) * qty
            rate = (close / avg - 1) * 100
            L.append(f"- {'📈' if rate>=0 else '📉'} 현재 수익: {pnl:,.0f}원 ({rate:+.1f}%)")
        L.append("")

    # 오늘 주가
    L.append("### 오늘 주가 흐름")
    if opn is not None and high is not None and low is not None and close is not None:
        L.append(f"- 시가(장 시작): **{int(opn):,}원**")
        L.append(f"- 고가(오늘 최고): **{int(high):,}원**")
        L.append(f"- 저가(오늘 최저): **{int(low):,}원**")
        L.append(f"- 종가(장 마감): **{int(close):,}원**")
        if close > 0:
            spread = (high - low) / close * 100
            if spread >= 20:
                L.append(f"- 하루 변동폭 {spread:.1f}%로 **매우 큼** (의견 대립 심함)")
            elif spread >= 10:
                L.append(f"- 하루 변동폭 {spread:.1f}%로 **큰 편** (활발한 거래)")
            elif spread >= 5:
                L.append(f"- 하루 변동폭 {spread:.1f}%로 보통")
            else:
                L.append(f"- 하루 변동폭 {spread:.1f}%로 안정적")
        if vol: L.append(f"- 거래량: {int(vol):,}주")
        if tv and tv > 0: L.append(f"- 거래대금: 약 {tv:,.0f}억원")
    else:
        L.append("- 가격 데이터 부족")
    L.append("")

    # 기간별 수익률 (NEW)
    if returns:
        L.append("### 기간별 수익률 (이 종목을 얼마 전에 샀다면?)")
        L.append('"만약 그때 샀다면 지금 얼마나 벌었을까?"를 보여줘요.')
        L.append("")
        for period, ret in returns.items():
            emoji = "📈" if ret >= 5 else ("📉" if ret <= -5 else "➡️")
            L.append(f"- {emoji} {period} 전에 샀다면: **{ret:+.1f}%** {'수익' if ret >= 0 else '손실'}")
        # 종합 평가
        vals = list(returns.values())
        if all(v > 0 for v in vals):
            L.append("- 평가: 모든 기간에서 수익 (꾸준한 상승 중)")
        elif all(v < 0 for v in vals):
            L.append("- 평가: 모든 기간에서 손실 (지속 하락 중)")
        elif vals and vals[0] > 0 and vals[-1] < 0:
            L.append("- 평가: 최근 반등 중이지만 장기적으로는 아직 마이너스")
        L.append("")

    # 52주 고저 (NEW)
    if w52:
        L.append("### 52주 고저 위치 (1년간 어디쯤?)")
        L.append('"지난 1년간 가장 높았던 가격과 낮았던 가격 사이에서 지금 어디에 있는지" 보여줘요.')
        L.append("")
        L.append(f"- 52주 최고: **{w52['high']:,.0f}원**")
        L.append(f"- 52주 최저: **{w52['low']:,.0f}원**")
        L.append(f"- 현재 위치: 바닥에서 **{w52['pct']:.0f}%** 지점")
        if w52['pct'] >= 80:
            L.append('→ 1년 중 거의 꼭대기 근처예요. "더 올라갈 수 있을까?" 신중하게 판단 필요')
        elif w52['pct'] >= 50:
            L.append('→ 중간 위치예요. 추세를 따라 판단하는 구간')
        elif w52['pct'] >= 20:
            L.append('→ 바닥 근처예요. 반등을 노릴 수 있지만 더 빠질 수도 있어요')
        else:
            L.append('→ 1년 중 거의 바닥이에요. 이유가 있는 하락인지 확인 필요')
        L.append("")

    # 거래량 (NEW)
    if vol_trend:
        L.append("### 거래량 추세 (사람들이 얼마나 관심 있나)")
        L.append('"거래량이 갑자기 늘면 뭔가 일어나고 있다는 뜻이에요."')
        L.append("")
        L.append(f"- 오늘: **{int(vol_trend['today']):,}주**")
        L.append(f"- 5일 평균 대비: **{vol_trend['ratio_5']:.1f}배**")
        L.append(f"- 20일 평균 대비: **{vol_trend['ratio_20']:.1f}배**")
        if vol_trend['ratio_20'] >= 3:
            L.append("→ 🔴 거래량 **폭증**! 큰 뉴스나 세력 움직임 가능")
        elif vol_trend['ratio_20'] >= 2:
            L.append("→ 🟡 거래량 급증. 무언가 관심을 끌고 있어요")
        elif vol_trend['ratio_20'] <= 0.5:
            L.append("→ 거래량 급감. 관심이 줄었거나 방향 전환 대기 중")
        else:
            L.append("→ 거래량 정상 범위")
        if vol_trend.get("surge_days", 0) > 0:
            L.append(f"- 최근 10일 중 급증일: {vol_trend['surge_days']}일 (평균의 2배 이상)")
        L.append("")

    # 캔들 패턴 (NEW)
    if candle and candle.get("patterns"):
        L.append("### 캔들 패턴 (최근 5일 봉 모양)")
        L.append('"주가 봉의 모양으로 매수/매도 심리를 읽을 수 있어요."')
        L.append("")
        L.append(f"- 양봉(상승): **{candle['bullish']}일** / 음봉(하락): **{candle['bearish']}일**")
        if candle.get("consecutive_bull"):
            L.append("- 🟢 최근 3일 연속 양봉! 상승 힘이 유지되고 있어요")
        elif candle.get("consecutive_bear"):
            L.append("- 🔴 최근 3일 연속 음봉. 하락 압력이 계속되고 있어요")
        for p in candle["patterns"]:
            L.append(f"- {p['date']}: **{p['pattern']}**")
        L.append("")

    # 매물대
    L.append("### 매물대 (과거에 많이 거래된 가격대)")
    L.append('"매물대"란 과거에 사람들이 많이 사고팔았던 가격대예요.')
    L.append("매물대 근처에서 주가가 멈추거나 튕기는 경우가 많아요.")
    L.append("")
    if vp:
        L.append(f"상태: {_sig(_vp_sig(vp.tag))} **{vp.tag}** (점수 {vp.score:.1f}/13)")
        above_note = " (적음→위로 갈 때 방해 적음)" if vp.above_pct < 30 else (" (많음→위에 벽)" if vp.above_pct > 50 else "")
        below_note = " (많음→아래에 쿠션)" if vp.below_pct > 50 else (" (적음→지지 약함)" if vp.below_pct < 20 else "")
        L.append(f"- 위쪽 매물: **{vp.above_pct:.1f}%**{above_note}")
        L.append(f"- 아래쪽 매물: **{vp.below_pct:.1f}%**{below_note}")
        if vp.poc_price: L.append(f"- 최다 거래가(POC): **{vp.poc_price:,.0f}원**")
        if vp.support: L.append(f"- 지지선(바닥 역할): {vp.support:,.0f}원")
        if vp.resistance: L.append(f"- 저항선(천장 역할): {vp.resistance:,.0f}원")
        if vp.above_pct < 30 and vp.below_pct > 50:
            L.append('→ 쉽게 말하면: "위는 뻥 뚫려있고 아래는 쿠션이 두꺼운" 상태')
        elif vp.above_pct > 50 and vp.below_pct < 30:
            L.append('→ "위에 벽이 두껍고 아래는 허공인" 상태, 주의 필요')
    else:
        L.append("- 매물대 데이터 부족")
    L.append("")

    # 기술 지표
    L.append("### 기술 지표 (주가의 체온 측정)")
    L.append('"너무 뜨거운지 차가운지"를 숫자로 보여주는 도구예요.')
    L.append("")
    if tech and tech.cci is not None:
        L.append(f"**CCI(14일)**: {tech.cci:.1f} → {_sig(_cci_sig(tech.cci))} {_cci_text(tech.cci)}")
        L.append(f"  +{CCI_OVERBOUGHT}이상=과열 / {CCI_OVERSOLD}이하=과냉각 / 사이=보통")
    if tech and tech.rsi is not None:
        L.append(f"**RSI(14일)**: {tech.rsi:.1f} → {_sig(_rsi_sig(tech.rsi))} {_rsi_text(tech.rsi)}")
        L.append("  70이상=과열 / 30이하=과냉각")
    if tech and tech.macd is not None and tech.macd_signal is not None:
        d = tech.macd - tech.macd_signal
        L.append(f"**MACD**: {'상승 전환 중' if d>0 else '하락 전환 중'} (MACD {tech.macd:.0f}, 시그널 {tech.macd_signal:.0f})")
    L.append("")
    if tech and tech.ma20 is not None:
        L.append("**이동평균선** (최근 N일간 평균 가격)")
        for lbl, val in [("5일",tech.ma5),("20일",tech.ma20),("60일",tech.ma60),("120일",tech.ma120)]:
            if val is not None and close:
                diff = (close - val) / val * 100
                L.append(f"- {lbl}: {val:,.0f}원 (현재가 대비 {diff:+.1f}%)")
        L.append(f"→ {_ma_align(tech.ma5, tech.ma20, tech.ma60, tech.ma120, close)}")
    if tech and tech.bb_mid is not None and close:
        L.append("")
        L.append("**볼린저밴드** (가격의 정상 범위)")
        L.append(f"- 상단: {tech.bb_upper:,.0f} / 중앙: {tech.bb_mid:,.0f} / 하단: {tech.bb_lower:,.0f}")
        if close > tech.bb_upper: L.append("→ 현재가가 상단 위 = 과열 가능")
        elif close < tech.bb_lower: L.append("→ 현재가가 하단 아래 = 과매도 가능")
        elif close > tech.bb_mid: L.append("→ 현재가가 중앙선 위 = 양호")
        else: L.append("→ 현재가가 중앙선 아래 = 약세")
        bw = (tech.bb_upper - tech.bb_lower) / tech.bb_mid * 100 if tech.bb_mid else 0
        if bw > 30: L.append(f"→ 밴드폭 {bw:.0f}%로 넓음 (변동성 큰 상태)")
        elif bw > 15: L.append(f"→ 밴드폭 {bw:.0f}%")
        else: L.append(f"→ 밴드폭 {bw:.0f}%로 좁음 (큰 움직임 대기)")
    L.append("")

    # 이동평균 크로스 (NEW)
    if ma_cross and ma_cross.get("crosses"):
        L.append("### 이동평균 크로스 (추세 전환 신호)")
        L.append('"단기선이 장기선을 뚫고 올라가면 상승 신호, 내려가면 하락 신호예요."')
        L.append("")
        for cross in ma_cross["crosses"]:
            L.append(f"- {cross}")
        L.append("")

    # 변동성 (NEW)
    if volatility:
        L.append("### 변동성 분석 (이 종목이 얼마나 출렁이는지)")
        L.append('"변동성이 클수록 하루에 오르내리는 폭이 크다는 뜻이에요."')
        L.append("")
        L.append(f"- 14일 평균 변동폭(ATR): **{volatility['atr14']:,.0f}원** (종가의 {volatility['atr_pct']:.1f}%)")
        L.append(f"- 최근 5일 평균 변동폭: {volatility['avg_range_5']:.1f}%")
        L.append(f"- 최근 20일 평균 변동폭: {volatility['avg_range_20']:.1f}%")
        if volatility['atr_pct'] >= 10:
            L.append("→ **매우 높은 변동성**. 하루에 10% 이상 움직일 수 있어요. 조심!")
        elif volatility['atr_pct'] >= 5:
            L.append("→ 높은 변동성. 단타에 적합하지만 리스크도 커요")
        elif volatility['atr_pct'] >= 2:
            L.append("→ 보통 변동성. 일반적인 주식 수준이에요")
        else:
            L.append("→ 낮은 변동성. 조용한 구간이에요 (큰 움직임 전 징조일 수도)")
        L.append("")

    # 거래원
    L.append("### 거래원 흐름 (누가 사고 있나)")
    L.append('"거래원"은 어느 증권사를 통해 거래했는지 보여주는 정보예요.')
    L.append("")
    if broker and broker.status == "ok":
        L.append(f"상태: {_sig(_bk_sig(broker.tag))} **{broker.tag}**")
        L.append(f"- 이상 점수: {broker.avg_anomaly:.1f} (0에 가까울수록 정상)")
        if broker.max_anomaly and broker.max_anomaly > 5:
            L.append(f"- 최대 이상치: {broker.max_anomaly:.1f} (큰손 움직임 가능)")
    else:
        L.append("- 거래원 데이터 부족")
    L.append("")

    # 뉴스/공시
    L.append("### 뉴스 공시 요약")
    if news:
        nc = len(news.news) if news.news else 0
        dc = len(news.disclosures) if news.disclosures else 0
        L.append(f"- 뉴스 **{nc}건** / 공시 **{dc}건**")
        if news.disclosures:
            warned = False
            for d in news.disclosures[:5]:
                t = d.get("report_nm", "")
                ex = _disc_explain(t)
                if ex:
                    warned = True
                    L.append(f'- ⚠️ "{t}"')
                    L.append(f"  → {ex}")
            if not warned:
                L.append("- 특별히 주의할 공시는 없어요")
    else:
        L.append("- 뉴스/공시 데이터 부족")
    L.append("")

    # CB 점수 분해 (NEW)
    if score_obj is not None:
        L.append("### 종합 점수 분해 (어디서 점수를 받았나)")
        L.append('"7개 항목별로 점수를 분해해서 어디가 강점이고 약점인지 보여줘요."')
        L.append("")
        breakdown = _score_breakdown(score_obj)
        L.extend(breakdown)
        L.append("")

    return L


# ────── 메인 리포트 생성 ──────

def generate_stock_report(stock_code: str, full: bool = False) -> StockReportResult:
    code = str(stock_code).zfill(6)
    now = datetime.now()
    df, data_path = _load_ohlcv_df(code)

    L: List[str] = []
    L.append("# 종목 분석 리포트")
    L.append("")
    L.append(f"- 종목코드: {code}")
    L.append(f"- 생성시각: {now.strftime('%Y-%m-%d %H:%M')}")
    L.append(f"- 데이터: {_fmt_src(data_path)}")
    L.append("")

    # 보유 현황
    holding = _get_holding(code)
    if holding:
        L.append("## 보유 관찰 현황")
        qty = holding.get("last_qty", 0) or 0
        price = holding.get("last_price", 0.0) or 0.0
        L.append(f"- 상태: {holding.get('status', '-')}")
        L.append(f"- 수량: {int(qty):,}주 | 평균단가: {float(price):,.0f}원")
        L.append(f"- 첫 관찰: {holding.get('first_seen', '-')} | 최근: {holding.get('last_seen', '-')}")
        L.append("")

    # 가격 거래 요약
    L.append("## 가격 거래 요약")
    close = opn = high = low = vol = chg = tv = None
    if df is None:
        L.append("- 가격 데이터 없음")
    else:
        df = df.sort_values("date").reset_index(drop=True)
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else None
        close = float(last["close"]); opn = float(last["open"])
        high = float(last["high"]); low = float(last["low"])
        vol = int(last["volume"]); tv = _calc_tv(last)
        chg = ((close - float(prev["close"])) / float(prev["close"]) * 100) if prev is not None and float(prev["close"]) > 0 else 0.0
        p0 = df["date"].iloc[0].date(); p1 = last["date"].date()
        L.append(f"- 기간: {p0} ~ {p1} ({len(df):,}거래일)")
        L.append(f"- 최근({p1}): 시가 {int(opn):,} / 고가 {int(high):,} / 저가 {int(low):,} / 종가 {int(close):,}")
        L.append(f"- 전일 대비: {chg:+.1f}% ({_change_word(chg)})")
        L.append(f"- 거래량: {vol:,}주 | 거래대금: 약 {tv:,.0f}억원")
        tail = df.tail(20) if len(df) >= 20 else df
        L.append(f"- 20일 고가/저가: {float(tail['high'].max()):,.0f} / {float(tail['low'].min()):,.0f}")
    L.append("")

    # 기간별 수익률 (NEW)
    returns = _calc_period_returns(df, close) if df is not None else {}
    if returns:
        L.append("## 기간별 수익률")
        for period, ret in returns.items():
            emoji = "📈" if ret >= 0 else "📉"
            L.append(f"- {emoji} {period}: {ret:+.1f}%")
        L.append("")

    # 52주 고저 분석 (NEW)
    w52 = _calc_52week(df, close) if df is not None else {}
    if w52:
        L.append("## 52주 고저 분석")
        L.append(f"- 52주 최고: {w52['high']:,.0f}원")
        L.append(f"- 52주 최저: {w52['low']:,.0f}원")
        L.append(f"- 현재 위치: 바닥에서 **{w52['pct']:.0f}%** 지점")
        if w52['pct'] >= 80:
            L.append("- 해석: 52주 고점 근처 (고점 부담 있음)")
        elif w52['pct'] >= 50:
            L.append("- 해석: 중간 위치 (추세에 따라 판단)")
        elif w52['pct'] >= 20:
            L.append("- 해석: 저점 근처 (반등 여부 관찰)")
        else:
            L.append("- 해석: 52주 최저 근처 (바닥 다지기 가능)")
        L.append("")

    # 거래량 추세 (NEW)
    vol_trend = _calc_volume_trend(df) if df is not None else {}
    if vol_trend:
        L.append("## 거래량 추세 분석")
        L.append(f"- 오늘 거래량: {int(vol_trend['today']):,}주")
        L.append(f"- 5일 평균: {int(vol_trend['avg5']):,}주 (오늘 대비 {vol_trend['ratio_5']:.1f}배)")
        L.append(f"- 20일 평균: {int(vol_trend['avg20']):,}주 (오늘 대비 {vol_trend['ratio_20']:.1f}배)")
        if vol_trend['ratio_20'] >= 3:
            L.append("- 판단: 거래량 **폭증** (큰 이벤트 발생 가능)")
        elif vol_trend['ratio_20'] >= 2:
            L.append("- 판단: 거래량 **급증** (관심 집중 중)")
        elif vol_trend['ratio_20'] >= 1.5:
            L.append("- 판단: 거래량 약간 증가")
        elif vol_trend['ratio_20'] <= 0.5:
            L.append("- 판단: 거래량 **급감** (관심 이탈 또는 방향 전환 대기)")
        else:
            L.append("- 판단: 거래량 보통")
        if vol_trend.get("vol_trend", 0) > 50:
            L.append("- 추세: 최근 5일 평균이 20일 평균보다 크게 높음 (단기 관심 급등)")
        elif vol_trend.get("vol_trend", 0) < -30:
            L.append("- 추세: 최근 5일 평균이 20일 평균보다 낮음 (관심 감소)")
        if vol_trend.get("surge_days", 0) > 0:
            L.append(f"- 최근 10일 중 거래량 급증일: **{vol_trend['surge_days']}일** (평균의 2배 이상)")
        L.append("")

    # 캔들 패턴 (NEW)
    candle = _calc_candle_pattern(df) if df is not None else {}
    if candle and candle.get("patterns"):
        L.append("## 캔들 패턴 분석 (최근 5일)")
        L.append(f"- 양봉: {candle['bullish']}일 / 음봉: {candle['bearish']}일")
        if candle.get("consecutive_bull"):
            L.append("- 최근 3일 연속 양봉 (상승세 유지)")
        elif candle.get("consecutive_bear"):
            L.append("- 최근 3일 연속 음봉 (하락세 유지)")
        for p in candle["patterns"]:
            L.append(f"- {p['date']}: {p['pattern']} (몸통 {p['body_ratio']:.0f}%, 윗꼬리 {p['upper_pct']:.0f}%, 아랫꼬리 {p['lower_pct']:.0f}%)")
        L.append("")

    # 이동평균 크로스 (NEW)
    ma_cross = _calc_ma_cross(df) if df is not None else {}
    if ma_cross and ma_cross.get("crosses"):
        L.append("## 이동평균 크로스 (최근 10일)")
        for cross in ma_cross["crosses"]:
            L.append(f"- {cross}")
        L.append("")
    elif df is not None and len(df) >= 60:
        L.append("## 이동평균 크로스 (최근 10일)")
        L.append("- 최근 10일 내 크로스 없음 (추세 유지 중)")
        L.append("")

    # 변동성 분석 (NEW)
    volatility = _calc_volatility(df) if df is not None else {}
    if volatility:
        L.append("## 변동성 분석")
        L.append(f"- ATR(14일): {volatility['atr14']:,.0f}원 (종가 대비 {volatility['atr_pct']:.1f}%)")
        L.append(f"- 최근 20일 일간 변동폭: 평균 {volatility['avg_range_20']:.1f}%")
        L.append(f"- 최근 5일 일간 변동폭: 평균 {volatility['avg_range_5']:.1f}%")
        if volatility['atr_pct'] >= 10:
            L.append("- 판단: **매우 높은 변동성** (급등/급락 모두 가능)")
        elif volatility['atr_pct'] >= 5:
            L.append("- 판단: 높은 변동성 (활발한 매매 구간)")
        elif volatility['atr_pct'] >= 2:
            L.append("- 판단: 보통 변동성")
        else:
            L.append("- 판단: 낮은 변동성 (횡보 구간, 큰 움직임 대기)")
        if volatility['avg_range_5'] > volatility['avg_range_20'] * 1.5:
            L.append("- 주의: 최근 5일 변동폭이 20일 평균보다 크게 증가 (불안정)")
        L.append("")

    # 매물대
    L.append("## 매물대 분석")
    vp_tag = "없음"; vp = None
    if df is not None and close:
        vp = analyze_volume_profile(df, current_price=close, n_days=60)
        vp_tag = vp.tag
        L.append(f"- 점수: {vp.score:.1f}/13 | 상태: {vp.tag}")
        L.append(f"- 위쪽: {vp.above_pct:.1f}% / 아래쪽: {vp.below_pct:.1f}%")
        if vp.poc_price: L.append(f"- 최다 거래가(POC): {vp.poc_price:,.0f}원 ({vp.poc_pct:.1f}%)")
        if vp.support or vp.resistance:
            L.append(f"- 지지: {vp.support:,.0f}원 / 저항: {vp.resistance:,.0f}원"
                     if vp.support and vp.resistance else
                     f"- 지지: {vp.support:,.0f}원" if vp.support else f"- 저항: {vp.resistance:,.0f}원")
        if vp.reason: L.append(f"- 참고: {vp.reason}")
    else:
        L.append("- 매물대 데이터 부족")
    L.append("")

    # 기술 지표
    L.append("## 기술 지표 분석")
    tech = analyze_technical(df) if df is not None else analyze_technical(None)
    if tech.note:
        L.append(f"- {tech.note}")
    else:
        if tech.cci is not None: L.append(f"- CCI(14): {tech.cci:.1f} ({_cci_text(tech.cci)})")
        if tech.rsi is not None: L.append(f"- RSI(14): {tech.rsi:.1f} ({_rsi_text(tech.rsi)})")
        if tech.macd is not None and tech.macd_signal is not None:
            d = tech.macd - tech.macd_signal
            L.append(f"- MACD: {tech.macd:.1f} / 시그널: {tech.macd_signal:.1f} / {'상승' if d>0 else '하락'} 전환")
        if tech.ma20 is not None:
            parts = [f"{n}={v:,.0f}" for n, v in [("5일",tech.ma5),("20일",tech.ma20),("60일",tech.ma60),("120일",tech.ma120)] if v]
            L.append(f"- 이동평균: {', '.join(parts)}")
            L.append(f"- 배열: {_ma_align(tech.ma5, tech.ma20, tech.ma60, tech.ma120, close)}")
        if tech.bb_mid is not None:
            L.append(f"- 볼린저: 상단 {tech.bb_upper:,.0f} / 중앙 {tech.bb_mid:,.0f} / 하단 {tech.bb_lower:,.0f}")
    L.append("")

    # 거래원
    L.append("## 거래원 수급 분석")
    broker = analyze_broker_flow(code, limit=5 if full else 1)
    if broker.status != "ok":
        L.append(f"- {broker.note or '데이터 없음'}")
    else:
        L.append(f"- 상태: {broker.tag} | 최대: {broker.max_anomaly:.1f} | 평균: {broker.avg_anomaly:.1f}")
        if broker.note: L.append(f"- 참고: {broker.note}")
        if full and broker.recent_rows:
            L.append("| 날짜 | 이상치 | 점수 | 상태 |")
            L.append("| --- | --- | --- | --- |")
            for r in broker.recent_rows:
                L.append(f"| {r.get('screen_date','')} | {r.get('anomaly_score','')} | {float(r.get('broker_score',0)):.1f} | {r.get('tag','')} |")
    L.append("")

    # 뉴스/공시
    L.append("## 뉴스 공시")
    news = analyze_news_timeline(code, stock_name=code)
    if news.note: L.append(f"- {news.note}")
    if news.news:
        L.append("- 뉴스:")
        for item in news.news[:5]:
            L.append(f"  - {item.get('pub_date','')} {item.get('source','')} {item.get('title','')}".strip())
    else:
        L.append("- 뉴스: 없음")
    if news.disclosures:
        L.append("- 공시:")
        for item in news.disclosures[:5]:
            t = item.get("report_nm", "")
            line = f"  - {item.get('rcept_dt','')} {t}".strip()
            ex = _disc_explain(t)
            if ex: line += f" → {ex}"
            L.append(line)
    else:
        L.append("- 공시: 없음")
    L.append("")

    # CB 점수
    cb_score = None
    score_obj = None
    if df is not None:
        try:
            prices = _to_daily_prices(df)
            last = df.iloc[-1]; tv2 = _calc_tv(last)
            stock = StockData(code=code, name=code, daily_prices=prices,
                             current_price=int(last["close"]), trading_value=tv2)
            scores = ScoreCalculatorV5().calculate_scores([stock])
            if scores:
                score_obj = scores[0]
                cb_score = scores[0].score_total
        except Exception:
            pass

    # CB 점수 항목별 분해 (NEW)
    if score_obj is not None:
        L.append("## 점수 항목별 분해")
        L.append(f"총점: **{cb_score:.1f}**/100 (등급 **{_grade(cb_score)}**)")
        L.append("")
        breakdown = _score_breakdown(score_obj)
        L.extend(breakdown)
        L.append("")

    # 쉬운 요약
    L.append("## 쉬운 요약")
    easy = _build_easy_summary(
        chg, close, opn, high, low, vol, tv, vp, tech, broker, news, cb_score, holding,
        returns=returns, w52=w52, vol_trend=vol_trend, candle=candle,
        ma_cross=ma_cross, volatility=volatility, score_obj=score_obj,
    )
    L.extend(easy or ["- 요약 데이터 부족"])
    L.append("")

    # 기업 정보
    L.append("## 기업 정보")
    try:
        dart = get_dart_service()
        txt = dart.format_full_profile_for_ai(code, stock_name=code)
        if txt:
            for line in txt.splitlines(): L.append(line)
        else:
            L.append("- 기업 정보 없음")
    except Exception:
        L.append("- 기업 정보 없음")
    L.append("")

    # AI 의견
    L.append("## AI 분석 의견")
    ai = _ai_summary("\n".join(L))
    if ai:
        for line in ai.splitlines():
            if line.strip(): L.append(line.rstrip())
    else:
        L.append("- AI 의견 없음 (Gemini API 키 필요)")
    L.append("")

    # 매매 계획
    L.append("## 매매 계획")
    if vp is None:
        vp = VolumeProfileSummary(score=0, tag="데이터부족", above_pct=0, below_pct=0,
                                  poc_price=0, poc_pct=0, support=None, resistance=None, reason="")
    plan = calculate_entry_exit(df, close or 0, vp, tech) if df is not None else calculate_entry_exit(None, 0, vp, tech)
    if plan.entry is None:
        L.append(f"- {plan.note or '데이터 부족'}")
    else:
        L.append(f"- 진입가: {plan.entry:,.0f}원")
        L.append(f"- 1차 목표: {plan.target1:,.0f}원")
        L.append(f"- 2차 목표: {plan.target2:,.0f}원")
        L.append(f"- 손절가: {plan.stop_loss:,.0f}원")
        L.append(f"- 예상 보유: {plan.holding_days}")
        if plan.note: L.append(f"- 참고: {plan.note}")
    L.append("")

    # 종합 판단
    L.append("## 종합 판단")
    if cb_score is not None:
        L.append(f"- 종합 점수: **{cb_score:.1f}**/100 (등급 **{_grade(cb_score)}**)")
    else:
        L.append("- 종합 점수: 계산 불가")
    L.append(f"- 매물대: {vp_tag}")
    L.append(f"- AI 의견: {'위 섹션 참고' if ai else '없음'}")

    parts = []
    if tech.cci is not None: parts.append(f"CCI{tech.cci:.0f}")
    if tech.rsi is not None: parts.append(f"RSI{tech.rsi:.0f}")
    if vp_tag: parts.append(f"매물대:{vp_tag}")
    if cb_score is not None: parts.append(f"{cb_score:.0f}점")
    summary = f"{code} | {', '.join(parts)}" if parts else f"{code} | 리포트 생성"

    return StockReportResult(lines=L, summary=summary)


if __name__ == "__main__":
    # 리팩토링된 상수 및 함수 테스트
    print("=" * 60)
    print("StockReport 상수 및 함수 테스트")
    print("=" * 60)
    
    print(f"CCI 과열 기준: {CCI_OVERBOUGHT} (기존 100)")
    print(f"RSI 과열 기준: {RSI_OVERBOUGHT} (기존 70)")
    print(f"S등급 기준점수: {GRADE_S} (기존 85)")
    
    print(f"\nCCI 150 평가: {_cci_text(150)}")
    print(f"RSI 25 평가: {_rsi_text(25)}")
    print(f"점수 88점 등급: {_grade(88)}")