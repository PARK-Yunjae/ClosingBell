"""
ClosingBell v3.5 — 풀 파이프라인 백필
======================================
위치: ClosingBell/ 프로젝트 루트 (main.py 옆)

◆ 기존 backfill.py와 차이:
  ✅ 9지표 100점 (vol_burst + overheat) — screener와 점수 100% 일치
  ✅ DART 공시 — 전체 유니버스, 과거 날짜 기준, 월 단위 캐시
  ✅ 거래원(ka10038) — 최근 120거래일 이내 (API 제한)
  ✅ 룰기반 AI — 전체 유니버스 (Gemini 미호출, 비용 0)
  ✅ 워치리스트 생성 → 눌림목 매수후보 시뮬레이션 (A/B/C 등급)
  ✅ 성과: 스크리닝 D+1~D+5 + 매수신호 D+1~D+5 별도

◆ 결과물:
  data/logs/*.json           — 기존 형식 호환 (+ vol_ratio, overheat, dart, ai)
  data/watchlist/*.json      — 기존 형식 호환
  data/performance/tracking.json — 재계산
  data/backtest/
    ├── buy_signals.json     — 눌림목 매수 신호
    ├── buy_performance.json — 매수 신호 D+1~D+5
    └── summary.json         — 전체 통계

◆ 소요시간 (~300거래일 기준):
  기본(스크리닝):     ~10분
  + DART 전체:       +1~3시간 (0.5초/건, 캐시 적용)
  + 거래원(enrich):  +30분 (최근 120일만)
  합계:              약 2~4시간

사용법:
    python backfill_full.py                                      # 전체 (2024-11-01~어제)
    python backfill_full.py --start 2025-01-01 --end 2026-03-07  # 기간 지정
    python backfill_full.py --force                               # 기존 로그 덮어쓰기
    python backfill_full.py --no-dart                             # DART 스킵
    python backfill_full.py --no-enrich                           # 거래원 스킵
    python backfill_full.py --dry-run                             # 추정만
"""
import argparse
import json
import logging
import sys
import time as _time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

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
    SCORE_VOLUME_BURST, VOL_BURST_OPTIMAL, VOL_BURST_ZERO_HIGH,
    OVERHEAT_PENALTY, OVERHEAT_CCI_THRESH, OVERHEAT_RSI_THRESH, OVERHEAT_GAP_THRESH,
    TOP_N, TOP_N_CONSERVATIVE,
    MIN_PRICE, MAX_PRICE,
    MIN_CHANGE_RATE, MAX_CHANGE_RATE,
    NASDAQ_DROP_THRESHOLD, NASDAQ_PENALTY,
    EXCLUDE_NAMES, ETF_KEYWORDS,
    WATCHLIST_DIR, WATCHLIST_MAX_DAYS, PERFORMANCE_DIR,
    PULLBACK_MA5_GAP, PULLBACK_VOL_DECLINE, PULLBACK_BB_LOWER,
    BACKTEST_DIR,
    KIWOOM_BASE_URL, KIWOOM_APPKEY, KIWOOM_SECRETKEY, API_DELAY,
    DART_API_KEY,
)
from screener import bell_score, _count_rising
from trading_calendar import add_trading_days, trading_days_between
from watchlist_monitor import RANK_TIMING
from ai_analyzer import AIAnalyzer
from storage import (
    get_screen_result,
    get_watchlist,
    save_backtest_dataset,
    save_legacy_json,
    save_screen_result,
    save_watchlist_payload,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("backfill_full")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  데이터 로드
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _load_ohlcv():
    log.info("OHLCV 로드 중...")
    out = {}
    for f in OHLCV_DIR.glob("*.csv"):
        if f.stem.startswith("INDEX_"): continue
        try:
            df = pd.read_csv(f); df.columns = [c.lower() for c in df.columns]
            df["date"] = pd.to_datetime(df["date"]); df = df.sort_values("date").reset_index(drop=True)
            if len(df) >= 30: out[f.stem] = df
        except Exception: pass
    log.info("  %d종목 로드", len(out)); return out

def _load_map():
    try:
        df = pd.read_csv(MAPPING_CSV, dtype={"code":str}, encoding="utf-8-sig")
        df["code"] = df["code"].str.zfill(6); return df.set_index("code").to_dict("index")
    except: return {}

def _load_global():
    try:
        df = pd.read_csv(GLOBAL_CSV); df.columns = [c.strip().lower() for c in df.columns]
        df["date"] = pd.to_datetime(df["date"]); return df
    except: return pd.DataFrame()

def _excluded(code, name):
    for kw in EXCLUDE_NAMES:
        if kw in name: return True
    for kw in ETF_KEYWORDS:
        if kw in name: return True
    if code[-1] in "5789": return True
    if name.endswith("우") or name.endswith("우B"): return True
    return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  9지표 점수 (screener.py v3.5와 100% 동일)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _calc(df, idx):
    if idx < 30: return None
    w = df.iloc[max(0,idx-59):idx+1].copy()
    if len(w) < 20: return None
    latest = w.iloc[-1]; price = int(latest["close"])
    if price < MIN_PRICE or price > MAX_PRICE: return None

    prev_close = df.iloc[idx-1]["close"] if idx > 0 else price
    cr = (price/prev_close - 1)*100 if prev_close > 0 else 0
    if not (MIN_CHANGE_RATE <= cr <= MAX_CHANGE_RATE): return None

    w["ma20"] = w["close"].rolling(20).mean(); w["ma5"] = w["close"].rolling(5).mean()
    ma20 = w.iloc[-1]["ma20"]; ma5 = w.iloc[-1]["ma5"]
    if pd.isna(ma20) or ma20 <= 0: return None
    mg = (price/ma20 - 1)*100

    tp = (w["high"]+w["low"]+w["close"])/3
    sma = tp.rolling(CCI_PERIOD).mean()
    mad = tp.rolling(CCI_PERIOD).apply(lambda x: np.abs(x-x.mean()).mean(), raw=True)
    w["cci"] = (tp-sma)/(0.015*mad)

    delta = w["close"].diff()
    g = delta.clip(lower=0).rolling(RSI_PERIOD).mean()
    l = (-delta.clip(upper=0)).rolling(RSI_PERIOD).mean()
    w["rsi"] = 100 - 100/(1 + g/l.replace(0, np.nan))

    cci = float(w.iloc[-1]["cci"]) if pd.notna(w.iloc[-1]["cci"]) else 0
    rsi = float(w.iloc[-1]["rsi"]) if pd.notna(w.iloc[-1]["rsi"]) else 50
    cs = _count_rising(w.tail(4)["cci"].dropna().tolist())
    ms = _count_rising(w.tail(4)["ma20"].dropna().tolist())

    vw = w.tail(50); vol = int(latest["volume"])
    if len(vw) >= 10 and price > 0:
        tv = vw["volume"].sum()
        av = vw[((vw["open"]+vw["close"])/2) > price]["volume"].sum()
        vp = (av/tv*100) if tv > 0 else 50
    else: vp = 50

    tval = int(vol*price/1_000_000)
    vm20 = w["volume"].tail(20).mean()
    vr = vol/vm20 if vm20 > 0 else 1.0

    # ── 점수 ──
    sc = 0.0
    sc += bell_score(cci, CCI_OPTIMAL[0], CCI_OPTIMAL[1], CCI_ZERO_LOW, CCI_ZERO_HIGH, SCORE_CCI)
    sc += bell_score(mg, MA20_GAP_OPTIMAL[0], MA20_GAP_OPTIMAL[1], 0, MA20_GAP_ZERO, SCORE_MA20_GAP)
    sc += bell_score(cr, CHANGE_OPTIMAL[0], CHANGE_OPTIMAL[1], 0, CHANGE_ZERO, SCORE_CHANGE)
    sc += min(SCORE_CCI_SLOPE, max(0, cs)*3.33)
    sc += min(SCORE_MA20_SLOPE, max(0, ms)*3.33)
    sc += bell_score(rsi, RSI_OPTIMAL[0], RSI_OPTIMAL[1], RSI_ZERO_LOW, RSI_ZERO_HIGH, SCORE_RSI)
    if vp <= 20: sc += SCORE_VOLUME_PROFILE
    elif vp <= 35: sc += SCORE_VOLUME_PROFILE*0.7
    elif vp <= 50: sc += SCORE_VOLUME_PROFILE*0.4
    elif vp <= 65: sc += SCORE_VOLUME_PROFILE*0.2
    # broker_score added in enrich phase
    if vr >= VOL_BURST_OPTIMAL[0]:
        sc += bell_score(vr, VOL_BURST_OPTIMAL[0], VOL_BURST_OPTIMAL[1], 1.0, VOL_BURST_ZERO_HIGH, SCORE_VOLUME_BURST)

    oh = bool(cci > OVERHEAT_CCI_THRESH and rsi > OVERHEAT_RSI_THRESH and mg > OVERHEAT_GAP_THRESH)
    if oh: sc = max(0, sc - OVERHEAT_PENALTY)

    c20 = list(w["close"].tail(20).values)
    bm = np.mean(c20); bs = np.std(c20)
    bl = bm-2*bs; bu = bm+2*bs
    bp = (price-bl)/(bu-bl) if bu > bl else 0.5

    return {
        "price": price, "change_rate": round(cr,1), "score": round(sc,1),
        "cci": round(cci,1), "rsi": round(rsi,1), "ma20_gap": round(mg,1),
        "cci_slope": cs, "ma20_slope": ms,
        "vp_above_pct": round(vp,1),
        "vp_tag": "위 매물 적음" if vp<=30 else ("위 저항 강함" if vp>=60 else "매물대 중립"),
        "trading_value": tval, "volume": vol,
        "vol_ratio": round(vr,2), "overheat": oh,
        "ma5": round(float(ma5),1) if pd.notna(ma5) else 0,
        "bb_position": round(bp,3),
        "broker_score":0, "broker_signal":"", "broker_top_buy":"",
        "foreign_net":0,
        "dart_risk":"", "dart_note":"", "profit_loss":"",
        "ai_action":"", "ai_risk":"", "ai_summary":"",
    }


def _rescore(s):
    """broker_score 반영 재계산"""
    sc = 0.0
    sc += bell_score(s.get("cci",0), CCI_OPTIMAL[0], CCI_OPTIMAL[1], CCI_ZERO_LOW, CCI_ZERO_HIGH, SCORE_CCI)
    sc += bell_score(s.get("ma20_gap",0), MA20_GAP_OPTIMAL[0], MA20_GAP_OPTIMAL[1], 0, MA20_GAP_ZERO, SCORE_MA20_GAP)
    sc += bell_score(s.get("change_rate",0), CHANGE_OPTIMAL[0], CHANGE_OPTIMAL[1], 0, CHANGE_ZERO, SCORE_CHANGE)
    sc += min(SCORE_CCI_SLOPE, max(0, s.get("cci_slope",0))*3.33)
    sc += min(SCORE_MA20_SLOPE, max(0, s.get("ma20_slope",0))*3.33)
    sc += bell_score(s.get("rsi",50), RSI_OPTIMAL[0], RSI_OPTIMAL[1], RSI_ZERO_LOW, RSI_ZERO_HIGH, SCORE_RSI)
    a = s.get("vp_above_pct",50)
    if a<=20: sc += SCORE_VOLUME_PROFILE
    elif a<=35: sc += SCORE_VOLUME_PROFILE*0.7
    elif a<=50: sc += SCORE_VOLUME_PROFILE*0.4
    elif a<=65: sc += SCORE_VOLUME_PROFILE*0.2
    sc += min(SCORE_BROKER_FLOW, s.get("broker_score",0))
    vr = s.get("vol_ratio",1.0)
    if vr >= VOL_BURST_OPTIMAL[0]:
        sc += bell_score(vr, VOL_BURST_OPTIMAL[0], VOL_BURST_OPTIMAL[1], 1.0, VOL_BURST_ZERO_HIGH, SCORE_VOLUME_BURST)
    if s.get("cci",0)>OVERHEAT_CCI_THRESH and s.get("rsi",0)>OVERHEAT_RSI_THRESH and s.get("ma20_gap",0)>OVERHEAT_GAP_THRESH:
        sc = max(0, sc - OVERHEAT_PENALTY)
    return round(sc,1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DART — 과거 날짜, 월 단위 캐시
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class _Dart:
    RISK = ["횡령","배임","상장폐지","감사의견거절","감사의견한정","관리종목","투자주의"]
    WARN = ["전환사채","신주인수권","유상증자","무상감자","주식분할"]

    def __init__(self):
        from dart_checker import DartChecker
        self._dc = DartChecker()
        self._cache = {}
        self.calls = 0

    def check(self, code, check_date):
        if not DART_API_KEY:
            return {"risk":"확인불가","note":"API키없음","profit_loss":""}
        ym = check_date[:7]
        ck = f"{code}_{ym}"
        if ck in self._cache: return self._cache[ck]

        cc = self._dc._get_corp_code(code)
        if not cc:
            r = {"risk":"확인불가","note":"매핑없음","profit_loss":""}
            self._cache[ck] = r; return r

        import requests
        ed = datetime.strptime(check_date, "%Y-%m-%d")
        sd = ed - timedelta(days=30)
        _time.sleep(0.5); self.calls += 1
        try:
            resp = requests.get("https://opendart.fss.or.kr/api/list.json", params={
                "crtfc_key": DART_API_KEY, "corp_code": cc,
                "bgn_de": sd.strftime("%Y%m%d"), "end_de": ed.strftime("%Y%m%d"),
                "page_count": "10"}, timeout=10)
            data = resp.json()
            if data.get("status") not in ("000","013"):
                r = {"risk":"확인불가","note":"","profit_loss":""}
                self._cache[ck] = r; return r
            risk = "정상"; notes = []
            for d in data.get("list",[]):
                t = d.get("report_nm","")
                for kw in self.RISK:
                    if kw in t: risk="위험"; notes.append(kw)
                for kw in self.WARN:
                    if kw in t and risk!="위험": risk="주의"; notes.append(kw)
            note = ", ".join(dict.fromkeys(notes))[:50] or ("양호" if risk=="정상" else "")
            r = {"risk":risk, "note":note, "profit_loss":""}
        except Exception as e:
            r = {"risk":"확인불가","note":str(e)[:30],"profit_loss":""}
        self._cache[ck] = r; return r


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  거래원 enrich (키움 API)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _enrich_broker(scored, api):
    from enricher import Enricher
    enricher = Enricher()
    ok = 0
    for s in scored:
        try:
            enricher._enrich_broker(s, api); ok += 1
        except:
            s.setdefault("broker_signal",""); s.setdefault("broker_score",0)
        _time.sleep(API_DELAY)
    return ok


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  눌림목 시뮬레이션
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _sim_pullback(ohlcv, wls, day, ds):
    sigs = []
    for _, wl in wls.items():
        if wl.get("expires","") < ds: continue
        de = trading_days_between(wl["created"], day)
        if de < 1: continue

        for st in wl.get("stocks",[]):
            if st.get("triggered"): continue
            code = st["code"]; rk = st.get("rank",99)
            ws = st.get("window_start",1); we = st.get("window_end",5)
            ss = st.get("sweet_spot_day",2); iw = ws <= de <= we

            if code not in ohlcv: continue
            df = ohlcv[code]; mask = df["date"]==day
            if not mask.any(): continue
            idx = df.index[mask][0]
            if idx < 20: continue

            row = df.iloc[idx]; price = int(row["close"]); vol = int(row["volume"])
            ep = st.get("entry_price", price)

            r5 = df.iloc[max(0,idx-4):idx+1]
            ma5 = r5["close"].mean(); mg5 = abs((price/ma5-1)*100) if ma5>0 else 999
            r20 = df.iloc[max(0,idx-19):idx+1]
            vm20 = r20["volume"].mean(); vd = vol/vm20 if vm20>0 else 1.0
            cls20 = r20["close"]; bm = cls20.mean(); bsd = cls20.std()
            bl = bm-2*bsd; bu = bm+2*bsd; bp = (price-bl)/(bu-bl) if bu>bl else 0.5
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
            sc += {1:20,3:15,4:5,5:5}.get(rk,0)
            if st.get("overheat"): sc -= 15
            if pc < -10: sc -= 5

            conv = "A" if sc>=60 else ("B" if sc>=40 else "C")
            ri = RANK_TIMING.get(rk,{})
            sig = {"code":code,"name":st.get("name",code),
                   "watchlist_date":wl["created"],"check_date":ds,
                   "rank":rk,"days_elapsed":de,"in_window":iw,"sweet_spot_day":ss,
                   "current_price":price,"entry_price":ep,
                   "price_change_pct":round(pc,1),
                   "signal_type":"+".join(tech) if tech else "",
                   "conditions_met":len(tech),
                   "conviction":conv,"conviction_score":sc,
                   "expected_wr":ri.get("exp_wr",0),"expected_ret":ri.get("exp_ret",0),
                   "original_score":st["score"]}
            sigs.append(sig)
            if conv=="A" and iw:
                st["triggered"]=True; st["trigger_date"]=ds
                st["trigger_price"]=price; st["trigger_type"]=sig["signal_type"] or "타이밍"
                st["conviction"]=conv
    return sigs


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  성과 계산
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _perf_screen(ohlcv, logs, days=5):
    recs = []
    for ds, ld in sorted(logs.items()):
        for s in ld.get("top",[]):
            code = s["code"].strip().zfill(6)
            if code not in ohlcv: continue
            fut = ohlcv[code][ohlcv[code]["date"] > pd.Timestamp(ds)].head(days)
            bp = s["price"]
            if bp <= 0: continue
            for i, (_, r) in enumerate(fut.iterrows(), 1):
                ret = (r["close"]/bp - 1)*100
                recs.append({"rec_date":ds,"code":code,"name":s.get("name",""),
                    "rank":s.get("rank",0),"score":s.get("score",0),"buy_price":bp,
                    "track_day":i,"track_date":r["date"].strftime("%Y-%m-%d"),
                    "track_price":int(r["close"]),"return_pct":round(ret,2),"win":ret>0,
                    "overheat":s.get("overheat",False),
                    "dart_risk":s.get("dart_risk",""),"ai_action":s.get("ai_action",""),
                    "broker_signal":s.get("broker_signal","")})
    return recs

def _perf_signal(ohlcv, sigs, days=5):
    recs = []
    for sig in sigs:
        if sig["conviction"] not in ("A","B"): continue
        code = sig["code"].strip().zfill(6)
        if code not in ohlcv: continue
        fut = ohlcv[code][ohlcv[code]["date"] > pd.Timestamp(sig["check_date"])].head(days)
        bp = sig["current_price"]
        if bp <= 0: continue
        for i, (_, r) in enumerate(fut.iterrows(), 1):
            ret = (r["close"]/bp - 1)*100
            recs.append({"signal_date":sig["check_date"],"watchlist_date":sig["watchlist_date"],
                "code":code,"name":sig.get("name",""),
                "rank":sig["rank"],"conviction":sig["conviction"],
                "conviction_score":sig["conviction_score"],"signal_type":sig["signal_type"],
                "days_elapsed":sig["days_elapsed"],
                "buy_price":bp,"track_day":i,"track_date":r["date"].strftime("%Y-%m-%d"),
                "track_price":int(r["close"]),"return_pct":round(ret,2),"win":ret>0})
    return recs


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  메인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def run(start_date, end_date, force=False, use_dart=True, use_enrich=True, dry_run=False):
    ohlcv = _load_ohlcv(); smap = _load_map(); gdf = _load_global()
    start = pd.Timestamp(start_date); end = pd.Timestamp(end_date)
    sdf = ohlcv[next(iter(ohlcv))]
    tdays = sorted(sdf[(sdf["date"]>=start)&(sdf["date"]<=end)]["date"].tolist())

    # 거래원 120거래일 cutoff
    bcut = tdays[-120] if use_enrich and KIWOOM_APPKEY and len(tdays)>120 else (tdays[0] if use_enrich and KIWOOM_APPKEY else None)
    new_days = sum(
        1
        for d in tdays
        if force or get_screen_result(d.strftime("%Y-%m-%d")) is None
    )
    est = new_days*2 + (new_days*40*0.5 if use_dart else 0) + (min(120,new_days)*40*0.15 if use_enrich else 0)

    log.info("="*60)
    log.info("풀 파이프라인 백필")
    log.info("  기간: %s ~ %s (%d거래일, 신규 %d일)", start_date, end_date, len(tdays), new_days)
    log.info("  DART: %s | 거래원: %s", "전체 유니버스" if use_dart else "OFF",
             f"~120일 ({bcut.strftime('%Y-%m-%d')}~)" if bcut else "OFF")
    log.info("  예상: %d분", int(est/60)+1)
    log.info("="*60)
    if dry_run: return

    # API
    api = None
    if use_enrich and KIWOOM_APPKEY:
        from kiwoom_api import KiwoomAPI
        api = KiwoomAPI(KIWOOM_APPKEY, KIWOOM_SECRETKEY, KIWOOM_BASE_URL, API_DELAY)
        api.ensure_token(); log.info("키움 API 연결")

    dart = _Dart() if use_dart else None
    ai = AIAnalyzer()

    logs_all = {}; wls_all = {}; sigs_all = []; t0 = _time.time()

    for di, day in enumerate(tdays):
        ds = day.strftime("%Y-%m-%d"); lf = LOG_DIR/f"{ds}.json"

        # 기존 로드
        if not force:
            try:
                stored_log = get_screen_result(ds)
                if stored_log is None and lf.exists():
                    stored_log = json.loads(lf.read_text(encoding="utf-8"))
                stored_wl = get_watchlist(ds)
                wp = WATCHLIST_DIR / f"{ds}.json"
                if stored_wl is None and wp.exists():
                    stored_wl = json.loads(wp.read_text(encoding="utf-8"))
                if stored_log:
                    logs_all[ds] = stored_log
                if stored_wl:
                    wls_all[ds] = stored_wl
            except Exception:
                pass
            if ds in logs_all:
                if wls_all:
                    sigs_all.extend(_sim_pullback(ohlcv, wls_all, day, ds))
                continue

        # ── 유니버스 ──
        nq = 0
        if len(gdf)>0:
            pv = gdf[gdf["date"]<day]
            if len(pv)>0 and "nasdaq_change_pct" in pv.columns:
                nv = pv.dropna(subset=["nasdaq_change_pct"])
                if len(nv)>0:
                    v = nv.iloc[-1].get("nasdaq_change_pct",0)
                    nq = float(v) if pd.notna(v) else 0
        nw = nq <= NASDAQ_DROP_THRESHOLD

        cands = []
        for code, df in ohlcv.items():
            m = df["date"]==day
            if not m.any(): continue
            idx = df.index[m][0]; row = df.iloc[idx]
            nm = smap.get(code,{}).get("name",code)
            if _excluded(code,nm): continue
            vol = int(row.get("volume",0)); pr = int(row["close"])
            if vol>0 and pr>0:
                cands.append({"code":code,"name":nm,"idx":idx,"volume":vol,
                    "trading_value":int(vol*pr/1e6),"price":pr,
                    "sector":smap.get(code,{}).get("sector","")})

        bv = sorted(cands, key=lambda x:x["volume"], reverse=True)[:100]
        bt = sorted(cands, key=lambda x:x["trading_value"], reverse=True)[:100]
        univ = {}
        for s in bv+bt:
            if s["code"] not in univ: univ[s["code"]] = s

        scored = []
        for code, c in univ.items():
            ind = _calc(ohlcv[code], c["idx"])
            if ind is None: continue
            if ind["trading_value"] < 10000: continue
            scored.append({"code":code,"name":c["name"],"sector":c["sector"],**ind})
        scored.sort(key=lambda x:x["score"], reverse=True)

        # ── DART 전체 유니버스 ──
        if dart:
            for s in scored:
                dr = dart.check(s["code"], ds)
                s["dart_risk"]=dr["risk"]; s["dart_note"]=dr["note"]
                s["profit_loss"]=dr.get("profit_loss","")

        # ── 거래원 (120일 이내) ──
        if api and bcut and day >= bcut:
            _enrich_broker(scored, api)
            for s in scored: s["score"] = _rescore(s)
            scored.sort(key=lambda x:x["score"], reverse=True)

        # ── 룰기반 AI ──
        for s in scored:
            try:
                r = ai._rule_based(s)
                s["ai_action"]=r["action"]; s["ai_risk"]=r["risk"]; s["ai_summary"]=r["summary"]
            except: pass

        # ── 나스닥/보수모드 ──
        if nw:
            for s in scored: s["score"]=round(max(0,s["score"]-NASDAQ_PENALTY),1)
            scored.sort(key=lambda x:x["score"], reverse=True)

        tn = TOP_N
        if nw: tn = TOP_N_CONSERVATIVE
        elif len(gdf)>0:
            dg = gdf[gdf["date"]==day]
            if len(dg)>0 and "kospi_close" in dg.columns:
                kp = dg.iloc[0].get("kospi_close",0)
                rk = gdf[gdf["date"]<=day].tail(20)
                if "kospi_close" in rk.columns:
                    km = rk["kospi_close"].dropna().mean()
                    if kp and km and kp < km: tn = TOP_N_CONSERVATIVE

        top = scored[:tn]
        mkt = {"nasdaq_change":nq,"nasdaq_warning":nw}
        if len(gdf)>0:
            dr = gdf[gdf["date"]==day]
            if len(dr)>0:
                r = dr.iloc[0]
                for k,c in [("kospi","kospi_close"),("kospi_change","kospi_change_pct"),
                            ("kosdaq","kosdaq_close"),("kosdaq_change","kosdaq_change_pct"),
                            ("nasdaq","nasdaq_close")]:
                    mkt[k] = float(r.get(c,0)) if pd.notna(r.get(c)) else 0

        ld = {"date":ds,"timestamp":day.isoformat(),"market":mkt,
              "universe_count":len(scored),
              "overheat_count":sum(1 for s in scored if s.get("overheat")),
              "top":[{**s,"rank":i+1} for i,s in enumerate(top)],
              "all_scored":[{**s,"rank":i+1} for i,s in enumerate(scored)]}
        save_screen_result(ld)
        save_legacy_json(lf, ld)
        logs_all[ds] = ld

        # ── 워치리스트 ──
        if top:
            wl = {"created":ds,"expires":add_trading_days(ds, WATCHLIST_MAX_DAYS),"stocks":[]}
            for s in scored[:5]:
                rk=s.get("rank",99); tm=RANK_TIMING.get(rk,RANK_TIMING[3])
                wl["stocks"].append({"code":s["code"],"name":s["name"],"rank":rk,"score":s["score"],
                    "entry_price":s["price"],"cci_at_screen":s.get("cci",0),
                    "rsi_at_screen":s.get("rsi",0),"ma20_gap_at_screen":s.get("ma20_gap",0),
                    "overheat":s.get("overheat",False),"sweet_spot_day":tm["sweet_spot"],
                    "window_start":tm["window"][0],"window_end":tm["window"][1],
                    "triggered":False,"trigger_date":None,"trigger_price":None,
                    "trigger_type":None,"conviction":None})
            save_watchlist_payload(wl)
            save_legacy_json(WATCHLIST_DIR / f"{ds}.json", wl)
            wls_all[ds] = wl

        # ── 눌림목 ──
        if wls_all: sigs_all.extend(_sim_pullback(ohlcv, wls_all, day, ds))

        # 진행률
        if (di+1)%10==0:
            el=_time.time()-t0; pct=(di+1)/len(tdays)*100
            rm=el/(di+1)*(len(tdays)-di-1)
            ac=sum(1 for s in sigs_all if s["conviction"]=="A")
            log.info("  [%3.0f%%] %d/%d (%s) 로그%d 신호%d(A:%d) 남음%d분",
                     pct,di+1,len(tdays),ds,len(logs_all),len(sigs_all),ac,int(rm/60)+1)

    # ── 성과 ──
    log.info("성과 계산...")
    sp = _perf_screen(ohlcv, logs_all)
    bp = _perf_signal(ohlcv, sigs_all)

    (PERFORMANCE_DIR/"tracking.json").write_text(
        json.dumps({"records":sp,"last_updated":datetime.now().isoformat()},ensure_ascii=False,indent=2),encoding="utf-8")
    save_backtest_dataset("buy_signals", sigs_all)
    save_legacy_json(BACKTEST_DIR / "buy_signals.json", sigs_all)
    save_backtest_dataset("buy_performance", bp)
    save_legacy_json(BACKTEST_DIR / "buy_performance.json", bp)

    # 요약
    summary = _summary(sp, bp, sigs_all, len(tdays), len(logs_all), dart.calls if dart else 0)
    save_backtest_dataset("summary", summary)
    (BACKTEST_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    el = _time.time()-t0
    log.info("="*60)
    log.info("완료! %d분%d초", int(el//60), int(el%60))
    log.info("  로그%d일 신호%d건(A:%d B:%d) 성과%d+%d건",
             len(logs_all), len(sigs_all),
             sum(1 for s in sigs_all if s["conviction"]=="A"),
             sum(1 for s in sigs_all if s["conviction"]=="B"),
             len(sp), len(bp))
    if dart: log.info("  DART: API %d건 캐시 %d건", dart.calls, len(dart._cache))
    log.info("="*60)
    _print(summary)


def _summary(sp, bp, sigs, td, tl, dc):
    s = {"generated":datetime.now().isoformat(),"total_days":td,"total_logs":tl,"dart_calls":dc}
    if sp:
        pdf = pd.DataFrame(sp); rows = []
        for rk in sorted(pdf["rank"].unique()):
            for d in range(1,6):
                sub = pdf[(pdf["rank"]==rk)&(pdf["track_day"]==d)]
                if len(sub)==0: continue
                rows.append({"rank":int(rk),"day":f"D+{d}","n":len(sub),
                    "wr":round(sub["win"].mean()*100,1),"avg":round(sub["return_pct"].mean(),2),
                    "med":round(sub["return_pct"].median(),2)})
        s["screen"] = rows
        if "overheat" in pdf.columns:
            oh=pdf[pdf["overheat"]==True]; no=pdf[pdf["overheat"]==False]
            if len(oh)>0 and len(no)>0:
                s["overheat"]={"normal_wr":round(no["win"].mean()*100,1),
                    "oh_wr":round(oh["win"].mean()*100,1),
                    "normal_avg":round(no["return_pct"].mean(),2),
                    "oh_avg":round(oh["return_pct"].mean(),2)}
        if "dart_risk" in pdf.columns:
            for r in ["정상","주의","위험"]:
                sub = pdf[pdf["dart_risk"]==r]
                if len(sub)>=5: s[f"dart_{r}"]={"n":len(sub),"wr":round(sub["win"].mean()*100,1),
                    "avg":round(sub["return_pct"].mean(),2)}
    if bp:
        bdf = pd.DataFrame(bp)
        for g in ["A","B"]:
            sub = bdf[bdf["conviction"]==g]
            if len(sub)==0: continue
            rows = []
            for d in range(1,6):
                ds = sub[sub["track_day"]==d]
                if len(ds)==0: continue
                rows.append({"day":f"D+{d}","n":len(ds),"wr":round(ds["win"].mean()*100,1),
                    "avg":round(ds["return_pct"].mean(),2)})
            s[f"sig_{g}"] = rows
    s["sig_stats"]={"total":len(sigs),
        "A":sum(1 for x in sigs if x["conviction"]=="A"),
        "B":sum(1 for x in sigs if x["conviction"]=="B"),
        "C":sum(1 for x in sigs if x["conviction"]=="C"),
        "in_window":sum(1 for x in sigs if x.get("in_window"))}
    return s


def _print(s):
    print("\n"+"="*70); print("📊 풀 백필 결과"); print("="*70)
    print(f"거래일{s['total_days']}일 로그{s['total_logs']}건 DART{s.get('dart_calls',0)}건")
    for r in s.get("screen",[]):
        print(f"  #{r['rank']} {r['day']} {r['n']:>4d}건 승률{r['wr']:>5.1f}% 평균{r['avg']:>+6.2f}% 중위{r['med']:>+6.2f}%")
    oh = s.get("overheat")
    if oh: print(f"  과열효과: 일반{oh['normal_wr']:.1f}%/{oh['normal_avg']:+.2f}% vs 과열{oh['oh_wr']:.1f}%/{oh['oh_avg']:+.2f}%")
    for r in ["정상","주의","위험"]:
        d = s.get(f"dart_{r}")
        if d: print(f"  DART {r}: {d['n']}건 {d['wr']:.1f}% {d['avg']:+.2f}%")
    for g in ["A","B"]:
        rows = s.get(f"sig_{g}",[])
        if rows:
            print(f"\n  매수신호[{g}]:")
            for r in rows: print(f"    {r['day']} {r['n']:>3d}건 {r['wr']:>5.1f}% {r['avg']:>+6.2f}%")
    bs = s.get("sig_stats",{})
    print(f"\n  신호: 총{bs.get('total',0)} A:{bs.get('A',0)} B:{bs.get('B',0)} C:{bs.get('C',0)} 윈도우:{bs.get('in_window',0)}")
    print("="*70)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="ClosingBell 풀 파이프라인 백필")
    p.add_argument("--start", default="2024-11-01")
    p.add_argument("--end", default="")
    p.add_argument("--days", type=int, default=0, help="최근 N일 (--start/end 대신)")
    p.add_argument("--force", action="store_true")
    p.add_argument("--no-dart", action="store_true")
    p.add_argument("--no-enrich", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    if a.days > 0:
        ed = datetime.now()-timedelta(days=1)
        sd = ed-timedelta(days=a.days+15)
        run(sd.strftime("%Y-%m-%d"), ed.strftime("%Y-%m-%d"), a.force, not a.no_dart, not a.no_enrich, a.dry_run)
    else:
        ed = a.end or (datetime.now()-timedelta(days=1)).strftime("%Y-%m-%d")
        run(a.start, ed, a.force, not a.no_dart, not a.no_enrich, a.dry_run)


