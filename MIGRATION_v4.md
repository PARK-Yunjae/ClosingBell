# ClosingBell v3.8 → v4.0 마이그레이션 가이드

## ⚠️ 반드시 해야 할 것: .env 정리

기존 `.env`에 아래 값이 있으면 **v4 기본값을 덮어써서 의도대로 작동하지 않습니다.**
해당 줄을 **삭제하거나 주석처리(`#`)** 해주세요.

### 삭제 또는 주석처리 대상

```bash
# ❌ 이것들이 .env에 남아있으면 v4가 제대로 안 됩니다

MIN_CHANGE_RATE=1.0        # v4 기본: -30.0 (등락률 필터 사실상 제거)
MAX_CHANGE_RATE=29.0       # v4 기본: 30.0
WATCHLIST_MAX_STOCKS=3     # v4 기본: 5 (감시종목 3→5개)
DAILY_PICK_TOP_K=3         # v4 기본: 5
TOP_N=3                    # v4 기본: 5
WATCHLIST_ALLOWED_RANKS=1,2,3  # v4 기본: 1,2,3,4,5
UNIVERSE_MODE=intersection     # v4: 항상 합집합 (Core/Fringe 태깅)
BUY_A_MIN_SCORE=60.0       # v4 기본: 68.0 (100점 체계)
BUY_B_MIN_SCORE=40.0       # v4 기본: 45.0 (100점 체계)
RANK1_PULLBACK_BONUS=10.0  # v4 기본: 5.0 (평탄화)
RANK3_PULLBACK_BONUS=-10.0 # v4 기본: 0.0 (평탄화)
DISCORD_SCREEN_TOP_N=3     # v4 기본: 5
DISCORD_PICK_TOP_N=3       # v4 기본: 5
```

### 가장 간단한 방법

```powershell
# .env를 열어서 위 항목들이 있으면 줄 앞에 # 붙이기
# 예:
# MIN_CHANGE_RATE=1.0      ← 주석처리
# WATCHLIST_MAX_STOCKS=3   ← 주석처리
```

config.py가 `.env`에 값이 없으면 v4 기본값을 사용합니다.

## 적용 순서

```powershell
# 1. 기존 폴더 백업
xcopy C:\Coding\ClosingBell C:\Coding\ClosingBell_v38_backup /E /I

# 2. v4 zip 해제 (기존 폴더에 덮어쓰기)
# ClosingBell_v4.zip을 C:\Coding\ClosingBell에 풀기

# 3. .env 정리 (위 항목 주석처리)

# 4. DB 마이그레이션 (pick_snapshots 테이블 자동 생성)
python -c "from storage import init_storage; init_storage(); print('OK')"

# 5. 테스트
python main.py --pick
```

## DB 호환성

- 기존 테이블(`screen_runs`, `watchlists`, `buy_pick_runs` 등)은 그대로 유지
- `pick_snapshots` 테이블이 자동으로 추가됨 (기존 데이터 손상 없음)
- 기존 워치리스트도 v4에서 로드 가능 (하위 호환)

## 삭제해도 되는 파일 (데드코드 아닌 잔재)

v4에서 **호출하지 않지만 남겨둔 것들** (나중에 재활용 가능):
- `notifier.py`의 `send_recommendation()` — v3 15:40 스크리닝 웹훅
- `notifier.py`의 `send_pullback_signals()` — v3 눌림목 웹훅
- `config.py`의 `UNIVERSE_MODE` — v4에서 항상 합집합, 분기 제거됨

이것들은 삭제해도 되고 냅둬도 됩니다. 런타임에 영향 없음.
