"""
ClosingBell v3 — 백필 (과거 데이터 시뮬레이션)
===============================================
로컬 OHLCV CSV 기반으로 과거 N일의 스크리닝 결과를 생성.
키움 API 없이 동작 (로컬 데이터만 사용).

사용법:
    python backfill.py --days 20
    python backfill.py --start 2026-02-01 --end 2026-03-07
    python backfill.py --days 20 --force  (기존 로그 덮어쓰기)
"""
import argparse
import json
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

from config import (
    OHLCV_DIR, MAPPING_CSV, GLOBAL_CSV, LOG_DIR,
    CCI_PERIOD, RSI_PERIOD,
    CCI_OPTIMAL, CCI_ZERO_LOW, CCI_ZERO_HIGH,
    MA20_GAP_OPTIMAL, MA20_GAP_ZERO,
    CHANGE_OPTIMAL, CHANGE_ZERO,
    RSI_OPTIMAL, RSI_ZERO_LOW, RSI_ZERO_HIGH,
    SCORE_CCI, SCORE_MA20_GAP, SCORE_CHANGE,
    SCORE_CCI_SLOPE, SCORE_MA20_SLOPE, SCORE_RSI,
    SCORE_VOLUME_PROFILE, SCORE_BROKER_FLOW,
    TOP_N, MIN_PRICE, MAX_PRICE,
    MIN_CHANGE_RATE, MAX_CHANGE_RATE,
    NASDAQ_DROP_THRESHOLD, NASDAQ_PENALTY,
    EXCLUDE_NAMES, ETF_KEYWORDS,
)
from screener import bell_score, _count_rising

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill")


def load_all_ohlcv() -> dict[str, pd.DataFrame]:
    """모든 OHLCV CSV 로드"""
    logger.info("OHLCV 로드 중...")
    data = {}
    files = list(OHLCV_DIR.glob("*.csv"))
    for f in files:
        code = f.stem
        if code.startswith("INDEX_"):
            continue
        try:
            df = pd.read_csv(f)
            df.columns = [c.lower() for c in df.columns]  # 대문자→소문자 통일
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            if len(df) >= 30:
                data[code] = df
        except Exception:
            pass
    logger.info("로드 완료: %d종목", len(data))
    return data


def load_stock_map() -> dict:
    try:
        df = pd.read_csv(MAPPING_CSV, dtype={"code": str}, encoding="utf-8-sig")
        df["code"] = df["code"].str.zfill(6)
        return df.set_index("code").to_dict("index")
    except Exception:
        return {}


def load_global() -> pd.DataFrame:
    try:
        df = pd.read_csv(GLOBAL_CSV)
        df.columns = [c.strip().lower() for c in df.columns]
        df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


def is_excluded(code: str, name: str) -> bool:
    for kw in EXCLUDE_NAMES:
        if kw in name:
            return True
    for kw in ETF_KEYWORDS:
        if kw in name:
            return True
    if code[-1] in ("5", "7", "8", "9"):
        return True
    if name.endswith("우") or name.endswith("우B"):
        return True
    return False


def calc_indicators(df: pd.DataFrame, idx: int) -> dict | None:
    """특정 인덱스(날짜)에서의 지표 계산"""
    if idx < 30:
        return None

    window = df.iloc[max(0, idx - 59):idx + 1].copy()
    if len(window) < 20:
        return None

    latest = window.iloc[-1]
    price = int(latest["close"])
    if price < MIN_PRICE or price > MAX_PRICE:
        return None

    # 등락률
    if idx > 0:
        prev_close = df.iloc[idx - 1]["close"]
        change_rate = (price / prev_close - 1) * 100 if prev_close > 0 else 0
    else:
        change_rate = 0

    if not (MIN_CHANGE_RATE <= change_rate <= MAX_CHANGE_RATE):
        return None

    # MA20
    window["ma20"] = window["close"].rolling(20).mean()
    ma20 = window.iloc[-1]["ma20"]
    if pd.isna(ma20) or ma20 <= 0:
        return None

    ma20_gap = (price / ma20 - 1) * 100

    # CCI
    tp = (window["high"] + window["low"] + window["close"]) / 3
    sma_tp = tp.rolling(CCI_PERIOD).mean()
    mad = tp.rolling(CCI_PERIOD).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    window["cci"] = (tp - sma_tp) / (0.015 * mad)

    # RSI
    delta = window["close"].diff()
    gain = delta.clip(lower=0).rolling(RSI_PERIOD).mean()
    loss = (-delta.clip(upper=0)).rolling(RSI_PERIOD).mean()
    rs = gain / loss.replace(0, np.nan)
    window["rsi"] = 100 - (100 / (1 + rs))

    cci = float(window.iloc[-1]["cci"]) if pd.notna(window.iloc[-1]["cci"]) else 0
    rsi = float(window.iloc[-1]["rsi"]) if pd.notna(window.iloc[-1]["rsi"]) else 50

    # 기울기
    prev_4 = window.tail(4)
    cci_slope = _count_rising(prev_4["cci"].dropna().tolist())
    ma20_slope = _count_rising(prev_4["ma20"].dropna().tolist())

    # 매물대 (간이 — 50일 가격대별 거래량)
    vp_window = window.tail(50)
    current_price = float(latest["close"])
    if len(vp_window) >= 10 and current_price > 0:
        total_vol = vp_window["volume"].sum()
        above_vol = vp_window[
            ((vp_window["open"] + vp_window["close"]) / 2) > current_price
        ]["volume"].sum()
        vp_above_pct = (above_vol / total_vol * 100) if total_vol > 0 else 50
    else:
        vp_above_pct = 50

    # 거래대금 (백만원 기준 추정)
    trading_value = int(latest.get("volume", 0) * price / 1_000_000)

    # 점수 계산
    score = 0.0
    score += bell_score(cci, CCI_OPTIMAL[0], CCI_OPTIMAL[1], CCI_ZERO_LOW, CCI_ZERO_HIGH, SCORE_CCI)
    score += bell_score(ma20_gap, MA20_GAP_OPTIMAL[0], MA20_GAP_OPTIMAL[1], 0, MA20_GAP_ZERO, SCORE_MA20_GAP)
    score += bell_score(change_rate, CHANGE_OPTIMAL[0], CHANGE_OPTIMAL[1], 0, CHANGE_ZERO, SCORE_CHANGE)
    score += min(SCORE_CCI_SLOPE, max(0, cci_slope) * 3.33)
    score += min(SCORE_MA20_SLOPE, max(0, ma20_slope) * 3.33)
    score += bell_score(rsi, RSI_OPTIMAL[0], RSI_OPTIMAL[1], RSI_ZERO_LOW, RSI_ZERO_HIGH, SCORE_RSI)

    # 매물대 점수
    if vp_above_pct <= 20:
        score += SCORE_VOLUME_PROFILE
    elif vp_above_pct <= 35:
        score += SCORE_VOLUME_PROFILE * 0.7
    elif vp_above_pct <= 50:
        score += SCORE_VOLUME_PROFILE * 0.4
    elif vp_above_pct <= 65:
        score += SCORE_VOLUME_PROFILE * 0.2

    return {
        "price": price, "change_rate": round(change_rate, 1),
        "score": round(score, 1),
        "cci": round(cci, 1), "rsi": round(rsi, 1),
        "ma20_gap": round(ma20_gap, 1),
        "cci_slope": cci_slope, "ma20_slope": ma20_slope,
        "vp_above_pct": round(vp_above_pct, 1),
        "vp_tag": "위 매물 적음" if vp_above_pct <= 30 else (
            "위 저항 강함" if vp_above_pct >= 60 else "매물대 중립"),
        "trading_value": trading_value,
        "volume": int(latest["volume"]),
    }


def run_backfill(start_date: str, end_date: str, force: bool = False,
                 enrich: bool = False, kiwoom_api=None):
    """백필 실행"""
    all_ohlcv = load_all_ohlcv()
    stock_map = load_stock_map()
    global_df = load_global()

    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)

    # 거래일 목록 (아무 종목의 날짜로 추출)
    sample_code = next(iter(all_ohlcv))
    sample_df = all_ohlcv[sample_code]
    trading_days = sample_df[(sample_df["date"] >= start) & (sample_df["date"] <= end)]["date"].tolist()

    logger.info("백필 기간: %s ~ %s (%d거래일)", start_date, end_date, len(trading_days))

    for day in trading_days:
        day_str = day.strftime("%Y-%m-%d")
        log_file = LOG_DIR / f"{day_str}.json"

        if log_file.exists() and not force:
            logger.debug("스킵 (이미 존재): %s", day_str)
            continue

        # 나스닥 체크 (비어있으면 마지막 유효값 사용)
        nasdaq_change = 0
        if len(global_df) > 0:
            prev_day = global_df[global_df["date"] < day]
            if len(prev_day) > 0:
                # 나스닥이 비어있을 수 있으므로 마지막 유효값 사용
                nasdaq_valid = prev_day.dropna(subset=["nasdaq_change_pct"]) if "nasdaq_change_pct" in prev_day.columns else prev_day
                if len(nasdaq_valid) > 0:
                    val = nasdaq_valid.iloc[-1].get("nasdaq_change_pct", 0)
                    nasdaq_change = float(val) if pd.notna(val) else 0

        if nasdaq_change <= NASDAQ_DROP_THRESHOLD:
            nasdaq_warning = True
            logger.info("  %s: 나스닥 %.1f%% → 감점 모드", day_str, nasdaq_change)
        else:
            nasdaq_warning = False

        # ── 유니버스 시뮬레이션 (실시간과 동일) ──
        # 1) 해당 날짜에 거래된 모든 종목의 거래량/거래대금 수집
        day_candidates = []
        for code, df in all_ohlcv.items():
            day_mask = df["date"] == day
            if not day_mask.any():
                continue
            idx = df.index[day_mask][0]
            row = df.iloc[idx]
            name = stock_map.get(code, {}).get("name", code)
            if is_excluded(code, name):
                continue
            vol = int(row.get("volume", 0))
            price = int(row["close"])
            tv = vol * price / 1_000_000  # 백만원 단위 거래대금
            if vol > 0 and price > 0:
                day_candidates.append({
                    "code": code, "name": name, "idx": idx,
                    "volume": vol, "trading_value": tv, "price": price,
                    "sector": stock_map.get(code, {}).get("sector", ""),
                })

        # 2) 거래량 TOP100 + 거래대금 TOP100 합집합 (= 실시간 ka10030+ka10032)
        by_volume = sorted(day_candidates, key=lambda x: x["volume"], reverse=True)[:100]
        by_value = sorted(day_candidates, key=lambda x: x["trading_value"], reverse=True)[:100]
        universe_codes = set()
        universe = {}
        for s in by_volume + by_value:
            if s["code"] not in universe_codes:
                universe_codes.add(s["code"])
                universe[s["code"]] = s

        # 3) 필터 (실시간과 동일): 등락률 1~29%, 가격 3,000~150,000, 거래대금 100억+
        scored = []
        for code, cand in universe.items():
            df = all_ohlcv[code]
            idx = cand["idx"]

            indicators = calc_indicators(df, idx)
            if indicators is None:
                continue

            # 거래대금 100억 이상 (실시간 ka10030의 trde_prica_tp=1000과 동일)
            if indicators["trading_value"] < 10000:
                continue

            scored.append({
                "code": code, "name": cand["name"], "sector": cand["sector"],
                **indicators,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)

        # 나스닥 급락 감점
        if nasdaq_warning:
            for s in scored:
                s["score"] = round(max(0, s["score"] - NASDAQ_PENALTY), 1)
            scored.sort(key=lambda x: x["score"], reverse=True)

        top_n = TOP_N if not nasdaq_warning else 2  # 나스닥 급락 시 보수모드
        top = scored[:top_n]

        # market 데이터를 global_merged에서 채우기
        market_data = {"nasdaq_change": nasdaq_change, "nasdaq_warning": nasdaq_warning}
        if len(global_df) > 0:
            day_row = global_df[global_df["date"] == day]
            if len(day_row) > 0:
                r = day_row.iloc[0]
                market_data["kospi"] = float(r.get("kospi_close", 0)) if pd.notna(r.get("kospi_close")) else 0
                market_data["kospi_change"] = float(r.get("kospi_change_pct", 0)) if pd.notna(r.get("kospi_change_pct")) else 0
                market_data["kosdaq"] = float(r.get("kosdaq_close", 0)) if pd.notna(r.get("kosdaq_close")) else 0
                market_data["kosdaq_change"] = float(r.get("kosdaq_change_pct", 0)) if pd.notna(r.get("kosdaq_change_pct")) else 0
                market_data["nasdaq"] = float(r.get("nasdaq_close", 0)) if pd.notna(r.get("nasdaq_close")) else 0

        # ── enrich: 거래원(ka10038) + DART + 룰 기반 AI ──
        if enrich and kiwoom_api:
            logger.info("  enrich 시작 (%d종목)...", len(scored))
            _enrich_backfill(scored, kiwoom_api, day_str)
            # 거래원 점수 반영해서 재계산
            for s in scored:
                s["score"] = _recalc_score(s)
            scored.sort(key=lambda x: x["score"], reverse=True)
            top = scored[:TOP_N]
        else:
            # enrich 없으면 기본값
            for s in scored:
                s.setdefault("broker_signal", "")
                s.setdefault("broker_score", 0)
                s.setdefault("dart_risk", "")
                s.setdefault("dart_note", "")
                s.setdefault("ai_action", "")
                s.setdefault("ai_risk", "")
                s.setdefault("ai_summary", "")

        result = {
            "date": day_str,
            "timestamp": day.isoformat(),
            "market": market_data,
            "universe_count": len(scored),
            "top": [
                {**s, "rank": i + 1}
                for i, s in enumerate(top)
            ],
            "all_scored": [
                {**s, "rank": i + 1}
                for i, s in enumerate(scored)
            ],
        }

        log_file.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info(
            "%s: %d종목 → TOP%d [%s]",
            day_str, len(scored), len(top),
            ", ".join(f"{s['name']}({s['score']})" for s in top),
        )

    logger.info("백필 완료!")


def _enrich_backfill(scored: list, api, day_str: str):
    """
    백필 종목에 거래원(ka10038) + DART + 룰 기반 AI 적용
    ka10038은 dt 파라미터로 120거래일까지 조회 가능
    """
    from dart_checker import DartChecker
    from ai_analyzer import AIAnalyzer

    dart = DartChecker()
    ai = AIAnalyzer()  # Gemini 키 없으면 자동으로 룰 기반 fallback

    for s in scored:
        code = s["code"]

        # 1) 거래원 (ka10038 — 과거 데이터 지원)
        try:
            ranking = api.get_broker_ranking(code, period="1", sort="2")
            brokers = ranking.get("brokers", [])
            if brokers:
                s["broker_top_buy"] = brokers[0]["name"]
            # 간이 점수: 외국계 매수 창구 수로 판단
            from enricher import FOREIGN_BROKERS, MINOR_BROKERS
            detail = api.get_broker_detail(code)
            buy_top5 = detail.get("buy_top5", [])
            frgn_count = sum(1 for b in buy_top5
                             if b.get("code") in FOREIGN_BROKERS or
                             b.get("name") in FOREIGN_BROKERS.values())
            minor_count = sum(1 for b in buy_top5
                              if any(m in b.get("name", "") for m in MINOR_BROKERS))
            frgn_net = detail.get("foreign_net", 0)

            score = 0.0
            if frgn_net > 0: score += 2.0
            if frgn_count >= 2: score += 2.0
            elif frgn_count >= 1: score += 1.0
            if minor_count >= 2: score += 1.5
            elif minor_count >= 1: score += 0.5
            s["broker_score"] = min(5.0, max(0, score))
            s["broker_signal"] = "매집 신호" if score >= 3.5 else (
                "외국계 관심" if score >= 2.0 else "중립")
            s["foreign_net"] = frgn_net
        except Exception:
            s["broker_score"] = 0
            s["broker_signal"] = ""

        # 2) DART 간이 체크
        try:
            dr = dart.check(code)
            s["dart_risk"] = dr["risk"]
            s["dart_note"] = dr["note"]
            s["profit_loss"] = dr.get("profit_loss", "")
        except Exception:
            s["dart_risk"] = "확인불가"
            s["dart_note"] = ""

        # 3) 룰 기반 AI (Gemini 호출 안 함 — 과거 데이터이므로)
        try:
            result = ai._rule_based(s)
            s["ai_action"] = result["action"]
            s["ai_risk"] = result["risk"]
            s["ai_summary"] = result["summary"]
        except Exception:
            s["ai_action"] = "관망"
            s["ai_risk"] = "보통"
            s["ai_summary"] = ""


def _recalc_score(s: dict) -> float:
    """거래원 점수 반영해서 재계산"""
    score = 0.0
    score += bell_score(s.get("cci", 0), CCI_OPTIMAL[0], CCI_OPTIMAL[1],
                         CCI_ZERO_LOW, CCI_ZERO_HIGH, SCORE_CCI)
    score += bell_score(s.get("ma20_gap", 0), MA20_GAP_OPTIMAL[0], MA20_GAP_OPTIMAL[1],
                         0, MA20_GAP_ZERO, SCORE_MA20_GAP)
    score += bell_score(s.get("change_rate", 0), CHANGE_OPTIMAL[0], CHANGE_OPTIMAL[1],
                         0, CHANGE_ZERO, SCORE_CHANGE)
    score += min(SCORE_CCI_SLOPE, max(0, s.get("cci_slope", 0)) * 3.33)
    score += min(SCORE_MA20_SLOPE, max(0, s.get("ma20_slope", 0)) * 3.33)
    score += bell_score(s.get("rsi", 50), RSI_OPTIMAL[0], RSI_OPTIMAL[1],
                         RSI_ZERO_LOW, RSI_ZERO_HIGH, SCORE_RSI)
    above = s.get("vp_above_pct", 50)
    if above <= 20: score += SCORE_VOLUME_PROFILE
    elif above <= 35: score += SCORE_VOLUME_PROFILE * 0.7
    elif above <= 50: score += SCORE_VOLUME_PROFILE * 0.4
    elif above <= 65: score += SCORE_VOLUME_PROFILE * 0.2
    score += min(SCORE_BROKER_FLOW, s.get("broker_score", 0))
    return round(score, 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ClosingBell v3 백필")
    parser.add_argument("--days", type=int, default=20, help="최근 N일")
    parser.add_argument("--start", type=str, default="", help="시작일 (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default="", help="종료일 (YYYY-MM-DD)")
    parser.add_argument("--force", action="store_true", help="기존 로그 덮어쓰기")
    parser.add_argument("--enrich", action="store_true",
                        help="거래원(ka10038)+DART+AI 분석 추가 (키움 API 필요)")
    args = parser.parse_args()

    # --enrich 시 키움 API 초기화
    api = None
    if args.enrich:
        from config import KIWOOM_BASE_URL, KIWOOM_APPKEY, KIWOOM_SECRETKEY, API_DELAY
        from kiwoom_api import KiwoomAPI
        api = KiwoomAPI(KIWOOM_APPKEY, KIWOOM_SECRETKEY, KIWOOM_BASE_URL, API_DELAY)
        api.ensure_token()
        logger.info("키움 API 연결 완료 (enrich 모드)")

    if args.start and args.end:
        run_backfill(args.start, args.end, args.force, args.enrich, api)
    else:
        end = datetime.now() - timedelta(days=1)
        start = end - timedelta(days=args.days + 10)
        run_backfill(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"),
                     args.force, args.enrich, api)
