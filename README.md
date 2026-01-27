# ClosingBell v6.5 STABLE

종가매매 자동 스크리닝 시스템 - AI 분석 + DART 기업정보 통합

## 주요 기능

### 📊 스크리닝
- **12:30 프리뷰**: 장중 TOP5 미리보기 (DB 저장 안 함)
- **15:00 메인**: 종가매매 TOP5 확정 (DB 저장)
- CCI, 이격도, 거래량, 연속상승 등 기술적 지표 분석
- 섹터 주도주 표시

### 🤖 AI 분석 (Gemini)
- TOP5 종목 배치 분석 (5종목 1회 호출)
- 매수/관망/매도 추천
- 위험도 평가 (낮음/보통/높음)
- 투자 포인트 요약

### 📋 DART 연동
- 기업개황 (CEO, 업종 등)
- 재무정보 (매출, 영업이익, 순이익)
- 위험공시 탐지 (정리매매, 상장폐지, 횡령 등)
- PER/PBR/ROE 계산

### 📱 Discord 알림
- TOP5 웹훅 발송
- 주도섹터 표시
- AI 분석 결과 포함
- 등급별 매도전략 가이드

## 설치

### 1. 환경 설정
```bash
# 가상환경 생성
python -m venv venv

# 활성화 (Windows)
venv\Scripts\activate

# 패키지 설치
pip install -r requirements.txt
```

### 2. API 키 설정
```bash
copy .env.example .env
notepad .env  # API 키 입력
```

**필수 API 키:**
- `KIS_APP_KEY`, `KIS_APP_SECRET`: 한국투자증권 API
- `KIS_HTS_ID`: HTS 로그인 ID
- `DISCORD_WEBHOOK_URL`: Discord 웹훅

**선택 API 키:**
- `GEMINI_API_KEY`: AI 분석용
- `DART_API_KEY`: 기업정보용

### 3. DB 초기화
```bash
python -c "from src.infrastructure.database import Database; db = Database(); db.init_database(); print('완료')"
```

## 실행 방법

### bat 파일 사용 (권장)
```bash
run_scheduler.bat    # 스케줄러 (자동 실행)
run_all.bat          # 즉시 1회 실행
run_test.bat         # 스모크 테스트
run_dashboard.bat    # 대시보드 (Streamlit)
run_backfill.bat     # 과거 데이터 백필
```

### 직접 실행
```bash
# 스케줄러 (자동 실행)
python main.py --run-scheduler

# 프리뷰 스크리닝
python -c "from src.services.screener_service import run_preview_screening; run_preview_screening()"

# 메인 스크리닝
python -c "from src.services.screener_service import run_main_screening; run_main_screening()"

# 대시보드
streamlit run dashboard/app.py
```

## 스케줄 (평일)

| 시간 | 작업 | 설명 |
|------|------|------|
| 12:30 | 프리뷰 스크리닝 | 장중 TOP5 미리보기 |
| 15:00 | 메인 스크리닝 | 종가매매 TOP5 확정 |
| 16:35 | KIS OHLCV 수집 | 당일 시세 저장 |
| 16:40 | FDR 데이터 갱신 | 백테스팅용 |
| 16:45 | 글로벌 데이터 | 나스닥/환율 등 |
| 17:00 | 결과 수집 | 익일 결과 추적 |
| 17:10 | 일일 학습 | 가중치 최적화 |
| 17:20 | 유목민 수집 | 거래량 급등주 |
| 17:30 | 뉴스 수집 | 관련 뉴스 |
| 17:40 | 기업정보 | DART 크롤링 |
| 17:50 | AI 분석 | TOP5 AI 분석 |
| 18:00 | Git 커밋 | 자동 백업 |
| 18:05 | 자동 종료 | 안전 종료 |

## 웹훅 메시지 예시

```
🔔 종가매매 TOP5
📈 오늘의 주도섹터
🔥반도체(+5.2%) > 🔥2차전지(+3.1%)

🔥1위🔥 삼성전자 (005930)
94.1점 🏆S | 🔥 반도체 (#1)
현재가: 55,000원 (+3.5%)
시총: 3.2조 | 거래대금: 1.5조
━━━━━━━━━━
📊 핵심지표
CCI: 165 | 이격도: 5.2%
거래량: 1.5배 | 연속: 2일
🎁 보너스: CCI↑ MA20↑ 캔들✓
💰 PER 12.3 | PBR 1.45
🤖 AI 분석
추천: 🟢 매수 | 위험도: ✅ 낮음
💡 반도체 업황 개선, 실적 호조
━━━━━━━━━━
📈 매도전략
시초가 30% / 목표 +4.0%
손절 -3.0%
```

## 디렉토리 구조

```
ClosingBell/
├── main.py              # 진입점
├── requirements.txt     # 패키지
├── .env.example         # 환경변수 템플릿
├── run_*.bat            # 실행 스크립트
│
├── src/
│   ├── adapters/        # 외부 API 어댑터
│   ├── config/          # 설정
│   ├── domain/          # 도메인 모델
│   ├── infrastructure/  # DB, 스케줄러
│   └── services/        # 비즈니스 로직
│
├── dashboard/           # Streamlit 대시보드
├── scripts/             # 유틸리티 스크립트
├── data/                # DB, 캐시
└── logs/                # 로그 파일
```

## 문제 해결

### KIS API 토큰 오류
```
토큰 발급 실패: 403 Forbidden
```
→ `.env` 파일에서 API 키 확인 (따옴표 없이 입력)

### DART "조회된 데이터 없음"
```
DART: 조회된 데이터 없음 (status=013)
```
→ 정상입니다. 해당 종목에 관련 공시가 없는 경우

### AI 분석 실패
```
AI 분석 실패 (계속 진행)
```
→ GEMINI_API_KEY 확인, 모델명 확인 (`GEMINI_MODEL=gemini-2.0-flash`)

## 변경 이력

### v6.5 STABLE (2026-01-27)
- ✅ AI `_client` 초기화 버그 수정
- ✅ DART 013 로그 레벨 변경 (WARNING → DEBUG)
- ✅ EnrichedStock 웹훅 전달 버그 수정
- ✅ 시총/거래대금 표시 개선
- ✅ 순위 이모지 추가 (🔥1위🔥, ⭐2위 등)
- ✅ bat 실행 스크립트 추가
- ✅ 안전 종료 (실행 중 작업 대기)

### v6.4
- DART 기업정보 연동
- 위험공시 탐지
- PER/PBR/ROE 계산

### v6.3
- AI 배치 분석 (5종목 1회)
- 섹터 주도주 표시
- CCI 과열 필터

## 라이선스

MIT License
