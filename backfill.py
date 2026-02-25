"""
ClosingBell v2 — 백필 (과거 N일 스크리닝 시뮬레이션)

사용법:
    python backfill.py 10          # 최근 10거래일
    python backfill.py 10 --dry    # 저장 없이 미리보기
    python backfill.py 20 --force  # 기존 로그 덮어쓰기

로컬 OHLCV 데이터 기반으로 과거 스크리닝을 시뮬레이션하고
data/logs/{date}.json 로그를 생성합니다.
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

import pandas as pd
import numpy as np

from config import (
    OHLCV_DIR, GLOBAL_CSV, MAPPING_CSV, LOG_DIR,
    CCI_PERIOD, CCI_OPTIMAL, CCI_ZERO_LOW, CCI_ZERO_HIGH,
    MA20_GAP_OPTIMAL, MA20_GAP_ZERO,
    CHANGE_OPTIMAL, CHANGE_ZERO,
    SCORE_CCI, SCORE_MA20_GAP, SCORE_CHANGE, SCORE_CCI_SLOPE, SCORE_MA20_SLOPE,
    TOP_N, TOP_N_CONSERVATIVE, MIN_PRICE, MAX_PRICE,
    NASDAQ_DROP_THRESHOLD,
    EXCLUDE_NAMES, EXCLUDE_PREF_STOCK, EXCLUDE_ETF,
)
from screener import bell_score, _count_rising

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill")


# ──────────────────────────────────────────────
# 데이터 로드
# ──────────────────────────────────────────────
def load_stock_map() -> dict:
    """stock_mapping.csv → {code: {name, market, sector}}"""
    df = pd.read_csv(MAPPING_CSV, dtype={"code": str}, encoding="utf-8-sig")
    df["code"] = df["code"].str.zfill(6)
    return df.set_index("code").to_dict("index")


def load_all_ohlcv() -> dict[str, pd.DataFrame]:
    """전체 OHLCV CSV 로드 → {code: DataFrame}"""
    logger.info("OHLCV 로딩 중... (%s)", OHLCV_DIR)
    data = {}
    csv_files = list(OHLCV_DIR.glob("*.csv"))

    for i, path in enumerate(csv_files):
        code = path.stem.zfill(6)

        # INDEX 파일 스킵
        if code.startswith("INDEX") or not code.isdigit():
            continue

        try:
            df = pd.read_csv(path)
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)

            if len(df) >= 20:  # 최소 20일 필요 (MA20)
                data[code] = df
        except Exception:
            continue

        if (i + 1) % 500 == 0:
            logger.info("  %d/%d 파일 로드됨...", i + 1, len(csv_files))

    logger.info("OHLCV 로드 완료: %d종목", len(data))
    return data


def load_global() -> pd.DataFrame:
    """global_merged.csv 로드"""
    df = pd.read_csv(GLOBAL_CSV)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


# ──────────────────────────────────────────────
# 거래일 계산
# ──────────────────────────────────────────────
def get_trading_days(global_df: pd.DataFrame, n_days: int) -> list[str]:
    """최근 N거래일 리스트 (코스피 데이터 기준)"""
    valid = global_df.dropna(subset=["kospi_close"])
    dates = valid["date"].dt.strftime("%Y-%m-%d").tolist()

    # 오늘 날짜 제외 (오늘은 이미 실행했을 수 있음)
    today = datetime.now().strftime("%Y-%m-%d")
    dates = [d for d in dates if d < today]

    return dates[-n_days:]


# ──────────────────────────────────────────────
# 종목 필터
# ──────────────────────────────────────────────
def is_excluded(code: str, name: str, stock_map: dict) -> bool:
    """SPAC, ETF, 우선주 등 제외"""
    for keyword in EXCLUDE_NAMES:
        if keyword in name:
            return True

    if EXCLUDE_PREF_STOCK and code[-1] in ("5", "7", "8", "9"):
        return True
    if EXCLUDE_PREF_STOCK and (name.endswith("우") or name.endswith("우B")):
        return True

    if EXCLUDE_ETF:
        info = stock_map.get(code, {})
        if "ETF" in info.get("market", "").upper():
            return True
        if "ETF" in name.upper():
            return True

    return False


# ──────────────────────────────────────────────
# 유니버스 시뮬레이션
# ──────────────────────────────────────────────
def simulate_universe(
    target_date: str,
    all_ohlcv: dict[str, pd.DataFrame],
    stock_map: dict,
) -> list[dict]:
    """
    특정 날짜의 TV200 유사 유니버스 생성
    조건: 거래량 상위 150 + 거래대금 150억+ + 등락률 1~29%
    """
    target_dt = pd.Timestamp(target_date)
    candidates = []

    for code, df in all_ohlcv.items():
        # 해당 날짜 데이터 있는지
        mask = df["date"] == target_dt
        if mask.sum() == 0:
            continue

        row = df[mask].iloc[0]
        close = int(row["close"])
        volume = int(row["volume"])
        open_price = int(row["open"])

        if close <= 0 or open_price <= 0:
            continue

        # 등락률 (전일 대비)
        idx = df.index[mask].tolist()[0]
        if idx == 0:
            continue
        prev_close = int(df.iloc[idx - 1]["close"])
        if prev_close <= 0:
            continue

        change_rate = (close / prev_close - 1) * 100

        # 거래대금 (근사값: 종가 × 거래량)
        trade_amt = close * volume

        # 이름
        info = stock_map.get(code, {})
        name = info.get("name", code)

        candidates.append({
            "code": code,
            "name": name,
            "sector": info.get("sector", ""),
            "price": close,
            "open": open_price,
            "change_rate": round(change_rate, 2),
            "volume": volume,
            "trade_amt": trade_amt,
            "df_idx": idx,
        })

    # 필터: 등락률 1~29%, 거래대금 150억+
    filtered = [
        s for s in candidates
        if 1.0 <= s["change_rate"] <= 29.0
        and s["trade_amt"] >= 15_000_000_000  # 150억
    ]

    # 거래량 상위 150
    filtered.sort(key=lambda x: x["volume"], reverse=True)
    filtered = filtered[:150]

    # 종목 유형 필터
    filtered = [s for s in filtered if not is_excluded(s["code"], s["name"], stock_map)]

    # 가격 필터
    filtered = [s for s in filtered if MIN_PRICE <= s["price"] <= MAX_PRICE]

    return filtered


# ──────────────────────────────────────────────
# 지표 계산 + 점수
# ──────────────────────────────────────────────
def calc_indicators_and_score(
    stock: dict,
    all_ohlcv: dict[str, pd.DataFrame],
    target_date: str,
) -> dict | None:
    """OHLCV 기반 지표 계산 + 점수"""
    code = stock["code"]
    df = all_ohlcv.get(code)
    if df is None:
        return None

    target_dt = pd.Timestamp(target_date)
    mask = df["date"] <= target_dt
    df_slice = df[mask].tail(50).copy()

    if len(df_slice) < 20:
        return None

    # MA20
    df_slice["ma20"] = df_slice["close"].rolling(20).mean()

    # CCI
    tp = (df_slice["high"] + df_slice["low"] + df_slice["close"]) / 3
    sma_tp = tp.rolling(CCI_PERIOD).mean()
    mad = tp.rolling(CCI_PERIOD).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    df_slice["cci"] = (tp - sma_tp) / (0.015 * mad)

    latest = df_slice.iloc[-1]
    if pd.isna(latest["cci"]) or pd.isna(latest["ma20"]):
        return None

    cci = round(float(latest["cci"]), 1)
    ma20 = float(latest["ma20"])
    close = float(latest["close"])
    ma20_gap = round((close / ma20 - 1) * 100, 1) if ma20 > 0 else 0

    # 기울기
    prev_4 = df_slice.tail(4)
    cci_slope = _count_rising(prev_4["cci"].dropna().tolist())
    ma20_slope = _count_rising(prev_4["ma20"].dropna().tolist())

    # 점수
    score = 0.0
    score += bell_score(cci, CCI_OPTIMAL[0], CCI_OPTIMAL[1], CCI_ZERO_LOW, CCI_ZERO_HIGH, SCORE_CCI)
    score += bell_score(ma20_gap, MA20_GAP_OPTIMAL[0], MA20_GAP_OPTIMAL[1], 0, MA20_GAP_ZERO, SCORE_MA20_GAP)
    score += bell_score(stock["change_rate"], CHANGE_OPTIMAL[0], CHANGE_OPTIMAL[1], 0, CHANGE_ZERO, SCORE_CHANGE)
    score += min(SCORE_CCI_SLOPE, max(0, cci_slope) * 5)
    score += min(SCORE_MA20_SLOPE, max(0, ma20_slope) * 3.33)

    # 다음날 시가 (수익률 계산용)
    target_idx = df_slice.index[-1]
    full_idx = df.index.tolist()
    pos = full_idx.index(target_idx)
    next_open = None
    if pos + 1 < len(df):
        next_open = int(df.iloc[pos + 1]["open"])

    return {
        "code": code,
        "name": stock["name"],
        "sector": stock["sector"],
        "price": stock["price"],
        "change_rate": stock["change_rate"],
        "score": round(score, 1),
        "cci": cci,
        "ma20_gap": ma20_gap,
        "cci_slope": cci_slope,
        "ma20_slope": ma20_slope,
        "next_open": next_open,
    }


# ──────────────────────────────────────────────
# 시장 현황
# ──────────────────────────────────────────────
def get_market_for_date(global_df: pd.DataFrame, target_date: str) -> dict:
    """특정 날짜의 시장 현황"""
    target_dt = pd.Timestamp(target_date)
    mask = global_df["date"] == target_dt
    result = {"kospi": 0, "kospi_change": 0, "kosdaq": 0, "kosdaq_change": 0,
              "nasdaq": 0, "nasdaq_change": 0}

    if mask.sum() > 0:
        row = global_df[mask].iloc[0]
        for col, key in [
            ("kospi_close", "kospi"), ("kospi_change_pct", "kospi_change"),
            ("kosdaq_close", "kosdaq"), ("kosdaq_change_pct", "kosdaq_change"),
        ]:
            if col in row and pd.notna(row[col]):
                result[key] = round(float(row[col]), 2)

    # 나스닥은 전일 기준
    prev = global_df[global_df["date"] < target_dt].dropna(subset=["nasdaq_close"])
    if len(prev) > 0:
        last = prev.iloc[-1]
        result["nasdaq"] = round(float(last["nasdaq_close"]), 2)
        if pd.notna(last.get("nasdaq_change_pct")):
            result["nasdaq_change"] = round(float(last["nasdaq_change_pct"]), 2)

    return result


# ──────────────────────────────────────────────
# 전일 추천 수익률 계산
# ──────────────────────────────────────────────
def calc_prev_returns(
    current_date: str,
    prev_log: dict | None,
    all_ohlcv: dict[str, pd.DataFrame],
) -> list[dict]:
    """전일 추천 TOP5의 오늘 수익률"""
    if not prev_log or prev_log.get("skipped"):
        return []

    target_dt = pd.Timestamp(current_date)
    results = []

    for stock in prev_log.get("top5", []):
        code = stock["code"]
        buy_price = stock["price"]
        df = all_ohlcv.get(code)
        if df is None or buy_price <= 0:
            continue

        # 오늘 시가
        mask = df["date"] == target_dt
        if mask.sum() == 0:
            continue
        today_open = int(df[mask].iloc[0]["open"])
        if today_open <= 0:
            continue

        ret = (today_open / buy_price - 1) * 100
        results.append({
            "date": prev_log["date"],
            "code": code,
            "name": stock.get("name", ""),
            "rank": stock.get("rank", 0),
            "buy_price": buy_price,
            "today_price": today_open,
            "return_pct": round(ret, 2),
        })

    return results


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="ClosingBell 백필")
    parser.add_argument("days", type=int, help="백필할 거래일 수")
    parser.add_argument("--dry", action="store_true", help="저장하지 않고 미리보기")
    parser.add_argument("--force", action="store_true", help="기존 로그 덮어쓰기")
    args = parser.parse_args()

    # 데이터 로드
    stock_map = load_stock_map()
    all_ohlcv = load_all_ohlcv()
    global_df = load_global()

    # 거래일 목록
    trading_days = get_trading_days(global_df, args.days)
    logger.info("백필 대상: %d거래일 (%s ~ %s)", len(trading_days),
                trading_days[0] if trading_days else "?",
                trading_days[-1] if trading_days else "?")

    prev_log = None  # 전일 로그 (수익률 계산용)
    total_stats = {"days": 0, "skipped": 0, "total_stocks": 0}

    for i, date in enumerate(trading_days):
        log_path = LOG_DIR / f"{date}.json"

        # 기존 로그 있으면 스킵 (--force 아닐 때)
        if log_path.exists() and not args.force:
            logger.info("[%d/%d] %s — 기존 로그 있음 (스킵)", i+1, len(trading_days), date)
            prev_log = json.loads(log_path.read_text(encoding="utf-8"))
            continue

        logger.info("[%d/%d] %s 시뮬레이션...", i+1, len(trading_days), date)

        # 시장 현황
        market = get_market_for_date(global_df, date)

        # 나스닥 급락 스킵 (스케줄러와 동일)
        nasdaq_chg = market.get("nasdaq_change", 0)
        if nasdaq_chg <= NASDAQ_DROP_THRESHOLD:
            logger.info("  나스닥 급락 (%.1f%%) → 스킵", nasdaq_chg)
            result = {
                "date": date, "timestamp": f"{date}T15:06:00",
                "market": market, "skipped": True,
                "reason": f"나스닥 전일 {nasdaq_chg:+.1f}% (기준: {NASDAQ_DROP_THRESHOLD}%)",
                "universe_count": 0,
                "top5": [], "all_scored": [], "sector_summary": [], "prev_returns": [],
            }
            if not args.dry:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            prev_log = result
            total_stats["skipped"] += 1
            total_stats["days"] += 1
            continue

        # 유니버스
        universe = simulate_universe(date, all_ohlcv, stock_map)

        if not universe:
            logger.info("  유니버스 0종목 → 스킵")
            result = {
                "date": date, "timestamp": f"{date}T15:06:00",
                "market": market, "skipped": True,
                "reason": "유니버스 0종목", "universe_count": 0,
                "top5": [], "all_scored": [], "sector_summary": [], "prev_returns": [],
            }
            if not args.dry:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            prev_log = result
            total_stats["skipped"] += 1
            total_stats["days"] += 1
            continue

        # ETF 2차 필터 (스케줄러와 동일)
        ETF_KEYWORDS = ["KODEX", "TIGER", "KBSTAR", "HANARO", "SOL ", "ARIRANG",
                        "KOSEF", "ACE ", "PLUS ", "BNK", "RISE", "TIMEFOLIO",
                        "파워", "레버리지", "인버스"]
        before_etf = len(universe)
        universe = [s for s in universe
                    if not any(kw in s.get("name", "") for kw in ETF_KEYWORDS)]
        if before_etf != len(universe):
            logger.info("  ETF 2차 필터: %d → %d종목", before_etf, len(universe))

        # 지표 + 점수
        scored = []
        for stock in universe:
            result = calc_indicators_and_score(stock, all_ohlcv, date)
            if result:
                scored.append(result)

        scored.sort(key=lambda x: x["score"], reverse=True)

        # TOP_N 결정 — 보수 모드 (스케줄러와 동일)
        top_n = TOP_N
        # 코스피 MA20 계산
        kospi_col = global_df[global_df["date"] <= pd.Timestamp(date)].dropna(subset=["kospi_close"])
        if len(kospi_col) >= 20:
            kospi_ma20 = kospi_col["kospi_close"].tail(20).mean()
            kospi_now = market.get("kospi", 0)
            if kospi_now > 0 and kospi_now < kospi_ma20:
                top_n = TOP_N_CONSERVATIVE
                logger.info("  코스피 %.0f < MA20 %.0f → 보수 모드 (TOP%d)", kospi_now, kospi_ma20, top_n)

        # TOP5
        top5 = []
        for j, s in enumerate(scored[:top_n]):
            top5.append({**s, "rank": j + 1})

        # 전체
        all_scored = []
        for j, s in enumerate(scored):
            all_scored.append({**s, "rank": j + 1})

        # 섹터 분석
        sector_data = defaultdict(lambda: {"count": 0, "total_change": 0.0, "stocks": []})
        for s in scored:
            sec = s.get("sector") or "기타"
            sector_data[sec]["count"] += 1
            sector_data[sec]["total_change"] += s.get("change_rate", 0)
            sector_data[sec]["stocks"].append(s["name"])

        sector_summary = sorted([
            {"sector": k, "count": v["count"],
             "avg_change": round(v["total_change"] / v["count"], 2),
             "stocks": v["stocks"][:5]}
            for k, v in sector_data.items()
        ], key=lambda x: x["avg_change"], reverse=True)

        # 전일 수익률
        prev_returns = calc_prev_returns(date, prev_log, all_ohlcv)

        log_entry = {
            "date": date,
            "timestamp": f"{date}T15:06:00",
            "market": market,
            "universe_count": len(universe),
            "top5": top5,
            "all_scored": all_scored,
            "sector_summary": sector_summary,
            "prev_returns": prev_returns,
        }

        # 출력
        logger.info("  유니버스: %d → 점수계산: %d종목", len(universe), len(scored))
        for s in top5:
            ret_str = ""
            if s.get("next_open") and s["price"] > 0:
                ret = (s["next_open"] / s["price"] - 1) * 100
                ret_str = f" → 익일시가 {ret:+.1f}%"
            logger.info("  %d위: %s (%s) %.1f점 | CCI %.0f | 이격도 %.1f%%%s",
                        s["rank"], s["name"], s["code"], s["score"],
                        s["cci"], s["ma20_gap"], ret_str)

        if prev_returns:
            avg_ret = sum(r["return_pct"] for r in prev_returns) / len(prev_returns)
            logger.info("  전일 추천 수익률: 평균 %+.2f%%", avg_ret)

        # 저장
        if not args.dry:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(
                json.dumps(log_entry, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        prev_log = log_entry
        total_stats["days"] += 1
        total_stats["total_stocks"] += len(scored)

    # 최종 요약
    logger.info("")
    logger.info("=" * 50)
    logger.info("백필 완료!")
    logger.info("  처리: %d일 (스킵: %d일)", total_stats["days"], total_stats["skipped"])
    logger.info("  총 점수계산 종목: %d", total_stats["total_stocks"])
    if not args.dry:
        logger.info("  저장: data/logs/*.json")
        logger.info("")
        logger.info("git push하면 Streamlit 대시보드에 반영됩니다:")
        logger.info("  git add . && git commit -m \"backfill: %d days\" && git push", args.days)
    else:
        logger.info("  (--dry 모드: 저장하지 않음)")


if __name__ == "__main__":
    main()