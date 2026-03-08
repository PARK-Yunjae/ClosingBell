"""
ClosingBell v3 — 설정 및 상수
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

# ============================================================
# 경로
# ============================================================
PROJECT_DIR = Path(__file__).parent
DATA_DIR = Path(_env("DATA_DIR", "C:/Coding/data"))
OHLCV_DIR = DATA_DIR / "ohlcv"
GLOBAL_CSV = DATA_DIR / "global" / "global_merged.csv"
MAPPING_CSV = DATA_DIR / "stock_mapping.csv"
LOG_DIR = PROJECT_DIR / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

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
SCORE_CCI = _env("SCORE_CCI", 25, float)
SCORE_MA20_GAP = _env("SCORE_MA20_GAP", 20, float)
SCORE_CHANGE = _env("SCORE_CHANGE", 15, float)
SCORE_CCI_SLOPE = _env("SCORE_CCI_SLOPE", 10, float)
SCORE_MA20_SLOPE = _env("SCORE_MA20_SLOPE", 10, float)
SCORE_RSI = _env("SCORE_RSI", 5, float)
SCORE_VOLUME_PROFILE = _env("SCORE_VOLUME_PROFILE", 10, float)
SCORE_BROKER_FLOW = _env("SCORE_BROKER_FLOW", 5, float)

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
    "screen": _env("SCHEDULE_SCREEN", "14:55"),
    "update_data": _env("SCHEDULE_UPDATE_DATA", "15:35"),
    "git_push": _env("SCHEDULE_GIT_PUSH", "15:40"),
    "shutdown": _env("SCHEDULE_SHUTDOWN", "15:43"),
}

# API 속도 제한
API_DELAY = _env("API_DELAY", 0.12, float)
