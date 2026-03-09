"""
ClosingBell v3.5 — 눌림목 모니터 (순위별 타이밍 최적화)
======================================================
백테스트 데이터 기반 순위별 최적 진입 타이밍:

  1위: D+1 눌림목 진입 → D+2 승률 75%, 평균 +3.9%  ← 빠르게 잡아야
  2위: 전 구간 약세 → 우선순위 낮음 (참고용)
  3위: D+2~D+3 눌림목 진입 → D+3 승률 71%, 평균 +8.0%  ← 기다려야

14:50 최종 체크에서 조건 충족 시 디스코드 웹훅 발송.
웹훅에 확신도(A/B/C) 표시 → A등급만 매수 권장.

사용법:
    python watchlist_monitor.py              # 워치리스트 체크
    python watchlist_monitor.py --status     # 현재 상태
"""
import json
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

from config import (
    KIWOOM_BASE_URL, KIWOOM_APPKEY, KIWOOM_SECRETKEY, API_DELAY,
    OHLCV_DIR, LOG_DIR,
    WATCHLIST_DIR, WATCHLIST_MAX_DAYS,
    PULLBACK_MA5_GAP, PULLBACK_VOL_DECLINE, PULLBACK_BB_LOWER,
)

logger = logging.getLogger("closingbell")

# ──────────────────────────────────────────────
# 순위별 최적 타이밍 윈도우 (백테스트 18일 224건 기반)
# ──────────────────────────────────────────────
RANK_TIMING = {
    1: {"sweet_spot": 1, "window": (1, 2), "exp_wr": 75, "exp_ret": 3.9,
        "note": "빠른 반등형 — D+1 눌림목이 최적"},
    2: {"sweet_spot": 4, "window": (3, 5), "exp_wr": 64, "exp_ret": -0.6,
        "note": "느린 회복형 — 우선순위 낮음"},
    3: {"sweet_spot": 3, "window": (2, 4), "exp_wr": 71, "exp_ret": 8.0,
        "note": "깊은 조정 후 급반등 — 기다려야 큰 수익"},
}


def _trading_days_since(date_str: str) -> int:
    """스크리닝일로부터 오늘까지 거래일 수"""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    today = datetime.now()
    count = 0
    current = d + timedelta(days=1)
    while current.date() <= today.date():
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return count


def _add_trading_days(date_str: str, n: int) -> str:
    """date_str로부터 N거래일 후 날짜 반환"""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    added = 0
    current = d
    while added < n:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current.strftime("%Y-%m-%d")


# ──────────────────────────────────────────────
# 1단계: 워치리스트 저장
# ──────────────────────────────────────────────
def save_watchlist(result: dict):
    """스크리닝 결과에서 워치리스트 저장 (순위+타이밍 정보 포함)"""
    today = result.get("date", datetime.now().strftime("%Y-%m-%d"))
    top = result.get("all_scored", [])[:5]

    if not top:
        return

    watchlist = {
        "created": today,
        "expires": _add_trading_days(today, WATCHLIST_MAX_DAYS),  # 거래일 기준
        "stocks": [],
    }

    for stock in top:
        rank = stock.get("rank", 99)
        timing = RANK_TIMING.get(rank, RANK_TIMING[3])

        watchlist["stocks"].append({
            "code": stock["code"],
            "name": stock["name"],
            "rank": rank,
            "score": stock["score"],
            "entry_price": stock["price"],
            "cci_at_screen": stock.get("cci", 0),
            "rsi_at_screen": stock.get("rsi", 0),
            "ma20_gap_at_screen": stock.get("ma20_gap", 0),
            "overheat": stock.get("overheat", False),
            "sweet_spot_day": timing["sweet_spot"],
            "window_start": timing["window"][0],
            "window_end": timing["window"][1],
            "triggered": False,
            "trigger_date": None,
            "trigger_price": None,
            "trigger_type": None,
            "conviction": None,
        })

    path = WATCHLIST_DIR / f"{today}.json"
    path.write_text(
        json.dumps(watchlist, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("워치리스트 저장: %d종목 (%s)", len(watchlist["stocks"]), path.name)


# ──────────────────────────────────────────────
# 2단계: 활성 워치리스트 로드
# ──────────────────────────────────────────────
def load_active_watchlists() -> list[dict]:
    """만료되지 않은 활성 워치리스트 로드"""
    today = datetime.now().strftime("%Y-%m-%d")
    active = []

    for f in sorted(WATCHLIST_DIR.glob("*.json"), reverse=True):  # 최신 먼저
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("expires", "") >= today:
                untriggered = [
                    s for s in data.get("stocks", [])
                    if not s.get("triggered")
                ]
                if untriggered:
                    data["stocks"] = untriggered
                    active.append(data)
        except Exception:
            pass

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

    signals = []
    checked = set()

    for wl in watchlists:
        created = wl["created"]
        days_elapsed = _trading_days_since(created)

        for stock in wl["stocks"]:
            code = stock["code"]
            if code in checked:
                continue
            checked.add(code)

            rank = stock.get("rank", 99)
            window_start = stock.get("window_start", 1)
            window_end = stock.get("window_end", 5)
            sweet_spot = stock.get("sweet_spot_day", 2)

            # 타이밍 윈도우 밖이면 스킵
            if days_elapsed < window_start or days_elapsed > window_end:
                continue

            try:
                result = _check_single(code, stock, api, days_elapsed, sweet_spot)
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
        path = WATCHLIST_DIR / f"{wl['created']}.json"
        if path.exists():
            path.write_text(
                json.dumps(wl, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

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
    활성 워치리스트 전체를 스코어링 → TOP3 반환.
    15:00에 호출 — 키움 API로 현재가 + DART 재확인 + 네이버 뉴스.
    """
    from kiwoom_api import KiwoomAPI

    watchlists = load_active_watchlists()
    if not watchlists:
        logger.info("활성 워치리스트 없음 → daily_top3 스킵")
        return []

    api = KiwoomAPI(KIWOOM_APPKEY, KIWOOM_SECRETKEY, KIWOOM_BASE_URL, API_DELAY)
    api.ensure_token()

    all_scored = []
    checked = set()

    for wl in watchlists:
        created = wl["created"]
        days_elapsed = _trading_days_since(created)

        if days_elapsed < 1:
            continue

        for stock in wl["stocks"]:
            code = stock["code"]
            if code in checked:
                continue
            checked.add(code)

            rank = stock.get("rank", 99)
            sweet_spot = stock.get("sweet_spot_day", 2)

            try:
                # ① 현재가 조회
                cur = api.get_current_price(code)
                if cur["price"] <= 0:
                    logger.debug("%s: 현재가 0 → 거래정지 가능", stock["name"])
                    continue

                # ② 기술적 스코어링 (OHLCV + 현재가)
                result = _score_stock(code, stock, cur, days_elapsed, sweet_spot)
                if not result:
                    continue

                # ③ DART 공시 재확인
                dart_info = _check_dart(code)
                result["dart_risk"] = dart_info["risk"]
                result["dart_note"] = dart_info["note"]

                # DART 위험 감점
                if dart_info["risk"] == "위험":
                    result["conviction_score"] -= 10
                    result["risk_flags"] = result.get("risk_flags", []) + ["DART위험"]
                elif dart_info["risk"] == "주의":
                    result["conviction_score"] -= 5
                    result["risk_flags"] = result.get("risk_flags", []) + ["DART주의"]

                # ④ 뉴스 체크
                news_info = _check_news(stock.get("name", ""))
                result["news_risk"] = news_info["risk"]
                result["news_summary"] = news_info["summary"]

                if news_info["risk"] == "위험":
                    result["conviction_score"] -= 10
                    result["risk_flags"] = result.get("risk_flags", []) + ["뉴스위험"]
                elif news_info["risk"] == "주의":
                    result["conviction_score"] -= 3

                # 등급 재계산 (감점 반영)
                s = result["conviction_score"]
                result["conviction"] = "A" if s >= 60 else ("B" if s >= 40 else "C")

                result["watchlist_date"] = created
                result["rank"] = rank
                result["days_elapsed"] = days_elapsed
                result["original_score"] = stock["score"]
                all_scored.append(result)

            except Exception as e:
                logger.debug("daily 스코어링 실패 [%s]: %s", code, e)

    all_scored.sort(key=lambda x: x.get("conviction_score", 0), reverse=True)
    top3 = all_scored[:3]

    logger.info("daily_top3: %d종목 스코어링 → TOP3 선정", len(all_scored))
    for i, s in enumerate(top3):
        flags = ", ".join(s.get("risk_flags", [])) or "없음"
        logger.info("  %d. [%s] #%d %s — %d점 (%s) 위험:%s",
                     i + 1, s["conviction"], s["rank"], s["name"],
                     s["conviction_score"], s["signal_type"] or "조건없음", flags)

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


def _score_stock(code: str, stock_info: dict, cur_price: dict,
                  days_elapsed: int, sweet_spot: int) -> dict | None:
    """
    하이브리드 스코어링: OHLCV(과거) + API(현재가).
    15:00 호출이므로 CSV는 어제까지, 현재가는 API에서.
    """
    code = code.strip().zfill(6)

    csv_path = OHLCV_DIR / f"{code}.csv"
    if not csv_path.exists():
        return None

    df = pd.read_csv(csv_path)
    df.columns = [c.lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").tail(30)

    if len(df) < 20:
        return None

    price = cur_price["price"]
    volume = cur_price.get("volume", 0)

    # MA5 (CSV 최근 4일 + 오늘 현재가)
    recent_closes = list(df["close"].tail(4).values) + [price]
    ma5 = np.mean(recent_closes)
    ma5_gap = abs((price / ma5 - 1) * 100) if ma5 > 0 else 999

    # 거래량 감소율
    vol_ma20 = df["volume"].tail(20).mean()
    vol_decline = volume / vol_ma20 if vol_ma20 > 0 else 1.0

    # 볼린저밴드 (CSV 19일 + 오늘)
    recent_20 = list(df["close"].tail(19).values) + [price]
    bb_mid = np.mean(recent_20)
    bb_std = np.std(recent_20)
    bb_lower = bb_mid - 2 * bb_std
    bb_upper = bb_mid + 2 * bb_std
    bb_position = (price - bb_lower) / (bb_upper - bb_lower) if bb_upper > bb_lower else 0.5

    # 스크리닝 대비 가격 변동
    entry_price = stock_info.get("entry_price", price)
    price_change = (price / entry_price - 1) * 100 if entry_price > 0 else 0

    # CCI (14일)
    tp = (df["high"] + df["low"] + df["close"]) / 3
    sma_tp = tp.rolling(14).mean()
    mad = tp.rolling(14).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    cci_series = (tp - sma_tp) / (0.015 * mad)
    cci_now = float(cci_series.iloc[-1]) if pd.notna(cci_series.iloc[-1]) else 0

    # RSI (14일)
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi_series = 100 - (100 / (1 + rs))
    rsi_now = float(rsi_series.iloc[-1]) if pd.notna(rsi_series.iloc[-1]) else 50

    # ── 기술적 조건 점수화 ──
    tech = []
    score = 0
    risk_flags = []

    if ma5_gap <= PULLBACK_MA5_GAP:
        tech.append("MA5터치")
        score += 15
    elif ma5_gap <= PULLBACK_MA5_GAP * 2:
        score += 8

    if vol_decline <= PULLBACK_VOL_DECLINE:
        tech.append("거래량감소")
        score += 10
    elif vol_decline <= PULLBACK_VOL_DECLINE * 1.5:
        score += 5

    if bb_position <= PULLBACK_BB_LOWER:
        tech.append("BB하단")
        score += 10
    elif bb_position <= PULLBACK_BB_LOWER * 1.5:
        score += 5

    if price_change < -5:
        tech.append("깊은조정")
        score += 5
    elif price_change < -2:
        tech.append("가격조정")
        score += 3

    cci_at_screen = stock_info.get("cci_at_screen", 0)
    if cci_at_screen > 150 and cci_now < cci_at_screen * 0.7:
        tech.append("CCI냉각")
        score += 5

    if rsi_now < 40:
        tech.append("RSI과매도")
        score += 5
    elif rsi_now < 50:
        score += 2

    # ── 타이밍 (0~30점) ──
    window_start = stock_info.get("window_start", 1)
    window_end = stock_info.get("window_end", 5)
    timing_diff = abs(days_elapsed - sweet_spot)
    in_window = window_start <= days_elapsed <= window_end

    if in_window and timing_diff == 0:
        score += 30
    elif in_window and timing_diff == 1:
        score += 22
    elif in_window:
        score += 15
    elif days_elapsed < window_start:
        score += 5
    else:
        score += 0

    # ── 순위 보너스 (0~20점) ──
    rank = stock_info.get("rank", 99)
    rank_bonus = {1: 20, 3: 15, 4: 5, 5: 5}.get(rank, 0)
    score += rank_bonus

    # ── 과열 감점 ──
    if stock_info.get("overheat"):
        score -= 15
        risk_flags.append("과열")

    # ── 급락 감점 ──
    if price_change < -10:
        score -= 5
        risk_flags.append("급락")

    # ── 확신도 등급 ──
    if score >= 60:
        conviction = "A"
    elif score >= 40:
        conviction = "B"
    else:
        conviction = "C"

    rank_info = RANK_TIMING.get(rank, {})

    return {
        "code": code,
        "name": stock_info.get("name", code),
        "current_price": price,
        "signal_type": "+".join(tech) if tech else "",
        "ma5_gap": round(ma5_gap, 1),
        "vol_decline": round(vol_decline, 2),
        "bb_position": round(bb_position, 2),
        "price_change_from_screen": round(price_change, 1),
        "conditions_met": len(tech),
        "conviction": conviction,
        "conviction_score": score,
        "sweet_spot_day": sweet_spot,
        "in_window": in_window,
        "cci": round(cci_now, 1),
        "rsi": round(rsi_now, 1),
        "expected_wr": rank_info.get("exp_wr", 0),
        "expected_ret": rank_info.get("exp_ret", 0),
        "rank_note": rank_info.get("note", ""),
        "risk_flags": risk_flags,
        "dart_risk": "",
        "dart_note": "",
        "news_risk": "",
        "news_summary": "",
    }


def _check_single(code: str, stock_info: dict, api,
                   days_elapsed: int, sweet_spot: int) -> dict | None:
    """개별 종목 눌림목 조건 체크 (순위+타이밍 반영 확신도)"""
    code = code.strip().zfill(6)

    csv_path = OHLCV_DIR / f"{code}.csv"
    if not csv_path.exists():
        return None

    df = pd.read_csv(csv_path)
    df.columns = [c.lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").tail(30)

    if len(df) < 20:
        return None

    cur = api.get_current_price(code)
    if cur["price"] <= 0:
        return None

    price = cur["price"]
    volume = cur["volume"]

    # MA5
    prices = list(df["close"].values) + [price]
    ma5 = np.mean(prices[-5:])
    ma5_gap = abs((price / ma5 - 1) * 100) if ma5 > 0 else 999

    # 거래량 감소율
    vol_ma20 = df["volume"].tail(20).mean()
    vol_decline = volume / vol_ma20 if vol_ma20 > 0 else 1.0

    # 볼린저밴드
    close_20 = list(df["close"].values[-19:]) + [price]
    bb_mid = np.mean(close_20)
    bb_std = np.std(close_20)
    bb_lower = bb_mid - 2 * bb_std
    bb_upper = bb_mid + 2 * bb_std
    bb_position = (price - bb_lower) / (bb_upper - bb_lower) if bb_upper > bb_lower else 0.5

    # 스크리닝 대비 가격 변동
    entry_price = stock_info.get("entry_price", price)
    price_change = (price / entry_price - 1) * 100 if entry_price > 0 else 0

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
        return None

    # ── 확신도 점수 (0~100) ──
    score = 0

    # 기술적 조건 수 (최대 40)
    score += min(40, len(tech) * 10)

    # 타이밍 정확도 (최대 30)
    timing_diff = abs(days_elapsed - sweet_spot)
    score += [30, 20, 10, 5][min(timing_diff, 3)]

    # 순위 보너스 (최대 20)
    rank = stock_info.get("rank", 99)
    rank_bonus = {1: 20, 3: 15, 4: 5, 5: 5}.get(rank, 0)  # 2위: 0
    score += rank_bonus

    # 과열 감점
    if stock_info.get("overheat"):
        score -= 15

    # ── 등급 결정 ──
    if score >= 60:
        conviction = "A"
    elif score >= 40:
        conviction = "B"
    else:
        conviction = "C"

    # C등급 + 기술 조건 1개면 제외 (노이즈)
    if conviction == "C" and len(tech) < 2:
        return None

    rank_info = RANK_TIMING.get(rank, {})

    return {
        "code": code,
        "name": stock_info.get("name", code),
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
        "expected_wr": rank_info.get("exp_wr", 0),
        "expected_ret": rank_info.get("exp_ret", 0),
        "rank_note": rank_info.get("note", ""),
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
        days = _trading_days_since(created)
        print(f"\n[{created}] D+{days} | 만료: {wl['expires']}")

        for s in wl["stocks"]:
            rank = s.get("rank", "?")
            timing = RANK_TIMING.get(rank, {})
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
                  f"(D+{sig['days_elapsed']}, WR {sig['expected_wr']}%)")