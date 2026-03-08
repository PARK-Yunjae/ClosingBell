# ClosingBell v3

> 키움 REST API 기반 / 8지표 점수제 / 유니버스 전체 분석 / 매물대+거래원+AI

## 구조

```
ClosingBell/
├── main.py           # 스케줄러 + CLI
├── config.py         # 설정 (점수 파라미터, 필터, API)
├── kiwoom_api.py     # 키움 REST API 클라이언트
├── screener.py       # 8지표 점수 계산 + 유니버스 관리
├── enricher.py       # 거래원 + DART + AI 분석 (유니버스 전체)
├── dart_checker.py   # DART 공시 간이 체크
├── ai_analyzer.py    # Gemini 위험도 한줄 분석
├── notifier.py       # 디스코드 웹훅 (공유용 쉬운 버전)
├── data_updater.py   # OHLCV 데이터 갱신
├── dashboard/
│   └── app.py        # Streamlit 대시보드
├── data/
│   └── logs/         # 일별 JSON 로그
├── .env.example
├── requirements.txt
└── run_schedule.bat
```

## 8지표 점수 (100점)

| 지표 | 배점 | 최적 구간 | 근거 |
|------|------|-----------|------|
| CCI(14) | 25점 | 160~180 | 50.4% 승률 (9.5년 백테스트) |
| MA20 이격도 | 20점 | 2~8% | 추세 위 적정 거리 |
| 등락률 | 15점 | 2~8% | 적정 모멘텀 |
| CCI 기울기 | 10점 | 3일↑ | 단기 추세 |
| MA20 기울기 | 10점 | 3일↑ | 중기 추세 |
| RSI(14) | 5점 | 50~70 | 과매수/과매도 |
| 매물대 저항도 | 10점 | 위 매물 ≤30% | OHLCV 가격대별 거래량 |
| 거래원 이상도 | 5점 | 외국계 순매수 | ka10038+ka10040 |

## 웹훅 출력 예시

```
🔔 ClosingBell v3 — 2026-03-10

📊 코스피 2,750 (+1.2%) | 나스닥 +0.8%

🥇 삼성전기
  💰 182,000원 (+5.3%) | 82점
  📍 매물대: 위 매물 적음 ✅
  🏦 거래원: 외국계 순매수 ✅ (매수1위: 모건스탠리)
  📋 공시: 정상, 흑자 ✅
  ▶ 매수관심 🟢 | 위험도 낮음 ✅
  💡 "이평선 위 안정적 상승"
```

## 설치

```bash
# 1. 가상환경
python -m venv venv
.\venv\Scripts\activate

# 2. 패키지
pip install -r requirements.txt

# 3. 환경 설정
copy .env.example .env
# .env 편집: 키움 키, 디스코드 URL, Gemini 키 입력

# 4. 테스트
python main.py --once

# 5. 대시보드
streamlit run dashboard/app.py
```

## 스케줄

| 시간 | 작업 |
|------|------|
| 14:55 | 유니버스 확보 + 점수 계산 + enrich |
| ~15:06 | 디스코드 웹훅 |
| 15:35 | OHLCV 갱신 |
| 15:40 | git push |
| 15:43 | 종료 |

## v2 → v3 마이그레이션

1. `.env` 파일에 키움 키 추가 (KIS 키는 더 이상 불필요)
2. `data/logs/` 폴더의 기존 JSON 로그는 호환됨
3. `C:/Coding/data/ohlcv/` 로컬 CSV도 그대로 사용
4. Windows 작업 스케줄러의 시작 시간만 14:50→14:55 변경
