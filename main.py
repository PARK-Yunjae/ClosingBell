"""
ClosingBell v3 — 메인 스케줄러
===============================
14:55 스크리닝 → 15:06 디스코드 → 15:35 데이터 갱신 → 15:40 git push → 15:43 종료

사용법:
    python main.py              # 스케줄러 모드 (작업 스케줄러에서 실행)
    python main.py --once       # 즉시 1회 실행 (테스트용)
    python main.py --backtest   # 간단 백테스트
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

# ── 로깅 설정 ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            Path(__file__).parent / "data" / "closingbell.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("closingbell")


def run_screening(once: bool = False):
    """스크리닝 실행"""
    from kiwoom_api import KiwoomAPI
    from screener import Screener
    from enricher import Enricher
    from notifier import Notifier

    logger.info("=" * 50)
    logger.info("ClosingBell v3 스크리닝 시작")
    logger.info("=" * 50)

    try:
        # API 초기화
        api = KiwoomAPI(
            appkey=KIWOOM_APPKEY,
            secretkey=KIWOOM_SECRETKEY,
            base_url=KIWOOM_BASE_URL,
            api_delay=API_DELAY,
        )
        api.ensure_token()

        # 스크리닝 + 전체 enrich
        screener = Screener(api)
        enricher = Enricher()
        notifier = Notifier()

        result = screener.run(enricher=enricher)

        # JSON 로그 저장
        log_file = LOG_DIR / f"{result['date']}.json"
        log_file.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info("로그 저장: %s", log_file)

        # 디스코드 알림
        notifier.send_recommendation(result)

        # 결과 요약
        top = result.get("top", [])
        if top:
            logger.info("── TOP%d 결과 ──", len(top))
            for s in top:
                logger.info(
                    "  #%d %s (%s) — %s점 | %s | %s",
                    s["rank"], s["name"], s["code"], s["score"],
                    s.get("ai_action", ""), s.get("vp_tag", ""),
                )
        elif result.get("skipped"):
            logger.info("스킵: %s", result.get("reason", ""))
        else:
            logger.info("추천 종목 없음 (유니버스 %d종목)", result.get("universe_count", 0))

        return result

    except Exception as e:
        logger.exception("스크리닝 에러: %s", e)
        try:
            Notifier().send_error(str(e))
        except Exception:
            pass
        return None


def run_data_update():
    """OHLCV + 글로벌 데이터 갱신"""
    logger.info("데이터 갱신 시작...")
    try:
        from data_updater import update_ohlcv, update_global_data
        update_ohlcv()
        update_global_data()
        logger.info("데이터 갱신 완료")
    except Exception as e:
        logger.warning("데이터 갱신 실패: %s", e)


def run_git_push():
    """Git 커밋 + 푸시"""
    logger.info("Git push 시작...")
    try:
        cwd = Path(__file__).parent
        subprocess.run(["git", "add", "."], cwd=cwd, capture_output=True)
        msg = f"auto: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        subprocess.run(["git", "commit", "-m", msg], cwd=cwd, capture_output=True)
        subprocess.run(["git", "push"], cwd=cwd, capture_output=True, timeout=30)
        logger.info("Git push 완료")
    except Exception as e:
        logger.warning("Git push 실패: %s", e)


def run_scheduler():
    """스케줄 기반 실행"""
    import schedule as sched

    logger.info("스케줄러 시작 — %s", SCHEDULE)

    sched.every().day.at(SCHEDULE["screen"]).do(run_screening)
    sched.every().day.at(SCHEDULE["update_data"]).do(run_data_update)
    sched.every().day.at(SCHEDULE["git_push"]).do(run_git_push)

    def shutdown():
        logger.info("종료 스케줄 실행")
        run_git_push()  # 안전 커밋
        from notifier import Notifier
        Notifier().send_shutdown()
        sys.exit(0)

    sched.every().day.at(SCHEDULE["shutdown"]).do(shutdown)

    # Ctrl+C → 안전 종료
    def signal_handler(sig, frame):
        logger.info("Ctrl+C → 안전 종료")
        run_git_push()
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)

    logger.info("다음 스크리닝: %s", SCHEDULE["screen"])
    while True:
        sched.run_pending()
        time.sleep(30)


def main():
    parser = argparse.ArgumentParser(description="ClosingBell v3")
    parser.add_argument("--once", action="store_true", help="즉시 1회 실행")
    parser.add_argument("--backtest", action="store_true", help="간단 백테스트")
    parser.add_argument("--days", type=int, default=30, help="백테스트 기간")
    args = parser.parse_args()

    if args.once:
        run_screening(once=True)
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
