"""
상수 정의 모듈 v5.0 - 소프트 필터 방식 (점수제)
"""

from enum import Enum
from dataclasses import dataclass

# 기술 지표 계산 상수
CCI_PERIOD = 14
MA20_PERIOD = 20
CCI_SLOPE_PERIOD = 2
MA20_SLOPE_PERIOD = 3

# v5 점수 상수 (100점 만점)
SCORE_MAX = 100.0
SCORE_MIN = 0.0
SCORE_PER_INDICATOR = 15.0

# v5 등급 기준
GRADE_S_THRESHOLD = 85
GRADE_A_THRESHOLD = 75
GRADE_B_THRESHOLD = 65
GRADE_C_THRESHOLD = 55

# CCI 최적 구간
CCI_OPTIMAL = 170
CCI_OPTIMAL_MIN = 160
CCI_OPTIMAL_MAX = 180

# 이격도 최적 구간
DISTANCE_OPTIMAL_MIN = 2.0
DISTANCE_OPTIMAL_MAX = 8.0
DISTANCE_DANGER = 15.0

# 등락률 최적 구간
CHANGE_OPTIMAL_MIN = 2.0
CHANGE_OPTIMAL_MAX = 8.0
CHANGE_DANGER = 15.0

# 연속양봉 최적
CONSEC_OPTIMAL_MAX = 4
CONSEC_DANGER = 5

# 거래량비율 최적
VOLUME_OPTIMAL_MIN = 1.5
VOLUME_OPTIMAL_MAX = 3.0

# 하드 필터 (최소화)
MIN_TRADING_VALUE = 200
MIN_CHANGE_RATE_HARD = 0.0

# 제외 종목 패턴
EXCLUDED_STOCK_PATTERNS = [
    "인버스", "레버리지", "레버", "2X", "2x", "3X", "3x", "곱버스",
    "ETF", "ETN", "KODEX", "TIGER", "KBSTAR", "ARIRANG", "HANARO",
    "KOSEF", "KINDEX", "SOL", "ACE", "스팩", "SPAC", "리츠", "REIT",
    "선물", "파생", "우선주", "우B", "우C", "전환", "CB", "BW",
]
EXCLUDED_CODE_PREFIXES = ["Q"]

# API 상수
API_CALLS_PER_SECOND = 8
API_CALL_INTERVAL = 0.12
API_MAX_RETRIES = 3
API_RETRY_DELAY = 1.0
TOKEN_REFRESH_BUFFER = 3600

# 시스템 상수
TOP_N_COUNT = 5
MIN_DAILY_DATA_COUNT = 20
MIN_LEARNING_SAMPLES = 30

# 레거시 호환
WEIGHT_MIN = 0.5
WEIGHT_MAX = 5.0
WEIGHT_DEFAULT = 1.0
WEIGHT_CHANGE_MAX = 0.2

@dataclass(frozen=True)
class DefaultWeights:
    cci_value: float = 1.0
    cci_slope: float = 1.0
    ma20_slope: float = 1.0
    candle: float = 1.0
    change: float = 1.0

class ErrorCode(Enum):
    SCREEN_001 = "한투 API 인증 실패"
    SCREEN_002 = "한투 API 호출 실패"
    SCREEN_003 = "필터링 종목 0개"
    SCREEN_004 = "점수 계산 실패"
    SCREEN_005 = "DB 저장 실패"
    NOTIFY_001 = "웹훅 URL 무효"
    NOTIFY_002 = "Rate Limit"
    NOTIFY_003 = "네트워크 오류"
    KIS_001 = "토큰 발급 실패"
    KIS_002 = "토큰 만료"
    DB_001 = "연결 실패"
    DB_002 = "쿼리 실행 실패"

# 메시지 상수
DISCORD_COLOR_SUCCESS = 3066993
DISCORD_COLOR_WARNING = 16776960
DISCORD_COLOR_ERROR = 15158332
MSG_NO_CANDIDATES = "적합한 종목이 없습니다."
MSG_PREVIEW_LABEL = "[프리뷰]"
MSG_MAIN_LABEL = "[최종]"
