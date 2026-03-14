"""
ClosingBell runtime configuration.

Keep operational tuning in `.env` so the live scheduler can be adjusted
without changing code.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env(key: str, default, type_fn=str):
    value = os.getenv(key, "")
    if value == "":
        return default
    try:
        return type_fn(value)
    except (TypeError, ValueError):
        return default


def _env_bool(key: str, default: bool) -> bool:
    value = os.getenv(key, "")
    if value == "":
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int_list(key: str, default: list[int]) -> list[int]:
    value = os.getenv(key, "")
    if value == "":
        return default
    result: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.append(int(part))
        except ValueError:
            return default
    return result or default


def _env_str_list(key: str, default: list[str]) -> list[str]:
    value = os.getenv(key, "")
    if value == "":
        return default
    result = [part.strip() for part in value.split(",") if part.strip()]
    return result or default


def _env_path(key: str, default) -> Path:
    raw = os.getenv(key, "")
    return Path(raw or str(default)).expanduser()


PROJECT_DIR = Path(__file__).resolve().parent

DATA_DIR = _env_path("DATA_DIR", "C:/Coding/data")
META_DIR = _env_path("META_DIR", DATA_DIR / "meta")
OHLCV_DIR = _env_path("OHLCV_DIR", DATA_DIR / "ohlcv")
GLOBAL_CSV = _env_path("GLOBAL_CSV", DATA_DIR / "global" / "global_merged.csv")
MAPPING_CSV = _env_path("MAPPING_CSV", DATA_DIR / "stock_mapping.csv")
MAJOR_HOLDER_CSV = _env_path("MAJOR_HOLDER_CSV", META_DIR / "major_holder.csv")
COMPANY_PROFILE_CSV = _env_path("COMPANY_PROFILE_CSV", META_DIR / "company_profile.csv")

APP_DATA_DIR = _env_path("APP_DATA_DIR", PROJECT_DIR / "data")
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

REFERENCE_DIR = _env_path("REFERENCE_DIR", APP_DATA_DIR / "reference")
REFERENCE_DIR.mkdir(parents=True, exist_ok=True)

LOG_DIR = _env_path("LOG_DIR", APP_DATA_DIR / "logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

PERFORMANCE_DIR = _env_path("PERFORMANCE_DIR", APP_DATA_DIR / "performance")
PERFORMANCE_DIR.mkdir(parents=True, exist_ok=True)

APP_DB_PATH = _env_path("APP_DB_PATH", APP_DATA_DIR / "closingbell.db")
KRX_HOLIDAYS_PATH = _env_path(
    "KRX_HOLIDAYS_PATH",
    REFERENCE_DIR / "krx_holidays.json",
)
MARKET_CALENDAR_PATH = _env_path(
    "MARKET_CALENDAR_PATH",
    REFERENCE_DIR / "market_calendar.json",
)
TRADING_CALENDAR_REFERENCE_CODE = _env(
    "TRADING_CALENDAR_REFERENCE_CODE",
    "005930",
)

KIWOOM_BASE_URL = _env("KIWOOM_BASE_URL", "https://api.kiwoom.com")
KIWOOM_APPKEY = _env("KIWOOM_APPKEY", "")
KIWOOM_SECRETKEY = _env("KIWOOM_SECRETKEY", "")

DISCORD_WEBHOOK_URL = _env("DISCORD_WEBHOOK_URL", "")
GEMINI_API_KEY = _env("GEMINI_API_KEY", "")
GEMINI_MODEL = _env("GEMINI_MODEL", "gemini-2.0-flash")
DART_API_KEY = _env("DART_API_KEY", "")
NAVER_CLIENT_ID = _env("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = _env("NAVER_CLIENT_SECRET", "")

CCI_PERIOD = _env("CCI_PERIOD", 14, int)
RSI_PERIOD = _env("RSI_PERIOD", 14, int)

CCI_OPTIMAL = (
    _env("CCI_OPTIMAL_LOW", 160.0, float),
    _env("CCI_OPTIMAL_HIGH", 180.0, float),
)
CCI_ZERO_LOW = _env("CCI_ZERO_LOW", 80.0, float)
CCI_ZERO_HIGH = _env("CCI_ZERO_HIGH", 300.0, float)

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
    _env("RSI_OPTIMAL_LOW", 50.0, float),
    _env("RSI_OPTIMAL_HIGH", 70.0, float),
)
RSI_ZERO_LOW = _env("RSI_ZERO_LOW", 25.0, float)
RSI_ZERO_HIGH = _env("RSI_ZERO_HIGH", 85.0, float)

SCORE_CCI = _env("SCORE_CCI", 22.0, float)
SCORE_MA20_GAP = _env("SCORE_MA20_GAP", 18.0, float)
SCORE_CHANGE = _env("SCORE_CHANGE", 15.0, float)
SCORE_CCI_SLOPE = _env("SCORE_CCI_SLOPE", 10.0, float)
SCORE_MA20_SLOPE = _env("SCORE_MA20_SLOPE", 10.0, float)
SCORE_RSI = _env("SCORE_RSI", 5.0, float)
SCORE_VOLUME_PROFILE = _env("SCORE_VOLUME_PROFILE", 10.0, float)
SCORE_BROKER_FLOW = _env("SCORE_BROKER_FLOW", 5.0, float)
SCORE_VOLUME_BURST = _env("SCORE_VOLUME_BURST", 5.0, float)

OVERHEAT_PENALTY = _env("OVERHEAT_PENALTY", 8.0, float)
OVERHEAT_CCI_THRESH = _env("OVERHEAT_CCI_THRESH", 200.0, float)
OVERHEAT_RSI_THRESH = _env("OVERHEAT_RSI_THRESH", 80.0, float)
OVERHEAT_GAP_THRESH = _env("OVERHEAT_GAP_THRESH", 15.0, float)

VOL_BURST_OPTIMAL = (
    _env("VOL_BURST_OPTIMAL_LOW", 2.0, float),
    _env("VOL_BURST_OPTIMAL_HIGH", 5.0, float),
)
VOL_BURST_ZERO_HIGH = _env("VOL_BURST_ZERO_HIGH", 10.0, float)

WATCHLIST_MAX_DAYS = _env("WATCHLIST_MAX_DAYS", 5, int)
WATCHLIST_MAX_STOCKS = _env("WATCHLIST_MAX_STOCKS", 3, int)
DAILY_PICK_TOP_K = _env("DAILY_PICK_TOP_K", 3, int)
WATCHLIST_ALLOWED_RANKS = tuple(
    _env_int_list("WATCHLIST_ALLOWED_RANKS", [1, 2, 3])
)

RANK1_SWEET_SPOT = _env("RANK1_SWEET_SPOT", 1, int)
RANK1_WINDOW_START = _env("RANK1_WINDOW_START", 1, int)
RANK1_WINDOW_END = _env("RANK1_WINDOW_END", 2, int)
RANK2_SWEET_SPOT = _env("RANK2_SWEET_SPOT", 4, int)
RANK2_WINDOW_START = _env("RANK2_WINDOW_START", 3, int)
RANK2_WINDOW_END = _env("RANK2_WINDOW_END", 5, int)
RANK3_SWEET_SPOT = _env("RANK3_SWEET_SPOT", 3, int)
RANK3_WINDOW_START = _env("RANK3_WINDOW_START", 2, int)
RANK3_WINDOW_END = _env("RANK3_WINDOW_END", 4, int)

RANK1_PULLBACK_BONUS = _env("RANK1_PULLBACK_BONUS", 20.0, float)
RANK2_PULLBACK_BONUS = _env("RANK2_PULLBACK_BONUS", -5.0, float)
RANK3_PULLBACK_BONUS = _env("RANK3_PULLBACK_BONUS", 15.0, float)

BUY_REGIME_CHAOTIC_BONUS = _env("BUY_REGIME_CHAOTIC_BONUS", 3.0, float)
BUY_REGIME_RISING_PENALTY = _env("BUY_REGIME_RISING_PENALTY", 2.0, float)
BUY_REGIME_WEAK_PENALTY = _env("BUY_REGIME_WEAK_PENALTY", 1.0, float)
REGIME_CHAOTIC_NASDAQ_ABS = _env("REGIME_CHAOTIC_NASDAQ_ABS", 1.5, float)
REGIME_EVENT_HIGH_IMPACT = _env("REGIME_EVENT_HIGH_IMPACT", 3, int)

PULLBACK_MA5_GAP = _env("PULLBACK_MA5_GAP", 1.5, float)
PULLBACK_VOL_DECLINE = _env("PULLBACK_VOL_DECLINE", 0.5, float)
PULLBACK_BB_LOWER = _env("PULLBACK_BB_LOWER", 0.3, float)
BUY_A_MIN_SCORE = _env("BUY_A_MIN_SCORE", 60.0, float)
BUY_B_MIN_SCORE = _env("BUY_B_MIN_SCORE", 40.0, float)
BUY_DART_DANGER_PENALTY = _env("BUY_DART_DANGER_PENALTY", 10.0, float)
BUY_DART_CAUTION_PENALTY = _env("BUY_DART_CAUTION_PENALTY", 7.0, float)
BUY_NEWS_DANGER_PENALTY = _env("BUY_NEWS_DANGER_PENALTY", 10.0, float)
BUY_NEWS_CAUTION_PENALTY = _env("BUY_NEWS_CAUTION_PENALTY", 5.0, float)
DISCORD_SCREEN_TOP_N = _env("DISCORD_SCREEN_TOP_N", 3, int)
DISCORD_PICK_TOP_N = _env("DISCORD_PICK_TOP_N", 3, int)
NOTIFIER_RECENT_SESSIONS = _env("NOTIFIER_RECENT_SESSIONS", 20, int)

PERFORMANCE_TRACK_DAYS = _env("PERFORMANCE_TRACK_DAYS", 5, int)

TOP_N = _env("TOP_N", 3, int)
TOP_N_CONSERVATIVE = _env("TOP_N_CONSERVATIVE", 2, int)
MIN_PRICE = _env("MIN_PRICE", 3000, int)
MAX_PRICE = _env("MAX_PRICE", 150000, int)
NASDAQ_DROP_THRESHOLD = _env("NASDAQ_DROP_THRESHOLD", -2.0, float)
NASDAQ_PENALTY = _env("NASDAQ_PENALTY", 5.0, float)
MIN_CHANGE_RATE = _env("MIN_CHANGE_RATE", 1.0, float)
MAX_CHANGE_RATE = _env("MAX_CHANGE_RATE", 29.0, float)
MIN_TRADING_VALUE = _env("MIN_TRADING_VALUE", "1000")

EXCLUDE_NAMES = _env_str_list(
    "EXCLUDE_NAME_KEYWORDS",
    ["스팩", "SPAC", "ETN", "우선주", "리츠", "REIT", "ETF"],
)
ETF_KEYWORDS = _env_str_list(
    "ETF_KEYWORDS",
    [
        "KODEX",
        "TIGER",
        "KBSTAR",
        "HANARO",
        "SOL ",
        "ARIRANG",
        "KOSEF",
        "ACE ",
        "PLUS ",
        "BNK",
        "RISE",
        "TIMEFOLIO",
        "레버",
        "인버스",
        "채권",
    ],
)
EXCLUDE_PREF_STOCK = _env_bool("EXCLUDE_PREF_STOCK", True)
EXCLUDE_ETF = _env_bool("EXCLUDE_ETF", True)

SCHEDULE = {
    "daily_pick": _env("SCHEDULE_DAILY_PICK", "15:00"),
    "screen": _env("SCHEDULE_SCREEN", "15:40"),
}
GLOBAL_UPDATE_RETRY_COUNT = _env("GLOBAL_UPDATE_RETRY_COUNT", 3, int)
GLOBAL_UPDATE_RETRY_SLEEP_SEC = _env("GLOBAL_UPDATE_RETRY_SLEEP_SEC", 3, int)
SCHEDULER_LOOP_SLEEP_SEC = _env("SCHEDULER_LOOP_SLEEP_SEC", 30, int)
SCHEDULER_MAX_FAILS = _env("SCHEDULER_MAX_FAILS", 5, int)
MONTHLY_FINSTATE_DAY_CUTOFF = _env("MONTHLY_FINSTATE_DAY_CUTOFF", 10, int)
API_DELAY = _env("API_DELAY", 0.12, float)

HOLDER_DUMP_THRESHOLD = _env("HOLDER_DUMP_THRESHOLD", -10.0, float)
HOLDER_LOW_PENALTY = _env("HOLDER_LOW_PENALTY", 2.0, float)
HOLDER_LOW_THRESH = _env("HOLDER_LOW_THRESH", 30.0, float)
HOLDER_LOW_PRICE_MAX = _env("HOLDER_LOW_PRICE_MAX", 10000, int)
FOMC_PENALTY = _env("FOMC_PENALTY", 3.0, float)
POLITICAL_CRISIS_MODE = _env("POLITICAL_CRISIS_MODE", "top1")

# ── 수급 체커 (supply_checker.py) ──
SUPPLY_CHECK_ENABLED = _env_bool("SUPPLY_CHECK_ENABLED", True)
SUPPLY_SHORT_DAYS = _env("SUPPLY_SHORT_DAYS", 5, int)
SUPPLY_SHORT_INCREASE_THRESH = _env("SUPPLY_SHORT_INCREASE_THRESH", 5.0, float)
SUPPLY_LOAN_INCREASE_DAYS = _env("SUPPLY_LOAN_INCREASE_DAYS", 5, int)
SUPPLY_CREDIT_HOT_RATIO = _env("SUPPLY_CREDIT_HOT_RATIO", 8.0, float)
SUPPLY_STRENGTH_WEAK = _env("SUPPLY_STRENGTH_WEAK", 80.0, float)
SUPPLY_STRENGTH_STRONG = _env("SUPPLY_STRENGTH_STRONG", 120.0, float)
SUPPLY_CAUTION_PENALTY = _env("SUPPLY_CAUTION_PENALTY", 3.0, float)

# ── 외신 체커 (foreign_news_checker.py) ──
FOREIGN_NEWS_ENABLED = _env_bool("FOREIGN_NEWS_ENABLED", False)
FOREIGN_NEWS_API_KEY = _env("FOREIGN_NEWS_API_KEY", "")
FOREIGN_NEWS_DAYS = _env("FOREIGN_NEWS_DAYS", 7, int)
FOREIGN_NEWS_MAX_RESULTS = _env("FOREIGN_NEWS_MAX_RESULTS", 10, int)

# ── 유튜브 체커 (youtube_checker.py) ──
YOUTUBE_CHECK_ENABLED = _env_bool("YOUTUBE_CHECK_ENABLED", False)
YOUTUBE_API_KEY = _env("YOUTUBE_API_KEY", "")
YOUTUBE_SEARCH_DAYS = _env("YOUTUBE_SEARCH_DAYS", 7, int)
YOUTUBE_MAX_RESULTS = _env("YOUTUBE_MAX_RESULTS", 5, int)
