"""
ClosingBell v3.5 — 설정 및 상수
==============================
모든 튜닝 가능 값은 .env에서 변경 가능.
.env에 없으면 아래 기본값 사용.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def _env(key: str, default, type_fn=str):
    """환경변수 읽기 헬퍼"""
    val = os.getenv(key, "")
    if not val:
        return default
    try:
        return type_fn(val)
    except (ValueError, TypeError):
        return default


def _env_bool(key: str, default: bool) -> bool:
    """불리언 환경변수 읽기 헬퍼"""
    val = os.getenv(key, "")
    if not val:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}

# ============================================================
# 경로
# ============================================================
PROJECT_DIR = Path(__file__).parent
DATA_DIR = Path(_env("DATA_DIR", "C:/Coding/data"))
OHLCV_DIR = DATA_DIR / "ohlcv"
GLOBAL_CSV = DATA_DIR / "global" / "global_merged.csv"
MAPPING_CSV = DATA_DIR / "stock_mapping.csv"
APP_DATA_DIR = PROJECT_DIR / "data"
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR = PROJECT_DIR / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
BACKTEST_DIR = PROJECT_DIR / "data" / "backtest"
BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVE_DIR = APP_DATA_DIR / "archive"
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
APP_DB_PATH = APP_DATA_DIR / "closingbell.db"
SAVE_LEGACY_JSON = _env_bool("SAVE_LEGACY_JSON", False)
LEGACY_JSON_RETENTION_DAYS = _env("LEGACY_JSON_RETENTION_DAYS", 5, int)

# ============================================================
# 키움 REST API
# ============================================================
KIWOOM_BASE_URL = _env("KIWOOM_BASE_URL", "https://api.kiwoom.com")
KIWOOM_APPKEY = _env("KIWOOM_APPKEY", "")
KIWOOM_SECRETKEY = _env("KIWOOM_SECRETKEY", "")

# ============================================================
# Gemini AI
# ============================================================
GEMINI_API_KEY = _env("GEMINI_API_KEY", "")
GEMINI_MODEL = _env("GEMINI_MODEL", "gemini-2.0-flash")

# ============================================================
# DART 공시
# ============================================================
DART_API_KEY = _env("DART_API_KEY", "")

# ============================================================
# 디스코드
# ============================================================
DISCORD_WEBHOOK_URL = _env("DISCORD_WEBHOOK_URL", "")
DASHBOARD_URL = _env("DASHBOARD_URL", "https://closingbell.streamlit.app")

# ============================================================
# 네이버 뉴스 API (https://developers.naver.com/apps/)
# ============================================================
NAVER_CLIENT_ID = _env("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = _env("NAVER_CLIENT_SECRET", "")

# ============================================================
# 점수 파라미터 (.env에서 튜닝 가능)
# ============================================================
CCI_PERIOD = _env("CCI_PERIOD", 14, int)
RSI_PERIOD = _env("RSI_PERIOD", 14, int)

# 종형분포 최적 구간
CCI_OPTIMAL = (
    _env("CCI_OPTIMAL_LOW", 160, float),
    _env("CCI_OPTIMAL_HIGH", 180, float),
)
CCI_ZERO_LOW = _env("CCI_ZERO_LOW", 80, float)
CCI_ZERO_HIGH = _env("CCI_ZERO_HIGH", 300, float)

MA20_GAP_OPTIMAL = (
    _env("MA20_GAP_OPTIMAL_LOW", 2.0, float),
    _env("MA20_GAP_OPTIMAL_HIGH", 8.0, float),
)
MA20_GAP_ZERO = _env("MA20_GAP_ZERO", 20.0, float)

CHANGE_OPTIMAL = (
    _env("CHANGE_OPTIMAL_LOW", 2.0, float),
    _env("CHANGE_OPTIMAL_HIGH", 8.0, float),
)
CHANGE_ZERO = _env("CHANGE_ZERO", 20.0, float)

RSI_OPTIMAL = (
    _env("RSI_OPTIMAL_LOW", 50, float),
    _env("RSI_OPTIMAL_HIGH", 70, float),
)
RSI_ZERO_LOW = _env("RSI_ZERO_LOW", 25, float)
RSI_ZERO_HIGH = _env("RSI_ZERO_HIGH", 85, float)

# 배점 (합계 100점)
SCORE_CCI = _env("SCORE_CCI", 22, float)           # 25→22 (거래량 폭발 추가분)
SCORE_MA20_GAP = _env("SCORE_MA20_GAP", 18, float)  # 20→18
SCORE_CHANGE = _env("SCORE_CHANGE", 15, float)
SCORE_CCI_SLOPE = _env("SCORE_CCI_SLOPE", 10, float)
SCORE_MA20_SLOPE = _env("SCORE_MA20_SLOPE", 10, float)
SCORE_RSI = _env("SCORE_RSI", 5, float)
SCORE_VOLUME_PROFILE = _env("SCORE_VOLUME_PROFILE", 10, float)
SCORE_BROKER_FLOW = _env("SCORE_BROKER_FLOW", 5, float)
SCORE_VOLUME_BURST = _env("SCORE_VOLUME_BURST", 5, float)  # 거래량 폭발 (22+18+15+10+10+5+10+5+5=100)

# 과열 복합 감점 (CCI>200 & RSI>80 & MA20이격>15% 동시 충족 시)
OVERHEAT_PENALTY = _env("OVERHEAT_PENALTY", 8.0, float)
OVERHEAT_CCI_THRESH = _env("OVERHEAT_CCI_THRESH", 200, float)
OVERHEAT_RSI_THRESH = _env("OVERHEAT_RSI_THRESH", 80, float)
OVERHEAT_GAP_THRESH = _env("OVERHEAT_GAP_THRESH", 15.0, float)

# 거래량 폭발 최적 구간 (당일거래량 / 20일평균)
VOL_BURST_OPTIMAL = (
    _env("VOL_BURST_OPTIMAL_LOW", 2.0, float),
    _env("VOL_BURST_OPTIMAL_HIGH", 5.0, float),
)
VOL_BURST_ZERO_HIGH = _env("VOL_BURST_ZERO_HIGH", 10.0, float)

# ============================================================
# 눌림목 모니터 (2단계 아키텍처)
# ============================================================
WATCHLIST_DIR = PROJECT_DIR / "data" / "watchlist"
WATCHLIST_DIR.mkdir(parents=True, exist_ok=True)
WATCHLIST_MAX_DAYS = _env("WATCHLIST_MAX_DAYS", 5, int)  # 워치리스트 유효기간

# 눌림목 진입 조건
PULLBACK_MA5_GAP = _env("PULLBACK_MA5_GAP", 1.5, float)     # MA5 이격도 ±% 이내
PULLBACK_VOL_DECLINE = _env("PULLBACK_VOL_DECLINE", 0.5, float)  # 거래량 감소율 (50% 이하)
PULLBACK_BB_LOWER = _env("PULLBACK_BB_LOWER", 0.3, float)     # 볼린저 하단 근접도 (0~1)
BUY_A_MIN_SCORE = _env("BUY_A_MIN_SCORE", 60, float)
BUY_B_MIN_SCORE = _env("BUY_B_MIN_SCORE", 40, float)
BUY_DART_DANGER_PENALTY = _env("BUY_DART_DANGER_PENALTY", 10, float)
BUY_DART_CAUTION_PENALTY = _env("BUY_DART_CAUTION_PENALTY", 5, float)
BUY_NEWS_DANGER_PENALTY = _env("BUY_NEWS_DANGER_PENALTY", 10, float)
BUY_NEWS_CAUTION_PENALTY = _env("BUY_NEWS_CAUTION_PENALTY", 3, float)

# ============================================================
# 성과 추적
# ============================================================
PERFORMANCE_DIR = PROJECT_DIR / "data" / "performance"
PERFORMANCE_DIR.mkdir(parents=True, exist_ok=True)
PERFORMANCE_TRACK_DAYS = _env("PERFORMANCE_TRACK_DAYS", 5, int)

# ============================================================
# 필터 (.env에서 튜닝 가능)
# ============================================================
TOP_N = _env("TOP_N", 3, int)
TOP_N_CONSERVATIVE = _env("TOP_N_CONSERVATIVE", 2, int)
MIN_PRICE = _env("MIN_PRICE", 3000, int)
MAX_PRICE = _env("MAX_PRICE", 150000, int)
NASDAQ_DROP_THRESHOLD = _env("NASDAQ_DROP_THRESHOLD", -2.0, float)
NASDAQ_PENALTY = _env("NASDAQ_PENALTY", 5.0, float)
MIN_CHANGE_RATE = _env("MIN_CHANGE_RATE", 1.0, float)
MAX_CHANGE_RATE = _env("MAX_CHANGE_RATE", 29.0, float)
MIN_TRADING_VALUE = _env("MIN_TRADING_VALUE", "1000")  # 키움 API용 (백만원 단위)

# 제외 키워드
EXCLUDE_NAMES = [
    "스팩", "SPAC", "ETN", "인버스", "레버리지", "리츠", "REIT", "인프라",
]
ETF_KEYWORDS = [
    "KODEX", "TIGER", "KBSTAR", "HANARO", "SOL ", "ARIRANG",
    "KOSEF", "ACE ", "PLUS ", "BNK", "RISE", "TIMEFOLIO",
    "파워", "레버리지", "인버스",
]
EXCLUDE_PREF_STOCK = True
EXCLUDE_ETF = True

# ============================================================
# 스케줄 (.env에서 시간 변경 가능)
# ============================================================
SCHEDULE = {
    "daily_pick": _env("SCHEDULE_DAILY_PICK", "15:00"),    # 감시 종목 스캔 → TOP3 웹훅
    "screen": _env("SCHEDULE_SCREEN", "15:40"),             # 스크리닝 → 워치리스트 저장 (웹훅 없음)
    # 스크리닝 후 순차 실행: OHLCV → 글로벌 → 성과추적 → (월)매핑+메타 → (월초)재무 → git push → 종료
}

# API 속도 제한
API_DELAY = _env("API_DELAY", 0.12, float)
