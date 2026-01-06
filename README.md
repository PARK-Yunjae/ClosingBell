# 종가매매 스크리너 (Closing Trade Screener)

> 한국투자증권 API를 활용한 종가매매 후보 종목 자동 스크리닝 시스템

## 📋 프로젝트 개요

매일 장 마감 전 거래대금 300억 이상 종목 중 5가지 기술적 지표(CCI, CCI 기울기, MA20 기울기, 양봉 품질, 상승률)를 분석하여 종가매매 후보 TOP 3를 선정하고 디스코드로 알림을 발송합니다.

### 주요 기능

- 🔍 **자동 스크리닝**: 15:00 종가매매 후보 TOP 3 선정
- 📊 **5가지 지표 분석**: CCI(14), CCI 기울기, MA20 기울기, 양봉 품질, 상승률
- 📱 **실시간 알림**: 디스코드 웹훅 (12:30 프리뷰 + 15:00 본알림)
- 📈 **자동 학습**: 익일 결과 기반 점수 가중치 동적 최적화
- 📝 **매매일지**: 수동 매매 기록 및 성과 분석
- 🖥️ **대시보드**: Streamlit 기반 데이터 시각화

---

## 📁 설계 문서

| # | 문서 | 설명 |
|---|------|------|
| 1 | [PRD v1.0](docs/01_PRD_v1.0.md) | 목표, 범위, 비범위, 성공지표 |
| 2 | [유저 스토리](docs/02_User_Stories.md) | 15개 유저 스토리 + 수용 기준 |
| 3 | [사용자 흐름](docs/03_User_Flows.md) | 5개 핵심 플로우 시퀀스 다이어그램 |
| 4 | [DB 설계](docs/04_Database_Design.md) | ERD + 6개 테이블 정의서 |
| 5 | [API 스펙](docs/05_API_Spec.md) | 외부/내부 API 명세 |
| 6 | [아키텍처](docs/06_Architecture.md) | 시스템 구조 + 폴더 + 모듈 책임 |
| 7 | [리스크 분석](docs/07_Risk_Analysis.md) | 20개 예상 애로사항 + 대응전략 |
| 8 | [테스트 플랜](docs/08_Test_Plan.md) | 테스트 전략 + 릴리즈 체크리스트 |

---

## 🏗️ 기술 스택

- **언어**: Python 3.11+
- **DB**: SQLite 3
- **스케줄링**: APScheduler
- **대시보드**: Streamlit
- **외부 API**: 한국투자증권 REST API, Discord Webhook

---

## 📅 개발 일정

| Phase | 내용 | 기간 |
|-------|------|------|
| Phase 1 | 핵심 기능 (스크리닝 + 알림) | 1주 |
| Phase 2 | 12:30 프리뷰 + 익일 추적 | 3일 |
| Phase 3 | 매매일지 + 대시보드 | 1주 |
| Phase 4 | 카카오톡 + 최적화 | 3일 |

---

## 🔑 필요 API 키

- [x] 한국투자증권 API (APP_KEY, APP_SECRET)
- [x] Discord Webhook URL
- [x] Gemini API (추후 AI 분석용)
- [ ] 카카오 비즈니스 채널 (선택)

> **설계 철학:** 뉴스 수집은 제외. 모든 시장 정보(기대감, 내부자 정보 등)는 결국 차트에 반영된다고 봅니다. 닷컴버블(2000), IMF(1998), 금융위기(2008), 코로나(2020) 등 역사적 사건도 결국 가격과 거래량에 선반영되었습니다.

---

## 🚀 빠른 시작

```bash
# 1. 레포지토리 클론
git clone https://github.com/your/closing-trade-screener.git
cd closing-trade-screener

# 2. 가상환경 생성
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 의존성 설치
pip install -r requirements.txt

# 4. 환경 변수 설정
cp .env.example .env
# .env 파일 편집하여 API 키 입력

# 5. DB 초기화
python scripts/init_db.py

# 6. 스크리너 실행
python main.py

# 7. 대시보드 실행 (별도 터미널)
streamlit run dashboard/app.py
```

---

## 📊 점수 산출 로직

| 지표 | 최적 조건 | 최고점 |
|------|----------|--------|
| CCI(14) 값 | 180 정중앙 근접 | 10점 |
| CCI 기울기 (5일) | 상승세 유지 | 10점 |
| MA20 기울기 (7일) | 상승세 유지 | 10점 |
| 양봉 품질 | 윗꼬리 짧음 + MA 위 안착 | 10점 |
| 당일 상승률 | **5~20% 적정 상승** (과열/부족 시 감점) | 10점 |

**총점 = Σ(지표점수 × 가중치)**, 가중치는 익일 결과 기반 자동 조정 (0.5~5.0)

---

## 📝 라이선스

MIT License

---

## 👤 Author

박윤재

---

**설계 문서 작성일:** 2025-01-06
