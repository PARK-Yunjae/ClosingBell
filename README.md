# ClosingBell v3.7

한국 주식 종가 스크리닝과 15:00 감시종목 재평가를 위한 실운영 전용 프로젝트입니다.

대시보드, 백필, 시뮬, 리페어, 로컬 리플레이 경로는 제거했고, 현재는 스케줄러와 Discord 알림, SQLite 저장, 외부 데이터 갱신만 유지합니다.

## 운영 흐름

```text
15:00  활성 watchlist 재평가 -> TOP3 Discord 알림
15:40  장마감 스크리닝 -> watchlist 저장
       -> OHLCV 갱신
       -> 글로벌 지수 갱신
       -> 성과 추적
       -> 주간 meta 갱신
       -> 월간 finstate 갱신
```

## 현재 정책

- watchlist 저장과 추천은 rank `1,2,3`만 사용합니다.
- rank `4,5`는 저장과 추천에서 모두 제외합니다.
- 백테스트 숫자 문구와 대시보드 링크 같은 표시성 요소는 제거했습니다.
- 실데이터는 `SQLite + OHLCV CSV + runtime meta CSV/JSON`으로 유지합니다.

## 주요 파일

```text
main.py                scheduler entrypoint
config.py              .env-based runtime config
screener.py            end-of-day screener
watchlist_monitor.py   active watchlist evaluation and TOP3 pick
notifier.py            Discord webhook notifier
performance_tracker.py outcome tracking
fdr_update.py          OHLCV and global market updater
weekly_update.py       stock mapping, meta, holder, finstate updater
storage.py             SQLite persistence
```

## 필수 환경변수

```env
KIWOOM_APPKEY=
KIWOOM_SECRETKEY=
DISCORD_WEBHOOK_URL=
```

## 선택 환경변수

```env
GEMINI_API_KEY=
DART_API_KEY=
NAVER_CLIENT_ID=
NAVER_CLIENT_SECRET=
```

## 자주 조정하는 운영값

```env
SCHEDULE_DAILY_PICK=15:00
SCHEDULE_SCREEN=15:40
WATCHLIST_MAX_STOCKS=3
WATCHLIST_ALLOWED_RANKS=1,2,3
DAILY_PICK_TOP_K=3
DISCORD_SCREEN_TOP_N=3
DISCORD_PICK_TOP_N=3
RANK1_SWEET_SPOT=1
RANK2_SWEET_SPOT=2
RANK3_SWEET_SPOT=2
```

## 실행

```bash
cd C:\Coding\ClosingBell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## 운영 점검 명령

```bash
python main.py --pick
python main.py --once
python main.py --weekly
python watchlist_monitor.py --status
python performance_tracker.py --report
python fdr_update.py --check
python weekly_update.py --check
```

## 저장 위치

- screening, watchlist, buy-pick, notify log: `data/closingbell.db`
- performance tracking: `data/performance/tracking.json`
- DART corp map cache: `data/dart_corp_map.json`
- market calendar cache: `data/reference/market_calendar.json`
- OHLCV source: `C:/Coding/data/ohlcv`
- global merged source: `C:/Coding/data/global/global_merged.csv`
- runtime meta source: `C:/Coding/data/meta/*`

## 제거된 항목

- Streamlit dashboard
- Git push automation
- preflight import path
- backfill / repair / simulate / local replay scripts
- file-based legacy watchlist logs

## 기본 검증

```bash
python -m py_compile main.py watchlist_monitor.py notifier.py screener.py performance_tracker.py weekly_update.py fdr_update.py
python main.py --help
python weekly_update.py --check
python fdr_update.py --check
```
