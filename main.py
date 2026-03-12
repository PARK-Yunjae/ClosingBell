"""
ClosingBell v3.6 — 메인 스케줄러
=================================
[매일]
  15:00  🎯 감시 종목 스캔 → TOP3 디스코드 웹훅
  15:40  🔇 스크리닝 → 워치리스트 저장 (웹훅 없음, .env로 시간 변경 가능)
         ↓ 완료 후 자동 순차 실행 ↓
         ① OHLCV 전체 2,782종목 갱신 (~3분 스마트 스킵)
         ② 글로벌 지수 갱신
         ③ 성과 추적 D+1~D+5
         ④ [월요일만] stock_mapping + meta
         ⑤ [매월 초 월요일] 재무제표 갱신
         ⑥ Git push → Streamlit Cloud
         ⑦ 종료

사용법:
    python main.py              # 스케줄러 모드
    python main.py --once       # 즉시 1회 스크리닝 (조용히)
    python main.py --pick       # 즉시 TOP3 선정 + 웹훅 테스트
    python main.py --preflight  # 전체 파이프라인 검증
    python main.py --weekly     # 수동 주간 갱신
"""
import argparse
import json
import logging
import os
import signal
import sys
import subprocess
import time
from datetime import datetime
from pathlib import Path

from config import (
    KIWOOM_BASE_URL, KIWOOM_APPKEY, KIWOOM_SECRETKEY,
    LOG_DIR, SCHEDULE, API_DELAY,
)
from storage import (
    init_storage,
    prune_legacy_json,
    save_buy_picks,
    save_legacy_json,
    save_screen_result,
)

# ── 로깅 설정 ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            LOG_DIR.parent / "closingbell.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("closingbell")


# ══════════════════════════════════════════════
# 15:00 — 감시 종목 스캔 → TOP3 웹훅
# ══════════════════════════════════════════════
def run_daily_pick():
    """매일 15시: 워치리스트 전체 스코어링 → TOP3 웹훅"""
    logger.info("일일 매수 후보 TOP3 선정 시작...")
    try:
        from watchlist_monitor import daily_top3
        from notifier import Notifier
        pick_date = datetime.now().strftime("%Y-%m-%d")
        top3 = daily_top3()
        save_buy_picks(pick_date, top3)
        if top3:
            Notifier().send_daily_picks(top3, pick_date=pick_date)
        else:
            logger.info("활성 워치리스트 없음 — 내일부터 발송")
    except Exception as e:
        logger.warning("일일 선정 실패: %s", e)


# ══════════════════════════════════════════════
# 15:05 — 스크리닝 (조용히)
# ══════════════════════════════════════════════
def run_screening(once: bool = False):
    """스크리닝 실행 (워치리스트 저장만, 웹훅 없음)"""
    from kiwoom_api import KiwoomAPI
    from screener import Screener
    from enricher import Enricher

    logger.info("=" * 50)
    logger.info("ClosingBell v3.6 스크리닝 시작 (조용히)")
    logger.info("=" * 50)

    # v3.6: 시장 컨텍스트 로그
    try:
        from market_context import get_market_context
        ctx = get_market_context()
        today_ctx = ctx.today_context()
        if today_ctx["event_warning"]:
            logger.info("📅 오늘 이벤트: %s", today_ctx["event_warning"])
        if today_ctx["conservative"]:
            logger.warning("⚠️ 보수 모드 활성화 — %s", today_ctx["event_warning"])
    except Exception:
        pass

    try:
        api = KiwoomAPI(KIWOOM_APPKEY, KIWOOM_SECRETKEY, KIWOOM_BASE_URL, API_DELAY)
        api.ensure_token()

        screener = Screener(api)
        enricher = Enricher()
        result = screener.run(enricher=enricher)

        save_screen_result(result)
        save_legacy_json(LOG_DIR / f"{result['date']}.json", result)
        prune_legacy_json(LOG_DIR)
        logger.info("스크리닝 결과 저장: %s", result["date"])

        try:
            from watchlist_monitor import save_watchlist
            save_watchlist(result)
        except Exception as e:
            logger.debug("워치리스트 저장 실패: %s", e)

        top = result.get("top", [])
        if top:
            logger.info("── TOP%d 결과 ──", len(top))
            for s in top:
                logger.info("  #%d %s (%s) — %s점 | %s | %s",
                            s["rank"], s["name"], s["code"], s["score"],
                            s.get("ai_action", ""), s.get("vp_tag", ""))
        elif result.get("skipped"):
            logger.info("스킵: %s", result.get("reason", ""))

        return result

    except Exception as e:
        logger.exception("스크리닝 에러: %s", e)
        try:
            from notifier import Notifier
            Notifier().send_error(str(e))
        except Exception:
            pass
        return None


# ══════════════════════════════════════════════
# 장마감 순차 파이프라인 (스크리닝 완료 후 자동)
# ══════════════════════════════════════════════
def run_post_pipeline():
    """스크리닝 완료 후 순차 실행하는 장마감 파이프라인"""

    # ① 전체 OHLCV 2,782종목
    logger.info("[①] 전체 OHLCV 갱신 시작...")
    try:
        from fdr_update import update_ohlcv_all
        update_ohlcv_all()
    except Exception as e:
        logger.warning("OHLCV 갱신 실패: %s — fallback 실행", e)
        try:
            from data_updater import update_ohlcv
            update_ohlcv()
        except Exception:
            pass

    # ② 글로벌 지수
    logger.info("[②] 글로벌 지수 갱신...")
    for attempt in range(1, 4):
        try:
            from fdr_update import update_global
            update_global()
            break
        except Exception as e:
            logger.warning("글로벌 갱신 실패 (시도 %d/3): %s", attempt, e)
            if attempt < 3:
                time.sleep(3)

    # ③ 성과 추적 D+1~D+5
    logger.info("[③] 성과 추적...")
    try:
        from performance_tracker import track_from_ohlcv
        track_from_ohlcv()
    except Exception as e:
        logger.warning("성과 추적 실패: %s", e)

    # ④ [월요일] stock_mapping + meta
    if datetime.now().weekday() == 0:
        logger.info("[④] 월요일 → stock_mapping + meta 갱신")
        try:
            from weekly_update import update_stock_mapping, update_meta
            update_stock_mapping()
            update_meta()
        except Exception as e:
            logger.warning("주간 갱신 실패: %s", e)

        # ⑤ [매월 초 월요일] 재무제표
        if datetime.now().day <= 10:
            logger.info("[⑤] 매월 초 → 재무제표 갱신")
            try:
                from weekly_update import update_finstate
                update_finstate()
            except Exception as e:
                logger.warning("재무제표 갱신 실패: %s", e)

    # ⑥ Git push
    run_git_push()

    # ⑦ 종료
    logger.info("파이프라인 완료 — 종료")
    try:
        from notifier import Notifier
        Notifier().send_shutdown()
    except Exception:
        pass
    sys.exit(0)


def run_screening_then_pipeline():
    """스크리닝 시간에 호출: 스크리닝 → 장마감 파이프라인 순차 실행"""
    run_screening()
    run_post_pipeline()


# ══════════════════════════════════════════════
# Git push
# ══════════════════════════════════════════════
def run_git_push():
    """Git 커밋 + 푸시 (결과 검증)"""
    logger.info("Git push 시작...")
    try:
        cwd = Path(__file__).parent
        subprocess.run(["git", "add", "."], cwd=cwd, capture_output=True)
        msg = f"auto: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        commit = subprocess.run(["git", "commit", "-m", msg], cwd=cwd,
                                capture_output=True, text=True)
        if commit.returncode != 0 and "nothing to commit" not in commit.stdout:
            logger.warning("Git commit 실패: %s", commit.stderr.strip())
            return

        push = subprocess.run(["git", "push"], cwd=cwd,
                              capture_output=True, text=True, timeout=30)
        if push.returncode == 0:
            logger.info("Git push 완료")
        else:
            logger.warning("Git push 실패 (code %d): %s",
                           push.returncode, push.stderr.strip()[:100])
    except subprocess.TimeoutExpired:
        logger.warning("Git push 타임아웃 (30초)")
    except Exception as e:
        logger.warning("Git push 에러: %s", e)


# ══════════════════════════════════════════════
# 스케줄러 — 고정 시간 2개만
# ══════════════════════════════════════════════
def run_scheduler():
    """스케줄 기반 실행"""
    import schedule as sched

    logger.info("스케줄러 시작")
    logger.info("  %s → 🎯 TOP3 웹훅", SCHEDULE["daily_pick"])
    logger.info("  %s → 🔇 스크리닝 → OHLCV → 글로벌 → 성과추적", SCHEDULE["screen"])
    logger.info("         → [월] 매핑+메타 → [월초] 재무 → Git → 종료")

    sched.every().day.at(SCHEDULE["daily_pick"]).do(run_daily_pick)
    sched.every().day.at(SCHEDULE["screen"]).do(run_screening_then_pipeline)

    # Ctrl+C → 안전 종료
    def signal_handler(sig, frame):
        logger.info("Ctrl+C → 안전 종료")
        run_git_push()
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)

    logger.info("대기 중... (TOP3: %s, 파이프라인: %s)",
                SCHEDULE["daily_pick"], SCHEDULE["screen"])
    fail_count = 0
    while True:
        try:
            sched.run_pending()
            fail_count = 0
        except Exception as e:
            fail_count += 1
            logger.error("스케줄러 에러 (%d회연속): %s", fail_count, e)
            if fail_count >= 5:
                logger.critical("스케줄러 5회 연속 실패 — 종료")
                try:
                    from notifier import Notifier
                    Notifier().send_error(f"스케줄러 5회 연속 실패: {e}")
                except Exception:
                    pass
                sys.exit(1)
        time.sleep(30)


# ══════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════
def main():
    init_storage()
    parser = argparse.ArgumentParser(description="ClosingBell v3.6")
    parser.add_argument("--once", action="store_true", help="즉시 1회 스크리닝 (조용히)")
    parser.add_argument("--preflight", action="store_true", help="전체 파이프라인 검증")
    parser.add_argument("--pick", action="store_true", help="즉시 TOP3 선정 + 웹훅")
    parser.add_argument("--weekly", action="store_true", help="수동 주간 갱신")
    parser.add_argument("--backtest", action="store_true", help="간단 백테스트")
    parser.add_argument("--days", type=int, default=30, help="백테스트 기간")
    args = parser.parse_args()

    if args.preflight:
        from health_check import check_env, check_data, check_api_connection, preflight
        from health_check import print_results
        print(f"\n🔔 ClosingBell Preflight — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print_results("환경 설정", check_env())
        print_results("모듈 & 구성", preflight())
        print_results("데이터 상태", check_data())
        print_results("API 연결", check_api_connection())
        all_results = check_env() + preflight() + check_data() + check_api_connection()
        fails = sum(1 for s, _, _ in all_results if s == "❌")
        if fails:
            print(f"\n🔴 {fails}건 실패 — 스케줄러 실행 전 수정 필요\n")
            sys.exit(1)
        else:
            print(f"\n🟢 Preflight 통과 — 스케줄러 실행 가능\n")
    elif args.once:
        run_screening(once=True)
    elif args.pick:
        run_daily_pick()
    elif args.weekly:
        from weekly_update import update_stock_mapping, update_meta, check_status
        update_stock_mapping()
        update_meta()
        check_status()
    elif args.backtest:
        from kiwoom_api import KiwoomAPI
        from screener import Screener
        api = KiwoomAPI(KIWOOM_APPKEY, KIWOOM_SECRETKEY, KIWOOM_BASE_URL, API_DELAY)
        api.ensure_token()
        screener = Screener(api)
        result = screener.run_backtest(args.days) if hasattr(screener, 'run_backtest') else {}
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        run_scheduler()


if __name__ == "__main__":
    main()
