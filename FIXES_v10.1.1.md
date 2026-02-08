# ClosingBell v10.1.1 버그 수정 요약

## 수정된 파일 (5개, 8개 패치)

### 1. `src/services/enrichment_service.py` — 공매도/지지저항 로깅 강화
**문제**: 공매도/SR 분석이 실패해도 `logger.debug()` 레벨이라 스레드 내 실행 시 로그가 보이지 않음
**수정**:
- 공매도 분석 성공 로그: `debug` → `info` (score, ratio, summary 포함)
- 지지/저항 분석 성공 로그: `debug` → `info` (score, S/R 레벨 포함)
- 실패 로그에 `type(e).__name__` 추가 (ImportError vs APIError 구분)
- 가격 데이터 없음 경고 추가 (`prices=None` 케이스)

### 2. `src/services/top5_pipeline.py` — DB 저장 로직 개선 (3개 수정)
**문제 A**: 공매도/SR 데이터 저장 시 로깅이 `debug` 레벨이라 실패 원인 추적 불가
**수정**: 각 종목의 ss/sr 존재 여부를 `info` 레벨로 출력, 저장 성공/실패 로그 추가

**문제 B**: AI 캐시 체크에서 `sqlite3.Row` 객체에 `.get()` 호출하여 에러
**수정**: `existing = dict(existing)` 변환 후 `.get()` 호출

**문제 C**: AI 캐시 체크 실패 로그가 `debug` 레벨
**수정**: `debug` → `info` 레벨로 상향

### 3. `src/services/pullback_tracker.py` — API 폴백 추가
**문제**: OHLCV CSV 파일이 없는 종목은 `continue`로 무시 → pullback_daily_prices 0건
**수정**: 
- `_load_ohlcv_df()` 헬퍼 함수 추가 (CSV → 키움 API 폴백)
- API 클라이언트 lazy initialization

### 4. `src/services/screener_service.py` — VP 매물대 오류 방어
**문제**: `'NoneType' object has no attribute 'score'` 오류가 76건 로그 스팸
**수정**:
- `score.score_detail is not None and vp_result is not None` 방어 코드 추가
- 개별 DEBUG 로그 76건 → 1줄 요약 INFO 로그로 통합
- except 블록에서도 score_detail None 체크

### 5. `dashboard/pages/1_top5_tracker.py` — CSS 렌더링 수정
**문제**: `#888` (3자리 hex) + alpha suffix `15` → `#88815` (잘못된 CSS)
**수정**: 2곳의 `#888` → `#888888` (6자리 hex)

## 다음 거래일 검증 포인트

### 15:00 메인 스크리닝 후 확인할 로그
```
# 공매도 분석 성공 시:
📉 공매도 분석: 332290 → score=1.0, ratio=2.5%, 숏비중낮음

# 지지/저항 성공 시:
📊 지지/저항: 332290 → score=3, S=4500, R=5200

# DB 저장 시:
공매도/SR 체크: 332290 → ss=있음, sr=있음
✅ 공매도/SR 저장: 332290
공매도/SR 필드 저장: 5개

# 실패 시 (원인 추적용):
⚠️ 공매도 분석 실패 (332290): ImportError: ...
공매도/SR 체크: 332290 → ss=None, sr=None
⚠️ 공매도/SR 데이터 누락: 5개 종목
```

### 16:07 눌림목 추적 후 확인할 로그
```
# API 폴백 사용 시:
[pullback_tracker] API 폴백: 001520 → 30일
[pullback_tracker] 완료: 5개 시그널, 25개 가격 업데이트
```

### DB 검증 쿼리
```sql
-- 공매도/SR 데이터 확인
SELECT screen_date, stock_code, short_ratio, short_score, sr_score, 
       sr_nearest_support, sr_nearest_resistance 
FROM closing_top5_history 
WHERE screen_date = '2026-02-10'
ORDER BY rank;

-- 눌림목 추적 확인
SELECT COUNT(*) FROM pullback_daily_prices;
```
