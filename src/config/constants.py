"""
상수 정의 모듈 v8.0 - 7핵심 지표 점수제 (거래원 편입)
"""

from enum import Enum
from dataclasses import dataclass

# 기술 지표 계산 상수
CCI_PERIOD = 14
MA20_PERIOD = 20
CCI_SLOPE_PERIOD = 2
MA20_SLOPE_PERIOD = 3

# v8 점수 상수 (100점 만점)
# 핵심 7개 × 13점 = 91점 + 보너스 3개 = 9점 = 100점
SCORE_MAX = 100.0
SCORE_MIN = 0.0
SCORE_PER_INDICATOR = 13.0  # v8: 15 → 13 (7핵심 체계)
BONUS_CCI_RISING_MAX = 3.0  # v8: 4 → 3
BONUS_MA20_3DAY_MAX = 3.0
BONUS_NOT_HIGH_EQ_CLOSE_MAX = 3.0

# v8 등급 기준 (유지)
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
# ★ P0-B: TOP_N_COUNT는 settings.screening.top_n_count와 통일
# 하위 호환성을 위해 상수로 유지하되, 기본값은 settings에서 오버라이드 가능
TOP_N_COUNT = 5  # 기본값 (settings.screening.top_n_count로 오버라이드 권장)

def get_top_n_count() -> int:
    """TOP N 종목 수 반환 (settings 우선, 없으면 기본값 5)"""
    try:
        from src.config.settings import settings
        return settings.screening.top_n_count
    except Exception:
        return TOP_N_COUNT

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
    SCREEN_001 = "키움 API 인증 실패"
    SCREEN_002 = "키움 API 호출 실패"
    SCREEN_003 = "필터링 종목 0개"
    SCREEN_004 = "점수 계산 실패"
    SCREEN_005 = "DB 저장 실패"
    NOTIFY_001 = "웹훅 URL 무효"
    NOTIFY_002 = "Rate Limit"
    NOTIFY_003 = "네트워크 오류"
    KIWOOM_001 = "토큰 발급 실패"
    KIWOOM_002 = "토큰 만료"
    DB_001 = "연결 실패"
    DB_002 = "쿼리 실행 실패"

# 메시지 상수
DISCORD_COLOR_SUCCESS = 3066993
DISCORD_COLOR_WARNING = 16776960
DISCORD_COLOR_ERROR = 15158332
MSG_NO_CANDIDATES = "적합한 종목이 없습니다."
MSG_PREVIEW_LABEL = "🔮 감시종목 TOP5 (프리뷰)"
MSG_MAIN_LABEL = "감시종목 TOP5"

# ============================================
# 레거시 호환 (v5.2 가중치 - 참조용)
# ============================================
# v8에서는 사용하지 않으나 백필/호환성을 위해 유지
WEIGHT_VOLUME_V52 = 25
WEIGHT_CHANGE_V52 = 20
WEIGHT_CONSEC_V52 = 15
WEIGHT_CCI_V52 = 15
WEIGHT_DISTANCE_V52 = 15
WEIGHT_CANDLE_V52 = 10
WEIGHT_TOTAL_V52 = 100

# v5.2 거래량비 필터
VOLUME_RATIO_SOFT_MAX = 5.0    # 소프트 감점 시작
VOLUME_RATIO_HARD_MAX = 10.0   # 하드 필터 (제외)

# v5.2 CCI 페널티
CCI_PENALTY_START_V52 = 230    # 230+ 페널티 시작 (기존 250)

# v5.2 대형주 보너스
LARGE_CAP_1T = 10000           # 1조 (억 단위)
LARGE_CAP_5000 = 5000          
LARGE_CAP_1000 = 1000          
LARGE_CAP_BONUS_1T = 5.0       # +5점
LARGE_CAP_BONUS_5000 = 4.0     # +4점
LARGE_CAP_BONUS_1000 = 2.0     # +2점
