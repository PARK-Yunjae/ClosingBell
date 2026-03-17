"""
ClosingBell v4.0 watchlist monitor.

Runtime-only watchlist logic:
- store and evaluate ranked watchlist candidates (v4: 1~5위)
- send the 15:00 Discord pick based on live watchlist checks
- v3.8: 최소 기술적 조건 필터 (BUY_MIN_CONDITIONS), rank 보너스 평탄화
"""
import logging
import pandas as pd
import numpy as np
from datetime import datetime
from functools import lru_cache

from config import (
    KIWOOM_BASE_URL, KIWOOM_APPKEY, KIWOOM_SECRETKEY, API_DELAY,
    GLOBAL_CSV, OHLCV_DIR, WATCHLIST_MAX_DAYS, WATCHLIST_MAX_STOCKS,
    PULLBACK_MA5_GAP, PULLBACK_VOL_DECLINE, PULLBACK_BB_LOWER,
    DAILY_PICK_TOP_K,
    BUY_A_MIN_SCORE, BUY_B_MIN_SCORE, BUY_MIN_CONDITIONS,
    BUY_DART_DANGER_PENALTY, BUY_DART_CAUTION_PENALTY,
    BUY_NEWS_DANGER_PENALTY, BUY_NEWS_CAUTION_PENALTY,
    BUY_REGIME_CHAOTIC_BONUS, BUY_REGIME_RISING_PENALTY, BUY_REGIME_WEAK_PENALTY,
    REGIME_CHAOTIC_NASDAQ_ABS, REGIME_EVENT_HIGH_IMPACT,
    RANK1_PULLBACK_BONUS, RANK2_PULLBACK_BONUS, RANK3_PULLBACK_BONUS,
    WATCHLIST_ALLOWED_RANKS,
    RANK1_SWEET_SPOT, RANK1_WINDOW_START, RANK1_WINDOW_END,
    RANK2_SWEET_SPOT, RANK2_WINDOW_START, RANK2_WINDOW_END,
    RANK3_SWEET_SPOT, RANK3_WINDOW_START, RANK3_WINDOW_END,
    RANK4_SWEET_SPOT, RANK4_WINDOW_START, RANK4_WINDOW_END,
    RANK5_SWEET_SPOT, RANK5_WINDOW_START, RANK5_WINDOW_END,
    RANK4_PULLBACK_BONUS, RANK5_PULLBACK_BONUS,
    SUPPLY_CAUTION_PENALTY, SUPPLY_DANGER_PENALTY,
    SUPPLY_DANGER_THRESH, SUPPLY_CAUTION_THRESH,
    SUPPLY_GOOD_BONUS, SUPPLY_GOOD_THRESH,
)
from storage import (
    load_active_watchlists as load_active_watchlists_db,
    save_market_regime_daily,
    save_watchlist_payload,
)
from trading_calendar import add_trading_days, trading_days_since

try:
    from market_context import get_market_context
except Exception:
    def get_market_context():
        return None

logger = logging.getLogger("closingbell")
CONVICTION_FORCE_C_FLAGS = {"DART위험", "뉴스위험", "대주주투매"}
CONVICTION_A_CAP_FLAGS = {
    "DART주의",
    "뉴스주의",
    "수급위험",
    "수급주의",
    "과열",
    "급락",
    "약세장",
    "이벤트주의",
    "외신경고",
    "테마과열",
}

# ──────────────────────────────────────────────
# Rank timing windows loaded from .env-backed config.
# ──────────────────────────────────────────────
RANK_TIMING = {
    1: {
        "sweet_spot": RANK1_SWEET_SPOT,
        "window": (RANK1_WINDOW_START, RANK1_WINDOW_END),
        "note": "빠른 반등형",
    },
    2: {
        "sweet_spot": RANK2_SWEET_SPOT,
        "window": (RANK2_WINDOW_START, RANK2_WINDOW_END),
        "note": "느린 회복형",
    },
    3: {
        "sweet_spot": RANK3_SWEET_SPOT,
        "window": (RANK3_WINDOW_START, RANK3_WINDOW_END),
        "note": "깊은 조정 후 반등형",
    },
    4: {
        "sweet_spot": RANK4_SWEET_SPOT,
        "window": (RANK4_WINDOW_START, RANK4_WINDOW_END),
        "note": "중기 눌림형",
    },
    5: {
        "sweet_spot": RANK5_SWEET_SPOT,
        "window": (RANK5_WINDOW_START, RANK5_WINDOW_END),
        "note": "초기 모멘텀형",
    },
}
RANK_PULLBACK_BONUS = {
    1: RANK1_PULLBACK_BONUS,
    2: RANK2_PULLBACK_BONUS,
    3: RANK3_PULLBACK_BONUS,
    4: RANK4_PULLBACK_BONUS,
    5: RANK5_PULLBACK_BONUS,
}
DEFAULT_TIMING_RANK = max(RANK_TIMING)


def _is_allowed_rank(rank: int) -> bool:
    try:
        return int(rank) in WATCHLIST_ALLOWED_RANKS
    except (TypeError, ValueError):
        return False


def _rank_timing(rank: int) -> dict:
    return RANK_TIMING.get(rank, RANK_TIMING[DEFAULT_TIMING_RANK])


def _load_recent_ohlcv(code: str, tail: int = 30) -> pd.DataFrame | None:
    csv_path = OHLCV_DIR / f"{code.strip().zfill(6)}.csv"
    if not csv_path.exists():
        return None
    df = pd.read_csv(csv_path)
    df.columns = [c.lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").tail(tail)
    if len(df) < 20:
        return None
    return df


def _calc_pullback_snapshot(df: pd.DataFrame, price: float, volume: float, entry_price: float) -> dict:
    recent_closes = list(df["close"].tail(4).values) + [price]
    ma5 = np.mean(recent_closes)
    ma5_gap = abs((price / ma5 - 1) * 100) if ma5 > 0 else 999

    vol_ma20 = df["volume"].tail(20).mean()
    vol_decline = volume / vol_ma20 if vol_ma20 > 0 else 1.0

    recent_20 = list(df["close"].tail(19).values) + [price]
    bb_mid = np.mean(recent_20)
    bb_std = np.std(recent_20)
    bb_lower = bb_mid - 2 * bb_std
    bb_upper = bb_mid + 2 * bb_std
    bb_position = (price - bb_lower) / (bb_upper - bb_lower) if bb_upper > bb_lower else 0.5

    price_change = (price / entry_price - 1) * 100 if entry_price > 0 else 0
    return {
        "ma5_gap": ma5_gap,
        "vol_decline": vol_decline,
        "bb_position": bb_position,
        "price_change": price_change,
    }


def _calc_rsi_cci(df: pd.DataFrame) -> tuple[float, float]:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    sma_tp = tp.rolling(14).mean()
    mad = tp.rolling(14).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    cci_series = (tp - sma_tp) / (0.015 * mad)
    cci_now = float(cci_series.iloc[-1]) if pd.notna(cci_series.iloc[-1]) else 0

    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi_series = 100 - (100 / (1 + rs))
    rsi_now = float(rsi_series.iloc[-1]) if pd.notna(rsi_series.iloc[-1]) else 50
    return cci_now, rsi_now


def _conviction_from_score(score: float) -> str:
    if score >= BUY_A_MIN_SCORE:
        return "A"
    if score >= BUY_B_MIN_SCORE:
        return "B"
    return "C"


def _dedupe_flags(flags: list[str] | None) -> list[str]:
    result = []
    seen = set()
    for flag in flags or []:
        text = str(flag).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _conviction_with_guardrails(
    score: float,
    risk_flags: list[str] | None,
    dart_risk: str = "",
    news_risk: str = "",
) -> str:
    flags = set(_dedupe_flags(risk_flags))
    if dart_risk == "위험" or news_risk == "위험" or flags & CONVICTION_FORCE_C_FLAGS:
        return "C"

    conviction = _conviction_from_score(score)
    if conviction == "A" and (
        dart_risk == "주의"
        or news_risk == "주의"
        or bool(flags & CONVICTION_A_CAP_FLAGS)
    ):
        return "B"
    return conviction


def make_action_label(pick: dict) -> dict:
    """
    종목 데이터로부터 한줄 액션 라벨 + 색상을 생성.
    웹훅 상단에 표시할 결론 문구.
    Returns: {"label": str, "detail": str, "color": "green"|"yellow"|"red"}
    """
    days = pick.get("days_elapsed", 0)
    conv = pick.get("conviction", "C")
    score = pick.get("conviction_score", 0)
    flags = pick.get("risk_flags", [])
    news_risk = pick.get("news_risk", "")
    dart_risk = pick.get("dart_risk", "")
    in_window = pick.get("in_window", False)

    # 위험 종목
    danger_flags = {"DART위험", "뉴스위험", "대주주투매", "수급위험"}
    if danger_flags & set(flags):
        reasons = []
        if "DART위험" in flags or dart_risk == "위험":
            reasons.append("공시 위험")
        if "뉴스위험" in flags or news_risk == "위험":
            reasons.append("악재 뉴스")
        if "대주주투매" in flags:
            reasons.append("대주주 매도")
        if "수급위험" in flags:
            reasons.append("수급 위험")
        return {
            "label": "⛔ 진입 비추",
            "detail": " + ".join(reasons),
            "color": "red",
        }

    # D+1 이르다
    if days <= 1:
        return {
            "label": "⏳ 아직 이르다",
            "detail": f"포착 당일 — D+2~3 눌림목 기다리기",
            "color": "yellow",
        }

    # 주의 종목 (뉴스/DART 주의 or 과열)
    caution_flags = {"DART주의", "뉴스주의", "과열", "급락", "약세장", "수급주의", "외신경고", "테마과열"}
    active_cautions = caution_flags & set(flags)
    if news_risk == "주의":
        active_cautions.add("뉴스주의")

    # 매수 적기
    if in_window and conv in ("A", "B") and not active_cautions:
        sweet = pick.get("sweet_spot_day", 2)
        if days == sweet:
            return {
                "label": "🟢 매수 적기",
                "detail": f"D+{days} 최적 타이밍 진입 구간",
                "color": "green",
            }
        return {
            "label": "🟢 매수 고려",
            "detail": f"D+{days} 진입 가능 구간 (최적 D+{sweet})",
            "color": "green",
        }

    # 관심 (주의사항 있거나 C등급)
    if active_cautions:
        caution_text = ", ".join(sorted(active_cautions))
        return {
            "label": "🟡 주의하며 관심",
            "detail": caution_text,
            "color": "yellow",
        }

    # 윈도우 밖이거나 C등급
    if not in_window:
        return {
            "label": "⏸️ 타이밍 대기",
            "detail": f"D+{days} — 아직 감시 윈도우 밖",
            "color": "yellow",
        }

    return {
        "label": "🟡 관심 종목",
        "detail": f"C등급 — 보조 참고용",
        "color": "yellow",
    }


def _company_context(code: str, price: float = 0) -> dict:
    market_ctx = get_market_context()
    if not market_ctx:
        return {}
    ctx = market_ctx.stock_context(code, price)
    return {
        "sector": ctx.get("sector", ""),
        "industry": ctx.get("industry", ""),
        "company_brief": ctx.get("brief", ""),
        "main_products": ctx.get("main_products", ""),
        "holder_tag": ctx.get("holder_tag", ""),
    }


def _merged_company_context(stock_info: dict, price: float = 0) -> dict:
    code = str(stock_info.get("code", "")).strip().zfill(6)
    context = _company_context(code, price)
    return {
        "sector": stock_info.get("sector") or context.get("sector", ""),
        "industry": stock_info.get("industry") or context.get("industry", ""),
        "company_brief": stock_info.get("company_brief") or context.get("company_brief", ""),
        "main_products": stock_info.get("main_products") or context.get("main_products", ""),
        "holder_tag": stock_info.get("holder_tag") or context.get("holder_tag", ""),
    }


@lru_cache(maxsize=1)
def _load_global_snapshot() -> pd.DataFrame:
    if not GLOBAL_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(GLOBAL_CSV)
    df.columns = [c.strip().lower() for c in df.columns]
    if "date" not in df.columns:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def _event_impact(date_str: str) -> int:
    market_ctx = get_market_context()
    if not market_ctx:
        return 0
    score_map = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    return max((score_map.get(ev.get("impact", ""), 0) for ev in market_ctx.get_events(date_str)), default=0)


def _market_regime_context(date_str: str | None = None) -> dict:
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    snapshot = _load_global_snapshot()
    if snapshot.empty:
        return {"regime": "unknown", "nasdaq_prev_change": None, "kospi_ma20_gap": None, "event_impact": 0}

    target = pd.Timestamp(date_str)
    same_or_prev = snapshot[snapshot["date"] <= target]
    prev_global = snapshot[snapshot["date"] < target]
    nasdaq_prev = None
    kospi_gap = None

    if "nasdaq_change_pct" in prev_global.columns:
        valid = prev_global.dropna(subset=["nasdaq_change_pct"])
        if not valid.empty:
            nasdaq_prev = float(valid.iloc[-1]["nasdaq_change_pct"])

    if "kospi_close" in same_or_prev.columns:
        valid = same_or_prev.dropna(subset=["kospi_close"]).tail(20)
        if len(valid) >= 20:
            current = float(valid.iloc[-1]["kospi_close"])
            ma20 = float(valid["kospi_close"].mean())
            if ma20:
                kospi_gap = (current / ma20 - 1) * 100

    impact = _event_impact(date_str)
    if nasdaq_prev is not None and nasdaq_prev > 0 and kospi_gap is not None and kospi_gap > 0:
        regime = "rising"
    elif (nasdaq_prev is not None and abs(nasdaq_prev) >= REGIME_CHAOTIC_NASDAQ_ABS) or impact >= REGIME_EVENT_HIGH_IMPACT:
        regime = "chaotic"
    elif nasdaq_prev is not None and nasdaq_prev < 0 and kospi_gap is not None and kospi_gap < 0:
        regime = "weak"
    else:
        regime = "mixed"

    return {
        "regime": regime,
        "nasdaq_prev_change": nasdaq_prev,
        "kospi_ma20_gap": kospi_gap,
        "event_impact": impact,
    }


def _apply_regime_adjustment(score: float, risk_flags: list[str], date_str: str | None = None) -> tuple[float, str]:
    regime_ctx = _market_regime_context(date_str)
    regime = regime_ctx["regime"]
    if regime == "chaotic":
        score += BUY_REGIME_CHAOTIC_BONUS
    elif regime == "rising":
        score -= BUY_REGIME_RISING_PENALTY
        risk_flags.append("상승장보수")
    elif regime == "weak":
        score -= BUY_REGIME_WEAK_PENALTY
        risk_flags.append("약세장")
    return score, regime


def _apply_market_context_adjustment(
    code: str,
    rank: int,
    price: float,
    score: float,
    risk_flags: list[str],
    date_str: str | None = None,
) -> tuple[float, dict]:
    market_ctx = get_market_context()
    if not market_ctx:
        return score, {
            "blocked": False,
            "conservative": False,
            "event_warning": "",
            "event_adj": 0.0,
            "holder_penalty": 0.0,
        }

    score_ctx = market_ctx.stock_score_context(code, price, date_str)
    for flag in score_ctx.get("flags", []):
        if flag not in risk_flags:
            risk_flags.append(flag)

    blocked = bool(score_ctx.get("skip"))
    if score_ctx.get("conservative") and rank != 1:
        blocked = True
        if "정치위기TOP1만" not in risk_flags:
            risk_flags.append("정치위기TOP1만")

    if not blocked:
        score += score_ctx.get("score_adj", 0.0)

    return score, {
        "blocked": blocked,
        "conservative": bool(score_ctx.get("conservative")),
        "event_warning": score_ctx.get("event_warning", ""),
        "event_adj": score_ctx.get("event_adj", 0.0),
        "holder_penalty": score_ctx.get("holder_penalty", 0.0),
    }



# ──────────────────────────────────────────────
# 1단계: 워치리스트 저장
# ──────────────────────────────────────────────
def save_watchlist(result: dict):
    """스크리닝 결과에서 워치리스트 저장 (순위+타이밍 정보 포함)"""
    today = result.get("date", datetime.now().strftime("%Y-%m-%d"))
    limit = WATCHLIST_MAX_STOCKS
    market_ctx = get_market_context()
    if market_ctx and market_ctx.should_conservative(today):
        limit = 1
    top = [stock for stock in result.get("all_scored", []) if _is_allowed_rank(stock.get("rank", 99))][:limit]

    if not top:
        return

    watchlist = {
        "created": today,
        "expires": add_trading_days(today, WATCHLIST_MAX_DAYS),  # 거래일 기준
        "stocks": [],
    }

    for stock in top:
        rank = stock.get("rank", 99)
        timing = _rank_timing(rank)
        meta = _merged_company_context(stock, stock.get("price", 0))

        watchlist["stocks"].append({
            "code": stock["code"],
            "name": stock["name"],
            "rank": rank,
            "score": stock["score"],
            "entry_price": stock["price"],
            "change_rate": stock.get("change_rate", 0),
            "cci_at_screen": stock.get("cci", 0),
            "rsi_at_screen": stock.get("rsi", 0),
            "ma20_gap_at_screen": stock.get("ma20_gap", 0),
            "vp_above_pct": stock.get("vp_above_pct", 50),
            "foreign_net": stock.get("foreign_net", 0),
            "pool_type": stock.get("pool_type", "unknown"),
            "overheat": stock.get("overheat", False),
            "sweet_spot_day": timing["sweet_spot"],
            "window_start": timing["window"][0],
            "window_end": timing["window"][1],
            "rank_note": timing["note"],
            "sector": meta["sector"],
            "industry": meta["industry"],
            "company_brief": meta["company_brief"],
            "main_products": meta["main_products"],
            "holder_tag": meta["holder_tag"],
            "triggered": False,
            "trigger_date": None,
            "trigger_price": None,
            "trigger_type": None,
            "conviction": None,
        })

    save_watchlist_payload(watchlist)
    logger.info("워치리스트 저장: %d종목 (%s)", len(watchlist["stocks"]), today)


# ──────────────────────────────────────────────
# 2단계: 활성 워치리스트 로드
# ──────────────────────────────────────────────
def load_active_watchlists() -> list[dict]:
    """만료되지 않은 활성 워치리스트 로드"""
    active = []
    for data in load_active_watchlists_db():
        untriggered = []
        for stock in data.get("stocks", []):
            if stock.get("triggered"):
                continue
            if not _is_allowed_rank(stock.get("rank", 99)):
                continue
            meta = _merged_company_context(stock, stock.get("entry_price", 0))
            if not stock.get("rank_note"):
                stock["rank_note"] = _rank_timing(stock.get("rank", 99)).get("note", "")
            for key, value in meta.items():
                if not stock.get(key):
                    stock[key] = value
            untriggered.append(stock)
        if untriggered:
            data["stocks"] = untriggered
            active.append(data)

    return active


# ──────────────────────────────────────────────
# 3단계: 눌림목 감지 (순위별 타이밍 최적화)
# ──────────────────────────────────────────────
def check_pullback() -> list[dict]:
    """활성 워치리스트 눌림목 감지 (타이밍 윈도우 내에서만)"""
    from kiwoom_api import KiwoomAPI

    watchlists = load_active_watchlists()
    if not watchlists:
        logger.info("활성 워치리스트 없음")
        return []

    api = KiwoomAPI(KIWOOM_APPKEY, KIWOOM_SECRETKEY, KIWOOM_BASE_URL, API_DELAY)
    api.ensure_token()
    today = datetime.now().strftime("%Y-%m-%d")

    signals = []
    checked = set()

    for wl in watchlists:
        created = wl["created"]
        days_elapsed = trading_days_since(created)

        for stock in wl["stocks"]:
            code = stock["code"]
            if code in checked:
                continue
            checked.add(code)

            rank = stock.get("rank", 99)
            if not _is_allowed_rank(rank):
                continue
            window_start = stock.get("window_start", 1)
            window_end = stock.get("window_end", 5)
            sweet_spot = stock.get("sweet_spot_day", 2)

            # 타이밍 윈도우 밖이면 스킵
            if days_elapsed < window_start or days_elapsed > window_end:
                continue

            try:
                result = _check_single(code, stock, api, days_elapsed, sweet_spot, today)
                if result:
                    result["watchlist_date"] = created
                    result["rank"] = rank
                    result["days_elapsed"] = days_elapsed
                    result["original_score"] = stock["score"]
                    signals.append(result)

                    stock["triggered"] = True
                    stock["trigger_date"] = datetime.now().strftime("%Y-%m-%d")
                    stock["trigger_price"] = result["current_price"]
                    stock["trigger_type"] = result["signal_type"]
                    stock["conviction"] = result["conviction"]

            except Exception as e:
                logger.debug("눌림목 체크 실패 [%s]: %s", code, e)

    # 워치리스트 업데이트 저장
    for wl in watchlists:
        save_watchlist_payload(wl)

    if signals:
        signals.sort(key=lambda x: x.get("conviction_score", 0), reverse=True)
        logger.info("눌림목 신호: %d건", len(signals))
    else:
        logger.info("눌림목 체크: %d종목, 신호 없음", len(checked))

    return signals


# ──────────────────────────────────────────────
# 매일 15:00: 감시 종목 스캔 → TOP3 (API + DART + 뉴스)
# ──────────────────────────────────────────────
def daily_top3() -> list[dict]:
    """
    활성 워치리스트 전체를 스코어링 → 당일 매수 후보 반환.
    15:00에 호출 — 키움 API로 현재가 + DART 재확인 + 네이버 뉴스.
    """
    from kiwoom_api import KiwoomAPI

    watchlists = load_active_watchlists()
    if not watchlists:
        logger.info("활성 워치리스트 없음 → daily_top3 스킵")
        return []

    api = KiwoomAPI(KIWOOM_APPKEY, KIWOOM_SECRETKEY, KIWOOM_BASE_URL, API_DELAY)
    api.ensure_token()
    today = datetime.now().strftime("%Y-%m-%d")
    market_ctx = get_market_context()
    today_ctx = market_ctx.today_context(today) if market_ctx else {}

    # ⓪ 시장 지수 조회 (웹훅 상단 표시용)
    market_snapshot = {}
    try:
        kospi = api.get_index_price("001")
        market_snapshot["kospi"] = kospi["price"]
        market_snapshot["kospi_change"] = kospi["change_rate"]
    except Exception:
        market_snapshot["kospi"] = 0
        market_snapshot["kospi_change"] = 0
    try:
        kosdaq = api.get_index_price("101")
        market_snapshot["kosdaq"] = kosdaq["price"]
        market_snapshot["kosdaq_change"] = kosdaq["change_rate"]
    except Exception:
        market_snapshot["kosdaq"] = 0
        market_snapshot["kosdaq_change"] = 0
    try:
        gdf = pd.read_csv(GLOBAL_CSV)
        gdf.columns = [c.strip().lower() for c in gdf.columns]
        nasdaq_valid = gdf.dropna(subset=["nasdaq_change_pct"])
        if len(nasdaq_valid) > 0:
            market_snapshot["nasdaq_change"] = round(float(nasdaq_valid.iloc[-1]["nasdaq_change_pct"]), 2)
        else:
            market_snapshot["nasdaq_change"] = 0
    except Exception:
        market_snapshot["nasdaq_change"] = 0

    all_scored = []
    checked = set()

    for wl in watchlists:
        created = wl["created"]
        days_elapsed = trading_days_since(created)

        if days_elapsed < 1:
            continue

        for stock in wl["stocks"]:
            code = stock["code"]
            if code in checked:
                continue
            checked.add(code)

            rank = stock.get("rank", 99)
            if not _is_allowed_rank(rank):
                continue
            sweet_spot = stock.get("sweet_spot_day", 2)

            try:
                # ① 현재가 조회
                cur = api.get_current_price(code)
                if cur["price"] <= 0:
                    logger.debug("%s: 현재가 0 → 거래정지 가능", stock["name"])
                    continue

                # ② 기술적 스코어링 (OHLCV + 현재가)
                result = _score_stock(code, stock, cur, days_elapsed, sweet_spot, today)
                if not result:
                    continue

                # ③ DART 공시 재확인
                dart_info = _check_dart(code)
                result["dart_risk"] = dart_info["risk"]
                result["dart_note"] = dart_info["note"]

                # DART 위험 감점
                if dart_info["risk"] == "위험":
                    result["conviction_score"] -= BUY_DART_DANGER_PENALTY
                    result["risk_flags"] = result.get("risk_flags", []) + ["DART위험"]
                elif dart_info["risk"] == "주의":
                    result["conviction_score"] -= BUY_DART_CAUTION_PENALTY
                    result["risk_flags"] = result.get("risk_flags", []) + ["DART주의"]

                # ④ 뉴스 체크
                news_info = _check_news(stock.get("name", ""))
                result["news_risk"] = news_info["risk"]
                result["news_summary"] = news_info["summary"]
                result["news_highlight"] = news_info.get("highlight", "")

                if news_info["risk"] == "위험":
                    result["conviction_score"] -= BUY_NEWS_DANGER_PENALTY
                    result["risk_flags"] = result.get("risk_flags", []) + ["뉴스위험"]
                elif news_info["risk"] == "주의":
                    result["conviction_score"] -= BUY_NEWS_CAUTION_PENALTY
                    result["risk_flags"] = result.get("risk_flags", []) + ["뉴스주의"]

                # ⑤ 수급 체크 (공매도·대차·신용·투자자·체결강도)
                supply_info = _check_supply(code, api)
                result["supply"] = supply_info
                result["supply_line"] = supply_info.get("summary_line", "")
                supply_score = supply_info.get("total_score", 0)

                # 수급 2단계 감점/가점
                if supply_score <= SUPPLY_DANGER_THRESH:
                    result["conviction_score"] -= SUPPLY_DANGER_PENALTY
                    result["risk_flags"] = result.get("risk_flags", []) + ["수급위험"]
                elif supply_score <= SUPPLY_CAUTION_THRESH:
                    result["conviction_score"] -= SUPPLY_CAUTION_PENALTY
                    result["risk_flags"] = result.get("risk_flags", []) + ["수급주의"]
                elif supply_score >= SUPPLY_GOOD_THRESH:
                    result["conviction_score"] += SUPPLY_GOOD_BONUS
                    result["risk_flags"] = result.get("risk_flags", []) + ["수급양호"]

                # 등급 재계산 (감점 반영)
                s = result["conviction_score"]
                result["risk_flags"] = _dedupe_flags(result.get("risk_flags", []))
                result["conviction"] = _conviction_with_guardrails(
                    s,
                    result.get("risk_flags", []),
                    dart_risk=result.get("dart_risk", ""),
                    news_risk=result.get("news_risk", ""),
                )

                result["watchlist_date"] = created
                result["rank"] = rank
                result["days_elapsed"] = days_elapsed
                result["original_score"] = stock["score"]

                # 액션 라벨 재생성 (DART/뉴스 감점 반영)
                result["action"] = make_action_label(result)
                all_scored.append(result)

            except Exception as e:
                logger.debug("daily 스코어링 실패 [%s]: %s", code, e)

    all_scored.sort(key=lambda x: x.get("conviction_score", 0), reverse=True)
    pick_limit = DAILY_PICK_TOP_K
    market_ctx = get_market_context()
    if market_ctx and market_ctx.should_conservative(today):
        pick_limit = 1

    # ── v4 장세 프리셋 ──
    regime_ctx = _market_regime_context(today)
    regime = regime_ctx.get("regime", "mixed")
    if regime == "rising":
        # 공격장: 기본 TOP5, A 기준 완화(-3)
        logger.info("📈 장세 프리셋: 공격장 (rising)")
        for s in all_scored:
            s["conviction_score"] += 3  # 기대감 보정
            s["conviction"] = _conviction_from_score(s["conviction_score"])
    elif regime == "weak":
        # 방어장: TOP3만, A만 추천
        pick_limit = min(pick_limit, 3)
        logger.info("📉 장세 프리셋: 방어장 (weak) → TOP%d", pick_limit)
        # C등급 제거
        all_scored = [s for s in all_scored if s.get("conviction") in ("A", "B")]
    elif regime == "chaotic":
        # 혼란장: TOP3만, 보수적
        pick_limit = min(pick_limit, 3)
        logger.info("🌪️ 장세 프리셋: 혼란장 (chaotic) → TOP%d", pick_limit)

    top3 = all_scored[:pick_limit]

    # 시장 지수 데이터 + 장세 프리셋을 각 pick에 첨부
    for pick in top3:
        pick["market_snapshot"] = market_snapshot
        pick["market_regime"] = pick.get("market_regime", regime)
        pick["pick_date"] = today

    # ⑦ 테마 강도 (TOP에만 — API)
    for pick in top3:
        try:
            themes = api.get_stock_themes(pick["code"])
            if themes:
                # 가장 강한 테마 표시
                best = max(themes, key=lambda t: t["change_rate"])
                pick["theme_name"] = best["name"]
                pick["theme_change"] = best["change_rate"]
                pick["theme_count"] = len(themes)
                if best["change_rate"] > 0:
                    pick["theme_line"] = (
                        f"🔥 {best['name']} ({best['change_rate']:+.1f}%)"
                        + (f" 외 {len(themes)-1}개 테마" if len(themes) > 1 else "")
                    )
                else:
                    pick["theme_line"] = (
                        f"📊 {best['name']} ({best['change_rate']:+.1f}%)"
                        + (f" 외 {len(themes)-1}개 테마" if len(themes) > 1 else "")
                    )
            else:
                pick["theme_name"] = ""
                pick["theme_line"] = ""
        except Exception as e:
            logger.debug("테마 조회 실패 [%s]: %s", pick.get("name"), e)
            pick["theme_name"] = ""
            pick["theme_line"] = ""

    # 시장 전체 핫 테마 (1회 호출)
    hot_themes = []
    try:
        hot_themes = api.get_theme_groups(sort="3", period="1")[:3]
        market_theme_text = " | ".join(
            f"{t['name']}({t['change_rate']:+.1f}%)" for t in hot_themes
        )
        for pick in top3:
            pick["market_themes"] = market_theme_text
            pick["market_theme_items"] = hot_themes
    except Exception:
        pass

    # ⑧ 외신 거시 리스크 (1회) + 유튜브 테마 과열 (테마별 최대 3회)
    macro_theme_names = []
    for pick in top3:
        theme_name = pick.get("theme_name", "")
        if theme_name and theme_name not in macro_theme_names:
            macro_theme_names.append(theme_name)
    for theme in hot_themes:
        theme_name = theme.get("name", "")
        if theme_name and theme_name not in macro_theme_names:
            macro_theme_names.append(theme_name)

    macro_risk = _check_foreign_macro(macro_theme_names[:3])
    macro_note = macro_risk.get("note", "")
    macro_signal = macro_risk.get("signal", "중립")
    if macro_note:
        logger.info("  외신 거시: %s (hits=%s)", macro_note, macro_risk.get("hits", 0))

    theme_risk_map = {}
    theme_names = []
    for pick in top3:
        theme_name = pick.get("theme_name", "")
        if theme_name and theme_name not in theme_names:
            theme_names.append(theme_name)
    for theme in theme_names[:3]:
        yt = _check_theme_youtube(theme)
        theme_risk_map[theme] = yt
        yt_note = yt.get("note", "") or "결과없음"
        logger.info("  유튜브 테마 [%s]: %s (videos=%s)", theme, yt_note, yt.get("video_count", 0))

    for pick in top3:
        pick["macro_risk_note"] = macro_note
        pick["foreign_macro_risk"] = macro_signal

        if macro_signal == "주의":
            pick["risk_flags"] = pick.get("risk_flags", []) + ["외신경고"]

        theme_result = theme_risk_map.get(pick.get("theme_name", ""), {})
        pick["youtube_note"] = theme_result.get("note", "")
        pick["youtube_risk"] = theme_result.get("signal", "중립")
        if theme_result.get("signal") == "주의":
            pick["risk_flags"] = pick.get("risk_flags", []) + ["테마과열"]

        if not pick.get("event_warning"):
            pick["event_warning"] = today_ctx.get("event_warning", "")

        pick["risk_flags"] = _dedupe_flags(pick.get("risk_flags", []))
        pick["conviction"] = _conviction_with_guardrails(
            pick.get("conviction_score", 0),
            pick.get("risk_flags", []),
            dart_risk=pick.get("dart_risk", ""),
            news_risk=pick.get("news_risk", ""),
        )
        pick["action"] = make_action_label(pick)

    logger.info("daily_top3: %d종목 스코어링 → TOP%d 선정", len(all_scored), pick_limit)
    for i, s in enumerate(top3):
        flags = ", ".join(s.get("risk_flags", [])) or "없음"
        extras = []
        if s.get("foreign_news_note"):
            extras.append(f"외신:{s['foreign_news_note'][:20]}")
        if s.get("youtube_note"):
            extras.append(f"YT:{s['youtube_note'][:20]}")
        extra_str = f" | {', '.join(extras)}" if extras else ""
        logger.info("  %d. [%s] #%d %s — %d점 (%s) 조건%d개 위험:%s%s",
                     i + 1, s["conviction"], s["rank"], s["name"],
                     s["conviction_score"], s["signal_type"] or "조건없음",
                     s.get("conditions_met", 0), flags, extra_str)

    try:
        regime = top3[0].get("market_regime") if top3 else _market_regime_context(today).get("regime", "")
        save_market_regime_daily(
            {
                "date": today,
                "kospi_change": market_snapshot.get("kospi_change"),
                "kosdaq_change": market_snapshot.get("kosdaq_change"),
                "nasdaq_change": market_snapshot.get("nasdaq_change"),
                "regime": regime,
                "themes": [
                    {"name": item.get("name", ""), "change_rate": item.get("change_rate", 0)}
                    for item in hot_themes
                ],
                "macro_risk": macro_note,
                "event_warning": today_ctx.get("event_warning", ""),
            }
        )
    except Exception as e:
        logger.debug("market_regime_daily 저장 실패: %s", e)

    # v4: 조건 스냅샷 DB 저장 (분석용)
    try:
        from storage import delete_pick_snapshots, save_pick_snapshot
        delete_pick_snapshots(today)
        for pick in top3:
            save_pick_snapshot(pick, market_snapshot)
        logger.info("pick_snapshots 저장: %d건", len(top3))
    except Exception as e:
        logger.debug("스냅샷 저장 실패: %s", e)

    return top3


def _check_dart(code: str) -> dict:
    """DART 공시 재확인 (스크리닝 후 변동 체크)"""
    try:
        from dart_checker import DartChecker
        dc = DartChecker()
        return dc.check(code)
    except Exception:
        return {"risk": "확인불가", "note": ""}


def _check_news(stock_name: str) -> dict:
    """뉴스 위험 체크 (네이버 + Gemini)"""
    try:
        from news_checker import check_stock_news
        return check_stock_news(stock_name)
    except Exception:
        return {"risk": "확인불가", "summary": "뉴스 체크 실패"}


def _check_supply(code: str, api) -> dict:
    """수급 종합 체크 (공매도·대차·신용·투자자·체결강도)"""
    try:
        from supply_checker import check_supply
        return check_supply(code, api)
    except Exception:
        return {"summary_line": "", "total_score": 0}


def _check_foreign_macro(theme_names: list[str] | None = None) -> dict:
    """시장 전체용 거시 외신 체크"""
    try:
        from foreign_news_checker import check_macro_risk
        return check_macro_risk(theme_names=theme_names)
    except Exception as e:
        logger.debug("외신 거시 체크 실패: %s", e)
        return {"signal": "중립", "note": "", "hits": 0, "score": 0}


def _check_theme_youtube(theme_name: str) -> dict:
    """유튜브 테마 과열 체크"""
    try:
        from youtube_checker import check_theme_overheat
        return check_theme_overheat(theme_name)
    except Exception as e:
        logger.debug("유튜브 체크 실패 [%s]: %s", theme_name, e)
        return {"signal": "중립", "note": "", "video_count": 0, "score": 0}


def _score_stock(
    code: str,
    stock_info: dict,
    cur_price: dict,
    days_elapsed: int,
    sweet_spot: int,
    date_str: str | None = None,
) -> dict | None:
    """
    하이브리드 스코어링: OHLCV(과거) + API(현재가).
    15:00 호출이므로 CSV는 어제까지, 현재가는 API에서.
    """
    code = code.strip().zfill(6)
    df = _load_recent_ohlcv(code)
    if df is None:
        return None

    price = cur_price["price"]
    volume = cur_price.get("volume", 0)
    entry_price = stock_info.get("entry_price", price)
    snapshot = _calc_pullback_snapshot(df, price, volume, entry_price)
    ma5_gap = snapshot["ma5_gap"]
    vol_decline = snapshot["vol_decline"]
    bb_position = snapshot["bb_position"]
    price_change = snapshot["price_change"]
    cci_now, rsi_now = _calc_rsi_cci(df)
    recent_20 = list(df["close"].tail(19).values) + [price]
    ma20_now = float(np.mean(recent_20)) if len(recent_20) == 20 else 0
    ma20_gap_now = (price / ma20_now - 1) * 100 if ma20_now > 0 else 0

    # ── 구조점수 (0~55점): 차트가 지금 예쁜가 ──
    tech = []
    structure = 0
    risk_flags = []

    # MA5 근접 (0~15)
    if ma5_gap <= PULLBACK_MA5_GAP:
        tech.append("MA5터치")
        structure += 15
    elif ma5_gap <= PULLBACK_MA5_GAP * 2:
        structure += 8

    # 거래량 감소 (0~12)
    if vol_decline <= PULLBACK_VOL_DECLINE:
        tech.append("거래량감소")
        structure += 12
    elif vol_decline <= PULLBACK_VOL_DECLINE * 1.5:
        structure += 6

    # BB 하단 (0~10)
    if bb_position <= PULLBACK_BB_LOWER:
        tech.append("BB하단")
        structure += 10
    elif bb_position <= PULLBACK_BB_LOWER * 1.5:
        structure += 5

    # 가격 조정 깊이 (0~6)
    if price_change < -5:
        tech.append("깊은조정")
        structure += 6
    elif price_change < -2:
        tech.append("가격조정")
        structure += 3

    # CCI 냉각 (0~6)
    cci_at_screen = stock_info.get("cci_at_screen", 0)
    if cci_at_screen > 150 and cci_now < cci_at_screen * 0.7:
        tech.append("CCI냉각")
        structure += 6

    # RSI 위치 (0~6)
    if rsi_now < 40:
        tech.append("RSI과매도")
        structure += 6
    elif rsi_now < 50:
        structure += 3

    # 최소 1개 이상 충족해야 매수 후보
    if len(tech) == 0:
        return None

    # ── 기대감점수 (0~45점): 왜 다시 갈 수 있는가 ──
    expectation = 0

    # 복합 신호 보너스 (0~5)
    if len(tech) >= 3:
        expectation += 5
    elif len(tech) >= BUY_MIN_CONDITIONS:
        expectation += 3

    # 타이밍 정확도 (0~30)
    window_start = stock_info.get("window_start", 1)
    window_end = stock_info.get("window_end", 5)
    timing_diff = abs(days_elapsed - sweet_spot)
    in_window = window_start <= days_elapsed <= window_end

    if in_window and timing_diff == 0:
        expectation += 30
    elif in_window and timing_diff == 1:
        expectation += 22
    elif in_window:
        expectation += 15
    elif days_elapsed < window_start:
        expectation += 5

    # 순위 보너스 (0~10)
    rank = stock_info.get("rank", 99)
    rank_bonus = RANK_PULLBACK_BONUS.get(rank, 0)
    expectation += max(0, rank_bonus + 5)  # shift: rank1=10, rank2=5, rank3=5, rank4=0, rank5=0

    # ── 리스크감점 (0~-30): 좋아 보여도 위험한가 ──
    risk_penalty = 0

    # D+1 이른 진입
    if days_elapsed <= 1:
        risk_penalty -= 8
        risk_flags.append("D+1이른진입")

    # 과열
    if stock_info.get("overheat"):
        risk_penalty -= 12
        risk_flags.append("과열")

    # 급락
    if price_change < -10:
        risk_penalty -= 5
        risk_flags.append("급락")

    # ── 최종 합산 (100점 만점) ──
    score = structure + expectation + risk_penalty

    score, regime = _apply_regime_adjustment(score, risk_flags, date_str)
    score, market_ctx_info = _apply_market_context_adjustment(code, rank, price, score, risk_flags, date_str)
    if market_ctx_info["blocked"]:
        return None

    # ── ABC 등급 ──
    risk_flags = _dedupe_flags(risk_flags)
    conviction = _conviction_with_guardrails(score, risk_flags)

    rank_info = _rank_timing(rank)
    meta = _merged_company_context(stock_info, price)

    result = {
        "code": code,
        "name": stock_info.get("name", code),
        "sector": meta["sector"],
        "industry": meta["industry"],
        "company_brief": meta["company_brief"],
        "main_products": meta["main_products"],
        "holder_tag": meta["holder_tag"],
        "current_price": price,
        "change_rate": cur_price.get("change_rate", 0),
        "signal_type": "+".join(tech) if tech else "",
        "ma5_gap": round(ma5_gap, 1),
        "ma20_gap": round(ma20_gap_now, 1),
        "vol_decline": round(vol_decline, 2),
        "bb_position": round(bb_position, 2),
        "price_change_from_screen": round(price_change, 1),
        "conditions_met": len(tech),
        "conviction": conviction,
        "conviction_score": score,
        "structure_score": structure,
        "expectation_score": expectation,
        "risk_score": risk_penalty,
        "sweet_spot_day": sweet_spot,
        "in_window": in_window,
        "cci": round(cci_now, 1),
        "rsi": round(rsi_now, 1),
        "vp_above_pct": stock_info.get("vp_above_pct"),
        "overheat": bool(stock_info.get("overheat")),
        "rank_note": rank_info.get("note", ""),
        "market_regime": regime,
        "event_warning": market_ctx_info["event_warning"],
        "calendar_adj": market_ctx_info["event_adj"],
        "holder_penalty": market_ctx_info["holder_penalty"],
        "risk_flags": risk_flags,
        "pool_type": stock_info.get("pool_type", "unknown"),
        "foreign_net": stock_info.get("foreign_net", 0),
        "dart_risk": "",
        "dart_note": "",
        "news_risk": "",
        "news_summary": "",
    }
    result["action"] = make_action_label(result)
    return result


def _check_single(
    code: str,
    stock_info: dict,
    api,
    days_elapsed: int,
    sweet_spot: int,
    date_str: str | None = None,
) -> dict | None:
    """개별 종목 눌림목 조건 체크 (순위+타이밍 반영 확신도)"""
    code = code.strip().zfill(6)
    df = _load_recent_ohlcv(code)
    if df is None:
        return None

    cur = api.get_current_price(code)
    if cur["price"] <= 0:
        return None

    price = cur["price"]
    volume = cur["volume"]
    entry_price = stock_info.get("entry_price", price)
    snapshot = _calc_pullback_snapshot(df, price, volume, entry_price)
    ma5_gap = snapshot["ma5_gap"]
    vol_decline = snapshot["vol_decline"]
    bb_position = snapshot["bb_position"]
    price_change = snapshot["price_change"]

    # ── 기술적 조건 ──
    tech = []
    if ma5_gap <= PULLBACK_MA5_GAP:
        tech.append("MA5터치")
    if vol_decline <= PULLBACK_VOL_DECLINE:
        tech.append("거래량감소")
    if bb_position <= PULLBACK_BB_LOWER:
        tech.append("BB하단")
    if price_change < -2:
        tech.append("가격조정")

    if not tech:
        return None  # 기술조건 0개면 제외, 1개 이상이면 점수로 판단

    # ── 확신도 점수 (0~100) ──
    score = 0
    risk_flags = []

    # 기술적 조건 수 (최대 40)
    score += min(40, len(tech) * 10)

    # 타이밍 정확도 (최대 30)
    timing_diff = abs(days_elapsed - sweet_spot)
    score += [30, 20, 10, 5][min(timing_diff, 3)]

    # 순위 보너스 (최대 20)
    rank = stock_info.get("rank", 99)
    rank_bonus = RANK_PULLBACK_BONUS.get(rank, 0)
    score += rank_bonus

    # 과열 감점
    if stock_info.get("overheat"):
        score -= 15
        risk_flags.append("과열")

    score, regime = _apply_regime_adjustment(score, risk_flags, date_str)
    score, market_ctx_info = _apply_market_context_adjustment(code, rank, price, score, risk_flags, date_str)
    if market_ctx_info["blocked"]:
        return None

    # ── 등급 결정 ──
    conviction = _conviction_from_score(score)

    # C등급 + 기술 조건 1개면 제외 (노이즈)
    if conviction == "C" and len(tech) < 2:
        return None

    rank_info = _rank_timing(rank)
    meta = _merged_company_context(stock_info, price)

    return {
        "code": code,
        "name": stock_info.get("name", code),
        "sector": meta["sector"],
        "industry": meta["industry"],
        "company_brief": meta["company_brief"],
        "holder_tag": meta["holder_tag"],
        "current_price": price,
        "signal_type": "+".join(tech),
        "ma5_gap": round(ma5_gap, 1),
        "vol_decline": round(vol_decline, 2),
        "bb_position": round(bb_position, 2),
        "price_change_from_screen": round(price_change, 1),
        "conditions_met": len(tech),
        "conviction": conviction,
        "conviction_score": score,
        "sweet_spot_day": sweet_spot,
        "rank_note": rank_info.get("note", ""),
        "market_regime": regime,
        "event_warning": market_ctx_info["event_warning"],
        "calendar_adj": market_ctx_info["event_adj"],
        "holder_penalty": market_ctx_info["holder_penalty"],
        "risk_flags": risk_flags,
    }


# ──────────────────────────────────────────────
# 상태 조회
# ──────────────────────────────────────────────
def show_status():
    """현재 워치리스트 상태 + 타이밍 가이드"""
    watchlists = load_active_watchlists()

    if not watchlists:
        print("활성 워치리스트 없음")
        return

    print("=" * 70)
    print("  활성 워치리스트 (순위별 타이밍 가이드)")
    print("=" * 70)

    for wl in watchlists:
        created = wl["created"]
        days = trading_days_since(created)
        print(f"\n[{created}] D+{days} | 만료: {wl['expires']}")

        for s in wl["stocks"]:
            rank = s.get("rank", "?")
            timing = _rank_timing(rank)
            sweet = s.get("sweet_spot_day", "?")
            w_start = s.get("window_start", "?")
            w_end = s.get("window_end", "?")

            if s.get("triggered"):
                status = f"  -> {s['conviction']}등급 | {s['trigger_date']} {s['trigger_type']}"
            elif days < w_start:
                status = f"  -> 대기 (D+{w_start}부터 감시, 최적 D+{sweet})"
            elif days <= w_end:
                status = f"  -> 감시중 (최적 D+{sweet}, 잔여 {w_end - days}일)"
            else:
                status = "  -> 윈도우 만료"

            note = timing.get("note", "")
            print(f"  #{rank} {s['name']} ({s['code']}) -- {s['score']}점")
            print(f"  {status}")
            if note:
                print(f"     {note}")


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="ClosingBell -- pullback monitor")
    parser.add_argument("--status", action="store_true", help="watchlist status")
    args = parser.parse_args()

    if args.status:
        show_status()
    else:
        signals = check_pullback()
        for sig in signals:
            conv = sig["conviction"]
            emoji = {"A": "***", "B": "**", "C": "*"}.get(conv, "")
            print(f"[{conv}] #{sig['rank']} {sig['name']} "
                  f"-- {sig['signal_type']} "
                  f"(D+{sig['days_elapsed']})")
