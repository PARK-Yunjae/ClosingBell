"""
ClosingBell — 매수신호 재생성 v2 (rank 수정 + DART/AI 연동)
============================================================
repair_watchlist.py의 업그레이드 버전.
매수신호 생성 시 로그에서 해당 종목의 DART/AI 정보를 가져와서 반영.

추가사항 (v1 대비):
  ✅ rank 올바르게 적용
  ✅ DART 위험 종목 → 확신도 감점
  ✅ AI "주의" 종목 → 확신도 감점
  ✅ 성과 지표에 시가/고가 수익률 추가

사용법:
    python repair_v2.py
"""
import json
import logging
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import (
    OHLCV_DIR, LOG_DIR, WATCHLIST_DIR, WATCHLIST_MAX_DAYS,
    PERFORMANCE_DIR, BACKTEST_DIR,
    PULLBACK_MA5_GAP, PULLBACK_VOL_DECLINE, PULLBACK_BB_LOWER,
    CCI_PERIOD,
)
from storage import (
    iter_screen_results,
    list_watchlists,
    load_screen_results_from_fs,
    load_watchlists_from_fs,
    save_backtest_dataset,
    save_legacy_json,
    save_watchlist_payload,
)
from watchlist_monitor import RANK_TIMING
from trading_calendar import add_trading_days, trading_days_between

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("repair_v2")

def _load_ohlcv():
    log.info("OHLCV 로드 중...")
    out = {}
    for f in OHLCV_DIR.glob("*.csv"):
        if f.stem.startswith("INDEX_"): continue
        try:
            df = pd.read_csv(f); df.columns = [c.lower() for c in df.columns]
            df["date"] = pd.to_datetime(df["date"]); df = df.sort_values("date").reset_index(drop=True)
            if len(df) >= 20: out[f.stem] = df
        except: pass
    log.info("  %d종목", len(out))
    return out



def _load_screen_results():
    results = iter_screen_results()
    if results:
        return results
    return load_screen_results_from_fs()


def _load_watchlist_payloads():
    watchlists = list_watchlists(desc=False)
    if watchlists:
        return watchlists
    return list(reversed(load_watchlists_from_fs()))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  로그에서 DART/AI 정보 캐시
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _build_dart_cache():
    """로그의 all_scored에서 종목별 DART/AI 정보 추출"""
    cache = {}  # (code, date) → {dart_risk, dart_note, ai_action, ai_risk}

    for data in _load_screen_results():
        try:
            if data.get("skipped"):
                continue
            ds = data["date"]
            for s in data.get("all_scored", []):
                code = s.get("code", "")
                cache[(code, ds)] = {
                    "dart_risk": s.get("dart_risk", ""),
                    "dart_note": s.get("dart_note", ""),
                    "ai_action": s.get("ai_action", ""),
                    "ai_risk": s.get("ai_risk", ""),
                    "ai_summary": s.get("ai_summary", ""),
                    "broker_signal": s.get("broker_signal", ""),
                    "broker_score": s.get("broker_score", 0),
                }
        except Exception:
            pass

    log.info("DART/AI 캐시: %d건", len(cache))
    return cache


def _get_dart_for_signal(code, wl_date, dart_cache):
    """매수신호에 연결할 DART/AI 정보 (워치리스트 생성일 기준)"""
    # 워치리스트 생성일의 스크리닝 데이터에서 가져옴
    info = dart_cache.get((code, wl_date))
    if info:
        return info

    # 없으면 가장 가까운 날짜에서
    for days_back in range(1, 10):
        dt = datetime.strptime(wl_date, "%Y-%m-%d") - timedelta(days=days_back)
        ds = dt.strftime("%Y-%m-%d")
        info = dart_cache.get((code, ds))
        if info:
            return info

    return {"dart_risk": "", "dart_note": "", "ai_action": "", "ai_risk": "",
            "ai_summary": "", "broker_signal": "", "broker_score": 0}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Phase 1: 워치리스트 재생성
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def rebuild_watchlists():
    log_files = _load_screen_results()
    log.info("로그 %d개에서 워치리스트 재생성", len(log_files))
    created = 0

    for data in log_files:
        try:
            if data.get("skipped"):
                continue
        except Exception:
            continue

        ds = data["date"]
        top5 = data.get("all_scored", [])[:5]
        if not top5: continue

        wl = {"created": ds, "expires": add_trading_days(ds, WATCHLIST_MAX_DAYS), "stocks": []}

        for stock in top5:
            rank = stock.get("rank", 99)
            if rank == 99 or rank == 0:
                rank = top5.index(stock) + 1

            timing = RANK_TIMING.get(rank, RANK_TIMING.get(3, {"sweet_spot": 3, "window": (2, 4)}))

            wl["stocks"].append({
                "code": stock["code"], "name": stock.get("name", stock["code"]),
                "rank": rank, "score": stock.get("score", 0),
                "entry_price": stock.get("price", 0),
                "cci_at_screen": stock.get("cci", 0),
                "rsi_at_screen": stock.get("rsi", 0),
                "ma20_gap_at_screen": stock.get("ma20_gap", 0),
                "overheat": bool(stock.get("overheat", False)),
                "sweet_spot_day": timing["sweet_spot"],
                "window_start": timing["window"][0], "window_end": timing["window"][1],
                "triggered": False, "trigger_date": None, "trigger_price": None,
                "trigger_type": None, "conviction": None,
            })

        save_watchlist_payload(wl)
        save_legacy_json(WATCHLIST_DIR / f"{ds}.json", wl)
        created += 1

    log.info("워치리스트 %d개 생성", created)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Phase 2: 매수신호 재생성 (DART/AI 연동)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def rebuild_signals(ohlcv, dart_cache):
    watchlists = {}
    for wl in _load_watchlist_payloads():
        try:
            watchlists[wl["created"]] = wl
        except Exception:
            pass

    log.info("워치리스트 %d개 로드", len(watchlists))

    # 거래일 목록 (백필 범위만)
    ref = ohlcv.get("005930", ohlcv[next(iter(ohlcv))])
    min_date = min(wl["created"] for wl in watchlists.values())
    all_dates = sorted(d for d in ref["date"].tolist() if d >= pd.Timestamp(min_date))

    all_signals = []

    for di, day in enumerate(all_dates):
        ds = day.strftime("%Y-%m-%d")

        for wl_date, wl in watchlists.items():
            if wl.get("expires", "") < ds: continue
            if wl["created"] >= ds: continue

            de = trading_days_between(wl["created"], day)
            if de < 1: continue

            for stock in wl.get("stocks", []):
                if stock.get("triggered"): continue

                code = stock["code"]; rank = stock.get("rank", 99)
                ws = stock.get("window_start", 1); we = stock.get("window_end", 5)
                ss = stock.get("sweet_spot_day", 2); iw = ws <= de <= we

                if code not in ohlcv: continue
                df = ohlcv[code]; mask = df["date"] == day
                if not mask.any(): continue
                idx = df.index[mask][0]
                if idx < 20: continue

                row = df.iloc[idx]
                price = int(row["close"]); volume = int(row["volume"])
                ep = stock.get("entry_price", price)

                r5 = df.iloc[max(0,idx-4):idx+1]
                ma5 = r5["close"].mean(); mg5 = abs((price/ma5-1)*100) if ma5>0 else 999
                r20 = df.iloc[max(0,idx-19):idx+1]
                vm20 = r20["volume"].mean(); vd = volume/vm20 if vm20>0 else 1.0
                cls20 = r20["close"]; bm = cls20.mean(); bsd = cls20.std()
                bl = bm-2*bsd; bu = bm+2*bsd
                bp = (price-bl)/(bu-bl) if bu>bl else 0.5
                pc = (price/ep-1)*100 if ep>0 else 0

                tech = []; sc = 0
                if mg5 <= PULLBACK_MA5_GAP: tech.append("MA5터치"); sc += 15
                elif mg5 <= PULLBACK_MA5_GAP*2: sc += 8
                if vd <= PULLBACK_VOL_DECLINE: tech.append("거래량감소"); sc += 10
                elif vd <= PULLBACK_VOL_DECLINE*1.5: sc += 5
                if bp <= PULLBACK_BB_LOWER: tech.append("BB하단"); sc += 10
                elif bp <= PULLBACK_BB_LOWER*1.5: sc += 5
                if pc < -5: tech.append("깊은조정"); sc += 5
                elif pc < -2: tech.append("가격조정"); sc += 3

                td = abs(de-ss)
                if iw and td==0: sc+=30
                elif iw and td==1: sc+=22
                elif iw: sc+=15
                elif de<ws: sc+=5

                sc += {1: 20, 3: 15, 4: 5, 5: 5}.get(rank, 0)
                if stock.get("overheat"): sc -= 15
                if pc < -10: sc -= 5

                # ★ DART/AI 감점 (v2 신규)
                dart_info = _get_dart_for_signal(code, wl["created"], dart_cache)
                risk_flags = []

                if dart_info["dart_risk"] == "위험":
                    sc -= 10; risk_flags.append("DART위험")
                elif dart_info["dart_risk"] == "주의":
                    sc -= 5; risk_flags.append("DART주의")

                if dart_info["ai_action"] == "주의":
                    sc -= 5; risk_flags.append("AI주의")
                elif dart_info["ai_risk"] == "높음":
                    sc -= 3; risk_flags.append("AI위험")

                conv = "A" if sc>=60 else ("B" if sc>=40 else "C")
                ri = RANK_TIMING.get(rank, {})

                sig = {
                    "code": code, "name": stock.get("name", code),
                    "watchlist_date": wl["created"], "check_date": ds,
                    "rank": rank, "days_elapsed": de,
                    "in_window": iw, "sweet_spot_day": ss,
                    "current_price": price, "entry_price": ep,
                    "price_change_pct": round(pc, 1),
                    "signal_type": "+".join(tech) if tech else "",
                    "conditions_met": len(tech),
                    "conviction": conv, "conviction_score": sc,
                    "expected_wr": ri.get("exp_wr", 0),
                    "expected_ret": ri.get("exp_ret", 0),
                    "original_score": stock["score"],
                    # ★ DART/AI 정보
                    "dart_risk": dart_info["dart_risk"],
                    "dart_note": dart_info["dart_note"],
                    "ai_action": dart_info["ai_action"],
                    "ai_risk": dart_info["ai_risk"],
                    "broker_signal": dart_info["broker_signal"],
                    "risk_flags": risk_flags,
                }
                all_signals.append(sig)

                if conv == "A" and iw:
                    stock["triggered"] = True
                    stock["trigger_date"] = ds
                    stock["trigger_price"] = price
                    stock["trigger_type"] = sig["signal_type"] or "타이밍"
                    stock["conviction"] = conv

        if (di+1) % 50 == 0:
            ac = sum(1 for s in all_signals if s["conviction"]=="A")
            log.info("  %d/%d (%s) 신호%d(A:%d)", di+1, len(all_dates), ds,
                     len(all_signals), ac)

    log.info("매수신호 총 %d건 (A:%d B:%d C:%d)",
             len(all_signals),
             sum(1 for s in all_signals if s["conviction"]=="A"),
             sum(1 for s in all_signals if s["conviction"]=="B"),
             sum(1 for s in all_signals if s["conviction"]=="C"))
    return all_signals


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Phase 3: 성과 (시가/고가 추가)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def calc_perf(ohlcv, signals, days=5):
    recs = []
    for sig in signals:
        if sig["conviction"] not in ("A", "B"): continue
        code = sig["code"].strip().zfill(6)
        if code not in ohlcv: continue
        df = ohlcv[code]
        fut = df[df["date"] > pd.Timestamp(sig["check_date"])].head(days)
        bp = sig["current_price"]
        if bp <= 0: continue
        for i, (_, r) in enumerate(fut.iterrows(), 1):
            close_ret = (r["close"]/bp - 1)*100
            open_ret = (r["open"]/bp - 1)*100
            high_ret = (r["high"]/bp - 1)*100
            low_ret = (r["low"]/bp - 1)*100
            recs.append({
                "signal_date": sig["check_date"],
                "code": code, "name": sig.get("name", ""),
                "rank": sig["rank"], "conviction": sig["conviction"],
                "conviction_score": sig["conviction_score"],
                "signal_type": sig["signal_type"],
                "dart_risk": sig.get("dart_risk", ""),
                "ai_action": sig.get("ai_action", ""),
                "buy_price": bp, "track_day": i,
                "track_date": r["date"].strftime("%Y-%m-%d"),
                # ★ 종가 + 시가 + 고가 + 저가 수익률
                "return_pct": round(close_ret, 2),
                "open_ret": round(open_ret, 2),
                "high_ret": round(high_ret, 2),
                "low_ret": round(low_ret, 2),
                "win": close_ret > 0,
                "win_open": open_ret > 0,
            })
    return recs


def make_summary(signals, perf):
    s = {}
    s["sig_stats"] = {
        "total": len(signals),
        "A": sum(1 for x in signals if x["conviction"]=="A"),
        "B": sum(1 for x in signals if x["conviction"]=="B"),
        "C": sum(1 for x in signals if x["conviction"]=="C"),
        "in_window": sum(1 for x in signals if x.get("in_window")),
    }

    if perf:
        bdf = pd.DataFrame(perf)
        for g in ["A", "B"]:
            sub = bdf[bdf["conviction"]==g]
            if len(sub)==0: continue
            rows = []
            for d in range(1, 6):
                ds = sub[sub["track_day"]==d]
                if len(ds)==0: continue
                rows.append({
                    "day": f"D+{d}", "n": len(ds),
                    "wr_close": round(ds["win"].mean()*100, 1),
                    "avg_close": round(ds["return_pct"].mean(), 2),
                    "med_close": round(ds["return_pct"].median(), 2),
                    "wr_open": round(ds["win_open"].mean()*100, 1),
                    "avg_open": round(ds["open_ret"].mean(), 2),
                    "avg_high": round(ds["high_ret"].mean(), 2),
                    "avg_low": round(ds["low_ret"].mean(), 2),
                })
            s[f"sig_{g}"] = rows

        # A등급 순위별
        a_sub = bdf[bdf["conviction"]=="A"]
        if len(a_sub)>0:
            rr = []
            for rk in sorted(a_sub["rank"].unique()):
                sub = a_sub[a_sub["rank"]==rk]
                rr.append({"rank": int(rk), "n": len(sub),
                    "wr": round(sub["win"].mean()*100,1),
                    "avg": round(sub["return_pct"].mean(),2),
                    "avg_high": round(sub["high_ret"].mean(),2)})
            s["sig_A_by_rank"] = rr

        # DART별 A등급 성과
        if "dart_risk" in bdf.columns:
            a_dart = bdf[bdf["conviction"]=="A"]
            for risk in ["정상", "주의", "위험", ""]:
                sub = a_dart[a_dart["dart_risk"]==risk]
                if len(sub)>=5:
                    label = risk or "미확인"
                    s[f"A_dart_{label}"] = {
                        "n": len(sub),
                        "wr": round(sub["win"].mean()*100,1),
                        "avg": round(sub["return_pct"].mean(),2)}

    return s


def print_summary(s):
    print(f"\n{'='*70}")
    print(f"📊 매수신호 v2 (rank + DART/AI 연동)")
    print(f"{'='*70}")

    bs = s.get("sig_stats", {})
    print(f"\n신호: 총{bs.get('total',0)} A:{bs.get('A',0)} B:{bs.get('B',0)} C:{bs.get('C',0)}")

    for g in ["A", "B"]:
        rows = s.get(f"sig_{g}", [])
        if rows:
            print(f"\n── 매수신호 [{g}등급] (종가 / 시가 / 고가) ──")
            print(f"  {'기간':>5s} {'건수':>5s} {'종가승률':>7s} {'종가평균':>7s} {'시가평균':>7s} {'고가평균':>7s} {'저가평균':>7s}")
            for r in rows:
                print(f"  {r['day']:>5s} {r['n']:>5d} {r['wr_close']:>6.1f}% {r['avg_close']:>+6.2f}% "
                      f"{r['avg_open']:>+6.2f}% {r['avg_high']:>+6.2f}% {r['avg_low']:>+6.2f}%")

    ar = s.get("sig_A_by_rank", [])
    if ar:
        print(f"\n── A등급 순위별 ──")
        for r in ar:
            print(f"  #{r['rank']}: {r['n']}건 승률{r['wr']:.1f}% 종가{r['avg']:+.2f}% 고가{r['avg_high']:+.2f}%")

    for risk in ["정상", "주의", "위험", "미확인"]:
        d = s.get(f"A_dart_{risk}")
        if d:
            print(f"  A+DART {risk}: {d['n']}건 승률{d['wr']:.1f}% 평균{d['avg']:+.2f}%")

    print(f"{'='*70}")


def main():
    log.info("="*60)
    log.info("매수신호 재생성 v2 (rank + DART/AI)")
    log.info("="*60)

    # ① DART/AI 캐시
    dart_cache = _build_dart_cache()

    # ② 워치리스트 재생성
    rebuild_watchlists()

    # ③ OHLCV
    ohlcv = _load_ohlcv()

    # ④ 매수신호
    signals = rebuild_signals(ohlcv, dart_cache)

    # ⑤ 성과 (시가/고가 포함)
    log.info("성과 계산 (종가+시가+고가+저가)...")
    perf = calc_perf(ohlcv, signals)

    # ⑥ 저장
    save_backtest_dataset("buy_signals", signals)
    save_legacy_json(BACKTEST_DIR / "buy_signals.json", signals)
    save_backtest_dataset("buy_performance_v2", perf)
    save_legacy_json(BACKTEST_DIR / "buy_performance_v2.json", perf)

    summary = make_summary(signals, perf)
    save_backtest_dataset("summary_v2", summary)
    (BACKTEST_DIR / "summary_v2.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print_summary(summary)
    log.info("완료!")


if __name__ == "__main__":
    main()


