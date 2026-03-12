"""
시장 이벤트 캘린더 × 매매 성과 시뮬레이션
==========================================
buy_signals 기간(2024-11~2026-03)에 해당하는 시장 이벤트를 매핑하고,
이벤트 유무/유형별 D+1~D+5 성과를 비교.

사용법:
    python tools/calendar_backtest.py              # 전체 분석
    python tools/calendar_backtest.py --detail      # 이벤트 유형별 상세
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from storage import load_backtest_dataset

# ═══════════════════════════════════════════════════════════════
# 시장 이벤트 캘린더 (2024-11 ~ 2026-03)
# ═══════════════════════════════════════════════════════════════
# 규칙: 한국 옵션만기일 = 매월 두 번째 목요일
#       선물옵션 동시만기(쿼드러플위칭) = 3,6,9,12월 두 번째 목요일
#       FOMC = 연 8회 (2일간, 결과 발표 둘째날)
#       한은 금통위 = 연 8회
#       MSCI 리밸런싱 = 분기 리뷰 공표 + 실제 변경일

EVENTS = [
    # ── 2024년 11~12월 ──
    {"date": "2024-11-07", "type": "fomc", "name": "FOMC 금리결정", "impact": "high"},
    {"date": "2024-11-11", "type": "msci", "name": "MSCI 분기 리뷰", "impact": "high"},
    {"date": "2024-11-14", "type": "options_expiry", "name": "옵션만기일", "impact": "medium"},
    {"date": "2024-11-28", "type": "bok", "name": "한은 금통위", "impact": "high"},
    {"date": "2024-12-12", "type": "quad_witching", "name": "선물옵션 동시만기", "impact": "high"},
    {"date": "2024-12-18", "type": "fomc", "name": "FOMC 금리결정(점도표)", "impact": "high"},
    {"date": "2024-12-27", "type": "seasonal", "name": "배당락일", "impact": "medium"},
    {"date": "2024-12-30", "type": "seasonal", "name": "연말 폐장일", "impact": "low"},

    # ── 2025년 1월 ──
    {"date": "2025-01-02", "type": "seasonal", "name": "신년 첫 거래일(1월효과)", "impact": "medium"},
    {"date": "2025-01-09", "type": "options_expiry", "name": "옵션만기일", "impact": "medium"},
    {"date": "2025-01-16", "type": "bok", "name": "한은 금통위", "impact": "high"},
    {"date": "2025-01-29", "type": "fomc", "name": "FOMC 금리결정", "impact": "high"},

    # ── 2025년 2월 ──
    {"date": "2025-02-10", "type": "msci", "name": "MSCI 분기 리뷰", "impact": "high"},
    {"date": "2025-02-13", "type": "options_expiry", "name": "옵션만기일", "impact": "medium"},
    {"date": "2025-02-27", "type": "bok", "name": "한은 금통위(경제전망)", "impact": "high"},

    # ── 2025년 3월 ──
    {"date": "2025-03-13", "type": "quad_witching", "name": "선물옵션 동시만기", "impact": "high"},
    {"date": "2025-03-19", "type": "fomc", "name": "FOMC 금리결정(점도표)", "impact": "high"},
    {"date": "2025-03-31", "type": "audit", "name": "사업보고서 제출 마감", "impact": "high"},

    # ── 2025년 4월 ──
    {"date": "2025-04-10", "type": "options_expiry", "name": "옵션만기일", "impact": "medium"},
    {"date": "2025-04-17", "type": "bok", "name": "한은 금통위", "impact": "high"},

    # ── 2025년 5월 ──
    {"date": "2025-05-01", "type": "seasonal", "name": "Sell in May 시작", "impact": "medium"},
    {"date": "2025-05-07", "type": "fomc", "name": "FOMC 금리결정", "impact": "high"},
    {"date": "2025-05-08", "type": "options_expiry", "name": "옵션만기일", "impact": "medium"},
    {"date": "2025-05-12", "type": "msci", "name": "MSCI 반기 리뷰(대형)", "impact": "high"},
    {"date": "2025-05-15", "type": "earnings", "name": "1분기 실적시즌 마감", "impact": "medium"},
    {"date": "2025-05-29", "type": "bok", "name": "한은 금통위(경제전망)", "impact": "high"},

    # ── 2025년 6월 ──
    {"date": "2025-06-03", "type": "political", "name": "지방선거+재보궐선거", "impact": "high"},
    {"date": "2025-06-12", "type": "quad_witching", "name": "선물옵션 동시만기", "impact": "high"},
    {"date": "2025-06-18", "type": "fomc", "name": "FOMC 금리결정(점도표)", "impact": "high"},

    # ── 2025년 7월 ──
    {"date": "2025-07-09", "type": "geopolitical", "name": "미국 상호관세 유예 만료", "impact": "high"},
    {"date": "2025-07-10", "type": "options_expiry", "name": "옵션만기일+금통위", "impact": "high"},
    {"date": "2025-07-30", "type": "fomc", "name": "FOMC 금리결정", "impact": "high"},

    # ── 2025년 8월 ──
    {"date": "2025-08-01", "type": "geopolitical", "name": "상호관세 유예 만료일", "impact": "high"},
    {"date": "2025-08-07", "type": "msci", "name": "MSCI 분기 리뷰", "impact": "high"},
    {"date": "2025-08-14", "type": "options_expiry", "name": "옵션만기일", "impact": "medium"},
    {"date": "2025-08-28", "type": "bok", "name": "한은 금통위(경제전망)", "impact": "high"},

    # ── 2025년 9월 ──
    {"date": "2025-09-11", "type": "quad_witching", "name": "선물옵션 동시만기", "impact": "high"},
    {"date": "2025-09-17", "type": "fomc", "name": "FOMC 금리결정(점도표)", "impact": "high"},
    {"date": "2025-09-22", "type": "seasonal", "name": "9월 변동성 시즌", "impact": "medium"},

    # ── 2025년 10월 ──
    {"date": "2025-10-02", "type": "options_expiry", "name": "옵션만기일", "impact": "medium"},
    {"date": "2025-10-23", "type": "bok", "name": "한은 금통위", "impact": "high"},
    {"date": "2025-10-29", "type": "fomc", "name": "FOMC 금리결정", "impact": "high"},

    # ── 2025년 11월 ──
    {"date": "2025-11-05", "type": "msci", "name": "MSCI 분기 리뷰", "impact": "high"},
    {"date": "2025-11-13", "type": "options_expiry", "name": "옵션만기일", "impact": "medium"},
    {"date": "2025-11-27", "type": "bok", "name": "한은 금통위(경제전망)", "impact": "high"},

    # ── 2025년 12월 ──
    {"date": "2025-12-10", "type": "fomc", "name": "FOMC 금리결정(점도표)", "impact": "high"},
    {"date": "2025-12-11", "type": "quad_witching", "name": "선물옵션 동시만기", "impact": "high"},
    {"date": "2025-12-26", "type": "seasonal", "name": "배당락일", "impact": "medium"},
    {"date": "2025-12-30", "type": "seasonal", "name": "연말 폐장일", "impact": "low"},

    # ── 2026년 1~3월 ──
    {"date": "2026-01-02", "type": "seasonal", "name": "신년 첫 거래일", "impact": "medium"},
    {"date": "2026-01-08", "type": "options_expiry", "name": "옵션만기일", "impact": "medium"},
    {"date": "2026-01-15", "type": "bok", "name": "한은 금통위", "impact": "high"},
    {"date": "2026-01-28", "type": "fomc", "name": "FOMC 금리결정", "impact": "high"},
    {"date": "2026-02-10", "type": "msci", "name": "MSCI 분기 리뷰", "impact": "high"},
    {"date": "2026-02-12", "type": "options_expiry", "name": "옵션만기일", "impact": "medium"},
    {"date": "2026-02-26", "type": "bok", "name": "한은 금통위(경제전망)", "impact": "high"},
    {"date": "2026-03-12", "type": "quad_witching", "name": "선물옵션 동시만기", "impact": "high"},
    {"date": "2026-03-18", "type": "fomc", "name": "FOMC 금리결정(점도표)", "impact": "high"},
    {"date": "2026-03-31", "type": "audit", "name": "사업보고서 제출 마감", "impact": "high"},

    # ── 특수 이벤트 (한국 정치/지정학) ──
    {"date": "2024-12-03", "type": "political", "name": "계엄령 선포", "impact": "critical"},
    {"date": "2024-12-04", "type": "political", "name": "계엄령 해제/폭락", "impact": "critical"},
    {"date": "2024-12-14", "type": "political", "name": "대통령 탄핵안 가결", "impact": "critical"},
    {"date": "2025-01-15", "type": "political", "name": "대통령 체포 집행", "impact": "high"},
    {"date": "2025-04-04", "type": "political", "name": "탄핵 인용 결정", "impact": "critical"},
]

# 이벤트 ±1일 영향권 (전날/당일/다음날)
EVENT_WINDOW = 1  # 당일 + 전후 1일


def build_event_map(window=EVENT_WINDOW):
    """날짜 → 이벤트 리스트 매핑 (영향권 포함)"""
    event_map = {}  # date_str -> [events]
    for ev in EVENTS:
        center = datetime.strptime(ev["date"], "%Y-%m-%d").date()
        for delta in range(-window, window + 1):
            d = center + timedelta(days=delta)
            ds = d.strftime("%Y-%m-%d")
            if ds not in event_map:
                event_map[ds] = []
            event_map[ds].append({
                **ev,
                "distance": delta,  # 0=당일, -1=전날, +1=다음날
            })
    return event_map


def load_perf():
    """performance 데이터 로드"""
    perf = load_backtest_dataset("buy_performance_v2")
    if not perf:
        perf = load_backtest_dataset("buy_performance")
    df = pd.DataFrame(perf or [])
    if df.empty:
        return df
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["signal_date"] = pd.to_datetime(df["signal_date"], errors="coerce")
    return df


def tag_events(perf_df, event_map):
    """각 신호에 이벤트 태그 부착"""
    perf = perf_df.copy()
    perf["signal_date_str"] = perf["signal_date"].dt.strftime("%Y-%m-%d")

    perf["has_event"] = perf["signal_date_str"].isin(event_map)
    perf["event_types"] = perf["signal_date_str"].apply(
        lambda d: list({e["type"] for e in event_map.get(d, [])})
    )
    perf["event_names"] = perf["signal_date_str"].apply(
        lambda d: [e["name"] for e in event_map.get(d, []) if e["distance"] == 0]
    )
    perf["event_impact"] = perf["signal_date_str"].apply(
        lambda d: max(
            ({"critical": 4, "high": 3, "medium": 2, "low": 1}.get(e["impact"], 0)
             for e in event_map.get(d, [])),
            default=0
        )
    )
    perf["event_count"] = perf["event_types"].apply(len)

    return perf


def event_vs_no_event(perf):
    """이벤트 유/무 성과 비교"""
    print(f"\n{'='*90}")
    print(f"  이벤트 유무별 D+1~D+5 성과")
    print(f"{'='*90}")

    for td in [1, 2, 3, 5]:
        day = perf[perf["track_day"] == td]
        ev = day[day["has_event"]]
        no = day[~day["has_event"]]

        if ev.empty or no.empty:
            continue

        print(f"\n  D+{td}:")
        print(f"  {'':16} {'건수':>6} {'승률':>7} {'평균수익':>9} {'고가평균':>9}")
        print(f"  {'─'*50}")

        for label, sub in [("이벤트 있음", ev), ("이벤트 없음", no), ("전체", day)]:
            wr = sub["win"].astype(int).mean() * 100
            avg = sub["return_pct"].mean()
            hi = sub["high_ret"].mean() if "high_ret" in sub.columns else 0
            print(f"  {label:<16} {len(sub):>6} {wr:>6.1f}% {avg:>+8.2f}% {hi:>+8.2f}%")


def by_event_type(perf):
    """이벤트 유형별 성과"""
    print(f"\n{'='*90}")
    print(f"  이벤트 유형별 D+1~D+5 성과")
    print(f"{'='*90}")

    # 모든 유형 추출
    all_types = set()
    for types in perf["event_types"]:
        all_types.update(types)

    type_labels = {
        "fomc": "FOMC",
        "bok": "한은 금통위",
        "options_expiry": "옵션만기일",
        "quad_witching": "동시만기(쿼드)",
        "msci": "MSCI 리밸런싱",
        "seasonal": "시즌이벤트",
        "audit": "감사/사업보고서",
        "political": "정치이벤트",
        "geopolitical": "지정학",
        "earnings": "실적시즌",
    }

    for td in [1, 3, 5]:
        day = perf[perf["track_day"] == td]
        no_event = day[~day["has_event"]]

        print(f"\n{'─'*90}")
        print(f"  D+{td}")
        print(f"{'─'*90}")
        print(f"  {'유형':<18} {'건수':>6} {'승률':>7} {'평균수익':>9} {'고가평균':>9} {'vs 비이벤트':>12}")
        print(f"  {'─'*68}")

        no_wr = no_event["win"].astype(int).mean() * 100 if not no_event.empty else 0
        no_avg = no_event["return_pct"].mean() if not no_event.empty else 0
        no_hi = no_event["high_ret"].mean() if "high_ret" in no_event.columns and not no_event.empty else 0
        print(f"  {'비이벤트일(기준)':<18} {len(no_event):>6} {no_wr:>6.1f}% {no_avg:>+8.2f}% {no_hi:>+8.2f}%")

        results = []
        for etype in sorted(all_types):
            sub = day[day["event_types"].apply(lambda x: etype in x)]
            if len(sub) < 10:
                continue
            wr = sub["win"].astype(int).mean() * 100
            avg = sub["return_pct"].mean()
            hi = sub["high_ret"].mean() if "high_ret" in sub.columns else 0
            diff = avg - no_avg
            label = type_labels.get(etype, etype)
            results.append((label, len(sub), wr, avg, hi, diff))

        # 차이순 정렬
        results.sort(key=lambda x: x[5])
        for label, n, wr, avg, hi, diff in results:
            marker = " ⚠️" if diff < -0.5 else (" ✅" if diff > 0.5 else "")
            print(f"  {label:<18} {n:>6} {wr:>6.1f}% {avg:>+8.2f}% {hi:>+8.2f}% {diff:>+11.2f}%{marker}")


def by_impact_level(perf):
    """임팩트 레벨별 성과"""
    print(f"\n{'='*90}")
    print(f"  이벤트 영향도별 D+3 성과")
    print(f"{'='*90}")

    day3 = perf[perf["track_day"] == 3]
    impact_labels = {0: "이벤트없음", 1: "낮음(low)", 2: "보통(medium)", 3: "높음(high)", 4: "극심(critical)"}

    print(f"  {'영향도':<16} {'건수':>6} {'승률':>7} {'평균수익':>9} {'고가평균':>9}")
    print(f"  {'─'*52}")

    for level in [0, 1, 2, 3, 4]:
        sub = day3[day3["event_impact"] == level]
        if len(sub) < 5:
            continue
        wr = sub["win"].astype(int).mean() * 100
        avg = sub["return_pct"].mean()
        hi = sub["high_ret"].mean() if "high_ret" in sub.columns else 0
        print(f"  {impact_labels[level]:<16} {len(sub):>6} {wr:>6.1f}% {avg:>+8.2f}% {hi:>+8.2f}%")


def multi_event_effect(perf):
    """이벤트 겹침 효과"""
    print(f"\n{'='*90}")
    print(f"  이벤트 겹침 효과 (D+3)")
    print(f"{'='*90}")

    day3 = perf[perf["track_day"] == 3]

    print(f"  {'겹침수':<10} {'건수':>6} {'승률':>7} {'평균수익':>9}")
    print(f"  {'─'*38}")

    for count in range(5):
        sub = day3[day3["event_count"] == count]
        if len(sub) < 5:
            continue
        wr = sub["win"].astype(int).mean() * 100
        avg = sub["return_pct"].mean()
        label = f"{count}개" if count > 0 else "없음"
        print(f"  {label:<10} {len(sub):>6} {wr:>6.1f}% {avg:>+8.2f}%")


def calendar_summary(event_map):
    """캘린더 요약"""
    print(f"\n{'='*90}")
    print(f"  등록된 이벤트 요약")
    print(f"{'='*90}")

    from collections import Counter
    type_count = Counter(e["type"] for e in EVENTS)
    print(f"  총 이벤트: {len(EVENTS)}개")
    for t, c in type_count.most_common():
        print(f"    {t}: {c}개")

    # buy_signals 기간 내 이벤트
    signals = load_backtest_dataset("buy_signals") or []
    dates = sorted(set(s["check_date"] for s in signals))
    event_dates = set()
    for d in dates:
        if d in event_map:
            event_dates.add(d)
    print(f"\n  buy_signals 거래일 {len(dates)}일 중 이벤트 영향권: {len(event_dates)}일 ({len(event_dates)/len(dates)*100:.1f}%)")


def main():
    parser = argparse.ArgumentParser(description="시장 캘린더 백테스트")
    parser.add_argument("--detail", action="store_true", help="유형별 상세")
    parser.add_argument("--window", type=int, default=1, help="이벤트 영향 범위 (기본: ±1일)")
    args = parser.parse_args()

    event_map = build_event_map(args.window)
    perf = load_perf()

    if perf.empty:
        print("❌ performance 데이터 없음")
        return

    perf = tag_events(perf, event_map)

    calendar_summary(event_map)
    event_vs_no_event(perf)
    by_event_type(perf)
    by_impact_level(perf)
    multi_event_effect(perf)

    # JSON 저장
    cal_path = ROOT / "data" / "reference" / "market_calendar.json"
    cal_path.parent.mkdir(parents=True, exist_ok=True)
    cal_path.write_text(json.dumps(EVENTS, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n캘린더 저장: {cal_path}")


if __name__ == "__main__":
    main()
