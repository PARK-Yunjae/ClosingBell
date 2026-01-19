# ClosingBell v6.0 업그레이드 가이드

## 📋 변경 사항 요약

### 🆕 새 기능
1. **TOP5 20일 추적**: D+1 ~ D+20 수익률 자동 추적
2. **유목민 공부법**: 상한가/거래량폭발 종목 뉴스 분석
3. **과거 데이터 백필**: OHLCV 파일로 과거 데이터 자동 생성
4. **멀티페이지 대시보드**: Streamlit 멀티페이지 구조

### 📁 새로 추가된 파일
```
src/
├── config/
│   └── backfill_config.py          # 백필 설정
├── services/
│   └── backfill/
│       ├── __init__.py
│       ├── backfill_service.py     # 백필 메인 서비스
│       ├── data_loader.py          # OHLCV 로더
│       └── indicators.py           # 기술적 지표 계산
├── infrastructure/
│   ├── database.py                 # v6.0 스키마 추가
│   └── repository.py               # v6.0 Repository 추가

dashboard/
├── app.py                          # 홈페이지 (v6.0 업데이트)
└── pages/
    ├── 1_📊_종가매매_TOP5.py        # TOP5 20일 추적
    └── 2_📚_유목민_공부법.py        # 유목민 대시보드

scripts/
└── run_migration_v6.py             # 마이그레이션 스크립트

migrations/
└── v6_schema.sql                   # DDL 스크립트
```

### 🗃️ 새 DB 테이블
1. `closing_top5_history`: TOP5 20일 추적 마스터
2. `top5_daily_prices`: D+1 ~ D+20 일별 가격
3. `nomad_candidates`: 유목민 후보 종목
4. `nomad_news`: 유목민 뉴스 기사

---

## 🚀 업그레이드 방법

### 1단계: 파일 교체
```bash
# 기존 프로젝트 백업
copy ClosingBell ClosingBell_backup_v5.4

# 새 파일 압축 해제
# (기존 파일 덮어쓰기)
```

### 2단계: DB 마이그레이션
```bash
# 마이그레이션 실행 (자동 백업 포함)
python scripts/run_migration_v6.py
```

### 3단계: 데이터 백필 (선택)
```bash
# 과거 20일 데이터 백필
python main.py --backfill 20

# TOP5만 백필
python main.py --backfill-top5 20

# 유목민만 백필
python main.py --backfill-nomad 20
```

### 4단계: 대시보드 확인
```bash
streamlit run dashboard/app.py
```

---

## 📌 새 명령어

```bash
# 기존 명령어 (동일)
python main.py              # 스케줄러 모드
python main.py --run        # 스크리닝 즉시 실행
python main.py --check CODE # 종목 점수 확인

# v6.0 신규 명령어
python main.py --backfill 20        # 과거 20일 백필 (TOP5 + 유목민)
python main.py --backfill-top5 20   # TOP5만 백필
python main.py --backfill-nomad 20  # 유목민만 백필
python main.py --auto-fill          # 누락 데이터 자동 수집
python main.py --run-top5-update    # TOP5 일일 추적 업데이트
python main.py --run-nomad          # 유목민 공부 실행
python main.py --version            # 버전 확인
```

---

## ⚠️ 주의사항

### 전략 코드 변경 없음
- `score_calculator.py` 변경 없음
- `screener_service.py` 변경 없음
- 기존 점수 계산 로직 100% 유지

### 백필 데이터 경로
백필 기능은 Windows 환경에서 아래 경로 필요:
```
C:\Coding\data\ohlcv\          # OHLCV 파일들 (*.csv)
C:\Coding\data\stock_mapping.csv   # 종목 매핑
C:\Coding\data\global\         # 지수 데이터
```

### DB 호환성
- 기존 `screener.db`에 새 테이블 추가
- 기존 데이터 영향 없음
- 마이그레이션 스크립트가 자동 백업

---

## 📊 대시보드 구조

```
🔔 ClosingBell v6.0 (홈)
├── 📊 종가매매 TOP5 (페이지 1)
│   ├── 날짜별 TOP5 목록
│   ├── 20일 수익률 차트
│   └── 종목별 상세 분석
└── 📚 유목민 공부법 (페이지 2)
    ├── 상한가/거래량폭발 종목
    ├── 기업 정보
    └── 관련 뉴스
```

---

## 🐛 트러블슈팅

### "테이블이 없음" 에러
```bash
python scripts/run_migration_v6.py
```

### "OHLCV 파일 없음" 경고
백필 기능은 OHLCV 파일이 필요합니다. 실시간 데이터 수집은 정상 작동합니다.

### Streamlit 페이지 안 보임
`dashboard/pages/` 폴더에 파일이 있는지 확인:
```bash
dir dashboard\pages\
```

---

## 📞 문의
문제 발생 시 이전 버전으로 롤백:
```bash
copy data\screener.db.backup_* data\screener.db
```
