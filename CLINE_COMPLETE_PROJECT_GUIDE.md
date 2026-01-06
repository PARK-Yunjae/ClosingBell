# ClosingBell 프로젝트 완성 가이드

이 문서는 종가매매 스크리너 프로젝트를 **처음부터 끝까지** 완성하는 Cline 프롬프트입니다.
순서대로 진행하세요.

---

## 📋 현재 상태 체크리스트

Phase 1을 진행했다면 아래 파일들이 있어야 합니다:
- [x] main.py
- [x] requirements.txt  
- [x] src/adapters/kis_client.py
- [x] src/adapters/discord_notifier.py
- [x] src/config/settings.py, constants.py
- [x] src/domain/models.py, indicators.py, score_calculator.py
- [x] src/infrastructure/database.py, repository.py, scheduler.py
- [x] src/services/screener_service.py

없다면 Phase 1부터 시작하세요.

---

# 🔧 Phase 1 보완 - 누락 파일 및 버그 수정

## 1-1. 거래대금 조회 버그 수정 (중요!)

```
거래대금 300억 이상 종목이 16개밖에 안 나오는 문제가 있어.
한국투자증권 HTS에서는 200개 이상인데 API가 30개만 반환하는 것 같아.

kis_client.py의 get_top_trading_value_stocks를 수정해줘:

1. KOSPI와 KOSDAQ을 별도로 호출해서 합치기
   - KOSPI: FID_COND_MRKT_DIV_CODE = "1"
   - KOSDAQ: FID_COND_MRKT_DIV_CODE = "2"

2. 각 시장에서 100개씩 조회 (총 200개)

3. 중복 제거 후 거래대금 순 정렬

4. 디버깅용 로그 추가:
   - API 응답 개수
   - 첫 번째 종목의 거래대금 원본값

수정 후 테스트: python main.py --run-test
```

## 1-2. 유틸리티 스크립트 생성

```
scripts/ 폴더를 만들고 유틸리티 스크립트들을 생성해줘.

1. scripts/check_stock_score.py - 특정 종목 점수 조회
   사용법: python scripts/check_stock_score.py 006800
   출력:
   - 종목명, 현재가, 등락률, 거래대금
   - 5가지 지표별 점수 (상세히)
   - CCI, MA20 원시값
   - 전체 종목 중 순위 (오늘 스크리닝 기준)

2. scripts/manual_screening.py - 수동 스크리닝 실행
   사용법: python scripts/manual_screening.py
   - main.py --run과 유사하지만 더 상세한 출력
   - 전체 종목 점수 리스트 출력 옵션

3. scripts/backup_db.py - DB 백업
   사용법: python scripts/backup_db.py
   - data/backup/ 폴더에 타임스탬프 붙여서 백업
   - 최근 7일 백업만 유지 (오래된 것 자동 삭제)
```

## 1-3. 설정 파일 생성

```
프로젝트 루트에 설정 파일들을 생성해줘.

1. .env.example - 환경 변수 예시 (실제 값 없이)
   KIS_APP_KEY=your_app_key_here
   KIS_APP_SECRET=your_app_secret_here
   KIS_ACCOUNT_NO=your_account_number
   DISCORD_WEBHOOK_URL=your_webhook_url
   # ... 기타 설정

2. .gitignore - Git 제외 파일
   .env
   __pycache__/
   *.pyc
   data/*.db
   data/backup/
   logs/
   .venv/
   # ... 기타

3. pyproject.toml - 프로젝트 메타데이터
   [project]
   name = "closing-bell"
   version = "1.0.0"
   # ... 기타
```

## 1-4. 테스트 기본 구조

```
tests/ 폴더 기본 구조를 만들어줘.

tests/
├── __init__.py
├── conftest.py              # pytest 설정 및 공통 fixture
├── unit/
│   ├── __init__.py
│   ├── test_indicators.py   # CCI, MA20 계산 테스트
│   ├── test_score_calculator.py  # 점수 산출 테스트
│   └── test_models.py       # 데이터 모델 테스트
├── integration/
│   ├── __init__.py
│   └── test_kis_client.py   # API 연동 테스트 (mock)
└── fixtures/
    └── sample_daily_prices.json  # 테스트용 더미 데이터

각 테스트 파일에 기본 테스트 케이스 2~3개씩 작성해줘.
pytest로 실행 가능하게.
```

---

# 🧠 Phase 2 - 학습 시스템 (Learner)

## 2-1. 가중치 최적화 로직

```
src/domain/weight_optimizer.py를 생성해줘.
docs/02_User_Stories.md의 US-12, US-13을 참고해.

기능:
1. analyze_correlation(screening_data, next_day_results)
   - 각 지표 점수와 익일 시초가 상승률의 상관관계 분석
   - Pearson 상관계수 계산
   - 결과: {indicator_name: correlation_coefficient}

2. calculate_optimal_weights(correlations, current_weights)
   - 상관관계 높은 지표는 가중치 증가
   - 상관관계 낮은 지표는 가중치 감소
   - 1회 조정폭: ±0.2 이내
   - 가중치 범위: 0.5 ~ 5.0

3. validate_weights(weights)
   - 가중치 범위 검증
   - 극단값 방지

테스트 케이스도 함께 작성: tests/unit/test_weight_optimizer.py
```

## 2-2. Learner Service

```
src/services/learner_service.py를 생성해줘.

클래스: LearnerService

메서드:
1. collect_next_day_results()
   - 전일 스크리닝 종목의 익일 결과 수집
   - next_day_results 테이블에 저장
   - 필드: open_price, close_price, high_price, low_price,
          volume, trading_value, gap_rate, volatility

2. analyze_performance(days=30)
   - 최근 N일간의 스크리닝 성과 분석
   - 지표별 상관관계 계산
   - 승률, 평균 수익률 등 통계

3. optimize_weights()
   - 30일 이상 데이터 있을 때만 실행
   - weight_optimizer 호출
   - 새 가중치 저장 (weight_config 테이블)
   - 변경 이력 저장 (weight_history 테이블)

4. run_daily_learning()
   - 16:30에 실행될 일일 학습 프로세스
   - collect_next_day_results() 호출
   - 30일 이상이면 optimize_weights() 호출

테스트: tests/integration/test_learner_service.py
```

## 2-3. 스케줄러 업데이트

```
src/infrastructure/scheduler.py를 수정해줘.

추가할 스케줄:
- 16:30: LearnerService.run_daily_learning()

main.py에도 반영:
- --learn 옵션 추가 (수동 학습 실행)

수정 후 테스트:
python main.py --learn
```

## 2-4. 알림 서비스 통합

```
src/services/notifier_service.py를 생성해줘.

역할: 여러 알림 채널 통합 관리

클래스: NotifierService

메서드:
1. send_screening_result(result, channels=['discord'])
   - 채널별로 알림 발송
   - 실패 시 다른 채널로 폴백

2. send_learning_report(report)
   - 일일 학습 결과 리포트 발송
   - 가중치 변경 내역 포함

3. send_error_alert(error, context)
   - 에러 발생 시 즉시 알림

4. get_available_channels()
   - 활성화된 알림 채널 목록

추후 카카오 알림 추가 시 확장 가능한 구조로.
```

---

# 📊 Phase 3 - 대시보드 (Streamlit)

## 3-1. 대시보드 기본 구조

```
dashboard/ 폴더와 Streamlit 앱을 생성해줘.

구조:
dashboard/
├── __init__.py
├── app.py                    # 메인 앱 (멀티페이지 설정)
├── pages/
│   ├── 01_📊_Overview.py     # 개요/요약
│   ├── 02_🔍_Screening.py    # 스크리닝 결과
│   ├── 03_📈_Analysis.py     # 분석/통계
│   └── 04_📝_Journal.py      # 매매일지
└── components/
    ├── __init__.py
    ├── charts.py             # 차트 컴포넌트
    └── tables.py             # 테이블 컴포넌트

requirements.txt에 추가:
streamlit>=1.28.0
plotly>=5.18.0
```

## 3-2. Overview 페이지

```
dashboard/pages/01_📊_Overview.py를 구현해줘.

내용:
1. 오늘의 TOP 3 카드
   - 종목명, 현재가, 등락률, 총점
   - 클릭 시 상세 정보

2. 최근 7일 스크리닝 요약
   - 일별 TOP 1 종목
   - 익일 성과 (시초가 상승률)

3. 시스템 상태
   - 마지막 스크리닝 시간
   - 다음 스크리닝 예정
   - DB 상태

4. 가중치 현황
   - 현재 적용 중인 가중치
   - 최근 변경 이력
```

## 3-3. Screening 페이지

```
dashboard/pages/02_🔍_Screening.py를 구현해줘.

내용:
1. 날짜 선택기
   - 특정 날짜의 스크리닝 결과 조회

2. 전체 종목 테이블
   - 순위, 종목명, 코드, 현재가, 등락률
   - 5가지 지표 점수, 총점
   - 정렬/필터링 기능

3. 종목 상세 모달
   - 선택한 종목의 상세 점수
   - 일봉 차트 (최근 30일)
   - CCI, MA20 차트

4. 수동 스크리닝 버튼
   - 클릭 시 즉시 스크리닝 실행
   - 결과 실시간 표시
```

## 3-4. Analysis 페이지

```
dashboard/pages/03_📈_Analysis.py를 구현해줘.

내용:
1. 성과 분석 (30일)
   - 승률 (익일 시초가 상승 비율)
   - 평균 수익률
   - 최대 수익/손실

2. 지표별 상관관계 차트
   - 각 지표와 익일 수익률의 상관관계
   - 히트맵 또는 바차트

3. 가중치 변화 추이
   - 시간에 따른 가중치 변화 라인 차트
   - 변경 사유 표시

4. 종목별 통계
   - 자주 선정되는 종목
   - 종목별 평균 성과
```

## 3-5. Journal 페이지

```
dashboard/pages/04_📝_Journal.py를 구현해줘.

내용:
1. 매매일지 입력 폼
   - 종목 선택 (스크리닝 결과에서)
   - 매수/매도 선택
   - 가격, 수량, 메모
   - 저장 버튼

2. 매매 내역 테이블
   - 날짜, 종목, 매수/매도, 가격, 수량, 손익
   - 필터링 (기간, 종목)

3. 손익 요약
   - 총 실현 손익
   - 월별 손익 차트
   - 종목별 손익

4. 현재 보유 현황
   - 보유 종목 리스트
   - 평균 단가, 현재가, 손익률
```

## 3-6. 차트 컴포넌트

```
dashboard/components/charts.py를 구현해줘.

함수들:
1. render_candlestick_chart(daily_prices, indicators=None)
   - Plotly 캔들스틱 차트
   - CCI, MA20 오버레이 옵션

2. render_score_radar_chart(score_detail)
   - 5가지 지표 점수 레이더 차트

3. render_correlation_heatmap(correlations)
   - 상관관계 히트맵

4. render_performance_line_chart(performance_data)
   - 누적 수익률 라인 차트

5. render_weight_history_chart(weight_history)
   - 가중치 변화 추이
```

## 3-7. 대시보드 실행 설정

```
대시보드 실행을 위한 설정을 추가해줘.

1. main.py에 --dashboard 옵션 추가
   python main.py --dashboard
   → streamlit run dashboard/app.py 실행

2. 또는 별도 실행 스크립트
   scripts/run_dashboard.py
   또는
   scripts/run_dashboard.bat (Windows)
   scripts/run_dashboard.sh (Linux/Mac)

3. README.md 업데이트
   대시보드 실행 방법 추가
```

---

# 📱 Phase 4 - 추가 기능 (선택)

## 4-1. 카카오톡 알림 (선택)

```
src/adapters/kakao_notifier.py를 생성해줘.

카카오 REST API를 사용한 알림 발송:
1. OAuth 토큰 관리
2. 나에게 메시지 보내기 API
3. 스크리닝 결과 포맷팅

.env에 추가:
KAKAO_REST_API_KEY=
KAKAO_REDIRECT_URI=
KAKAO_ACCESS_TOKEN=
KAKAO_REFRESH_TOKEN=

설정에서 활성화/비활성화 가능하게.
```

## 4-2. 텔레그램 알림 (선택)

```
src/adapters/telegram_notifier.py를 생성해줘.

Telegram Bot API 사용:
1. 봇 토큰으로 메시지 발송
2. 마크다운 포맷 지원
3. 이미지 첨부 (차트)

.env에 추가:
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

## 4-3. 백테스트 기능

```
src/services/backtest_service.py를 생성해줘.

과거 데이터로 전략 검증:
1. load_historical_data(start_date, end_date)
2. run_backtest(strategy_params)
3. calculate_metrics() - 샤프비율, MDD 등
4. generate_report()

별도 스크립트: scripts/run_backtest.py
대시보드 페이지: dashboard/pages/05_🧪_Backtest.py
```

---

# ✅ 최종 체크리스트

## 전체 파일 구조 (완성 시)

```
ClosingBell/
├── main.py
├── requirements.txt
├── pyproject.toml
├── .env
├── .env.example
├── .gitignore
├── README.md
│
├── src/
│   ├── __init__.py
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── kis_client.py          ✅ Phase 1
│   │   ├── discord_notifier.py    ✅ Phase 1
│   │   ├── kakao_notifier.py      ⬜ Phase 4
│   │   └── telegram_notifier.py   ⬜ Phase 4
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── screener_service.py    ✅ Phase 1
│   │   ├── learner_service.py     ⬜ Phase 2
│   │   ├── notifier_service.py    ⬜ Phase 2
│   │   └── backtest_service.py    ⬜ Phase 4
│   │
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── models.py              ✅ Phase 1
│   │   ├── indicators.py          ✅ Phase 1
│   │   ├── score_calculator.py    ✅ Phase 1
│   │   └── weight_optimizer.py    ⬜ Phase 2
│   │
│   ├── infrastructure/
│   │   ├── __init__.py
│   │   ├── database.py            ✅ Phase 1
│   │   ├── repository.py          ✅ Phase 1
│   │   └── scheduler.py           ✅ Phase 1 (Phase 2 업데이트)
│   │
│   └── config/
│       ├── __init__.py
│       ├── settings.py            ✅ Phase 1
│       └── constants.py           ✅ Phase 1
│
├── dashboard/                      ⬜ Phase 3
│   ├── __init__.py
│   ├── app.py
│   ├── pages/
│   │   ├── 01_📊_Overview.py
│   │   ├── 02_🔍_Screening.py
│   │   ├── 03_📈_Analysis.py
│   │   ├── 04_📝_Journal.py
│   │   └── 05_🧪_Backtest.py      ⬜ Phase 4
│   └── components/
│       ├── __init__.py
│       ├── charts.py
│       └── tables.py
│
├── scripts/                        ⬜ Phase 1 보완
│   ├── check_stock_score.py
│   ├── manual_screening.py
│   ├── backup_db.py
│   ├── run_dashboard.py
│   └── run_backtest.py            ⬜ Phase 4
│
├── tests/                          ⬜ Phase 1 보완
│   ├── __init__.py
│   ├── conftest.py
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_indicators.py
│   │   ├── test_score_calculator.py
│   │   ├── test_weight_optimizer.py
│   │   └── test_models.py
│   ├── integration/
│   │   ├── __init__.py
│   │   ├── test_kis_client.py
│   │   ├── test_screener_service.py
│   │   └── test_learner_service.py
│   └── fixtures/
│       └── sample_daily_prices.json
│
├── data/
│   ├── screener.db
│   └── backup/
│
└── logs/
    └── screener.log
```

---

# 🚀 실행 순서 요약

```
# Phase 1 보완
1. 거래대금 조회 버그 수정
2. scripts/ 폴더 생성
3. 설정 파일 생성
4. tests/ 기본 구조

# Phase 2
5. weight_optimizer.py
6. learner_service.py
7. notifier_service.py
8. scheduler.py 업데이트

# Phase 3
9. dashboard/ 폴더 전체
10. 각 페이지 구현
11. components 구현

# Phase 4 (선택)
12. 추가 알림 채널
13. 백테스트 기능
```

---

# 💡 팁

1. **한 번에 하나씩**: 각 프롬프트를 순서대로 실행
2. **테스트 확인**: 각 단계 후 테스트 실행
3. **커밋**: 각 Phase 완료 후 Git 커밋
4. **문서 참조**: 막히면 docs/ 폴더의 설계 문서 참조 요청

```
막히면 이렇게 요청:
"docs/02_User_Stories.md의 US-XX를 다시 읽고 구현해줘"
"docs/06_Architecture.md의 6.X절을 참고해서 수정해줘"
```
