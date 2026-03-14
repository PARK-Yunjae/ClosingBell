# ClosingBell v3.8

한국 주식 자동 스크리닝 + 매수 추천 시스템.
유목민 프레임워크(저점→악재소멸→거래량급감→폭발) 기반.

## 운영 흐름

```
15:00  daily_top3 매수 추천
       현재가 → 기술 스코어링 → DART → 뉴스 → 수급 → TOP3 → Discord

15:40  장마감 스크리닝
       유니버스 확보 → bell_score → 거래원+DART+AI → 워치리스트 저장 → Discord
       → OHLCV 갱신, 성과 추적, 주간/월간 메타 갱신
```

## 파일 구조 (18개 Python, ~7,100줄)

**엔진**: `main.py` `screener.py` `watchlist_monitor.py` `enricher.py`
**데이터**: `kiwoom_api.py` `dart_checker.py` `news_checker.py` `supply_checker.py` `ai_analyzer.py`
**인프라**: `config.py` `storage.py` `market_context.py` `trading_calendar.py` `notifier.py`
**유지보수**: `fdr_update.py` `weekly_update.py` `performance_tracker.py` `tools/healthcheck.py`

## 키움 API 사용 (13개)

유니버스: ka10030(거래량상위), ka10032(거래대금상위)
기본정보: ka10001(현재가), ka10100(종목메타), ka10081(일봉)
거래원: ka10025(매물대), ka10038(증권사순위), ka10040(주요거래원)
수급(v3.8): ka10014(공매도), ka20068(대차), ka10013(신용), ka10059(투자자), ka10047(체결강도)

## 실행

```bash
pip install -r requirements.txt
cp .env.example .env   # API 키 입력

python main.py          # 스케줄러 (15:00 + 15:40)
python main.py --pick   # 즉시 매수 추천
python main.py --once   # 즉시 스크리닝
python tools/healthcheck.py  # 시스템 점검
```

## 저장 위치

- DB: `data/closingbell.db` (스크리닝, 워치리스트, 추천, 알림 이력)
- 성과: `data/performance/tracking.json`
- OHLCV: `C:/Coding/data/ohlcv/*.csv`
- 메타: `C:/Coding/data/meta/*`, `C:/Coding/data/stock_mapping.csv`
- 글로벌: `C:/Coding/data/global/global_merged.csv`

## 필수 환경변수

```env
KIWOOM_APPKEY=
KIWOOM_SECRETKEY=
DISCORD_WEBHOOK_URL=
```

## 선택 환경변수

```env
GEMINI_API_KEY=       # 뉴스 AI 분석
DART_API_KEY=         # DART 공시 체크
NAVER_CLIENT_ID=      # 네이버 뉴스 검색
NAVER_CLIENT_SECRET=
```

## 점검 명령

```bash
python tools/healthcheck.py        # DB, 캘린더, 워치리스트 상태
python watchlist_monitor.py --status  # 감시 종목 타이밍 가이드
python performance_tracker.py --report  # 성과 리포트
python fdr_update.py --check       # OHLCV 최신성
python weekly_update.py --check    # 메타 최신성
```

## 정책

- 워치리스트/추천: rank 1,2,3만 (4,5 제외)
- D+1 진입: -8점 감점 (백테스트 42% vs D+2~3: 71~75%)
- 수급 주의(공매도↑ + 대차↑ 등): -3점 감점
- 캘린더 91+개 이벤트 (FOMC, 옵션만기, CPI, 선거, 연휴 등)
