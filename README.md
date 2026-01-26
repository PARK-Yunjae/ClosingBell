# 🔔 ClosingBell v6.5

> 종가매매 TOP5 자동 스크리닝 + 유목민 공부법 시스템

## 📌 개요

한국 주식시장 종가매매 자동화 시스템입니다.
- 매일 15:00 장 마감 전 TOP5 종목 선정
- D+1 ~ D+20 수익률 자동 추적
- 유목민 공부법 (상한가/거래량천만) 병행 분석
- Streamlit 대시보드 제공

## ✨ v6.5 주요 기능

### 종가매매 TOP5
- TV200 유니버스 기반 스크리닝
- 9.5년 백테스팅 최적화 점수제
- CCI 160~180, 등락률 4~6%, 이격도 2~8% 최적 구간
- Gemini AI 종목 분석

### 유목민 공부법
- 상한가/거래량천만 종목 자동 수집
- 네이버 금융 기업정보 크롤링
- 뉴스 수집 + AI 요약
- 최근 30일 등장 횟수 추적

### 대시보드
- 실시간 TOP5 현황
- 유목민 등장 횟수 랭킹 (승률 실시간 계산)
- 종목 검색 기능
- D+N 수익률 차트

## 🚀 설치

```bash
# 1. 가상환경 생성
python -m venv venv
venv\Scripts\activate

# 2. 의존성 설치
pip install -r requirements.txt

# 3. 환경변수 설정
copy .env.example .env
# .env 파일에 API 키 입력
```

## ⚙️ 환경변수 (.env)

```env
# 한국투자증권 API
KIS_APP_KEY=your_app_key
KIS_APP_SECRET=your_app_secret
KIS_ACCOUNT_NO=your_account_no

# Gemini API (AI 분석용)
GEMINI_API_KEY=your_gemini_key

# Discord Webhook (알림용, 선택)
DISCORD_WEBHOOK_URL=your_webhook_url
```

## 📂 프로젝트 구조

```
ClosingBell/
├── main.py                 # 메인 실행 파일
├── dashboard/              # Streamlit 대시보드
│   ├── app.py             # 메인 페이지
│   └── pages/             # 서브 페이지
├── src/
│   ├── domain/            # 도메인 로직
│   │   ├── screener.py    # 스크리닝 엔진
│   │   └── score_calculator.py  # 점수 계산
│   ├── services/          # 서비스 레이어
│   │   ├── ai_service.py  # Gemini AI 분석
│   │   └── data_updater.py # OHLCV 수집
│   └── infrastructure/    # 인프라
│       ├── scheduler.py   # 스케줄러
│       └── repository.py  # DB 접근
├── scripts/
│   └── collect_kis_ohlcv.py  # KIS OHLCV 수집
├── data/
│   └── screener.db        # SQLite DB
└── migrations/            # DB 스키마
```

## 🕐 자동 스케줄

| 시간 | 작업 |
|------|------|
| 12:30 | 프리뷰 스크리닝 |
| 15:00 | 메인 스크리닝 (TOP5 저장) |
| 16:00 | KIS OHLCV 수집 |
| 16:05 | FDR OHLCV 수집 |
| 16:10 | 글로벌 데이터 |
| 16:15 | D+N 결과 수집 |
| 16:20 | 일일 학습 |
| 16:25 | 유목민 수집 |
| 16:30 | 뉴스 수집 |
| 16:35 | 기업정보 수집 |
| 16:40 | 유목민 AI 분석 |
| 16:45 | TOP5 AI 분석 |
| 17:00 | Git 자동 커밋 |
| 17:05 | 자동 종료 |

## 💻 실행

### 스케줄러 모드 (권장)
```bash
python main.py
```

### 즉시 실행
```bash
python main.py --run
```

### 백필 (과거 데이터)
```bash
python main.py --backfill 20
```

### 대시보드
```bash
streamlit run dashboard/app.py
```

## 📊 점수 시스템 (100점 만점)

### 기본 점수 (90점)
| 지표 | 최적 구간 | 점수 |
|------|----------|------|
| CCI | 160~180 | 15점 |
| 등락률 | 4~6% | 15점 |
| 이격도 | 2~8% | 15점 |
| 연속양봉 | 2~3일 | 10점 |
| 거래량비 | 150~300% | 15점 |
| 5일평균대비 | 100~150% | 10점 |
| 20일평균대비 | 120~200% | 10점 |

### 보너스 (10점)
- CCI 상승 추세: +4점
- MA20 위: +3점
- 장중 조정 (고가≠종가): +3점

## 📈 백테스팅 결과 (9.5년)

### 매수 타이밍
| 시점 | 승률 | 평균 수익률 |
|------|------|------------|
| D+1 | 45.3% | +0.37% |
| D+5 | 52.0% | +5.28% |
| D+10 | 52.0% | +5.61% |

### 주가 금액대별 (D+5)
| 금액대 | 승률 | 비고 |
|--------|------|------|
| ~1만원 | 55~58% | ✅ 양호 |
| 1~3만원 | 30% | ❌ 회피 |
| 5만원+ | 70~83% | ⭐ 최적 |

## ⚠️ 주의사항

- **TOP5는 참고용**: 즉시 매수 신호가 아닌 관심 종목 리스트
- **D+1 하락 정상**: 통계적으로 D+5 전후가 더 좋음
- **공부 필수**: 뉴스/차트/섹터 분석 병행 권장

## 📜 라이선스

MIT License

## 🔗 관련 링크

- [Streamlit Cloud 대시보드](https://closingbell.streamlit.app)
