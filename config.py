"""
ClosingBell v3 — 설정 및 상수
==============================
키움 REST API 기반 / 8지표 점수제 / 유니버스 전체 분석
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# 경로
# ============================================================
PROJECT_DIR = Path(__file__).parent
DATA_DIR = Path(os.getenv("DATA_DIR", "C:/Coding/data"))
OHLCV_DIR = DATA_DIR / "ohlcv"
GLOBAL_CSV = DATA_DIR / "global" / "global_merged.csv"
MAPPING_CSV = DATA_DIR / "stock_mapping.csv"
LOG_DIR = PROJECT_DIR / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# 키움 REST API
# ============================================================
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")
KIWOOM_APPKEY = os.getenv("KIWOOM_APPKEY", "")
KIWOOM_SECRETKEY = os.getenv("KIWOOM_SECRETKEY", "")

# ============================================================
# Gemini AI
# ============================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# ============================================================
# DART 공시
# ============================================================
DART_API_KEY = os.getenv("DART_API_KEY", "")

# ============================================================
# 디스코드
# ============================================================
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# ============================================================
# 점수 파라미터 (9.5년 백테스트 기반, 8지표)
# ============================================================
CCI_PERIOD = 14
RSI_PERIOD = 14

# 종형분포 최적 구간 (optimal_low, optimal_high, zero_low, zero_high)
CCI_OPTIMAL = (160, 180)
CCI_ZERO_LOW = 80
CCI_ZERO_HIGH = 300

MA20_GAP_OPTIMAL = (2.0, 8.0)
MA20_GAP_ZERO = 20.0

CHANGE_OPTIMAL = (2.0, 8.0)
CHANGE_ZERO = 20.0

RSI_OPTIMAL = (50, 70)
RSI_ZERO_LOW = 25
RSI_ZERO_HIGH = 85

# 배점 (합계 100점)
SCORE_CCI = 25
SCORE_MA20_GAP = 20
SCORE_CHANGE = 15
SCORE_CCI_SLOPE = 10
SCORE_MA20_SLOPE = 10
SCORE_RSI = 5
SCORE_VOLUME_PROFILE = 10   # 매물대 저항도
SCORE_BROKER_FLOW = 5       # 거래원 이상도

# ============================================================
# 필터
# ============================================================
TOP_N = 3                       # 추천 종목 수 (5→3)
TOP_N_CONSERVATIVE = 2          # 시장 불안 시
MIN_PRICE = 3_000
MAX_PRICE = 150_000
MAX_MA20_GAP = 20.0
NASDAQ_DROP_THRESHOLD = -2.0
MIN_CHANGE_RATE = 1.0
MAX_CHANGE_RATE = 29.0
MIN_TRADING_VALUE = "1000"      # 키움 API용: 100억=1000 (백만원 단위)

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
# 스케줄
# ============================================================
SCHEDULE = {
    "screen": "14:55",
    "update_data": "15:35",
    "git_push": "15:40",
    "shutdown": "15:43",
}

# API 속도 제한
API_DELAY = 0.12  # 초당 ~8건
