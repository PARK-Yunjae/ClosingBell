# 5. API 스펙 (API Specification)

**프로젝트명:** 종가매매 스크리너  
**버전:** 1.0  
**작성일:** 2025-01-06  

---

## 5.1 개요

### 5.1.1 결론
내부 모듈 간 통신 및 Streamlit 대시보드 연동을 위한 API 스펙을 정의한다. 외부 API(한투, 디스코드)와의 연동 스펙도 포함한다.

### 5.1.2 근거
- Streamlit 대시보드와 백엔드 분리 가능성 고려
- 추후 FastAPI 전환 시 재사용
- 외부 API 연동 명세 문서화

### 5.1.3 리스크/대안
| 리스크 | 대안 |
|--------|------|
| 초기에는 API 서버 불필요 | 직접 DB 접근으로 시작, 추후 API 레이어 추가 |
| 한투 API 버전 변경 | 버전 명시 + 래퍼 클래스로 추상화 |

---

## 5.2 외부 API 연동 스펙

### 5.2.1 한국투자증권 API

#### A. 인증 (OAuth 토큰)

**Endpoint:** `POST /oauth2/tokenP`  
**Base URL:** `https://openapi.koreainvestment.com:9443`

**Request:**
```json
{
    "grant_type": "client_credentials",
    "appkey": "{APP_KEY}",
    "appsecret": "{APP_SECRET}"
}
```

**Response (200 OK):**
```json
{
    "access_token": "eyJ0eXAiOiJKV...",
    "token_type": "Bearer",
    "expires_in": 86400
}
```

**에러 코드:**
| 코드 | 메시지 | 원인 |
|------|--------|------|
| 401 | Invalid credentials | APP_KEY/SECRET 오류 |
| 429 | Too many requests | 요청 한도 초과 |

---

#### B. 국내주식 일봉 조회

**Endpoint:** `GET /uapi/domestic-stock/v1/quotations/inquire-daily-price`

**Headers:**
```
Content-Type: application/json
Authorization: Bearer {access_token}
appkey: {APP_KEY}
appsecret: {APP_SECRET}
tr_id: FHKST01010400
```

**Query Parameters:**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| FID_COND_MRKT_DIV_CODE | string | O | 시장 구분 (J: 주식) |
| FID_INPUT_ISCD | string | O | 종목코드 (6자리) |
| FID_PERIOD_DIV_CODE | string | O | 기간 구분 (D: 일) |
| FID_ORG_ADJ_PRC | string | O | 수정주가 여부 (0: 수정주가) |

**Response (200 OK):**
```json
{
    "rt_cd": "0",
    "msg_cd": "MCA00000",
    "msg1": "정상처리",
    "output": [
        {
            "stck_bsop_date": "20250106",
            "stck_oprc": "50000",
            "stck_hgpr": "52000",
            "stck_lwpr": "49500",
            "stck_clpr": "51500",
            "acml_vol": "1234567",
            "acml_tr_pbmn": "63456789000"
        }
    ]
}
```

**필드 매핑:**
| API 필드 | 내부 필드 | 설명 |
|----------|----------|------|
| stck_bsop_date | date | 영업일자 |
| stck_oprc | open | 시가 |
| stck_hgpr | high | 고가 |
| stck_lwpr | low | 저가 |
| stck_clpr | close | 종가 |
| acml_vol | volume | 누적거래량 |
| acml_tr_pbmn | trading_value | 누적거래대금 |

---

#### C. 국내주식 현재가 조회

**Endpoint:** `GET /uapi/domestic-stock/v1/quotations/inquire-price`

**Headers:** (B와 동일, tr_id만 변경)
```
tr_id: FHKST01010100
```

**Query Parameters:**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| FID_COND_MRKT_DIV_CODE | string | O | 시장 구분 (J) |
| FID_INPUT_ISCD | string | O | 종목코드 |

**Response (200 OK):**
```json
{
    "rt_cd": "0",
    "output": {
        "stck_prpr": "51500",
        "prdy_vrss": "1500",
        "prdy_ctrt": "3.00",
        "acml_tr_pbmn": "45678900000"
    }
}
```

---

#### D. 전종목 시세 조회 (거래대금 필터용)

**Endpoint:** `GET /uapi/domestic-stock/v1/quotations/inquire-daily-trade`

**Headers:**
```
tr_id: FHKST03010100
```

**Query Parameters:**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| FID_COND_MRKT_DIV_CODE | string | O | 시장 구분 (J: 전체) |
| FID_COND_SCR_DIV_CODE | string | O | 조건 (20001: 거래대금 상위) |
| FID_INPUT_ISCD | string | O | 업종코드 (0000: 전체) |
| FID_DIV_CLS_CODE | string | O | 분류 (0: 전체) |
| FID_RANK_SORT_CLS_CODE | string | O | 정렬 (0: 상위) |
| FID_ETC_CLS_CODE | string | O | 기타 (0) |

**Response:** 거래대금 상위 종목 리스트

---

### 5.2.2 Discord Webhook API

#### A. 메시지 발송

**Endpoint:** `POST {WEBHOOK_URL}`

**Request:**
```json
{
    "content": null,
    "embeds": [
        {
            "title": "🎯 종가매매 TOP 3 (15:00)",
            "description": "2025-01-06 스크리닝 결과",
            "color": 3066993,
            "fields": [
                {
                    "name": "🥇 1위: 삼성전자 (005930)",
                    "value": "현재가: 51,500원 (+3.0%)\n점수: 8.5점",
                    "inline": false
                },
                {
                    "name": "🥈 2위: LG에너지솔루션 (373220)",
                    "value": "현재가: 420,000원 (+5.2%)\n점수: 8.2점",
                    "inline": false
                },
                {
                    "name": "🥉 3위: SK하이닉스 (000660)",
                    "value": "현재가: 180,000원 (+2.8%)\n점수: 7.9점",
                    "inline": false
                }
            ],
            "footer": {
                "text": "종가매매 스크리너 v1.0"
            },
            "timestamp": "2025-01-06T15:05:00.000Z"
        }
    ]
}
```

**Response:**
| 코드 | 설명 |
|------|------|
| 204 No Content | 성공 |
| 400 Bad Request | 잘못된 요청 형식 |
| 404 Not Found | 웹훅 URL 무효 |
| 429 Too Many Requests | Rate Limit (5/5s) |

**Rate Limit 대응:**
```python
if response.status_code == 429:
    retry_after = response.headers.get('Retry-After', 5)
    time.sleep(float(retry_after))
    # 재시도
```

---

### 5.2.3 카카오 알림톡 API (선택)

> **보류 사항:** 카카오 비즈니스 채널 설정 필요. 설정 완료 시 추가 문서화.

**Endpoint:** `POST https://kapi.kakao.com/v2/api/talk/memo/default/send`

**Headers:**
```
Authorization: Bearer {ACCESS_TOKEN}
Content-Type: application/x-www-form-urlencoded
```

---

## 5.3 내부 서비스 인터페이스

### 5.3.1 Screener Service

#### A. 스크리닝 실행

**Interface:** `ScreenerService.run_screening()`

**Input:**
```python
@dataclass
class ScreeningConfig:
    min_trading_value: float = 300.0  # 억원
    screen_time: str = "15:00"
    save_to_db: bool = True  # False면 12:30 프리뷰
```

**Output:**
```python
@dataclass
class ScreeningResult:
    screen_date: date
    screen_time: str
    total_count: int
    top3: List[StockScore]
    all_items: List[StockScore]
    execution_time_sec: float
    status: str  # SUCCESS, FAILED, PARTIAL
    error_message: Optional[str]

@dataclass
class StockScore:
    stock_code: str
    stock_name: str
    current_price: int
    change_rate: float
    trading_value: float
    score_total: float
    score_cci_value: float
    score_cci_slope: float
    score_ma20_slope: float
    score_candle: float
    score_change: float
    raw_cci: float
    raw_ma20: float
    rank: int
```

**에러 코드:**
| 코드 | 설명 | 처리 |
|------|------|------|
| SCREEN_001 | 한투 API 인증 실패 | 토큰 재발급 후 재시도 |
| SCREEN_002 | 한투 API 호출 실패 | 3회 재시도 후 PARTIAL 상태 |
| SCREEN_003 | 필터링 종목 0개 | 조건 완화 또는 종료 |
| SCREEN_004 | 점수 계산 실패 | 해당 종목 제외 |
| SCREEN_005 | DB 저장 실패 | 로깅 후 알림 진행 |

---

#### B. 점수 계산

**Interface:** `ScoreCalculator.calculate(stock_data, weights)`

**Input:**
```python
@dataclass
class StockData:
    code: str
    name: str
    daily_prices: List[DailyPrice]  # 최근 20일 일봉
    current_price: int
    trading_value: float

@dataclass
class DailyPrice:
    date: date
    open: int
    high: int
    low: int
    close: int
    volume: int

@dataclass
class Weights:
    cci_value: float = 1.0
    cci_slope: float = 1.0
    ma20_slope: float = 1.0
    candle: float = 1.0
    change: float = 1.0
```

**Output:**
```python
@dataclass
class ScoreDetail:
    cci_value: float      # 0~10
    cci_slope: float      # 0~10
    ma20_slope: float     # 0~10
    candle: float         # 0~10
    change: float         # 0~10
    total: float          # 가중 합계
    raw_cci: float        # CCI 원시값
    raw_ma20: float       # MA20 원시값
```

**점수 산출 로직:**

```python
def calculate_cci_value_score(cci: float) -> float:
    """CCI 값 점수 (180 근접 시 최고점)"""
    if 170 <= cci <= 190:
        return 10.0
    elif 150 <= cci < 170 or 190 < cci <= 210:
        return 8.0
    elif 100 <= cci < 150:
        return 6.0
    elif 210 < cci <= 300:
        return 4.0  # 과열 구간
    elif cci > 300:
        return 2.0  # 고점 경고
    else:
        return 3.0  # 100 미만

def calculate_cci_slope_score(cci_values: List[float]) -> float:
    """CCI 기울기 점수 (최근 3일)"""
    if len(cci_values) < 3:
        return 0.0
    slope = (cci_values[-1] - cci_values[-3]) / 2
    
    # 200 이상에서 하락 시 감점
    if cci_values[-1] > 200 and slope < 0:
        return 2.0
    
    if slope > 10:
        return 10.0
    elif slope > 5:
        return 8.0
    elif slope > 0:
        return 6.0
    else:
        return 3.0
```

---

### 5.3.2 Notifier Service

#### A. 알림 발송

**Interface:** `NotifierService.send_alert(result, channel)`

**Input:**
```python
@dataclass
class AlertMessage:
    title: str
    screen_date: date
    screen_time: str
    top3: List[StockScore]
    is_preview: bool = False  # 12:30 프리뷰 여부

class NotifyChannel(Enum):
    DISCORD = "discord"
    KAKAO = "kakao"
```

**Output:**
```python
@dataclass
class NotifyResult:
    channel: NotifyChannel
    success: bool
    response_code: int
    error_message: Optional[str]
    sent_at: datetime
```

**에러 코드:**
| 코드 | 설명 | 처리 |
|------|------|------|
| NOTIFY_001 | 웹훅 URL 무효 | 설정 확인 알림 |
| NOTIFY_002 | Rate Limit | 대기 후 재시도 |
| NOTIFY_003 | 네트워크 오류 | 1회 재시도 |
| NOTIFY_004 | 메시지 포맷 오류 | 로깅 |

---

### 5.3.3 Learner Service

#### A. 익일 결과 수집

**Interface:** `LearnerService.collect_next_day_results()`

**Input:** 없음 (전일 스크리닝 종목 자동 조회)

**Output:**
```python
@dataclass
class CollectionResult:
    collected_count: int
    failed_codes: List[str]
    hit_rate: float  # TOP3 시초가 상승 비율
```

---

#### B. 가중치 최적화

**Interface:** `LearnerService.optimize_weights()`

**Input:**
```python
@dataclass
class OptimizeConfig:
    min_samples: int = 30         # 최소 데이터 수
    max_weight_change: float = 0.1  # 1회 최대 변경폭
    target_metric: str = "is_open_up"  # 최적화 대상
```

**Output:**
```python
@dataclass
class OptimizeResult:
    old_weights: Weights
    new_weights: Weights
    correlations: Dict[str, float]
    sample_size: int
    improved: bool
```

**최적화 알고리즘:**
```python
def optimize_weights(data: List[ScreeningItem], config: OptimizeConfig) -> Weights:
    """
    각 지표별 점수와 익일 시초가 상승 여부의 상관관계를 분석하여
    상관관계가 높은 지표의 가중치를 높이고, 낮은 지표의 가중치를 낮춤.
    
    1. 각 지표별로 피어슨 상관계수 계산
    2. 평균 상관계수 대비 높으면 가중치 UP, 낮으면 DOWN
    3. 변경폭 제한 (±0.1)
    4. 범위 제한 (0.5 ~ 2.0)
    """
    pass
```

---

### 5.3.4 Dashboard Service (Streamlit)

#### A. 대시보드 데이터 조회

**Interface:** `DashboardService.get_summary(days=30)`

**Output:**
```python
@dataclass
class DashboardSummary:
    hit_rate: float              # TOP3 적중률
    avg_return: float            # 평균 수익률
    screening_count: int         # 스크리닝 횟수
    current_weights: Weights     # 현재 가중치
    daily_stats: List[DailyStat] # 일별 통계

@dataclass
class DailyStat:
    date: date
    total_count: int
    hit_count: int
    hit_rate: float
```

---

## 5.4 에러 코드 종합

| 범위 | 모듈 | 설명 |
|------|------|------|
| SCREEN_0XX | Screener | 스크리닝 관련 |
| NOTIFY_0XX | Notifier | 알림 관련 |
| LEARN_0XX | Learner | 학습 관련 |
| DB_0XX | Database | DB 관련 |
| KIS_0XX | KIS Client | 한투 API 관련 |

**공통 에러 처리 패턴:**
```python
class ScreenerError(Exception):
    def __init__(self, code: str, message: str, recoverable: bool = True):
        self.code = code
        self.message = message
        self.recoverable = recoverable
        super().__init__(f"[{code}] {message}")
```

---

## 5.5 Rate Limit 정책

| API | 공식 제한 | 적용 제한 | 대응 |
|-----|---------|---------|------|
| 한투 일봉 | 초당 10회 | **초당 4회** | 0.25초 간격 호출 (안전 마진 확보) |
| 한투 현재가 | 초당 10회 | **초당 4회** | 배치 처리 + 0.25초 간격 |
| Discord 웹훅 | 5회/5초 | **3회/5초** | 메시지 통합 |

> ⚠️ **안정성 우선**: 공식 제한의 50% 수준으로 운영하여 Rate Limit 에러 원천 차단

---

## 5.6 문서 이력

| 버전 | 날짜 | 변경 내용 | 작성자 |
|------|------|----------|--------|
| 1.0 | 2025-01-06 | 초안 작성 | Architect AI |

---

**이전 문서:** [04_Database_Design.md](./04_Database_Design.md)  
**다음 문서:** [06_Architecture.md](./06_Architecture.md)
