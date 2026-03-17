"""
ClosingBell v4.0 — 메인 스케줄러
=================================
[매일]
  15:00  감시 종목 스캔 → TOP3 디스코드 웹훅
  15:40  스크리닝 → 워치리스트 저장
         ↓ 완료 후 자동 순차 실행 ↓
         ① OHLCV 전체 갱신
         ② 글로벌 지수 갱신
         ③ 성과 추적
         ④ [월요일만] stock_mapping + meta
         ⑤ [매월 초 월요일] 재무제표 갱신
         ⑥ 종료
"""
import argparse
import logging
import signal
import sys
import time
from datetime import datetime

from config import (
    KIWOOM_BASE_URL, KIWOOM_APPKEY, KIWOOM_SECRETKEY,
    LOG_DIR, SCHEDULE, API_DELAY,
    GLOBAL_UPDATE_RETRY_COUNT, GLOBAL_UPDATE_RETRY_SLEEP_SEC,
    MONTHLY_FINSTATE_DAY_CUTOFF, SCHEDULER_LOOP_SLEEP_SEC, SCHEDULER_MAX_FAILS,
)
from storage import (
    init_storage,
    save_buy_picks,
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


def run_daily_pick():
    """매일 15시: 워치리스트 전체 스코어링 → 당일 매수 후보 웹훅"""
    logger.info("일일 매수 후보 선정 시작...")
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
    logger.info("ClosingBell v4.0 스크리닝 시작")
    logger.info("=" * 50)

    # Log daily market context when optional data is available.
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

    # ① 전체 OHLCV
    logger.info("[①] 전체 OHLCV 갱신 시작...")
    try:
        from fdr_update import update_ohlcv_all
        update_ohlcv_all()
    except Exception as e:
        logger.warning("OHLCV 갱신 실패: %s", e)

    # ② 글로벌 지수
    logger.info("[②] 글로벌 지수 갱신...")
    for attempt in range(1, GLOBAL_UPDATE_RETRY_COUNT + 1):
        try:
            from fdr_update import update_global
            update_global()
            break
        except Exception as e:
            logger.warning("글로벌 갱신 실패 (시도 %d/%d): %s", attempt, GLOBAL_UPDATE_RETRY_COUNT, e)
            if attempt < GLOBAL_UPDATE_RETRY_COUNT:
                time.sleep(GLOBAL_UPDATE_RETRY_SLEEP_SEC)

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
        if datetime.now().day <= MONTHLY_FINSTATE_DAY_CUTOFF:
            logger.info("[⑤] 매월 초 → 재무제표 갱신")
            try:
                from weekly_update import update_finstate
                update_finstate()
            except Exception as e:
                logger.warning("재무제표 갱신 실패: %s", e)

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
# 스케줄러 — 고정 시간 2개만
# ══════════════════════════════════════════════
def run_scheduler():
    """스케줄 기반 실행"""
    import schedule as sched

    logger.info("스케줄러 시작")
    logger.info("  %s → 🎯 매수 후보 웹훅", SCHEDULE["daily_pick"])
    logger.info("  %s → 🔇 스크리닝 → OHLCV → 글로벌 → 성과추적", SCHEDULE["screen"])
    logger.info("         → [월] 매핑+메타 → [월초] 재무 → 종료")

    sched.every().day.at(SCHEDULE["daily_pick"]).do(run_daily_pick)
    sched.every().day.at(SCHEDULE["screen"]).do(run_screening_then_pipeline)

    # Ctrl+C → 안전 종료
    def signal_handler(sig, frame):
        logger.info("Ctrl+C → 안전 종료")
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)

    logger.info("대기 중... (매수후보: %s, 파이프라인: %s)",
                SCHEDULE["daily_pick"], SCHEDULE["screen"])
    fail_count = 0
    while True:
        try:
            sched.run_pending()
            fail_count = 0
        except Exception as e:
            fail_count += 1
            logger.error("스케줄러 에러 (%d회연속): %s", fail_count, e)
            if fail_count >= SCHEDULER_MAX_FAILS:
                logger.critical("스케줄러 %d회 연속 실패 — 종료", SCHEDULER_MAX_FAILS)
                try:
                    from notifier import Notifier
                    Notifier().send_error(f"스케줄러 {SCHEDULER_MAX_FAILS}회 연속 실패: {e}")
                except Exception:
                    pass
                sys.exit(1)
        time.sleep(SCHEDULER_LOOP_SLEEP_SEC)


# ══════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════
def main():
    init_storage()
    parser = argparse.ArgumentParser(description="ClosingBell v4.0")
    parser.add_argument("--once", action="store_true", help="즉시 1회 스크리닝 (조용히)")
    parser.add_argument("--pick", action="store_true", help="즉시 매수 후보 선정 + 웹훅")
    parser.add_argument("--weekly", action="store_true", help="수동 주간 갱신")
    args = parser.parse_args()

    if args.once:
        run_screening(once=True)
    elif args.pick:
        run_daily_pick()
    elif args.weekly:
        from weekly_update import update_stock_mapping, update_meta, check_status
        update_stock_mapping()
        update_meta()
        check_status()
    else:
        run_scheduler()


if __name__ == "__main__":
    main()
