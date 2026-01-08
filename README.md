# 🔔 종가매매 스크리너 (ClosingBell) v3.0

> 한국투자증권 API를 활용한 종가매매 후보 종목 자동 스크리닝 시스템

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## 📋 프로젝트 소개

**종가매매 스크리너**는 매일 장 마감 전 **거래대금 300억 이상** 종목 중 5가지 기술적 지표를 분석하여 **종가매매 후보 TOP 3**를 선정하고 **Discord**로 알림을 발송하는 시스템입니다.

### 종가매매란?
- 장 마감 직전(15:00 전후)에 매수하여 익일 갭 상승을 노리는 전략
- 장중 변동성을 피하고 안정적인 상승 모멘텀을 가진 종목에 투자
- 핵심: **거래대금**, **CCI 지표**, **이동평균선 기울기**, **양봉 품질** 등 기술적 분석

### 왜 만들었나?
- 매일 수백 개 종목을 수동으로 분석하는 시간 절약
- 감정에 휘둘리지 않는 객관적인 점수 기반 선정
- 익일 결과를 기반으로 가중치를 자동 학습하여 지속적 개선

---

## ✨ 주요 기능

| 기능 | 설명 |
|------|------|
| 🔍 **자동 스크리닝** | 거래대금 300억+ 종목 중 TOP 3 선정 |
| 📊 **5가지 지표 분석** | CCI(14), CCI 기울기(2일), MA20 기울기(3일), 양봉 품질, 상승률 |
| 📱 **실시간 알림** | Discord 알림 (12:30 프리뷰 + 15:00 본알림) |
| 📈 **자동 학습** | 익일 결과 기반 점수 가중치 동적 최적화 |
| 🔄 **백테스팅** | 과거 데이터로 전략 성과 검증 (서비스 모듈 지원) |
| 🖥️ **대시보드** | Streamlit 기반 데이터 시각화 (옵션) |

---

## 📊 점수 산출 로직

| 지표 | 설명 | 최적 조건 | 점수 |
|------|------|----------|------|
| **CCI(14) 값** | 상품 채널 지수 | 180 근접 (과열 전 상승세) | 0~10점 |
| **CCI 기울기** | CCI 2일 변화량 | 상승세 유지 | 0~10점 |
| **MA20 기울기** | 20일 이평선 3일 변화 | 우상향 추세 | 0~10점 |
| **양봉 품질** | 윗꼬리 비율 + MA 위치 | 윗꼬리 짧고 MA 위 안착 | 0~10점 |
| **당일 상승률** | 전일 대비 변동률 | 5~20% 적정 상승 | 0~10점 |

**총점 = Σ(지표점수 × 가중치)**, 가중치는 익일 결과 기반 자동 조정 (0.5~5.0)

---

## 🚀 빠른 시작

### 1. 요구 사항

- Python 3.11 이상
- 한국투자증권 계좌 및 API 키
- Discord 웹훅 (선택)

### 2. 설치

```bash
# 레포지토리 클론
git clone https://github.com/PARK-Yunjae/ClosingBell.git
cd ClosingBell

# 가상환경 생성 (권장)
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate

# 의존성 설치
pip install -r requirements.txt
```

### 3. 환경 변수 설정

```bash
# .env.example을 .env로 복사
copy .env.example .env   # Windows
cp .env.example .env     # Linux/Mac

# .env 파일 편집하여 API 키 입력
```

**필수 설정:**
```env
# 한국투자증권 API (필수)
KIS_APP_KEY=YOUR_APP_KEY_HERE
KIS_APP_SECRET=YOUR_APP_SECRET_HERE

# Discord 웹훅 (권장)
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

### 4. 설정 검증

```bash
# 설정이 올바른지 확인
python main.py --validate
```

### 5. 실행

```bash
# 즉시 스크리닝 (알림 발송)
python main.py --run

# 테스트 모드 (알림/저장 없음)
python main.py --run-test

# 스케줄러 모드 (12:30, 15:00, 16:30 자동 실행)
python main.py
```

---

## 📖 사용법

### CLI 옵션

```bash
python main.py [옵션]

옵션:
  (없음)          스케줄러 모드 (자동 실행)
  --run           즉시 스크리닝 실행 (알림 발송)
  --run-test      테스트 모드 (알림/저장 없음)
  --learn         수동 학습 실행
  --init-db       DB 초기화만 실행
  --validate      설정 검증만 실행
  --show-config   현재 설정 요약 출력
  --no-alert      알림 발송 안함 (--run과 함께 사용)
```

### 예시

```bash
# 스케줄러 모드 (권장 - 평일 자동 실행)
python main.py

# 지금 바로 스크리닝 (알림 발송)
python main.py --run

# 테스트 (API 연결 확인)
python main.py --run-test

# 알림 없이 스크리닝만
python main.py --run --no-alert
```

---

## 📁 프로젝트 구조

```
ClosingBell/
├── main.py                 # 메인 실행 파일
├── requirements.txt        # 의존성 목록
├── .env.example           # 환경 변수 예시
├── src/
│   ├── adapters/          # 외부 API 연동
│   │   ├── kis_client.py      # 한국투자증권 API
│   │   └── discord_notifier.py # Discord 알림
│   ├── config/            # 설정
│   │   ├── settings.py        # 환경 변수 로드
│   │   ├── constants.py       # 상수 정의
│   │   └── validator.py       # 설정 검증
│   ├── domain/            # 비즈니스 로직
│   │   ├── models.py          # 데이터 모델
│   │   ├── indicators.py      # 기술적 지표
│   │   └── score_calculator.py # 점수 산출
│   ├── infrastructure/    # 인프라
│   │   ├── database.py        # DB 관리
│   │   ├── scheduler.py       # 스케줄러
│   │   └── logging_config.py  # 로깅 설정
│   └── services/          # 서비스 레이어
│       ├── screener_service.py   # 스크리닝
│       ├── notifier_service.py   # 알림 통합
│       ├── learner_service.py    # 학습
│       └── backtest_service.py   # 백테스팅
├── data/                  # 데이터 저장
├── logs/                  # 로그 파일 (일별 자동 분리)
└── docs/                  # 설계 문서
```

---

## 🔧 기술 스택

- **언어**: Python 3.11+
- **DB**: SQLite 3
- **스케줄링**: APScheduler
- **HTTP 클라이언트**: requests
- **대시보드**: Streamlit (옵션)
- **외부 API**: 한국투자증권 REST API, Discord Webhook

---

## 📝 로그 파일

로그는 `logs/` 디렉토리에 일별로 자동 분리됩니다:

```
logs/
├── 2026-01-08.log      # 오늘 로그
├── errors.log          # 에러 전용 로그
└── ...                 # 30일 보관
```

---

## ⚠️ 알려진 이슈 및 주의사항

1. **Rate Limit**: 한국투자증권 API는 초당 호출 제한이 있습니다. `API_CALL_INTERVAL` 설정을 0.12초 이상 유지하세요.

2. **토큰 만료**: KIS API 토큰은 24시간 유효합니다. 시스템이 자동으로 재발급합니다.

3. **장 운영일 확인**: 공휴일에는 스케줄러가 자동으로 스킵합니다.

---

## 📋 TODO

- [ ] 텔레그램 알림 지원
- [ ] 웹 대시보드 개선
- [ ] AI 기반 추가 분석 (Gemini API)
- [ ] 포트폴리오 관리 기능
- [ ] 슬랙 알림 지원

---

## 📄 라이선스

MIT License

---

## 👤 Author

**박윤재**

- GitHub: [@PARK-Yunjae](https://github.com/PARK-Yunjae)

---

## 🙏 기여

버그 리포트, 기능 제안, PR 환영합니다!

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📚 참고 자료

- [한국투자증권 API 문서](https://apiportal.koreainvestment.com/)
- [Discord Webhook 가이드](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks)

---

**설계 철학:** 뉴스 수집은 제외합니다. 모든 시장 정보(기대감, 내부자 정보 등)는 결국 차트에 반영된다고 봅니다.
