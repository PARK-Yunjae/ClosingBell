# 🔔 ClosingBell v5.3

**종가매매 + K값 돌파 자동 스크리닝 & 학습 시스템**

한국투자증권 API를 활용한 종목 자동 스크리닝 시스템입니다.
매일 장 마감 전 기술적 분석을 수행하고 TOP5 종목을 추천합니다.
**실제 매매는 하지 않으며**, 알림 발송 + 익일 결과 학습 + 자동 최적화를 수행합니다.

## ✨ v5.3 주요 기능

### 🎯 이중 전략 시스템
| 전략 | 승률 | 평균 수익 | 매수 조건 | 매도 조건 |
|------|------|----------|----------|----------|
| **종가매매** | 60% | +0.6% | 장 마감 전 매수 | 익일 시초가 매도 |
| **K값 돌파** | 76~84% | +6.32% | 시가+레인지×0.3 돌파 | 익일 시초가 매도 |

### 📊 종가매매 점수 체계 (100점 만점)
| 지표 | 배점 | 최적 구간 |
|------|------|----------|
| 거래량비 | **25점** | 1.5~3.0배 |
| 등락률 | 20점 | 2~8% |
| 연속양봉 | 15점 | 2~3일 |
| CCI | 15점 | 160~190 |
| 이격도 | 15점 | 2~8% |
| 캔들품질 | 10점 | 윗꼬리 ≤40% |

### 🚀 K값 변동성 돌파 전략
```
• 돌파가 = 시가 + (전일고가 - 전일저가) × 0.3
• 손절: -2% / 익절: +5%
• 필터: 거래대금 200억+, 볼륨 2배+, 전일 0~10% 상승
```

### 📅 자동 스케줄 (매매 없음!)
| 시간 | 작업 | 설명 |
|------|------|------|
| 12:30 | 프리뷰 스크리닝 | 종가매매 TOP5 + K돌파 TOP3 알림 |
| 15:00 | 메인 스크리닝 | 종가매매 TOP5 + K돌파 TOP3 알림 + **DB 저장** |
| 16:30 | 데이터 갱신 | OHLCV 업데이트 |
| 17:00 | 종가매매 학습 | 익일 결과 수집 + 가중치 자동 조정 |
| **17:10** | **K값 학습** | 익일 결과 수집 + 파라미터 최적화 🆕 |
| 17:30 | 유목민 공부 | AI 기업분석 |
| 17:35 | Git 자동 커밋 | 변경사항 백업 |
| 17:40 | 자동 종료 | 프로그램 종료 |

### 🧠 자동 학습 시스템
```
[종가매매 학습]
├─ 전일 TOP5 익일 결과 수집
├─ CCI ↔ 수익률 상관관계 분석
└─ 가중치 자동 조정

[K값 학습] 🆕
├─ 전일 K시그널 익일 결과 수집
├─ 승률/수익률 분석
└─ 손절/익절 파라미터 자동 조정
```

## 🚀 설치 및 실행

### 1. 환경 설정
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 2. API 설정 (.env)
```env
KIS_APP_KEY="your_app_key"
KIS_APP_SECRET="your_app_secret"
KIS_ACCOUNT_NO="12345678-01"
DISCORD_WEBHOOK_URL="https://discord.com/..."
GEMINI_API_KEY="your_gemini_key"
NaverAPI_Client_ID="your_client_id"
NaverAPI_Client_Secret="your_secret"
```

### 3. 실행
```bash
# 스케줄러 모드 (17:40 자동 종료)
python main.py

# 즉시 스크리닝 (테스트)
python main.py --run-test

# K값 스크리닝만
python main.py --run-k

# 대시보드
streamlit run dashboard/app.py
```

### 4. 작업 스케줄러 등록 (Windows)
```
프로그램: C:\Coding\ClosingBell\run_screener.bat
시작 위치: C:\Coding\ClosingBell
트리거: 매일 08:50
```

## 📁 프로젝트 구조

```
ClosingBell/
├── src/
│   ├── adapters/           # 외부 API
│   │   ├── kis_client.py
│   │   ├── naver_client.py
│   │   ├── gemini_client.py
│   │   └── discord_notifier.py
│   ├── services/           # 비즈니스 로직
│   │   ├── screener_service.py   # 종가매매 스크리닝
│   │   ├── k_screener.py         # K값 스크리닝
│   │   ├── learner_service.py    # 종가매매 학습
│   │   ├── k_learner_service.py  # K값 학습 🆕
│   │   ├── nomad_study.py        # 유목민 공부
│   │   └── data_updater.py       # 데이터 갱신
│   ├── domain/             # 도메인 모델
│   │   ├── k_breakout.py         # K값 전략
│   │   ├── score_calculator.py   # 점수 계산
│   │   └── models.py
│   ├── infrastructure/     # 인프라
│   │   ├── scheduler.py          # 스케줄러
│   │   ├── repository.py         # DB 접근
│   │   └── database.py           # SQLite
│   └── config/             # 설정
├── dashboard/              # Streamlit
├── data/                   # SQLite DB
├── logs/                   # 로그 파일
└── docs/                   # 문서
```

## 📊 DB 테이블 (v5.3)

| 테이블 | 설명 |
|--------|------|
| screenings | 종가매매 스크리닝 기록 |
| screening_items | 종가매매 종목 상세 |
| next_day_results | 종가매매 익일 결과 |
| weight_config | 종가매매 가중치 설정 |
| **k_signals** | K값 돌파 시그널 🆕 |
| **k_signal_results** | K값 익일 결과 🆕 |
| **k_strategy_config** | K값 파라미터 설정 🆕 |
| nomad_studies | 유목민 공부 기록 |

## 📝 버전 히스토리

### v5.3 (현재)
- K값 변동성 돌파 전략 추가
- K값 시그널 DB 저장 + 학습 시스템
- 12:30/15:00 알림에 K돌파 TOP3 포함
- 17:10 K값 학습 스케줄 추가

### v5.2
- 유목민 공부법 자동화
- 계좌 잔고 연동
- 그리드서치 최적 가중치 적용
- 학습 시스템 재활성화

### v5.1
- 100점 만점 정규화
- 소프트 필터 방식 도입
- Discord Embed 포맷 개선

---
*ClosingBell v5.3 - 종가매매 + K값 돌파 자동화* 🔔
