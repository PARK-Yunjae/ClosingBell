"""
ClosingBell v3.7.1 점검 스크립트
=================================
로컬에서 실행: python tools/healthcheck.py

API 호출 없이 할 수 있는 것 + API 있으면 실제 테스트까지.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime


def section(title):
    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print(f"{'─' * 50}")


def main():
    print("=" * 50)
    print("  ClosingBell v3.7.1 점검")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    # ══════════════════════════════════════
    # 1. config 로드
    # ══════════════════════════════════════
    section("1. config 로드")
    try:
        from config import (
            KIWOOM_APPKEY, DISCORD_WEBHOOK_URL, GEMINI_API_KEY,
            NAVER_CLIENT_ID, DART_API_KEY,
            OHLCV_DIR, GLOBAL_CSV, MAPPING_CSV, MAJOR_HOLDER_CSV,
            BUY_NEWS_CAUTION_PENALTY,
        )
        print(f"  키움 API: {'✅ 설정됨' if KIWOOM_APPKEY else '❌ 없음'}")
        print(f"  Discord: {'✅ 설정됨' if DISCORD_WEBHOOK_URL else '❌ 없음'}")
        print(f"  Gemini: {'✅ 설정됨' if GEMINI_API_KEY else '⚠️ 없음 (뉴스 키워드 판정으로 대체)'}")
        print(f"  네이버 뉴스: {'✅ 설정됨' if NAVER_CLIENT_ID else '⚠️ 없음'}")
        print(f"  DART: {'✅ 설정됨' if DART_API_KEY else '⚠️ 없음'}")
        print(f"  뉴스 주의 감점: {BUY_NEWS_CAUTION_PENALTY}점 {'✅' if BUY_NEWS_CAUTION_PENALTY >= 5 else '⚠️ 3→5 반영 안됨'}")
    except Exception as e:
        print(f"  ❌ config 로드 실패: {e}")
        return

    # ══════════════════════════════════════
    # 2. 데이터 파일 확인
    # ══════════════════════════════════════
    section("2. 데이터 파일 확인")
    import pandas as pd
    from pathlib import Path

    data_checks = [
        ("OHLCV 디렉토리", OHLCV_DIR, "dir"),
        ("글로벌 지수 CSV", GLOBAL_CSV, "file"),
        ("종목 매핑 CSV", MAPPING_CSV, "file"),
        ("대주주 CSV", MAJOR_HOLDER_CSV, "file"),
    ]
    for name, path, kind in data_checks:
        p = Path(path)
        if kind == "dir":
            if p.exists():
                count = len(list(p.glob("*.csv")))
                print(f"  ✅ {name}: {count}개 종목")
            else:
                print(f"  ❌ {name}: 경로 없음 ({p})")
        else:
            if p.exists():
                print(f"  ✅ {name}: {p.stat().st_size // 1024}KB")
            else:
                print(f"  ❌ {name}: 파일 없음 ({p})")

    # main_products 컬럼 체크
    if Path(MAPPING_CSV).exists():
        try:
            df = pd.read_csv(MAPPING_CSV, dtype={"code": str}, nrows=5)
            has_products = "main_products" in df.columns
            if has_products:
                filled = df["main_products"].notna().sum()
                print(f"  ✅ main_products 컬럼: 있음 (샘플 {filled}/5 채워짐)")
            else:
                print(f"  ⚠️ main_products 컬럼: 없음 — 🔧 주요 제품이 웹훅에 안 뜸")
                print(f"     → stock_mapping.csv에 main_products 컬럼 추가 필요")
        except Exception as e:
            print(f"  ⚠️ stock_mapping 확인 실패: {e}")

    # ══════════════════════════════════════
    # 3. 캘린더 이벤트 확인
    # ══════════════════════════════════════
    section("3. 캘린더 이벤트 확인")
    try:
        from market_context import get_market_context, clear_market_context_cache
        clear_market_context_cache()
        ctx = get_market_context()

        today = datetime.now().strftime("%Y-%m-%d")
        today_events = ctx.get_events(today)
        today_adj = ctx.get_score_adjustment(today)
        today_warning = ctx.get_event_warning(today)

        print(f"  오늘 ({today}):")
        if today_events:
            for ev in today_events:
                dist = ev.get("distance", 0)
                dist_str = f"(±{abs(dist)}일)" if dist != 0 else "(당일)"
                print(f"    📅 {ev['name']} {dist_str} | 영향: {ev['impact']}")
            print(f"    점수 조정: {today_adj:+.1f}점")
        else:
            print(f"    이벤트 없음")

        # 다가오는 이벤트 5개
        from datetime import timedelta
        upcoming = []
        for days in range(1, 31):
            d = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
            evts = ctx.get_events(d)
            for ev in evts:
                if ev.get("distance", 0) == 0:  # 당일 이벤트만
                    upcoming.append((d, ev))
            if len(upcoming) >= 5:
                break

        print(f"\n  다가오는 이벤트 (30일 이내):")
        for d, ev in upcoming[:5]:
            days_left = (datetime.strptime(d, "%Y-%m-%d") - datetime.now()).days + 1
            print(f"    {d} (D-{days_left}) | {ev['name']} | {ev['impact']}")

        # 캘린더 총 이벤트 수
        total = len(ctx._events)
        print(f"\n  캘린더 총 이벤트: {total}개")

    except Exception as e:
        print(f"  ❌ 캘린더 확인 실패: {e}")

    # ══════════════════════════════════════
    # 4. 대주주 데이터 확인
    # ══════════════════════════════════════
    section("4. 대주주 데이터 확인")
    try:
        holder_count = len(ctx._holder_level)
        change_count = len(ctx._holder_change)
        print(f"  지분 수준: {holder_count}종목")
        print(f"  지분 변동: {change_count}종목")

        # 투매 종목 확인
        dumping = [code for code in ctx._holder_change if ctx.is_dumping(code)]
        if dumping:
            print(f"  ⚠️ 투매 의심 종목: {len(dumping)}개")
            for code in dumping[:3]:
                chg = ctx.get_holder_change(code)
                print(f"    {code}: {chg:+.1f}%p")
        else:
            print(f"  ✅ 투매 의심 종목 없음")
    except Exception as e:
        print(f"  ⚠️ 대주주 확인 실패: {e}")

    # ══════════════════════════════════════
    # 5. DB 상태 확인
    # ══════════════════════════════════════
    section("5. DB 상태 확인")
    try:
        from storage import (
            load_active_watchlists, list_screen_dates,
        )
        from config import APP_DB_PATH

        if Path(APP_DB_PATH).exists():
            size = Path(APP_DB_PATH).stat().st_size // 1024
            print(f"  DB 파일: {APP_DB_PATH} ({size}KB)")
        else:
            print(f"  ⚠️ DB 파일 없음 (첫 실행 시 자동 생성)")

        # 스크리닝 이력
        dates = list_screen_dates(desc=True)
        print(f"  스크리닝 이력: {len(dates)}일")
        if dates:
            print(f"    최근: {dates[0]} ~ 최초: {dates[-1]}")

        # 활성 워치리스트
        active = load_active_watchlists()
        total_stocks = sum(len(wl.get("stocks", [])) for wl in active)
        print(f"  활성 워치리스트: {len(active)}개 ({total_stocks}종목)")
        for wl in active[:3]:
            created = wl.get("created", "?")
            stocks = [s.get("name", "?") for s in wl.get("stocks", [])]
            print(f"    [{created}] {', '.join(stocks)}")

    except Exception as e:
        print(f"  ⚠️ DB 확인 실패: {e}")

    # ══════════════════════════════════════
    # 6. 액션 라벨 시뮬레이션
    # ══════════════════════════════════════
    section("6. 액션 라벨 시뮬레이션")
    try:
        from watchlist_monitor import make_action_label

        test_cases = [
            {"name": "D+1 이른 진입", "days_elapsed": 1, "conviction": "A",
             "conviction_score": 70, "in_window": True, "risk_flags": ["D+1이른진입"],
             "news_risk": "양호", "dart_risk": "정상", "sweet_spot_day": 2},
            {"name": "D+2 매수 적기", "days_elapsed": 2, "conviction": "A",
             "conviction_score": 72, "in_window": True, "risk_flags": [],
             "news_risk": "양호", "dart_risk": "정상", "sweet_spot_day": 2},
            {"name": "악재 뉴스 있음", "days_elapsed": 3, "conviction": "B",
             "conviction_score": 55, "in_window": True, "risk_flags": ["뉴스위험"],
             "news_risk": "위험", "dart_risk": "정상", "sweet_spot_day": 3},
            {"name": "대주주 투매", "days_elapsed": 2, "conviction": "B",
             "conviction_score": 50, "in_window": True, "risk_flags": ["대주주투매"],
             "news_risk": "양호", "dart_risk": "정상", "sweet_spot_day": 2},
            {"name": "C등급 관망", "days_elapsed": 4, "conviction": "C",
             "conviction_score": 35, "in_window": True, "risk_flags": [],
             "news_risk": "양호", "dart_risk": "정상", "sweet_spot_day": 3},
        ]
        for tc in test_cases:
            action = make_action_label(tc)
            print(f"  {tc['name']:15s} → {action['label']} ({action['detail']})")

    except Exception as e:
        print(f"  ❌ 액션 라벨 테스트 실패: {e}")

    # ══════════════════════════════════════
    # 7. 웹훅 포맷 시뮬레이션 (dry-run)
    # ══════════════════════════════════════
    section("7. 웹훅 포맷 시뮬레이션")
    try:
        from notifier import Notifier, _signal_kr, _regime_kr

        # 용어 변환 테스트
        tests = [
            ("MA5터치+CCI냉각", _signal_kr),
            ("BB하단+가격조정", _signal_kr),
            ("chaotic", _regime_kr),
            ("weak", _regime_kr),
        ]
        for raw, fn in tests:
            print(f"  {raw:25s} → {fn(raw)}")

        # embed 생성 테스트 (발송 안 함)
        mock_pick = {
            "name": "테스트종목", "code": "999999",
            "conviction": "A", "conviction_score": 65,
            "days_elapsed": 2, "sweet_spot_day": 2,
            "signal_type": "MA5터치+CCI냉각", "in_window": True,
            "current_price": 15000, "price_change_from_screen": -1.2,
            "sector": "전자부품", "industry": "반도체",
            "main_products": "메모리칩, SSD",
            "holder_tag": "지분증가(+5%p)",
            "dart_risk": "정상", "dart_note": "",
            "news_risk": "양호", "news_summary": "특이사항 없음",
            "news_highlight": "삼성전자 납품 계약 체결",
            "risk_flags": [], "rank_note": "빠른 반등형",
            "market_regime": "chaotic",
            "event_warning": "FOMC(점도표)",
            "action": {"label": "🟢 매수 적기", "detail": "D+2 최적 타이밍", "color": "green"},
        }
        n = Notifier()
        embed = n._daily_pick_embed(1, mock_pick)
        desc = embed.get("description", "")
        print(f"\n  --- 시뮬레이션 웹훅 ---")
        print(f"  제목: {embed['title']}")
        for line in desc.split("\n"):
            print(f"  │ {line}")
        for field in embed.get("fields", []):
            print(f"  [{field['name']}]")
            for line in field["value"].split("\n"):
                print(f"  │ {line}")

    except Exception as e:
        print(f"  ❌ 웹훅 포맷 테스트 실패: {e}")

    print(f"\n{'=' * 50}")
    print(f"  점검 완료!")
    print(f"  다음 단계: python main.py --pick (실제 웹훅 테스트)")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
