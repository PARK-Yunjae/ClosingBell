"""
ClosingBell — 워치리스트 + 매수신호 재생성 (rank 버그 수정)
==========================================================
기존 로그(data/logs/*.json)는 그대로 두고,
워치리스트와 매수신호만 올바른 rank로 재생성합니다.

버그: backfill_full.py가 워치리스트에 rank=99를 넣어서
     1위/3위 타이밍 최적화가 작동하지 않았음.

수정: 로그의 all_scored에서 rank를 가져오거나, 순서 기반으로 1,2,3,4,5 할당.

사용법:
    python repair_watchlist.py              # 재생성
    python repair_watchlist.py --dry-run    # 미리보기만
"""
import json
import logging
import sys
import pandas as pd
import numpy as np
from datetime import datetime
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
log = logging.getLogger("repair")

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


def rebuild_watchlists(dry_run=False):
    """로그에서 워치리스트 재생성 (올바른 rank)"""
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
        # all_scored에는 rank가 올바르게 들어있음
        all_scored = data.get("all_scored", [])
        top5 = all_scored[:5]
        if not top5: continue

        wl = {
            "created": ds,
            "expires": add_trading_days(ds, WATCHLIST_MAX_DAYS),
            "stocks": [],
        }

        for stock in top5:
            rank = stock.get("rank", 99)
            # 혹시 rank가 없으면 순서 기반
            if rank == 99 or rank == 0:
                rank = top5.index(stock) + 1

            timing = RANK_TIMING.get(rank, RANK_TIMING.get(3, {"sweet_spot": 3, "window": (2, 4)}))

            wl["stocks"].append({
                "code": stock["code"],
                "name": stock.get("name", stock["code"]),
                "rank": rank,
                "score": stock.get("score", 0),
                "entry_price": stock.get("price", 0),
                "cci_at_screen": stock.get("cci", 0),
                "rsi_at_screen": stock.get("rsi", 0),
                "ma20_gap_at_screen": stock.get("ma20_gap", 0),
                "overheat": bool(stock.get("overheat", False)),
                "sweet_spot_day": timing["sweet_spot"],
                "window_start": timing["window"][0],
                "window_end": timing["window"][1],
                "triggered": False,
                "trigger_date": None,
                "trigger_price": None,
                "trigger_type": None,
                "conviction": None,
            })

        if not dry_run:
            save_watchlist_payload(wl)
            save_legacy_json(WATCHLIST_DIR / f"{ds}.json", wl)

        created += 1

    log.info("워치리스트 %d개 %s", created, "생성" if not dry_run else "(드라이런)")
    return created


def rebuild_signals(ohlcv, dry_run=False):
    """워치리스트에서 눌림목 매수신호 재생성"""
    # 모든 워치리스트 로드
    watchlists = {}
    for wl in _load_watchlist_payloads():
        try:
            watchlists[wl["created"]] = wl
        except Exception:
            pass

    log.info("워치리스트 %d개 로드", len(watchlists))

    # 거래일 목록 (삼성전자 기준)
    ref = ohlcv.get("005930")
    if ref is None:
        ref = ohlcv[next(iter(ohlcv))]
    all_dates = sorted(ref["date"].tolist())

    all_signals = []

    for day in all_dates:
        ds = day.strftime("%Y-%m-%d")

        for wl_date, wl in watchlists.items():
            if wl.get("expires", "") < ds: continue
            if wl["created"] >= ds: continue

            days_elapsed = trading_days_between(wl["created"], day)
            if days_elapsed < 1: continue

            for stock in wl.get("stocks", []):
                if stock.get("triggered"): continue

                code = stock["code"]
                rank = stock.get("rank", 99)
                ws = stock.get("window_start", 1)
                we = stock.get("window_end", 5)
                ss = stock.get("sweet_spot_day", 2)
                iw = ws <= days_elapsed <= we

                if code not in ohlcv: continue
                df = ohlcv[code]
                mask = df["date"] == day
                if not mask.any(): continue
                idx = df.index[mask][0]
                if idx < 20: continue

                row = df.iloc[idx]
                price = int(row["close"]); volume = int(row["volume"])
                ep = stock.get("entry_price", price)

                # MA5
                r5 = df.iloc[max(0,idx-4):idx+1]
                ma5 = r5["close"].mean()
                mg5 = abs((price/ma5-1)*100) if ma5>0 else 999

                # 거래량
                r20 = df.iloc[max(0,idx-19):idx+1]
                vm20 = r20["volume"].mean()
                vd = volume/vm20 if vm20>0 else 1.0

                # 볼린저
                cls20 = r20["close"]
                bm = cls20.mean(); bsd = cls20.std()
                bl = bm-2*bsd; bu = bm+2*bsd
                bp = (price-bl)/(bu-bl) if bu>bl else 0.5

                pc = (price/ep-1)*100 if ep>0 else 0

                # 조건
                tech = []; sc = 0
                if mg5 <= PULLBACK_MA5_GAP: tech.append("MA5터치"); sc += 15
                elif mg5 <= PULLBACK_MA5_GAP*2: sc += 8
                if vd <= PULLBACK_VOL_DECLINE: tech.append("거래량감소"); sc += 10
                elif vd <= PULLBACK_VOL_DECLINE*1.5: sc += 5
                if bp <= PULLBACK_BB_LOWER: tech.append("BB하단"); sc += 10
                elif bp <= PULLBACK_BB_LOWER*1.5: sc += 5
                if pc < -5: tech.append("깊은조정"); sc += 5
                elif pc < -2: tech.append("가격조정"); sc += 3

                # 타이밍
                td = abs(days_elapsed - ss)
                if iw and td==0: sc+=30
                elif iw and td==1: sc+=22
                elif iw: sc+=15
                elif days_elapsed<ws: sc+=5

                # 순위 보너스 — 이제 올바른 rank 사용
                sc += {1: 20, 3: 15, 4: 5, 5: 5}.get(rank, 0)
                if stock.get("overheat"): sc -= 15
                if pc < -10: sc -= 5

                conv = "A" if sc>=60 else ("B" if sc>=40 else "C")
                ri = RANK_TIMING.get(rank, {})

                sig = {
                    "code": code, "name": stock.get("name", code),
                    "watchlist_date": wl["created"], "check_date": ds,
                    "rank": rank, "days_elapsed": days_elapsed,
                    "in_window": iw, "sweet_spot_day": ss,
                    "current_price": price, "entry_price": ep,
                    "price_change_pct": round(pc, 1),
                    "signal_type": "+".join(tech) if tech else "",
                    "conditions_met": len(tech),
                    "conviction": conv, "conviction_score": sc,
                    "expected_wr": ri.get("exp_wr", 0),
                    "expected_ret": ri.get("exp_ret", 0),
                    "original_score": stock["score"],
                }
                all_signals.append(sig)

                if conv == "A" and iw:
                    stock["triggered"] = True
                    stock["trigger_date"] = ds
                    stock["trigger_price"] = price
                    stock["trigger_type"] = sig["signal_type"] or "타이밍"
                    stock["conviction"] = conv

        # 진행률
        day_idx = all_dates.index(day)
        if (day_idx+1) % 50 == 0:
            ac = sum(1 for s in all_signals if s["conviction"]=="A")
            log.info("  %d/%d (%s) 신호%d(A:%d)", day_idx+1, len(all_dates), ds,
                     len(all_signals), ac)

    log.info("매수신호 총 %d건 (A:%d B:%d C:%d)",
             len(all_signals),
             sum(1 for s in all_signals if s["conviction"]=="A"),
             sum(1 for s in all_signals if s["conviction"]=="B"),
             sum(1 for s in all_signals if s["conviction"]=="C"))

    return all_signals


def calc_signal_perf(ohlcv, signals, days=5):
    """A/B등급 매수신호 D+1~D+5 수익률"""
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
            ret = (r["close"]/bp - 1)*100
            recs.append({
                "signal_date": sig["check_date"],
                "watchlist_date": sig["watchlist_date"],
                "code": code, "name": sig.get("name", ""),
                "rank": sig["rank"], "conviction": sig["conviction"],
                "conviction_score": sig["conviction_score"],
                "signal_type": sig["signal_type"],
                "days_elapsed": sig["days_elapsed"],
                "buy_price": bp, "track_day": i,
                "track_date": r["date"].strftime("%Y-%m-%d"),
                "track_price": int(r["close"]),
                "return_pct": round(ret, 2), "win": ret > 0,
            })
    return recs


def make_summary(signals, sig_perf):
    s = {}

    # 매수신호 통계
    s["sig_stats"] = {
        "total": len(signals),
        "A": sum(1 for x in signals if x["conviction"]=="A"),
        "B": sum(1 for x in signals if x["conviction"]=="B"),
        "C": sum(1 for x in signals if x["conviction"]=="C"),
        "in_window": sum(1 for x in signals if x.get("in_window")),
    }

    # 등급별 성과
    if sig_perf:
        bdf = pd.DataFrame(sig_perf)
        for g in ["A", "B"]:
            sub = bdf[bdf["conviction"]==g]
            if len(sub)==0: continue
            rows = []
            for d in range(1, 6):
                ds = sub[sub["track_day"]==d]
                if len(ds)==0: continue
                rows.append({
                    "day": f"D+{d}", "n": len(ds),
                    "wr": round(ds["win"].mean()*100, 1),
                    "avg": round(ds["return_pct"].mean(), 2),
                    "med": round(ds["return_pct"].median(), 2),
                })
            s[f"sig_{g}"] = rows

        # 순위별 A등급
        a_sigs = bdf[bdf["conviction"]=="A"]
        if len(a_sigs) > 0:
            rank_rows = []
            for rk in sorted(a_sigs["rank"].unique()):
                sub = a_sigs[a_sigs["rank"]==rk]
                rank_rows.append({
                    "rank": int(rk), "n": len(sub),
                    "wr": round(sub["win"].mean()*100, 1),
                    "avg": round(sub["return_pct"].mean(), 2),
                })
            s["sig_A_by_rank"] = rank_rows

    return s


def print_summary(s):
    print("\n" + "="*70)
    print("📊 워치리스트 + 매수신호 재생성 결과 (rank 수정)")
    print("="*70)

    bs = s.get("sig_stats", {})
    print(f"\n신호: 총{bs.get('total',0)} A:{bs.get('A',0)} B:{bs.get('B',0)} "
          f"C:{bs.get('C',0)} 윈도우:{bs.get('in_window',0)}")

    for g in ["A", "B"]:
        rows = s.get(f"sig_{g}", [])
        if rows:
            print(f"\n── 매수신호 [{g}등급] ──")
            print(f"  {'기간':>5s} {'건수':>5s} {'승률':>6s} {'평균':>7s} {'중위':>7s}")
            for r in rows:
                med = r.get('med', 0)
                print(f"  {r['day']:>5s} {r['n']:>5d} {r['wr']:>5.1f}% {r['avg']:>+6.2f}% {med:>+6.2f}%")

    ar = s.get("sig_A_by_rank", [])
    if ar:
        print(f"\n── A등급 순위별 ──")
        for r in ar:
            print(f"  #{r['rank']}: {r['n']}건 승률{r['wr']:.1f}% 평균{r['avg']:+.2f}%")

    # 비교
    print(f"\n── 수정 전 vs 후 비교 ──")
    print(f"  수정 전: A 16건, B 1,747건")
    print(f"  수정 후: A {bs.get('A',0)}건, B {bs.get('B',0)}건")
    print("="*70)


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    # ① 워치리스트 재생성
    log.info("=" * 60)
    log.info("Phase 1: 워치리스트 재생성 (올바른 rank)")
    log.info("=" * 60)
    rebuild_watchlists(a.dry_run)

    if a.dry_run:
        log.info("드라이런 — 종료")
        return

    # ② OHLCV 로드
    ohlcv = _load_ohlcv()

    # ③ 매수신호 재생성
    log.info("=" * 60)
    log.info("Phase 2: 매수신호 재생성")
    log.info("=" * 60)
    signals = rebuild_signals(ohlcv)

    # ④ 성과 계산
    log.info("Phase 3: 성과 계산")
    sig_perf = calc_signal_perf(ohlcv, signals)

    # ⑤ 저장
    save_backtest_dataset("buy_signals", signals)
    save_legacy_json(BACKTEST_DIR / "buy_signals.json", signals)
    save_backtest_dataset("buy_performance", sig_perf)
    save_legacy_json(BACKTEST_DIR / "buy_performance.json", sig_perf)

    summary = make_summary(signals, sig_perf)
    save_backtest_dataset("summary_repaired", summary)
    (BACKTEST_DIR / "summary_repaired.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print_summary(summary)
    log.info("완료! 결과: data/backtest/summary_repaired.json")


if __name__ == "__main__":
    main()

