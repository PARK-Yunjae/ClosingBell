# 🔔 ClosingBell v6.0

**종가매매 TOP5 20일 추적 + 유목민 공부법**

> _"차트가 모든 것을 반영한다"_ 📈

[![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=flat&logo=streamlit&logoColor=white)](https://closingbell.streamlit.app/)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)

---

## ✨ v6.0 주요 기능

### 📊 종가매매 TOP5 20일 추적
- 매일 장 종료 후 상위 5종목 선정
- D+1 ~ D+20 수익률 자동 추적
- 누적 수익률 & 승률 분석

### 📚 유목민 공부법
- 상한가/거래량천만 종목 자동 수집
- 네이버 뉴스 + Gemini AI 요약
- 기업 정보 자동 수집 (시총, PER, 섹터 등)

### 🎯 스코어링 시스템 (100점 만점)

| 지표 | 배점 | 최적 구간 |
|------|------|----------|
| CCI | 25점 | 170~190 |
| CCI 기울기 | 20점 | 양수 |
| MA20 기울기 | 20점 | 양수 |
| 연속양봉 | 15점 | 2일 |
| 등락률 | 10점 | 2~5% |
| 캔들 품질 | 10점 | 실체 비율 |

---

## 🚀 빠른 시작

### 1. 설치
```bash
git clone https://github.com/your-repo/closingbell.git
cd closingbell
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

### 2. 환경 설정
```bash
cp .env.example .env
# .env 파일에 API 키 설정
```

### 3. 초기 데이터 백필
```bash
python main.py --backfill 20
```

### 4. 실행
```bash
# 스케줄러 모드 (자동 실행)
python main.py

# 즉시 실행
python main.py --run

# 대시보드
streamlit run dashboard/app.py
```

---

## 📦 명령어

```bash
# 기본 실행
python main.py              # 스케줄러 모드
python main.py --run        # 즉시 실행
python main.py --run-all    # 모든 서비스 순차 실행

# 백필
python main.py --backfill 20        # 과거 20일 데이터
python main.py --backfill 60 --top5-only  # TOP5만

# v6.0 신규
python main.py --run-nomad          # 유목민 수집
python main.py --run-news           # 뉴스 수집
python main.py --run-company-info   # 기업정보 수집

# 대시보드
streamlit run dashboard/app.py
```

---

## 📁 프로젝트 구조

```
ClosingBell/
├── main.py                 # 메인 실행
├── dashboard/              # Streamlit 대시보드
│   ├── app.py              # 메인 페이지
│   └── pages/
│       ├── 1_종가매매_TOP5.py
│       └── 2_유목민_공부법.py
│
├── src/
│   ├── adapters/           # 외부 연동 (KIS, Discord)
│   ├── config/             # 설정
│   ├── domain/             # 도메인 모델
│   │   ├── models.py
│   │   ├── indicators.py
│   │   └── score_calculator.py
│   ├── infrastructure/     # DB, 스케줄러
│   │   ├── database.py
│   │   ├── repository.py
│   │   └── scheduler.py
│   └── services/           # 비즈니스 로직
│       ├── screener_service.py
│       ├── news_service.py
│       ├── company_service.py
│       ├── nomad_collector.py
│       └── backfill/
│
├── data/
│   └── screener.db         # SQLite DB
│
└── tests/                  # 테스트
```

---

## ⚙️ 환경 변수

```env
# KIS API (필수)
KIS_APP_KEY=your_app_key
KIS_APP_SECRET=your_app_secret
KIS_ACCOUNT_NO=your_account_no

# Discord (선택)
DISCORD_WEBHOOK_URL=your_webhook_url

# Gemini API (뉴스 요약용)
GEMINI_API_KEY=your_gemini_key

# Naver API (뉴스 검색용)
NAVER_CLIENT_ID=your_client_id
NAVER_CLIENT_SECRET=your_client_secret
```

---

## 📊 대시보드

**🔗 Live Demo:** https://closingbell.streamlit.app/

### 메인 페이지
- 전체 승률 게이지
- 누적 수익률 차트
- 최근 결과 테이블

### TOP5 20일 추적
- 일자별 TOP5 목록
- 종목별 20일 수익률 차트
- D+1 갭률 통계

### 유목민 공부법
- 상한가/거래량천만 종목 목록
- 관련 뉴스 + AI 요약
- 기업 정보 (시총, PER, 섹터)

---

## 🔄 버전 히스토리

### v6.0 (현재)
- TOP5 20일 추적 시스템
- 유목민 공부법 (뉴스/기업정보)
- 멀티페이지 대시보드

### v5.4
- 백테스트 기반 최적화
- 글로벌 지표 필터 (나스닥/환율)

### v5.3
- 점수제 도입 (100점 만점)
- CCI 중심 전략

---

## 📝 라이선스

MIT License

---

_Made with ❤️ for Korean Stock Market_
