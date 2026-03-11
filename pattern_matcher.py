"""
ClosingBell — 과거 유사 패턴 매칭
==================================
1) pattern_index: 전 종목의 모든 거래일 특징 벡터 사전 계산
2) pattern_match: 특정 종목+날짜와 유사한 과거 패턴 검색 + 이후 수익률

사용법:
    python pattern_matcher.py --build                   # 인덱스 구축 (~5분)
    python pattern_matcher.py --query 218150 2026-03-10  # 미래생명자원 유사 패턴
    python pattern_matcher.py --backtest                 # 백필 전체 매수신호에 대해 유사 패턴 조회
"""
import argparse
import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

from config import BACKTEST_DIR, OHLCV_DIR, MAPPING_CSV, CCI_PERIOD, RSI_PERIOD
from storage import (
    load_backtest_dataset,
    load_backtest_dataset_from_fs,
    save_backtest_dataset,
    save_legacy_json,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("pattern")

INDEX_FILE = BACKTEST_DIR / "pattern_index.npz"
META_FILE = BACKTEST_DIR / "pattern_meta.json"

# 특징 벡터 구성 (8차원)
FEATURE_NAMES = [
    "cci_norm",         # CCI / 200 (정규화)
    "cci_slope_3d",     # CCI 3일 변화율
    "rsi_norm",         # RSI / 100
    "ma20_gap_norm",    # MA20 이격도 / 20
    "vol_ratio_norm",   # 거래량 / MA20거래량, cap 10
    "vol_change_3d",    # 3일 거래량 변화 추세
    "candle_body",      # (종가-시가) / 시가 (양봉+, 음봉-)
    "price_position",   # 20일 range 내 위치 (0~1)
]


def _load_stock_map():
    try:
        df = pd.read_csv(MAPPING_CSV, dtype={"code": str}, encoding="utf-8-sig")
        df["code"] = df["code"].str.zfill(6)
        return df.set_index("code")["name"].to_dict()
    except:
        return {}


def _calc_features(df, idx):
    """단일 거래일의 8차원 특징 벡터 계산"""
    if idx < 30:
        return None

    w = df.iloc[max(0, idx-59):idx+1].copy()
    if len(w) < 20:
        return None

    latest = w.iloc[-1]
    price = float(latest["close"])
    if price <= 0:
        return None

    # MA20
    ma20 = w["close"].tail(20).mean()
    if ma20 <= 0:
        return None
    ma20_gap = (price / ma20 - 1) * 100

    # CCI
    tp = (w["high"] + w["low"] + w["close"]) / 3
    sma = tp.rolling(CCI_PERIOD).mean()
    mad = tp.rolling(CCI_PERIOD).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    cci_series = (tp - sma) / (0.015 * mad)
    cci = float(cci_series.iloc[-1]) if pd.notna(cci_series.iloc[-1]) else 0

    # CCI 3일 기울기
    cci_vals = cci_series.dropna().tail(4).values
    cci_slope = (cci_vals[-1] - cci_vals[0]) / 3 if len(cci_vals) >= 4 else 0

    # RSI
    delta = w["close"].diff()
    gain = delta.clip(lower=0).rolling(RSI_PERIOD).mean()
    loss = (-delta.clip(upper=0)).rolling(RSI_PERIOD).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi_series = 100 - (100 / (1 + rs))
    rsi = float(rsi_series.iloc[-1]) if pd.notna(rsi_series.iloc[-1]) else 50

    # 거래량
    vol = float(latest["volume"])
    vol_ma20 = w["volume"].tail(20).mean()
    vol_ratio = min(10.0, vol / vol_ma20) if vol_ma20 > 0 else 1.0

    # 3일 거래량 변화
    vol_3 = w["volume"].tail(4).values
    vol_change = (vol_3[-1] / vol_3[0] - 1) if len(vol_3) >= 4 and vol_3[0] > 0 else 0
    vol_change = max(-2.0, min(5.0, vol_change))

    # 캔들 몸통
    open_price = float(latest["open"])
    candle_body = (price - open_price) / open_price * 100 if open_price > 0 else 0
    candle_body = max(-15.0, min(15.0, candle_body))

    # 20일 range 내 위치
    high_20 = w["high"].tail(20).max()
    low_20 = w["low"].tail(20).min()
    price_pos = (price - low_20) / (high_20 - low_20) if high_20 > low_20 else 0.5

    return np.array([
        cci / 200,              # cci_norm
        cci_slope / 100,        # cci_slope_3d (정규화)
        rsi / 100,              # rsi_norm
        ma20_gap / 20,          # ma20_gap_norm
        vol_ratio / 5,          # vol_ratio_norm
        vol_change / 3,         # vol_change_3d
        candle_body / 10,       # candle_body
        price_pos,              # price_position
    ], dtype=np.float32)


def build_index(start_date="2024-11-01"):
    """전 종목 특징 벡터 인덱스 구축"""
    log.info("패턴 인덱스 구축 시작 (시작일: %s)", start_date)
    start = pd.Timestamp(start_date)

    name_map = _load_stock_map()

    all_vectors = []   # (N, 8) float32
    all_meta = []      # [{"code", "date", "name"}, ...]

    files = sorted(OHLCV_DIR.glob("*.csv"))
    total = len(files)

    for fi, f in enumerate(files):
        code = f.stem
        if code.startswith("INDEX_"):
            continue
        try:
            df = pd.read_csv(f)
            df.columns = [c.lower() for c in df.columns]
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
        except:
            continue

        if len(df) < 30:
            continue

        name = name_map.get(code, code)

        for idx in range(30, len(df)):
            if df.iloc[idx]["date"] < start:
                continue

            vec = _calc_features(df, idx)
            if vec is None:
                continue

            all_vectors.append(vec)
            all_meta.append({
                "code": code,
                "date": df.iloc[idx]["date"].strftime("%Y-%m-%d"),
                "name": name,
                "close": int(df.iloc[idx]["close"]),
            })

        if (fi + 1) % 500 == 0:
            log.info("  %d/%d종목, 벡터 %d개", fi + 1, total, len(all_vectors))

    if not all_vectors:
        log.error("벡터 없음")
        return

    vectors = np.array(all_vectors, dtype=np.float32)
    np.savez_compressed(INDEX_FILE, vectors=vectors)

    save_backtest_dataset("pattern_meta", all_meta)
    save_legacy_json(META_FILE, all_meta)

    log.info("인덱스 구축 완료: %d벡터, 파일 %s (%.1fMB)",
             len(vectors), INDEX_FILE.name,
             INDEX_FILE.stat().st_size / 1024 / 1024)


def load_index():
    """인덱스 로드"""
    meta = load_backtest_dataset("pattern_meta")
    if meta is None:
        meta = load_backtest_dataset_from_fs("pattern_meta")

    if not INDEX_FILE.exists() or meta is None:
        log.error("인덱스 없음 — python pattern_matcher.py --build 실행 필요")
        return None, None

    data = np.load(INDEX_FILE)
    vectors = data["vectors"]

    log.info("인덱스 로드: %d벡터", len(vectors))
    return vectors, meta


def find_similar(code, target_date, vectors, meta, top_n=10, exclude_same_code=True,
                 exclude_days=5):
    """유사 패턴 검색 (코사인 유사도)"""

    # 타겟 벡터 찾기
    target_key = f"{code}_{target_date}"
    target_vec = None
    target_idx = None

    for i, m in enumerate(meta):
        if m["code"] == code and m["date"] == target_date:
            target_vec = vectors[i]
            target_idx = i
            break

    if target_vec is None:
        # 인덱스에 없으면 직접 계산
        csv_path = OHLCV_DIR / f"{code}.csv"
        if not csv_path.exists():
            return []
        df = pd.read_csv(csv_path)
        df.columns = [c.lower() for c in df.columns]
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        mask = df["date"] == pd.Timestamp(target_date)
        if not mask.any():
            return []
        idx = df.index[mask][0]
        target_vec = _calc_features(df, idx)
        if target_vec is None:
            return []

    # 코사인 유사도 계산
    norms = np.linalg.norm(vectors, axis=1)
    target_norm = np.linalg.norm(target_vec)

    valid = norms > 0
    similarities = np.zeros(len(vectors))
    similarities[valid] = np.dot(vectors[valid], target_vec) / (norms[valid] * target_norm)

    # 자기 자신과 ±exclude_days 제외
    target_dt = pd.Timestamp(target_date)
    for i, m in enumerate(meta):
        if exclude_same_code and m["code"] == code:
            similarities[i] = -1
        # 같은 시기 제외 (모든 종목)
        dt = pd.Timestamp(m["date"])
        if abs((dt - target_dt).days) <= exclude_days:
            if m["code"] == code:
                similarities[i] = -1

    # TOP N
    top_indices = np.argsort(similarities)[::-1][:top_n * 2]  # 여유분

    results = []
    for idx in top_indices:
        if len(results) >= top_n:
            break
        sim = similarities[idx]
        if sim < 0:
            continue
        m = meta[idx]
        results.append({
            "code": m["code"],
            "name": m["name"],
            "date": m["date"],
            "close": m["close"],
            "similarity": round(float(sim) * 100, 1),
        })

    return results


def get_after_returns(code, date_str, ohlcv_cache=None, days=5):
    """패턴 이후 D+1~D+5 수익률"""
    if ohlcv_cache and code in ohlcv_cache:
        df = ohlcv_cache[code]
    else:
        csv_path = OHLCV_DIR / f"{code}.csv"
        if not csv_path.exists():
            return {}
        df = pd.read_csv(csv_path)
        df.columns = [c.lower() for c in df.columns]
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")

    mask = df["date"] == pd.Timestamp(date_str)
    if not mask.any():
        return {}

    idx = df.index[mask][0]
    close = float(df.iloc[idx]["close"])
    if close <= 0:
        return {}

    future = df.iloc[idx+1:idx+1+days]
    returns = {}
    for i, (_, row) in enumerate(future.iterrows(), 1):
        ret = (row["close"] / close - 1) * 100
        returns[f"D+{i}"] = round(ret, 2)
        # 시가/고가도 추가
        returns[f"D+{i}_open"] = round((row["open"] / close - 1) * 100, 2)
        returns[f"D+{i}_high"] = round((row["high"] / close - 1) * 100, 2)

    return returns


def query_pattern(code, target_date, top_n=5):
    """유사 패턴 조회 + 수익률"""
    vectors, meta = load_index()
    if vectors is None:
        return

    similar = find_similar(code, target_date, vectors, meta, top_n=top_n)

    name_map = _load_stock_map()
    target_name = name_map.get(code, code)

    print(f"\n{'='*70}")
    print(f"🔍 유사 패턴 분석: {target_name} ({code}) {target_date}")
    print(f"{'='*70}")

    if not similar:
        print("유사 패턴 없음")
        return

    all_returns = {f"D+{i}": [] for i in range(1, 6)}

    for i, s in enumerate(similar, 1):
        rets = get_after_returns(s["code"], s["date"])
        print(f"\n  {i}. {s['name']} ({s['code']}) {s['date']} — 유사도 {s['similarity']}%")
        print(f"     종가 {s['close']:,}원", end="")
        if rets:
            parts = []
            for d in range(1, 6):
                key = f"D+{d}"
                if key in rets:
                    r = rets[key]
                    parts.append(f"D+{d}:{r:+.1f}%")
                    all_returns[key].append(r)
            print(f"  →  {' | '.join(parts)}")
        else:
            print("  → 수익률 데이터 없음")

    # 요약
    print(f"\n{'─'*70}")
    print(f"  유사 패턴 평균 (상위 {len(similar)}건):")
    parts = []
    for d in range(1, 6):
        key = f"D+{d}"
        vals = all_returns[key]
        if vals:
            avg = np.mean(vals)
            wr = sum(1 for v in vals if v > 0) / len(vals) * 100
            parts.append(f"D+{d}: 승률{wr:.0f}% 평균{avg:+.1f}%")
    print(f"  {' | '.join(parts)}")
    print(f"{'='*70}")


def backtest_signals():
    """백필 매수신호 전체에 유사 패턴 적용"""
    vectors, meta = load_index()
    if vectors is None:
        return

    signals = load_backtest_dataset("buy_signals")
    if signals is None:
        signals = load_backtest_dataset_from_fs("buy_signals")
    if signals is None:
        log.error("buy_signals.json 없음")
        return
    a_signals = [s for s in signals if s.get("conviction") == "A"]
    log.info("A등급 신호 %d건에 대해 유사 패턴 조회", len(a_signals))

    results = []
    for si, sig in enumerate(a_signals):
        code = sig["code"]
        check_date = sig["check_date"]

        similar = find_similar(code, check_date, vectors, meta, top_n=10,
                               exclude_days=10)

        pattern_returns = {f"D+{i}": [] for i in range(1, 6)}
        for s in similar:
            rets = get_after_returns(s["code"], s["date"])
            for d in range(1, 6):
                key = f"D+{d}"
                if key in rets:
                    pattern_returns[key].append(rets[key])

        pattern_avg = {}
        pattern_wr = {}
        for d in range(1, 6):
            key = f"D+{d}"
            vals = pattern_returns[key]
            if vals:
                pattern_avg[key] = round(np.mean(vals), 2)
                pattern_wr[key] = round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1)

        results.append({
            "code": code,
            "name": sig.get("name", ""),
            "check_date": check_date,
            "rank": sig["rank"],
            "conviction_score": sig["conviction_score"],
            "similar_count": len(similar),
            "pattern_avg": pattern_avg,
            "pattern_wr": pattern_wr,
            "top_similar": similar[:3],
        })

        if (si + 1) % 50 == 0:
            log.info("  %d/%d 완료", si + 1, len(a_signals))

    save_backtest_dataset("pattern_analysis", results)
    save_legacy_json(BACKTEST_DIR / "pattern_analysis.json", results)

    # 요약
    print(f"\n{'='*70}")
    print(f"📊 A등급 매수신호 유사 패턴 분석 ({len(results)}건)")
    print(f"{'='*70}")

    for d in range(1, 6):
        key = f"D+{d}"
        wrs = [r["pattern_wr"][key] for r in results if key in r["pattern_wr"]]
        avgs = [r["pattern_avg"][key] for r in results if key in r["pattern_avg"]]
        if wrs:
            print(f"  {key}: 유사패턴 평균승률 {np.mean(wrs):.1f}%, 평균수익 {np.mean(avgs):+.2f}%")

    print("\n결과: backtest dataset 'pattern_analysis'")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="ClosingBell 패턴 매칭")
    p.add_argument("--build", action="store_true", help="인덱스 구축")
    p.add_argument("--start", default="2024-11-01", help="인덱스 시작일")
    p.add_argument("--query", nargs=2, metavar=("CODE", "DATE"), help="유사 패턴 조회")
    p.add_argument("--top", type=int, default=5, help="TOP N (기본 5)")
    p.add_argument("--backtest", action="store_true", help="전체 A등급 신호 패턴 분석")
    a = p.parse_args()

    if a.build:
        build_index(a.start)
    elif a.query:
        query_pattern(a.query[0], a.query[1], a.top)
    elif a.backtest:
        backtest_signals()
    else:
        p.print_help()
