# 🔔 ClosingBell v6.2

> 종가매매 TOP5 자동 스크리닝 시스템

## 📊 주요 기능

### 종가매매 TOP5
- 100점 만점 점수제로 TOP5 선정
- **CCI 하드 필터**: CCI 250+ 종목 자동 제외
- **대기업 표시**: 시총 1조 이상 종목 🏢 표시 (점수 가산 없음)
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

### CCI 하드 필터
- CCI 250 이상 → TOP5 제외

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

## 📝 v6.2 변경사항

- CCI 하드 필터 (250+)
- 대기업 표시 (점수 가산 없음)
- 숫자 표현 소수점 1자리 통일
- OHLCV 기반 캔들차트
- Gemini 2.0 Flash AI 분석

---

*최종 수정: 2026-01-20*
