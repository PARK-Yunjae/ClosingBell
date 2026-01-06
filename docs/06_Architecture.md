# 6. 아키텍처 설계 (Architecture Design)

**프로젝트명:** 종가매매 스크리너  
**버전:** 1.0  
**작성일:** 2025-01-06  

---

## 6.1 개요

### 6.1.1 결론
모듈러 모놀리식(Modular Monolith) 아키텍처를 채택하여, 단일 프로세스 내에서 명확히 분리된 모듈로 구성한다. 추후 마이크로서비스 전환 가능한 구조로 설계한다.

### 6.1.2 근거
- 단일 사용자 시스템으로 복잡한 분산 시스템 불필요
- 모듈 간 명확한 경계로 유지보수성 확보
- SQLite + Python 단일 프로세스로 운영 간소화

### 6.1.3 리스크/대안
| 리스크 | 대안 |
|--------|------|
| 모듈 간 결합도 증가 | 인터페이스 기반 의존성 주입 |
| 단일 프로세스 병목 | 비동기 처리 (asyncio) 도입 |
| 스케줄러 단일 장애점 | systemd 서비스로 자동 재시작 |

---

## 6.2 시스템 아키텍처

### 6.2.1 전체 구조도

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              System Architecture                             │
└─────────────────────────────────────────────────────────────────────────────┘

                              ┌─────────────────┐
                              │   External APIs │
                              └────────┬────────┘
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        │                              │                              │
        ▼                              ▼                              ▼
┌───────────────┐            ┌─────────────────┐            ┌─────────────────┐
│  한투 REST API │            │ Discord Webhook │            │  (카카오 API)   │
└───────┬───────┘            └────────┬────────┘            └────────┬────────┘
        │                              │                              │
        └──────────────────────────────┼──────────────────────────────┘
                                       │
┌──────────────────────────────────────┴────────────────────────────────────────┐
│                           Application Layer                                    │
│  ┌─────────────────────────────────────────────────────────────────────────┐  │
│  │                         External Adapters                                │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                   │  │
│  │  │  KIS Client  │  │   Discord    │  │    Kakao     │                   │  │
│  │  │   (한투 API) │  │   Notifier   │  │   Notifier   │                   │  │
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                   │  │
│  └─────────┼─────────────────┼─────────────────┼────────────────────────────┘  │
│            │                 │                 │                               │
│  ┌─────────┴─────────────────┴─────────────────┴────────────────────────────┐  │
│  │                         Core Services                                     │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │  │
│  │  │   Screener   │  │   Learner    │  │   Notifier   │  │  Dashboard   │  │  │
│  │  │   Service    │  │   Service    │  │   Service    │  │   Service    │  │  │
│  │  │              │  │              │  │              │  │  (Streamlit) │  │  │
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │  │
│  └─────────┼─────────────────┼─────────────────┼─────────────────┼───────────┘  │
│            │                 │                 │                 │              │
│  ┌─────────┴─────────────────┴─────────────────┴─────────────────┴───────────┐  │
│  │                         Domain Layer                                       │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │  │
│  │  │   Indicator  │  │    Score     │  │   Weight     │  │    Trade     │  │  │
│  │  │  Calculator  │  │  Calculator  │  │  Optimizer   │  │   Journal    │  │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│            │                                                                    │
│  ┌─────────┴─────────────────────────────────────────────────────────────────┐  │
│  │                      Infrastructure Layer                                  │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │  │
│  │  │  Repository  │  │   Scheduler  │  │    Logger    │  │    Config    │  │  │
│  │  │   (SQLite)   │  │   (APSched)  │  │  (logging)   │  │   (dotenv)   │  │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
                              ┌─────────────────┐
                              │     SQLite      │
                              │    Database     │
                              └─────────────────┘
```

### 6.2.2 레이어 설명

| 레이어 | 역할 | 주요 컴포넌트 |
|--------|------|---------------|
| External Adapters | 외부 API 통신 추상화 | KIS Client, Discord/Kakao Notifier |
| Core Services | 비즈니스 로직 오케스트레이션 | Screener, Learner, Notifier, Dashboard |
| Domain Layer | 순수 비즈니스 로직 | Indicator/Score Calculator, Optimizer |
| Infrastructure | 인프라 관심사 | Repository, Scheduler, Logger, Config |

---

## 6.3 폴더 구조

```
closing-trade-screener/
│
├── docs/                           # 설계 문서
│   ├── 01_PRD_v1.0.md
│   ├── 02_User_Stories.md
│   ├── 03_User_Flows.md
│   ├── 04_Database_Design.md
│   ├── 05_API_Spec.md
│   ├── 06_Architecture.md
│   ├── 07_Risk_Analysis.md
│   └── 08_Test_Plan.md
│
├── src/                            # 소스 코드
│   ├── __init__.py
│   │
│   ├── adapters/                   # 외부 시스템 어댑터
│   │   ├── __init__.py
│   │   ├── kis_client.py          # 한투 API 클라이언트
│   │   ├── discord_notifier.py    # 디스코드 웹훅
│   │   └── kakao_notifier.py      # 카카오 알림 (선택)
│   │
│   ├── services/                   # 핵심 서비스
│   │   ├── __init__.py
│   │   ├── screener_service.py    # 스크리닝 오케스트레이션
│   │   ├── learner_service.py     # 학습/최적화 서비스
│   │   └── notifier_service.py    # 알림 통합 서비스
│   │
│   ├── domain/                     # 도메인 로직
│   │   ├── __init__.py
│   │   ├── models.py              # 데이터 모델 (dataclass)
│   │   ├── indicators.py          # 기술 지표 계산 (CCI, MA)
│   │   ├── score_calculator.py    # 점수 산출 로직
│   │   └── weight_optimizer.py    # 가중치 최적화 로직
│   │
│   ├── infrastructure/             # 인프라 계층
│   │   ├── __init__.py
│   │   ├── database.py            # SQLite 연결 관리
│   │   ├── repository.py          # 데이터 접근 레이어
│   │   ├── scheduler.py           # APScheduler 설정
│   │   └── logger.py              # 로깅 설정
│   │
│   └── config/                     # 설정
│       ├── __init__.py
│       ├── settings.py            # 환경 변수 로드
│       └── constants.py           # 상수 정의
│
├── dashboard/                      # Streamlit 대시보드
│   ├── __init__.py
│   ├── app.py                     # 메인 앱
│   ├── pages/                     # 멀티페이지
│   │   ├── 01_overview.py         # 개요/요약
│   │   ├── 02_screening.py        # 스크리닝 결과
│   │   ├── 03_analysis.py         # 분석/통계
│   │   └── 04_journal.py          # 매매일지
│   └── components/                 # 재사용 컴포넌트
│       ├── charts.py
│       └── tables.py
│
├── tests/                          # 테스트
│   ├── __init__.py
│   ├── unit/                       # 단위 테스트
│   │   ├── test_indicators.py
│   │   ├── test_score_calculator.py
│   │   └── test_weight_optimizer.py
│   ├── integration/                # 통합 테스트
│   │   ├── test_kis_client.py
│   │   ├── test_screener_service.py
│   │   └── test_notifier_service.py
│   └── fixtures/                   # 테스트 데이터
│       └── sample_daily_prices.json
│
├── scripts/                        # 유틸리티 스크립트
│   ├── init_db.py                 # DB 초기화
│   ├── backup_db.py               # DB 백업
│   └── manual_screening.py        # 수동 스크리닝 실행
│
├── data/                           # 데이터 디렉토리
│   ├── screener.db                # SQLite DB 파일
│   └── backup/                    # 백업 디렉토리
│
├── logs/                           # 로그 디렉토리
│   └── screener.log
│
├── .env.example                    # 환경 변수 예시
├── .gitignore
├── requirements.txt               # Python 의존성
├── pyproject.toml                 # 프로젝트 메타데이터
├── main.py                        # 메인 실행 파일 (스케줄러)
└── README.md
```

---

## 6.4 모듈 책임 정의

### 6.4.1 Adapters Layer

#### kis_client.py
```python
"""
한국투자증권 API 클라이언트

책임:
- OAuth 토큰 발급 및 갱신
- 일봉 데이터 조회
- 현재가 조회
- 거래대금 상위 종목 조회
- Rate Limit 핸들링
- API 에러 변환

의존성:
- requests
- config.settings

인터페이스:
- get_daily_prices(stock_code, count=20) -> List[DailyPrice]
- get_current_price(stock_code) -> CurrentPrice
- get_top_trading_value_stocks(limit=200) -> List[StockInfo]
"""
```

#### discord_notifier.py
```python
"""
디스코드 웹훅 알림

책임:
- 웹훅 메시지 포맷팅
- Embed 생성
- 발송 및 재시도
- Rate Limit 핸들링

의존성:
- requests
- config.settings

인터페이스:
- send_screening_result(result: ScreeningResult, is_preview: bool) -> NotifyResult
- send_error_alert(error: Exception) -> NotifyResult
"""
```

---

### 6.4.2 Services Layer

#### screener_service.py
```python
"""
스크리닝 오케스트레이션 서비스

책임:
- 스크리닝 플로우 제어
- 필터링 → 분석 → 점수 산출 → 저장 → 알림 순서 관리
- 에러 처리 및 부분 실패 핸들링
- 실행 시간 측정

의존성:
- adapters.kis_client
- domain.score_calculator
- infrastructure.repository
- services.notifier_service

인터페이스:
- run_screening(config: ScreeningConfig) -> ScreeningResult
- run_preview_screening() -> ScreeningResult  # 12:30용
"""
```

#### learner_service.py
```python
"""
학습 및 최적화 서비스

책임:
- 익일 결과 수집 플로우
- 가중치 최적화 트리거
- 최적화 결과 저장

의존성:
- adapters.kis_client
- domain.weight_optimizer
- infrastructure.repository

인터페이스:
- collect_next_day_results() -> CollectionResult
- optimize_weights() -> OptimizeResult
"""
```

#### notifier_service.py
```python
"""
알림 통합 서비스

책임:
- 다중 채널 알림 발송 (Discord, Kakao)
- 채널별 활성화 상태 관리
- 발송 결과 집계

의존성:
- adapters.discord_notifier
- adapters.kakao_notifier

인터페이스:
- send_alert(result: ScreeningResult, is_preview: bool) -> List[NotifyResult]
- send_error(error: Exception) -> List[NotifyResult]
"""
```

---

### 6.4.3 Domain Layer

#### indicators.py
```python
"""
기술 지표 계산기

책임:
- CCI(14) 계산
- 이동평균선(MA20) 계산
- 기울기 계산
- 캔들 패턴 분석

의존성:
- 없음 (순수 계산 로직)

인터페이스:
- calculate_cci(prices: List[DailyPrice], period=14) -> List[float]
- calculate_ma(prices: List[DailyPrice], period=20) -> List[float]
- calculate_slope(values: List[float], period=3) -> float
- analyze_candle(price: DailyPrice, ma20: float) -> CandleAnalysis
"""
```

#### score_calculator.py
```python
"""
점수 산출기

책임:
- 5가지 지표별 점수 산출
- 가중치 적용
- 총점 계산
- TOP N 선정

의존성:
- domain.indicators
- domain.models

인터페이스:
- calculate_scores(stocks: List[StockData], weights: Weights) -> List[StockScore]
- select_top_n(scores: List[StockScore], n=3) -> List[StockScore]
"""
```

#### weight_optimizer.py
```python
"""
가중치 최적화기

책임:
- 상관관계 분석
- 최적 가중치 계산
- 가중치 범위 제한

의존성:
- numpy (선택)
- domain.models

인터페이스:
- analyze_correlation(data: List[ScreeningItem]) -> Dict[str, float]
- optimize(current: Weights, correlations: Dict, config: OptimizeConfig) -> Weights
"""
```

---

### 6.4.4 Infrastructure Layer

#### database.py
```python
"""
SQLite 데이터베이스 연결 관리

책임:
- 연결 풀 관리 (단일 연결)
- WAL 모드 설정
- 트랜잭션 관리
- 마이그레이션

의존성:
- sqlite3
- config.settings

인터페이스:
- get_connection() -> sqlite3.Connection
- execute(sql, params) -> cursor
- init_database() -> None
"""
```

#### repository.py
```python
"""
데이터 접근 레이어

책임:
- CRUD 오퍼레이션
- 복잡한 쿼리 캡슐화
- 데이터 모델 변환

의존성:
- infrastructure.database
- domain.models

인터페이스:
- save_screening(result: ScreeningResult) -> int
- get_screening_by_date(date) -> Optional[Screening]
- save_next_day_result(item_id, result: NextDayResult) -> None
- get_weights() -> Weights
- update_weights(weights: Weights, reason: str) -> None
- get_screening_history(days=30) -> List[ScreeningWithResults]
"""
```

#### scheduler.py
```python
"""
작업 스케줄러

책임:
- Cron 스케줄 관리
- 작업 등록/해제
- 장 운영일 체크

의존성:
- APScheduler
- services.*

인터페이스:
- setup_schedules() -> None
- add_job(func, trigger, **kwargs) -> None
- start() -> None
- shutdown() -> None
"""
```

---

## 6.5 의존성 다이어그램

```
┌─────────────────────────────────────────────────────────────────┐
│                    Dependency Direction                          │
│                    (위 → 아래로 의존)                            │
└─────────────────────────────────────────────────────────────────┘

                         ┌─────────────┐
                         │   main.py   │
                         └──────┬──────┘
                                │
                    ┌───────────┼───────────┐
                    ▼           ▼           ▼
            ┌───────────┐ ┌───────────┐ ┌───────────┐
            │ scheduler │ │ dashboard │ │  scripts  │
            └─────┬─────┘ └─────┬─────┘ └─────┬─────┘
                  │             │             │
                  └─────────────┼─────────────┘
                                ▼
                  ┌─────────────────────────┐
                  │       services/         │
                  │  screener, learner,     │
                  │  notifier               │
                  └───────────┬─────────────┘
                              │
            ┌─────────────────┼─────────────────┐
            ▼                 ▼                 ▼
    ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
    │   adapters/   │ │    domain/    │ │infrastructure/│
    │  kis_client,  │ │  indicators,  │ │  repository,  │
    │  notifiers    │ │  calculators  │ │  database     │
    └───────────────┘ └───────────────┘ └───────┬───────┘
                                                │
                                                ▼
                                        ┌───────────────┐
                                        │    config/    │
                                        │   settings,   │
                                        │   constants   │
                                        └───────────────┘
```

---

## 6.6 주요 설정 파일

### 6.6.1 .env.example

```env
# 한국투자증권 API
KIS_APP_KEY=your_app_key
KIS_APP_SECRET=your_app_secret
KIS_ACCOUNT_NO=your_account_number
KIS_BASE_URL=https://openapi.koreainvestment.com:9443

# Discord
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxx/yyy

# Kakao (선택)
KAKAO_REST_API_KEY=
KAKAO_ACCESS_TOKEN=

# Gemini API (추후 AI 분석용)
GEMINI_API_KEY=your_gemini_key

# Database
DB_PATH=./data/screener.db

# Logging
LOG_LEVEL=INFO
LOG_PATH=./logs/screener.log

# Screening Config
MIN_TRADING_VALUE=300  # 억원
SCREENING_TIME_1=12:30
SCREENING_TIME_2=15:00
LEARNING_TIME=16:00

# Rate Limit (안정성 우선)
API_CALL_INTERVAL=0.25  # 초당 4회
```

### 6.6.2 requirements.txt

```
# Core
python-dotenv==1.0.0
requests==2.31.0

# Scheduling
APScheduler==3.10.4

# Database
# sqlite3 is built-in

# Dashboard
streamlit==1.29.0
plotly==5.18.0
pandas==2.1.4

# Data Processing (선택)
numpy==1.26.2

# Testing
pytest==7.4.3
pytest-cov==4.1.0

# Development
black==23.12.1
isort==5.13.2
mypy==1.7.1
```

---

## 6.7 배포 구성

### 6.7.1 systemd 서비스 파일 (screener.service)

```ini
[Unit]
Description=Closing Trade Screener
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/closing-trade-screener
ExecStart=/home/ubuntu/closing-trade-screener/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 6.7.2 Streamlit 서비스 파일 (dashboard.service)

```ini
[Unit]
Description=Screener Dashboard
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/closing-trade-screener
ExecStart=/home/ubuntu/closing-trade-screener/venv/bin/streamlit run dashboard/app.py --server.port 8501
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

---

## 6.8 문서 이력

| 버전 | 날짜 | 변경 내용 | 작성자 |
|------|------|----------|--------|
| 1.0 | 2025-01-06 | 초안 작성 | Architect AI |

---

**이전 문서:** [05_API_Spec.md](./05_API_Spec.md)  
**다음 문서:** [07_Risk_Analysis.md](./07_Risk_Analysis.md)
