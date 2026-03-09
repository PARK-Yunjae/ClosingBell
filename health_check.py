"""
ClosingBell v3.5 — 시스템 헬스체크
==================================
데이터 갱신 상태, API 연결, 스케줄러 구성 등 전체 점검.

사용법:
    python health_check.py              # 전체 점검
    python health_check.py --data       # 데이터만 점검
    python health_check.py --api        # API 연결만 점검
"""
import json
import sys
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

from config import (
    OHLCV_DIR, GLOBAL_CSV, LOG_DIR, MAPPING_CSV,
    KIWOOM_BASE_URL, KIWOOM_APPKEY, KIWOOM_SECRETKEY, API_DELAY,
    DISCORD_WEBHOOK_URL, GEMINI_API_KEY, DART_API_KEY,
    NAVER_CLIENT_ID, NAVER_CLIENT_SECRET,
    SCHEDULE, PROJECT_DIR,
    WATCHLIST_DIR, PERFORMANCE_DIR,
)

# ── 유틸 ──
OK = "✅"
WARN = "⚠️"
FAIL = "❌"
INFO = "ℹ️"


def _last_trading_day() -> str:
    """가장 최근 거래일 (주말 제외)"""
    now = datetime.now()
    if now.hour < 16:
        now -= timedelta(days=1)  # 장마감 전이면 전일 기준
    while now.weekday() >= 5:
        now -= timedelta(days=1)
    return now.strftime("%Y-%m-%d")


def _days_since(date_str: str) -> int:
    try:
        dt = datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
        return (datetime.now() - dt).days
    except Exception:
        return 999


# ──────────────────────────────────────────────
# 1. 데이터 점검
# ──────────────────────────────────────────────
def check_data() -> list[tuple[str, str, str]]:
    """데이터 상태 점검. 반환: [(상태, 항목, 설명)]"""
    results = []
    expected = _last_trading_day()

    # (1) OHLCV 디렉토리
    if not OHLCV_DIR.exists():
        results.append((FAIL, "OHLCV 디렉토리", f"{OHLCV_DIR} 없음"))
        return results

    csv_files = list(OHLCV_DIR.glob("*.csv"))
    results.append((OK if len(csv_files) > 100 else WARN,
                     "OHLCV 파일 수", f"{len(csv_files)}개"))

    # 삼성전자 기준 최신일
    samsung = OHLCV_DIR / "005930.csv"
    if samsung.exists():
        df = pd.read_csv(samsung)
        df.columns = [c.lower() for c in df.columns]
        df["date"] = pd.to_datetime(df["date"])
        last = df["date"].max().strftime("%Y-%m-%d")
        gap = _days_since(last)
        status = OK if gap <= 1 else (WARN if gap <= 3 else FAIL)
        results.append((status, "OHLCV 최신일 (005930)",
                         f"{last} ({gap}일 전)" + (f" ← 예상: {expected}" if gap > 1 else "")))
    else:
        results.append((FAIL, "OHLCV 삼성전자", "005930.csv 없음"))

    # 랜덤 샘플 5개
    import random
    samples = random.sample(csv_files, min(5, len(csv_files)))
    outdated = 0
    for f in samples:
        try:
            sdf = pd.read_csv(f)
            sdf.columns = [c.lower() for c in sdf.columns]
            sdf["date"] = pd.to_datetime(sdf["date"])
            if _days_since(sdf["date"].max().strftime("%Y-%m-%d")) > 3:
                outdated += 1
        except Exception:
            outdated += 1
    if outdated > 0:
        results.append((WARN, "OHLCV 샘플 점검", f"{outdated}/{len(samples)} 오래됨"))
    else:
        results.append((OK, "OHLCV 샘플 점검", f"{len(samples)}개 모두 최신"))

    # (2) 글로벌 지수
    if GLOBAL_CSV.exists():
        gdf = pd.read_csv(GLOBAL_CSV)
        gdf.columns = [c.strip().lower() for c in gdf.columns]
        gdf["date"] = pd.to_datetime(gdf["date"])
        g_last = gdf["date"].max().strftime("%Y-%m-%d")
        g_gap = _days_since(g_last)

        status = OK if g_gap <= 1 else (WARN if g_gap <= 3 else FAIL)
        results.append((status, "글로벌 지수 최신일", f"{g_last} ({g_gap}일 전)"))

        # 각 지수 빈값 체크
        for col in ["kospi_close", "nasdaq_close", "sp500_close", "usdkrw_close"]:
            if col in gdf.columns:
                valid = gdf.dropna(subset=[col])
                if len(valid) > 0:
                    v_last = valid["date"].max().strftime("%Y-%m-%d")
                    v_gap = _days_since(v_last)
                    empty = len(gdf) - len(valid)
                    if v_gap > 3 or empty > 5:
                        results.append((WARN, f"  {col}", f"~{v_last}, 빈값 {empty}일"))
                    else:
                        results.append((OK, f"  {col}", f"~{v_last}"))
    else:
        results.append((FAIL, "글로벌 지수", f"{GLOBAL_CSV} 없음"))

    # (3) 스크리닝 로그
    log_files = sorted(LOG_DIR.glob("*.json"))
    if log_files:
        last_log = log_files[-1].stem
        l_gap = _days_since(last_log)
        status = OK if l_gap <= 1 else (WARN if l_gap <= 3 else FAIL)
        results.append((status, "스크리닝 로그", f"최신: {last_log} ({len(log_files)}일분)"))
    else:
        results.append((WARN, "스크리닝 로그", "로그 없음"))

    # (4) stock_mapping
    if MAPPING_CSV.exists():
        mdf = pd.read_csv(MAPPING_CSV, dtype={"code": str})
        results.append((OK, "종목 매핑", f"{len(mdf)}종목"))
    else:
        results.append((WARN, "종목 매핑", f"{MAPPING_CSV} 없음"))

    # (5) 워치리스트
    wl_files = sorted(WATCHLIST_DIR.glob("*.json")) if WATCHLIST_DIR.exists() else []
    if wl_files:
        active = 0
        today = datetime.now().strftime("%Y-%m-%d")
        for wf in wl_files:
            try:
                wd = json.loads(wf.read_text(encoding="utf-8"))
                if wd.get("expires", "") >= today:
                    active += 1
            except Exception:
                pass
        results.append((OK, "워치리스트", f"총 {len(wl_files)}개, 활성 {active}개"))
    else:
        results.append((INFO, "워치리스트", "아직 없음 (다음 스크리닝 후 생성)"))

    # (6) 성과 추적
    perf_file = PERFORMANCE_DIR / "tracking.json"
    if perf_file.exists():
        pdata = json.loads(perf_file.read_text(encoding="utf-8"))
        n = len(pdata.get("records", []))
        results.append((OK, "성과 추적", f"{n}건 기록"))
    else:
        results.append((INFO, "성과 추적", "아직 없음 (--rebuild로 생성)"))

    return results


# ──────────────────────────────────────────────
# 2. API / 환경 점검
# ──────────────────────────────────────────────
def check_env() -> list[tuple[str, str, str]]:
    """API 키 및 환경 점검"""
    results = []

    # 키움 API
    if KIWOOM_APPKEY and KIWOOM_SECRETKEY:
        results.append((OK, "키움 API 키", "설정됨"))
    else:
        results.append((FAIL, "키움 API 키", "KIWOOM_APPKEY/SECRETKEY 미설정"))

    # Gemini
    if GEMINI_API_KEY:
        results.append((OK, "Gemini API 키", "설정됨"))
    else:
        results.append((WARN, "Gemini API 키", "미설정 (AI 분석 불가)"))

    # DART
    if DART_API_KEY:
        results.append((OK, "DART API 키", "설정됨"))
    else:
        results.append((WARN, "DART API 키", "미설정 (공시 체크 불가)"))

    # 네이버 뉴스
    if NAVER_CLIENT_ID and NAVER_CLIENT_SECRET:
        results.append((OK, "네이버 뉴스 API", "설정됨"))
    else:
        results.append((WARN, "네이버 뉴스 API", "미설정 (뉴스 체크 키워드만)"))

    # Discord
    if DISCORD_WEBHOOK_URL:
        results.append((OK, "디스코드 웹훅", "설정됨"))
    else:
        results.append((WARN, "디스코드 웹훅", "미설정 (알림 불가)"))

    # 스케줄
    results.append((INFO, "스케줄", str(SCHEDULE)))

    return results


def check_api_connection() -> list[tuple[str, str, str]]:
    """실제 API 연결 테스트 (토큰 발급만)"""
    results = []

    if not KIWOOM_APPKEY or not KIWOOM_SECRETKEY:
        results.append((FAIL, "키움 API", "키 미설정"))
        return results

    try:
        from kiwoom_api import KiwoomAPI
        api = KiwoomAPI(KIWOOM_APPKEY, KIWOOM_SECRETKEY, KIWOOM_BASE_URL, API_DELAY)
        api.ensure_token()
        results.append((OK, "키움 토큰 발급", "성공"))

        # 간단한 API 호출 테스트 (삼성전자 현재가)
        try:
            cur = api.get_current_price("005930")
            if cur["price"] > 0:
                results.append((OK, "현재가 조회", f"삼성전자 {cur['price']:,}원"))
            else:
                results.append((WARN, "현재가 조회", "가격 0 (장외시간?)"))
        except Exception as e:
            results.append((WARN, "현재가 조회", str(e)[:50]))

    except Exception as e:
        results.append((FAIL, "키움 토큰 발급", str(e)[:80]))

    return results


# ──────────────────────────────────────────────
# 3. Preflight — 스케줄러 구성요소 전체 검증
# ──────────────────────────────────────────────
def preflight() -> list[tuple[str, str, str]]:
    """스케줄러 실행 전 전체 파이프라인 검증"""
    results = []

    # 필수 모듈 import 테스트
    modules = [
        ("config", "설정"),
        ("kiwoom_api", "키움 API"),
        ("screener", "스크리너"),
        ("enricher", "인리처"),
        ("notifier", "노티파이어"),
        ("watchlist_monitor", "워치리스트"),
        ("performance_tracker", "성과추적"),
        ("data_updater", "데이터갱신"),
        ("fdr_update", "FDR갱신"),
        ("dart_checker", "DART"),
        ("ai_analyzer", "AI분석"),
        ("news_checker", "뉴스체크"),
        ("weekly_update", "주간갱신"),
    ]
    for mod_name, label in modules:
        try:
            __import__(mod_name)
            results.append((OK, f"모듈: {label}", f"{mod_name}.py"))
        except Exception as e:
            results.append((FAIL, f"모듈: {label}", f"{mod_name} → {str(e)[:60]}"))

    # schedule 라이브러리
    try:
        import schedule
        results.append((OK, "schedule 패키지", "설치됨"))
    except ImportError:
        results.append((FAIL, "schedule 패키지", "pip install schedule 필요"))

    # 디렉토리 쓰기 권한
    for name, path in [("LOG_DIR", LOG_DIR), ("WATCHLIST_DIR", WATCHLIST_DIR),
                       ("PERFORMANCE_DIR", PERFORMANCE_DIR)]:
        try:
            test_file = path / ".write_test"
            test_file.write_text("test")
            test_file.unlink()
            results.append((OK, f"쓰기 권한: {name}", str(path)))
        except Exception as e:
            results.append((FAIL, f"쓰기 권한: {name}", str(e)[:60]))

    # .env 파일
    env_file = PROJECT_DIR / ".env"
    if env_file.exists():
        results.append((OK, ".env 파일", "존재"))
    else:
        results.append((WARN, ".env 파일", "없음 (.env.example 참고)"))

    # git 상태
    try:
        import subprocess
        r = subprocess.run(["git", "status", "--porcelain"],
                           capture_output=True, text=True, cwd=PROJECT_DIR)
        changed = len(r.stdout.strip().split("\n")) if r.stdout.strip() else 0
        results.append((OK if changed == 0 else INFO,
                         "Git 상태", f"변경 {changed}개" if changed else "클린"))
    except Exception:
        results.append((INFO, "Git", "git 미설치 또는 레포 아님"))

    return results


# ──────────────────────────────────────────────
# 출력
# ──────────────────────────────────────────────
def print_results(title: str, results: list[tuple[str, str, str]]):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")
    for status, item, desc in results:
        print(f"  {status} {item:30s} {desc}")

    fails = sum(1 for s, _, _ in results if s == FAIL)
    warns = sum(1 for s, _, _ in results if s == WARN)
    if fails:
        print(f"\n  🔴 실패 {fails}건 — 수정 필요")
    elif warns:
        print(f"\n  🟡 경고 {warns}건 — 동작하지만 확인 권장")
    else:
        print(f"\n  🟢 모두 정상")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="ClosingBell — 시스템 헬스체크")
    parser.add_argument("--data", action="store_true", help="데이터만 점검")
    parser.add_argument("--api", action="store_true", help="API 연결 테스트")
    parser.add_argument("--preflight", action="store_true", help="스케줄러 실행 전 전체 검증")
    args = parser.parse_args()

    print(f"\n🔔 ClosingBell 헬스체크 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   예상 최근 거래일: {_last_trading_day()}")

    if args.data:
        print_results("데이터 상태", check_data())
    elif args.api:
        print_results("환경 설정", check_env())
        print_results("API 연결", check_api_connection())
    elif args.preflight:
        print_results("환경 설정", check_env())
        print_results("모듈 & 구성", preflight())
        print_results("데이터 상태", check_data())
        print_results("API 연결", check_api_connection())
        print(f"\n{'=' * 60}")
        print(f"  스케줄 타임라인")
        print(f"{'=' * 60}")
        pick_t = SCHEDULE.get("daily_pick", "15:00")
        screen_t = SCHEDULE.get("screen", "15:05")
        print(f"  ⏰ {pick_t}  🎯 감시 종목 스캔 → TOP3 웹훅")
        print(f"  ⏰ {screen_t}  🔇 스크리닝 → 워치리스트 저장")
        print(f"         ↓ 순차 실행 ↓")
        print(f"         ① OHLCV 전체 2,782종목 (~3분)")
        print(f"         ② 글로벌 지수")
        print(f"         ③ 성과 추적 D+1~D+5")
        print(f"         ④ [월요일] stock_mapping + meta")
        print(f"         ⑤ [매월 초 월] 재무제표")
        print(f"         ⑥ Git push → 종료")
        print()
    else:
        # 전체
        print_results("환경 설정", check_env())
        print_results("데이터 상태", check_data())
    print()


if __name__ == "__main__":
    main()