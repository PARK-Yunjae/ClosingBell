"""
ClosingBell v2 — 종가매매 스크리닝 시스템

사용법:
    python main.py                  # 자동 스케줄러 (14:50~15:43)
    python main.py --screen         # 즉시 스크리닝
    python main.py --update         # 즉시 데이터 갱신
    python main.py --backtest 30    # 최근 30일 백테스트
    python main.py --list-conditions # TV200 조건 목록
    python main.py --dashboard      # Streamlit 대시보드 실행
"""
import argparse
import logging
import signal
import subprocess
import sys
import time
from datetime import datetime

import schedule

from config import SCHEDULE, LOG_DIR
from kis_api import KisAPI
from screener import Screener
from data_updater import DataUpdater
from notifier import Notifier

# ──────────────────────────────────────────────
# 로깅 설정
# ──────────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            LOG_DIR.parent / "closingbell.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("closingbell")

# ──────────────────────────────────────────────
# 글로벌 인스턴스
# ──────────────────────────────────────────────
api = KisAPI()
screener = Screener(api)
updater = DataUpdater(api)
notifier = Notifier()

# 마지막 스크리닝 결과 (데이터 갱신에서 유니버스 코드 참조용)
last_result: dict = {}


# ──────────────────────────────────────────────
# 작업 함수
# ──────────────────────────────────────────────
def job_screen():
    """15:00 — 스크리닝 + 웹훅 + 로그 저장"""
    global last_result
    logger.info("=" * 50)
    logger.info("스크리닝 시작")

    try:
        api.get_token()
        result = screener.run()
        last_result = result

        # 로그 저장
        updater.save_log(result)

        # 디스코드 웹훅
        notifier.send_recommendation(result)

        # 결과 출력
        if result.get("skipped"):
            logger.info("스크리닝 스킵: %s", result.get("reason"))
        else:
            logger.info("유니버스: %d종목", result.get("universe_count", 0))
            for s in result.get("top5", []):
                logger.info(
                    "  %d위: %s (%s) %.1f점 | CCI %.0f | 이격도 %.1f%%",
                    s["rank"], s["name"], s["code"], s["score"],
                    s["cci"], s["ma20_gap"],
                )
    except Exception as e:
        logger.error("스크리닝 실패: %s", e, exc_info=True)
        notifier.send_error(str(e))


def job_update_data():
    """15:35 — 데이터 갱신"""
    logger.info("데이터 갱신 시작")

    try:
        api.get_token()

        # 유니버스 종목 코드
        codes = set()
        for s in last_result.get("all_scored", []):
            codes.add(s["code"])
        codes = list(codes) if codes else []

        if codes:
            updater.update_ohlcv(codes)
        else:
            logger.info("갱신할 종목 없음 (유니버스 비어있음)")

        updater.update_global()

    except Exception as e:
        logger.error("데이터 갱신 실패: %s", e, exc_info=True)


def job_git_push():
    """Git commit + push (Streamlit Cloud 대시보드 갱신)"""
    logger.info("Git push 시작")

    try:
        subprocess.run(["git", "add", "data/logs/"], check=True, capture_output=True)
        subprocess.run(["git", "add", "data/closingbell.log"], capture_output=True)

        today = datetime.now().strftime("%Y-%m-%d")
        subprocess.run(
            ["git", "commit", "-m", f"auto: {today} screening log"],
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "push"], check=True, capture_output=True)
        logger.info("Git push 완료 → Streamlit Cloud 갱신 예정 (~5분)")
        return True
    except subprocess.CalledProcessError as e:
        logger.warning("Git push 실패 (변경사항 없음?): %s", e)
        return False
    except FileNotFoundError:
        logger.warning("Git이 설치되어 있지 않습니다")
        return False


def job_shutdown():
    """15:43 — 종료 전 커밋 + 자동 종료"""
    logger.info("=" * 50)

    # 종료 전 최종 커밋 (이전 git_push가 실패했거나 이후 변경사항 대비)
    logger.info("종료 전 최종 커밋 확인...")
    job_git_push()

    logger.info("ClosingBell v2 일일 작업 완료")
    notifier.send_shutdown()
    sys.exit(0)


# ──────────────────────────────────────────────
# 스케줄러
# ──────────────────────────────────────────────
def run_scheduler():
    """자동 스케줄러 (매일 실행)"""
    logger.info("=" * 50)
    logger.info("ClosingBell v2 스케줄러 시작")
    logger.info("스케줄: %s", SCHEDULE)

    # Ctrl+C 시 커밋 후 종료
    def _graceful_shutdown(signum, frame):
        logger.info("인터럽트 감지 (Ctrl+C) → 종료 전 커밋 시도...")
        job_git_push()
        logger.info("ClosingBell v2 수동 종료")
        notifier.send_shutdown("(수동 종료)")
        sys.exit(0)

    signal.signal(signal.SIGINT, _graceful_shutdown)
    signal.signal(signal.SIGTERM, _graceful_shutdown)

    # 토큰 미리 발급
    try:
        api.get_token()
    except Exception as e:
        logger.error("토큰 발급 실패: %s", e)

    schedule.every().day.at(SCHEDULE["screen"]).do(job_screen)
    schedule.every().day.at(SCHEDULE["update_data"]).do(job_update_data)
    schedule.every().day.at(SCHEDULE["git_push"]).do(job_git_push)
    schedule.every().day.at(SCHEDULE["shutdown"]).do(job_shutdown)

    logger.info("대기 중... (다음 작업: %s 스크리닝)", SCHEDULE["screen"])

    while True:
        schedule.run_pending()
        time.sleep(30)


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="ClosingBell v2 - 종가매매 스크리닝")
    parser.add_argument("--screen", action="store_true", help="즉시 스크리닝")
    parser.add_argument("--update", action="store_true", help="즉시 데이터 갱신")
    parser.add_argument("--backtest", type=int, metavar="N", help="최근 N일 백테스트")
    parser.add_argument("--list-conditions", action="store_true", help="TV200 조건 목록")
    parser.add_argument("--dashboard", action="store_true", help="Streamlit 대시보드")
    args = parser.parse_args()

    if args.screen:
        api.get_token()
        job_screen()

    elif args.update:
        api.get_token()
        job_update_data()

    elif args.backtest:
        result = screener.run_backtest(args.backtest)
        if "error" in result:
            print(f"에러: {result['error']}")
        else:
            print(f"\n{'='*40}")
            print(f"백테스트 결과 (최근 {args.backtest}일)")
            print(f"{'='*40}")
            print(f"  총 거래: {result['total']}건")
            print(f"  승률: {result['win_rate']}%")
            print(f"  평균 수익률: {result['avg_return']:+.2f}%")
            print(f"{'='*40}")

    elif args.list_conditions:
        api.get_token()
        conditions = api.get_condition_list()
        print("\n조건검색 목록:")
        for c in conditions:
            print(f"  [{c['seq']}] {c['name']}")

    elif args.dashboard:
        import os
        os.system("streamlit run dashboard/app.py")

    else:
        run_scheduler()


if __name__ == "__main__":
    main()
