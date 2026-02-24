"""
ClosingBell v2 — 설정 및 상수
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
# 한국투자증권 API
# ============================================================
KIS_BASE_URL = "https://openapi.koreainvestment.com:9443"
KIS_APP_KEY = os.getenv("KIS_APP_KEY", "")
KIS_APP_SECRET = os.getenv("KIS_APP_SECRET", "")
KIS_ACCOUNT_NO = os.getenv("KIS_ACCOUNT_NO", "")
KIS_HTS_ID = os.getenv("KIS_HTS_ID", "")

# 계좌 분리 (XXXXXXXX-XX)
CANO = KIS_ACCOUNT_NO.split("-")[0] if "-" in KIS_ACCOUNT_NO else KIS_ACCOUNT_NO[:8]
ACNT_PRDT_CD = KIS_ACCOUNT_NO.split("-")[1] if "-" in KIS_ACCOUNT_NO else KIS_ACCOUNT_NO[8:]

# ============================================================
# TV200 조건검색
# ============================================================
TV200_CONDITION_NAME = "TV200"

# ============================================================
# 점수 파라미터 (9.5년 백테스트 기반)
# ============================================================
CCI_PERIOD = 14

# 종형분포 최적 구간
CCI_OPTIMAL = (160, 180)        # 만점 구간 (50.4% 승률)
CCI_ZERO_LOW = 80               # 이하 0점
CCI_ZERO_HIGH = 300             # 이상 0점

MA20_GAP_OPTIMAL = (2.0, 8.0)   # 이격도 만점 구간
MA20_GAP_ZERO = 20.0            # 이상 0점

CHANGE_OPTIMAL = (2.0, 8.0)     # 등락률 만점 구간
CHANGE_ZERO = 20.0              # 이상 0점

# 배점
SCORE_CCI = 30
SCORE_MA20_GAP = 25
SCORE_CHANGE = 20
SCORE_CCI_SLOPE = 15
SCORE_MA20_SLOPE = 10

# ============================================================
# 필터
# ============================================================
TOP_N = 5                       # 추천 종목 수
TOP_N_CONSERVATIVE = 3          # 시장 불안 시
MIN_PRICE = 1_000               # 최소 가격
MAX_PRICE = 500_000             # 최대 가격 (거래대금 150억+ 종목 대응)
NASDAQ_DROP_THRESHOLD = -2.0    # 나스닥 급락 기준

# ============================================================
# 디스코드
# ============================================================
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# ============================================================
# 스케줄
# ============================================================
SCHEDULE = {
    "screen": "15:00",
    "update_data": "15:35",
    "git_push": "15:40",
    "shutdown": "15:43",
}

# ============================================================
# API 속도 제한
# ============================================================
API_DELAY = 0.06  # 초당 ~16건 (20건 제한 여유)
