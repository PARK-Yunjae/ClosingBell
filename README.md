# 🔔 ClosingBell v5.2

**종가매매 자동 스크리닝 시스템**

한국투자증권 API를 활용한 종가매매 전략 기반 종목 자동 스크리닝 시스템입니다.
매일 장 마감 전 기술적 분석을 수행하고 TOP5 종목을 추천합니다.

## ✨ v5.2 주요 기능

### 🎯 스크리닝 시스템
- **100점 만점 점수제** - 6개 핵심 지표 기반
- **그리드서치 최적화 가중치** 적용
- **하드 필터**: 거래량비 10x 이상 제외
- **대형주 보너스**: 1000억+ 시총 가산점

### 📊 점수 체계 (100점 만점)
| 지표 | 배점 | 최적 구간 |
|------|------|----------|
| 거래량비 | **25점** | 1.5~3.0배 |
| 등락률 | 20점 | 2~8% |
| 연속양봉 | 15점 | 2~3일 |
| CCI | 15점 | 160~190 |
| 이격도 | 15점 | 2~8% |
| 캔들품질 | 10점 | 윗꼬리 ≤40% |

### 📅 자동 스케줄
| 시간 | 작업 | 설명 |
|------|------|------|
| 12:30 | 프리뷰 스크리닝 | 예상 TOP5 |
| 15:00 | 메인 스크리닝 | 최종 TOP5 |
| 16:30 | 데이터 갱신 | 3000종목 OHLCV |
| 17:00 | 학습 | 익일 결과 수집 |
| **17:30** | **유목민 공부** | AI 기업분석 🆕 |

### 🆕 v5.2 신규 기능
- **유목민 공부법**: TOP5 종목 자동 기업분석
  - 네이버 뉴스 수집
  - Gemini AI 요약
  - Discord 알림
- **계좌 연동**: 잔고/수익률 조회
- **학습 시스템**: 상관관계 기반 가중치 자동 조정

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
python main.py              # 스케줄러
streamlit run dashboard/app.py  # 대시보드
```

## 📁 프로젝트 구조

```
ClosingBell/
├── src/
│   ├── adapters/           # 외부 API
│   │   ├── kis_client.py
│   │   ├── naver_client.py 🆕
│   │   ├── gemini_client.py 🆕
│   │   └── discord_notifier.py
│   ├── services/           # 비즈니스 로직
│   │   ├── screener_service.py
│   │   ├── learner_service.py 🆕
│   │   └── nomad_study.py 🆕
│   ├── domain/             # 도메인 모델
│   ├── infrastructure/     # 인프라
│   └── config/             # 설정
├── dashboard/              # Streamlit
│   └── pages/
│       ├── 05_NomadStudy.py 🆕
│       └── 06_MyInvest.py 🆕
├── data/                   # SQLite DB
└── docs/                   # 문서
```

## 📝 v5.2 변경사항
- 그리드서치 최적 가중치 적용
- 유목민 공부법 자동화
- 계좌 잔고 연동
- 115점 → 100점 정규화
- 학습 시스템 재활성화

---
*ClosingBell - 종가매매 자동화* 🔔
