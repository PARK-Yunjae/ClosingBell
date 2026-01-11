"""
상수 정의 모듈 v4.0 - 그리드 서치 최적화

📊 최적 조건 (그리드 서치 결과):
- CCI: 160~180 (최고 60.15%)
- 이격도: 2~8% 
- 등락률: 2~8%
- 연속양봉: ≤4일
- 거래대금: ≥200억
- 거래량: ≥1.0배
- CCI 상승중
- MA20 3일 연속 상승
- 고가≠종가
"""

from enum import Enum
from dataclasses import dataclass

# ============================================================
# 기술 지표 계산 상수
# ============================================================

CCI_PERIOD = 14
MA20_PERIOD = 20
CCI_SLOPE_PERIOD = 2
MA20_SLOPE_PERIOD = 3


# ============================================================
# 점수 산출 상수
# ============================================================

SCORE_MAX = 10.0
SCORE_MIN = 0.0

WEIGHT_MIN = 0.5
WEIGHT_MAX = 5.0
WEIGHT_DEFAULT = 1.0
WEIGHT_CHANGE_MAX = 0.2


@dataclass(frozen=True)
class DefaultWeights:
    """기본 가중치 - v4 균등 배분"""
    cci_value: float = 1.0
    cci_slope: float = 1.0  # v4: 이격도 점수
    ma20_slope: float = 1.0
    candle: float = 1.0
    change: float = 1.0


# ============================================================
# CCI 점수 기준 - v4 (그리드 서치 최적화)
# ============================================================

# CCI 최적 구간
CCI_OPTIMAL = 170  # 최적 CCI 값 (160~180 중앙)
CCI_OPTIMAL_MIN = 160
CCI_OPTIMAL_MAX = 180

CCI_SCORE_RANGES = [
    # (min, max, score) - v4: 160~180 최적
    (165, 175, 10.0),  # 최고점 (170 정중앙)
    (160, 165, 9.5),   # 매우 좋음
    (175, 180, 9.5),   # 매우 좋음
    (150, 160, 8.5),   # 좋음
    (180, 190, 8.0),   # 과열 시작
    (140, 150, 7.5),   # 중상
    (190, 200, 6.5),   # 과열 주의
    (130, 140, 6.5),   # 중상
    (120, 130, 5.5),   # 중간
    (200, 220, 5.0),   # 과열
    (100, 120, 4.5),   # 중간
    (220, 250, 4.0),   # 강한 과열
    (50, 100, 3.0),    # 모멘텀 부족
    (250, 300, 2.5),   # 위험
    (0, 50, 2.0),      # 저점
    (300, 500, 1.5),   # 고점 경고
]

CCI_EXTREME_HIGH = 300  # 이 이상은 매우 위험
CCI_EXTREME_LOW = 0


# ============================================================
# CCI 기울기 점수 기준
# ============================================================

CCI_SLOPE_STRONG_UP = 15
CCI_SLOPE_UP = 8
CCI_SLOPE_SLIGHT_UP = 3
CCI_SLOPE_FLAT = 0
CCI_SLOPE_WARNING_LEVEL = 200  # v4: 200 이상에서 하락 시 추가 감점


# ============================================================
# MA20 기울기 점수 기준
# ============================================================

MA20_SLOPE_STRONG_UP = 2.0
MA20_SLOPE_UP = 1.0
MA20_SLOPE_SLIGHT_UP = 0.3
MA20_SLOPE_FLAT = 0.1
MA20_SLOPE_STRONG_DOWN = -2.0


# ============================================================
# 이격도 점수 기준 - v4 신규
# ============================================================

# MA20 대비 이격도 (%) - 그리드 서치 최적
DISTANCE_OPTIMAL_MIN = 2.0  # 최적 하한
DISTANCE_OPTIMAL_MAX = 8.0  # 최적 상한
DISTANCE_DANGER = 8.0       # 위험 시작점


# ============================================================
# 양봉 품질 점수 기준
# ============================================================

CANDLE_UPPER_WICK_EXCELLENT = 0.1
CANDLE_UPPER_WICK_GOOD = 0.2
CANDLE_UPPER_WICK_NORMAL = 0.3
CANDLE_UPPER_WICK_BAD = 0.5

CANDLE_MA20_ABOVE_OPTIMAL = 0.0
CANDLE_MA20_ABOVE_OVERHEAT = 8.0  # v4: 8% 이상 과열


# ============================================================
# 등락률 점수 기준 - v4 (그리드 서치 최적화)
# ============================================================

# 등락률 최적 구간
CHANGE_OPTIMAL_MIN = 2.0   # 최적 하한
CHANGE_OPTIMAL_MAX = 8.0   # 최적 상한
CHANGE_DANGER = 15.0       # 추격 위험

CHANGE_SCORE_RANGES = [
    # (min, max, score) - v4: 2~8% 최적
    (4.0, 6.0, 10.0),   # 최고점 (5% 근처)
    (2.0, 4.0, 9.5),    # 매우 좋음
    (6.0, 8.0, 9.5),    # 매우 좋음
    (1.0, 2.0, 8.5),    # 좋음
    (8.0, 10.0, 8.0),   # 약간 높음
    (0.0, 1.0, 7.0),    # 약한 상승
    (10.0, 12.0, 6.5),  # 주의
    (12.0, 15.0, 5.0),  # 경고
    (15.0, 20.0, 3.0),  # 추격 위험
    (20.0, 25.0, 2.0),  # 고위험
    (25.0, 30.0, 1.0),  # 매우 위험
]

CHANGE_EXTREME_HIGH = 25.0
CHANGE_NEGATIVE_PENALTY = 4.0


# ============================================================
# 연속 양봉 점수 기준 - v4 신규
# ============================================================

CONSEC_OPTIMAL_MAX = 4   # 4일까지 양호
CONSEC_DANGER = 5        # 5일부터 위험

CONSEC_SCORE_MAP = {
    0: 4.0,   # 오늘 음봉
    1: 9.0,   # 1일차
    2: 10.0,  # 2일차 (최적)
    3: 9.5,   # 3일차
    4: 8.0,   # 4일차
    5: 5.0,   # 5일차 (위험 시작!)
    6: 3.0,   # 6일차
    7: 2.0,   # 7일차
}


# ============================================================
# 필터링 상수 - v4 (그리드 서치 최적화)
# ============================================================

# 거래대금 필터 (억원)
MIN_TRADING_VALUE = 200  # v4: 200억 이상 (그리드 서치 최적)

# 하드 필터 (필수 조건)
MAX_CHANGE_RATE = 15.0     # 등락률 15% 이하
MIN_CHANGE_RATE = 2.0      # 등락률 2% 이상 (v4: 그리드 서치 최적)
MAX_CCI_FILTER = 190       # CCI 190 이하 (v4: 과열 방지)
MIN_CCI_FILTER = 100       # CCI 100 이상
MAX_MA20_DISTANCE = 8.0    # 이격도 8% 이하
MAX_CONSECUTIVE_UP = 4     # 연속상승 4일 이하 (v4: 그리드 서치 최적)

# 소프트 필터 (점수 가감)
CANDLE_SCORE_MIN = 6
CANDLE_SCORE_MAX = 9

# 제외 종목 패턴
EXCLUDED_STOCK_PATTERNS = [
    "인버스", "레버리지", "레버", "2X", "2x", "3X", "3x", "곱버스",
    "ETF", "ETN", "KODEX", "TIGER", "KBSTAR", "ARIRANG", "HANARO",
    "KOSEF", "KINDEX", "SOL", "ACE",
    "스팩", "SPAC", "리츠", "REIT",
    "선물", "파생",
    "우선주", "우B", "우C",
    "전환", "CB", "BW",
]

EXCLUDED_CODE_PREFIXES = ["Q"]


# ============================================================
# API 관련 상수
# ============================================================

API_CALLS_PER_SECOND = 8
API_CALL_INTERVAL = 0.12
API_MAX_RETRIES = 3
API_RETRY_DELAY = 1.0
TOKEN_REFRESH_BUFFER = 3600


# ============================================================
# 시스템 상수 - v4
# ============================================================

TOP_N_COUNT = 5  # v4: TOP 5 선정
MIN_DAILY_DATA_COUNT = 20
MIN_LEARNING_SAMPLES = 30


# ============================================================
# 에러 코드
# ============================================================

class ErrorCode(Enum):
    SCREEN_001 = "한투 API 인증 실패"
    SCREEN_002 = "한투 API 호출 실패"
    SCREEN_003 = "필터링 종목 0개"
    SCREEN_004 = "점수 계산 실패"
    SCREEN_005 = "DB 저장 실패"
    
    NOTIFY_001 = "웹훅 URL 무효"
    NOTIFY_002 = "Rate Limit"
    NOTIFY_003 = "네트워크 오류"
    NOTIFY_004 = "메시지 포맷 오류"
    
    KIS_001 = "토큰 발급 실패"
    KIS_002 = "토큰 만료"
    KIS_003 = "요청 한도 초과"
    KIS_004 = "잘못된 종목코드"
    
    DB_001 = "연결 실패"
    DB_002 = "쿼리 실행 실패"
    DB_003 = "데이터 무결성 오류"


# ============================================================
# 메시지 상수
# ============================================================

DISCORD_COLOR_SUCCESS = 3066993
DISCORD_COLOR_WARNING = 16776960
DISCORD_COLOR_ERROR = 15158332

MSG_NO_CANDIDATES = "적합한 종목이 없습니다."
MSG_PREVIEW_LABEL = "[프리뷰]"
MSG_MAIN_LABEL = "[최종]"


# ============================================================
# 매도 추천 상수 - v4 신규
# ============================================================

SELL_STRATEGY = {
    "high_score": {
        "threshold": 80,
        "strategy": "시초가 매도",
        "target": "+1%~+3%",
        "stop_loss": "-2%",
    },
    "good_score": {
        "threshold": 70,
        "strategy": "목표가 매도",
        "target": "+2%~+3%",
        "stop_loss": "-2%",
    },
    "normal_score": {
        "threshold": 60,
        "strategy": "보수적 익절",
        "target": "+1%~+2%",
        "stop_loss": "-1.5%",
    },
    "low_score": {
        "threshold": 0,
        "strategy": "조기 손절",
        "target": "+1%",
        "stop_loss": "-1%",
    },
}


if __name__ == "__main__":
    print("=== v4 상수 확인 ===")
    print(f"CCI 최적 구간: {CCI_OPTIMAL_MIN}~{CCI_OPTIMAL_MAX}")
    print(f"이격도 최적 구간: {DISTANCE_OPTIMAL_MIN}%~{DISTANCE_OPTIMAL_MAX}%")
    print(f"등락률 최적 구간: {CHANGE_OPTIMAL_MIN}%~{CHANGE_OPTIMAL_MAX}%")
    print(f"연속양봉 최대: {CONSEC_OPTIMAL_MAX}일")
    print(f"거래대금 최소: {MIN_TRADING_VALUE}억")
    print(f"TOP N: {TOP_N_COUNT}개")
