# 🔔 ClosingBell v6.3.1

> 종가매매 TOP5 자동 스크리닝 시스템

## v6.3.1 변경사항

### 점수 로직 통일
- **백필 점수 = 실시간 점수** (보너스 포함 100점 만점)
- 기본 90점 (6개 지표 × 15점)
- 보너스 10점 (CCI↑ 4점, MA20↑ 3점, 고가≠종가 3점)

### 실시간 TOP5 우선 저장
- 15시 실시간 스크리닝 결과가 DB에 정확히 저장
- 백필 데이터보다 실시간 데이터 우선

### 거래대금 표시
- 대시보드에 종목별 거래대금 표시
- DB에 trading_value, volume 필드 추가

## 설치

```bash
# 1. 가상환경 생성
python -m venv venv
venv\Scripts\activate

# 2. 의존성 설치
pip install -r requirements.txt

# 3. 환경변수 설정
copy .env.example .env
# .env 파일 편집

# 4. DB 마이그레이션 (최초 1회)
sqlite3 data/screener.db < migrations/v6_schema.sql
sqlite3 data/screener.db < migrations/v6_1_add_company_fields.sql
sqlite3 data/screener.db < migrations/v6_3_add_sector_fields.sql
sqlite3 data/screener.db < migrations/v6_3_1_add_trading_fields.sql
```

## 실행

```bash
# 스크리너 (15시 자동 실행)
python main.py

# 대시보드
streamlit run dashboard/app.py
```

## 점수 체계 (100점 만점)

| 구분 | 지표 | 배점 |
|------|------|------|
| 기본 | CCI | 15점 |
| 기본 | 등락률 | 15점 |
| 기본 | 이격도 | 15점 |
| 기본 | 연속양봉 | 15점 |
| 기본 | 거래량비 | 15점 |
| 기본 | 캔들품질 | 15점 |
| 보너스 | CCI 상승 | 4점 |
| 보너스 | MA20 3일↑ | 3점 |
| 보너스 | 고가≠종가 | 3점 |

## 등급별 매도전략

| 등급 | 점수 | 시초 매도 | 목표가 | 손절가 |
|------|------|----------|--------|--------|
| S | 85+ | 30% | +4% | -3% |
| A | 75-84 | 40% | +3% | -2.5% |
| B | 65-74 | 50% | +2.5% | -2% |
| C | 55-64 | 70% | +2% | -1.5% |
| D | <55 | 전량 | - | -1% |

## 📊 주요 기능

### 종가매매 TOP5
- 100점 만점 점수제로 TOP5 선정
- **소프트 스코어링**: 모든 지표를 점수로 반영 (하드필터 최소화)
- **대기업 표시**: 시총 1조 이상 종목 🏢 표시 (점수 가산 없음)
- **업종 표시**: 종목별 섹터 정보 표시
- D+1 ~ D+20 수익률 추적

### 유목민 공부법
- 상한가/거래량천만 종목 자동 수집
- 네이버 금융 기업정보 크롤링
- Gemini 2.0 Flash AI 분석

## 🚀 설치

```bash
# 의존성 설치
pip install -r requirements.txt

# Gemini API 키 설정 (.env)
GEMINI_API_KEY=your_api_key_here

# DB 초기화 (최초 1회)
python main.py --init-db

# 과거 데이터 백필 (선택)
python main.py --backfill 20
```

## 📱 사용법

```bash
# 스케줄러 모드 (15:00 자동 실행)
python main.py

# 즉시 실행
python main.py --run

# 대시보드
streamlit run dashboard/app.py
```

## 📋 점수 체계

| 항목 | 배점 |
|------|------|
| 기본 점수 | 90점 |
| 보너스 | 10점 |
| 글로벌 조정 | ±5점 |
| **합계** | **100점** |

### 등급별 전략

| 등급 | 점수 | 시초가 매도 |
|------|------|-----------|
| S | 85+ | 30% |
| A | 75~84 | 40% |
| B | 65~74 | 50% |
| C | 55~64 | 70% |
| D | <55 | 100% |

## 📂 폴더 구조

```
ClosingBell/
├── src/
│   ├── services/
│   │   ├── screener_service.py  # 스크리닝
│   │   └── company_service.py   # 기업정보 크롤링
│   ├── domain/
│   │   └── score_calculator.py  # 점수 계산
│   └── infrastructure/
│       └── repository.py        # DB 접근
├── dashboard/
│   ├── app.py                   # 메인 대시보드
│   └── pages/
│       ├── 1_종가매매_TOP5.py
│       └── 2_유목민_공부법.py
├── data/
│   └── screener.db              # SQLite DB
└── docs/
    └── SCORE_SYSTEM_v6.2.md     # 점수제 문서
```

## 📝 v6.2.3 변경사항

- TV200 백필 필터 일치 (거래대금 100억+, 등락률 0.1~30%)
- CCI 하드 필터 제거 (점수제에서 자연 감점)
- 대시보드 업종 표시 추가
- 단순 선형 vs 구간별 점수제 비교 도구

## 📝 v6.2 변경사항

- 대기업 표시 (점수 가산 없음)
- 숫자 표현 소수점 1자리 통일
- OHLCV 기반 캔들차트
- Gemini 2.0 Flash AI 분석

---

*최종 수정: 2026-01-23*
