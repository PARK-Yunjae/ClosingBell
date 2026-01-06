# 4. 데이터베이스 설계 (Database Design)

**프로젝트명:** 종가매매 스크리너  
**버전:** 1.0  
**작성일:** 2025-01-06  
**DBMS:** SQLite 3  

---

## 4.1 개요

### 4.1.1 결론
6개의 테이블로 구성된 SQLite 데이터베이스를 설계한다. 핵심은 스크리닝 결과 저장, 익일 결과 추적, 가중치 관리, 매매일지 기록이다.

### 4.1.2 근거
- SQLite: 단일 파일, 서버리스, Python 기본 지원
- 정규화 수준: 3NF (과도한 정규화 지양, 쿼리 성능 우선)
- 인덱스: 자주 조회되는 컬럼에 적용

### 4.1.3 리스크/대안
| 리스크 | 대안 |
|--------|------|
| 동시 쓰기 충돌 | WAL 모드 활성화 + 단일 프로세스 운영 |
| 데이터 증가 시 성능 | 1년 단위 아카이빙 정책 |
| 백업 미흡 | 일간 자동 백업 스크립트 |

---

## 4.2 ERD (Entity Relationship Diagram)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ERD Overview                                    │
└─────────────────────────────────────────────────────────────────────────────┘

┌──────────────────┐       ┌──────────────────┐       ┌──────────────────┐
│    screenings    │       │  screening_items │       │   next_day_      │
│    (스크리닝)     │       │  (스크리닝 종목)  │       │   results        │
├──────────────────┤       ├──────────────────┤       │  (익일 결과)     │
│ PK id            │───┐   │ PK id            │       ├──────────────────┤
│    screen_date   │   │   │ FK screening_id  │───────│ PK id            │
│    screen_time   │   └──>│    stock_code    │<──┐   │ FK item_id       │
│    total_count   │       │    stock_name    │   │   │    open_price    │
│    created_at    │       │    score_total   │   │   │    close_price   │
└──────────────────┘       │    score_cci     │   │   │    high_price    │
                           │    score_cci_slope│   │   │    open_change   │
                           │    score_ma20    │   │   │    day_change    │
                           │    score_candle  │   │   │    collected_at  │
                           │    score_change  │   │   └──────────────────┘
                           │    rank          │   │
                           │    ...           │   │
                           └──────────────────┘   │
                                                  │
┌──────────────────┐       ┌──────────────────┐   │   ┌──────────────────┐
│  weight_config   │       │  weight_history  │   │   │   trade_journal  │
│  (가중치 설정)    │       │  (가중치 이력)   │   │   │   (매매일지)     │
├──────────────────┤       ├──────────────────┤   │   ├──────────────────┤
│ PK id            │       │ PK id            │   │   │ PK id            │
│    indicator     │       │    changed_at    │   │   │    trade_date    │
│    weight        │       │    indicator     │   │   │    stock_code    │──┘
│    updated_at    │       │    old_weight    │   │   │    stock_name    │
│    is_active     │       │    new_weight    │   │   │    buy_price     │
└──────────────────┘       │    reason        │   │   │    sell_price    │
                           └──────────────────┘   │   │    quantity      │
                                                  │   │    return_rate   │
                                                  │   │ FK screening_item_id
                                                  │   │    memo          │
                                                  │   │    created_at    │
                                                  │   └──────────────────┘
                                                  │
                                                  └── (선택적 연결)
```

---

## 4.3 테이블 정의서

### 4.3.1 screenings (스크리닝 실행 기록)

**목적:** 각 스크리닝 실행의 메타 정보 저장

| 컬럼명 | 데이터 타입 | NULL | 기본값 | 설명 |
|--------|-------------|------|--------|------|
| id | INTEGER | NO | AUTO | PK, 자동 증가 |
| screen_date | DATE | NO | - | 스크리닝 날짜 (YYYY-MM-DD) |
| screen_time | TEXT | NO | - | 스크리닝 시각 ('15:00' 고정) |
| total_count | INTEGER | NO | 0 | 필터링된 총 종목 수 |
| top3_codes | TEXT | YES | NULL | TOP 3 종목코드 (JSON) |
| execution_time_sec | REAL | YES | NULL | 실행 소요 시간 (초) |
| status | TEXT | NO | 'SUCCESS' | 상태 (SUCCESS/FAILED/PARTIAL) |
| error_message | TEXT | YES | NULL | 에러 메시지 |
| created_at | DATETIME | NO | CURRENT_TIMESTAMP | 생성 시각 |

**인덱스:**
- `idx_screenings_date` ON (screen_date) - UNIQUE
- `idx_screenings_status` ON (status)

**DDL:**
```sql
CREATE TABLE screenings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    screen_date DATE NOT NULL UNIQUE,
    screen_time TEXT NOT NULL DEFAULT '15:00',
    total_count INTEGER NOT NULL DEFAULT 0,
    top3_codes TEXT,
    execution_time_sec REAL,
    status TEXT NOT NULL DEFAULT 'SUCCESS' CHECK(status IN ('SUCCESS', 'FAILED', 'PARTIAL')),
    error_message TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_screenings_date ON screenings(screen_date);
CREATE INDEX idx_screenings_status ON screenings(status);
```

---

### 4.3.2 screening_items (스크리닝 종목 상세)

**목적:** 각 스크리닝에서 분석된 개별 종목의 점수 및 데이터 저장

| 컬럼명 | 데이터 타입 | NULL | 기본값 | 설명 |
|--------|-------------|------|--------|------|
| id | INTEGER | NO | AUTO | PK |
| screening_id | INTEGER | NO | - | FK → screenings.id |
| stock_code | TEXT | NO | - | 종목코드 (6자리) |
| stock_name | TEXT | NO | - | 종목명 |
| current_price | INTEGER | NO | - | 현재가 |
| change_rate | REAL | NO | - | 등락률 (%) |
| trading_value | REAL | NO | - | 거래대금 (억원) |
| score_total | REAL | NO | - | 총점 (가중 합계) |
| score_cci_value | REAL | NO | - | CCI 값 점수 |
| score_cci_slope | REAL | NO | - | CCI 기울기 점수 |
| score_ma20_slope | REAL | NO | - | MA20 기울기 점수 |
| score_candle | REAL | NO | - | 양봉 품질 점수 |
| score_change | REAL | NO | - | 상승률 점수 |
| raw_cci | REAL | YES | NULL | CCI 원시값 |
| raw_ma20 | REAL | YES | NULL | MA20 원시값 |
| rank | INTEGER | YES | NULL | 순위 (1, 2, 3...) |
| is_top3 | INTEGER | NO | 0 | TOP3 여부 (0/1) |
| created_at | DATETIME | NO | CURRENT_TIMESTAMP | 생성 시각 |

**인덱스:**
- `idx_items_screening` ON (screening_id)
- `idx_items_stock` ON (stock_code)
- `idx_items_rank` ON (rank) WHERE rank <= 3
- `idx_items_composite` ON (screening_id, is_top3)

**DDL:**
```sql
CREATE TABLE screening_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    screening_id INTEGER NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    current_price INTEGER NOT NULL,
    change_rate REAL NOT NULL,
    trading_value REAL NOT NULL,
    score_total REAL NOT NULL,
    score_cci_value REAL NOT NULL,
    score_cci_slope REAL NOT NULL,
    score_ma20_slope REAL NOT NULL,
    score_candle REAL NOT NULL,
    score_change REAL NOT NULL,
    raw_cci REAL,
    raw_ma20 REAL,
    rank INTEGER,
    is_top3 INTEGER NOT NULL DEFAULT 0 CHECK(is_top3 IN (0, 1)),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (screening_id) REFERENCES screenings(id) ON DELETE CASCADE
);

CREATE INDEX idx_items_screening ON screening_items(screening_id);
CREATE INDEX idx_items_stock ON screening_items(stock_code);
CREATE INDEX idx_items_rank ON screening_items(rank) WHERE rank <= 3;
CREATE INDEX idx_items_composite ON screening_items(screening_id, is_top3);
```

---

### 4.3.3 next_day_results (익일 결과)

**목적:** 스크리닝 종목의 익일 시장 데이터 저장 (확장된 분석 데이터 포함)

| 컬럼명 | 데이터 타입 | NULL | 기본값 | 설명 |
|--------|-------------|------|--------|------|
| id | INTEGER | NO | AUTO | PK |
| screening_item_id | INTEGER | NO | - | FK → screening_items.id |
| next_date | DATE | NO | - | 익일 날짜 |
| open_price | INTEGER | NO | - | 시초가 |
| close_price | INTEGER | NO | - | 종가 |
| high_price | INTEGER | NO | - | 고가 |
| low_price | INTEGER | NO | - | 저가 |
| volume | INTEGER | YES | NULL | 거래량 |
| trading_value | REAL | YES | NULL | 거래대금 (억원) |
| open_change_rate | REAL | NO | - | 시초가 대비 전일종가 등락률 (%) |
| day_change_rate | REAL | NO | - | 당일 등락률 (%) |
| high_change_rate | REAL | NO | - | 고점 대비 전일종가 등락률 (%) |
| gap_rate | REAL | YES | NULL | 시초가 갭 (전일종가 대비 %) |
| volatility | REAL | YES | NULL | 장중 변동성 ((고가-저가)/시가 %) |
| is_open_up | INTEGER | NO | - | 시초가 상승 여부 (0/1) |
| is_day_up | INTEGER | NO | - | 당일 상승 여부 (0/1) |
| collected_at | DATETIME | NO | CURRENT_TIMESTAMP | 수집 시각 |

**인덱스:**
- `idx_nextday_item` ON (screening_item_id) - UNIQUE
- `idx_nextday_date` ON (next_date)
- `idx_nextday_open_up` ON (is_open_up)

**DDL:**
```sql
CREATE TABLE next_day_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    screening_item_id INTEGER NOT NULL UNIQUE,
    next_date DATE NOT NULL,
    open_price INTEGER NOT NULL,
    close_price INTEGER NOT NULL,
    high_price INTEGER NOT NULL,
    low_price INTEGER NOT NULL,
    open_change_rate REAL NOT NULL,
    day_change_rate REAL NOT NULL,
    high_change_rate REAL NOT NULL,
    is_open_up INTEGER NOT NULL CHECK(is_open_up IN (0, 1)),
    is_day_up INTEGER NOT NULL CHECK(is_day_up IN (0, 1)),
    collected_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (screening_item_id) REFERENCES screening_items(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX idx_nextday_item ON next_day_results(screening_item_id);
CREATE INDEX idx_nextday_date ON next_day_results(next_date);
CREATE INDEX idx_nextday_open_up ON next_day_results(is_open_up);
```

---

### 4.3.4 weight_config (가중치 설정)

**목적:** 5가지 지표의 현재 가중치 저장

| 컬럼명 | 데이터 타입 | NULL | 기본값 | 설명 |
|--------|-------------|------|--------|------|
| id | INTEGER | NO | AUTO | PK |
| indicator | TEXT | NO | - | 지표명 (cci_value, cci_slope, ma20_slope, candle, change) |
| weight | REAL | NO | 1.0 | 가중치 (0.5 ~ 5.0) |
| min_weight | REAL | NO | 0.5 | 최소 가중치 |
| max_weight | REAL | NO | 5.0 | 최대 가중치 |
| is_active | INTEGER | NO | 1 | 활성화 여부 |
| updated_at | DATETIME | NO | CURRENT_TIMESTAMP | 수정 시각 |

**인덱스:**
- `idx_weight_indicator` ON (indicator) - UNIQUE

**DDL:**
```sql
CREATE TABLE weight_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    indicator TEXT NOT NULL UNIQUE,
    weight REAL NOT NULL DEFAULT 1.0 CHECK(weight >= 0.5 AND weight <= 5.0),
    min_weight REAL NOT NULL DEFAULT 0.5,
    max_weight REAL NOT NULL DEFAULT 5.0,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX idx_weight_indicator ON weight_config(indicator);

-- 초기 데이터
INSERT INTO weight_config (indicator, weight) VALUES
    ('cci_value', 1.0),
    ('cci_slope', 1.0),
    ('ma20_slope', 1.0),
    ('candle', 1.0),
    ('change', 1.0);
```

---

### 4.3.5 weight_history (가중치 변경 이력)

**목적:** 가중치 변경 이력 추적 (감사/롤백용)

| 컬럼명 | 데이터 타입 | NULL | 기본값 | 설명 |
|--------|-------------|------|--------|------|
| id | INTEGER | NO | AUTO | PK |
| indicator | TEXT | NO | - | 지표명 |
| old_weight | REAL | NO | - | 변경 전 가중치 |
| new_weight | REAL | NO | - | 변경 후 가중치 |
| change_reason | TEXT | YES | NULL | 변경 사유 |
| correlation | REAL | YES | NULL | 적중률 상관계수 |
| sample_size | INTEGER | YES | NULL | 분석 샘플 수 |
| changed_at | DATETIME | NO | CURRENT_TIMESTAMP | 변경 시각 |

**인덱스:**
- `idx_history_indicator` ON (indicator)
- `idx_history_date` ON (changed_at)

**DDL:**
```sql
CREATE TABLE weight_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    indicator TEXT NOT NULL,
    old_weight REAL NOT NULL,
    new_weight REAL NOT NULL,
    change_reason TEXT,
    correlation REAL,
    sample_size INTEGER,
    changed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_history_indicator ON weight_history(indicator);
CREATE INDEX idx_history_date ON weight_history(changed_at);
```

---

### 4.3.6 trade_journal (매매일지)

**목적:** 수동 매매 기록 저장 + 보유 현황 관리

| 컬럼명 | 데이터 타입 | NULL | 기본값 | 설명 |
|--------|-------------|------|--------|------|
| id | INTEGER | NO | AUTO | PK |
| trade_date | DATE | NO | - | 매매일 |
| stock_code | TEXT | NO | - | 종목코드 |
| stock_name | TEXT | NO | - | 종목명 |
| trade_type | TEXT | NO | 'BUY' | 매매 유형 (BUY/SELL) |
| price | INTEGER | NO | - | 체결가 |
| quantity | INTEGER | NO | - | 수량 |
| total_amount | INTEGER | NO | - | 총 금액 |
| holding_quantity | INTEGER | YES | NULL | 보유 수량 (매매 후 잔량) |
| return_rate | REAL | YES | NULL | 수익률 (%) |
| screening_item_id | INTEGER | YES | NULL | FK → screening_items.id (선택) |
| memo | TEXT | YES | NULL | 메모 |
| created_at | DATETIME | NO | CURRENT_TIMESTAMP | 생성 시각 |
| updated_at | DATETIME | NO | CURRENT_TIMESTAMP | 수정 시각 |

**인덱스:**
- `idx_journal_date` ON (trade_date)
- `idx_journal_stock` ON (stock_code)
- `idx_journal_screening` ON (screening_item_id)

**DDL:**
```sql
CREATE TABLE trade_journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date DATE NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    trade_type TEXT NOT NULL DEFAULT 'BUY' CHECK(trade_type IN ('BUY', 'SELL')),
    price INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    total_amount INTEGER NOT NULL,
    return_rate REAL,
    screening_item_id INTEGER,
    memo TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (screening_item_id) REFERENCES screening_items(id) ON DELETE SET NULL
);

CREATE INDEX idx_journal_date ON trade_journal(trade_date);
CREATE INDEX idx_journal_stock ON trade_journal(stock_code);
CREATE INDEX idx_journal_screening ON trade_journal(screening_item_id);

-- 트리거: updated_at 자동 갱신
CREATE TRIGGER update_journal_timestamp 
AFTER UPDATE ON trade_journal
BEGIN
    UPDATE trade_journal SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
```

---

## 4.4 주요 쿼리 예시

### 4.4.1 최근 30일 TOP 3 적중률 조회

```sql
SELECT 
    s.screen_date,
    COUNT(CASE WHEN ndr.is_open_up = 1 THEN 1 END) as hit_count,
    COUNT(ndr.id) as total_count,
    ROUND(COUNT(CASE WHEN ndr.is_open_up = 1 THEN 1 END) * 100.0 / COUNT(ndr.id), 2) as hit_rate
FROM screenings s
JOIN screening_items si ON s.id = si.screening_id AND si.is_top3 = 1
LEFT JOIN next_day_results ndr ON si.id = ndr.screening_item_id
WHERE s.screen_date >= DATE('now', '-30 days')
GROUP BY s.screen_date
ORDER BY s.screen_date DESC;
```

### 4.4.2 지표별 적중률 상관관계 분석

```sql
SELECT 
    'cci_value' as indicator,
    AVG(CASE WHEN si.score_cci_value > 7 AND ndr.is_open_up = 1 THEN 1.0
             WHEN si.score_cci_value > 7 AND ndr.is_open_up = 0 THEN 0.0 END) as high_score_hit_rate,
    AVG(CASE WHEN si.score_cci_value <= 7 AND ndr.is_open_up = 1 THEN 1.0
             WHEN si.score_cci_value <= 7 AND ndr.is_open_up = 0 THEN 0.0 END) as low_score_hit_rate
FROM screening_items si
JOIN next_day_results ndr ON si.id = ndr.screening_item_id
WHERE si.is_top3 = 1;
```

### 4.4.3 매매일지 수익률 요약

```sql
SELECT 
    strftime('%Y-%m', trade_date) as month,
    COUNT(*) as trade_count,
    SUM(CASE WHEN trade_type = 'SELL' THEN total_amount ELSE -total_amount END) as net_amount,
    AVG(return_rate) as avg_return_rate,
    COUNT(CASE WHEN return_rate > 0 THEN 1 END) * 100.0 / COUNT(CASE WHEN return_rate IS NOT NULL THEN 1 END) as win_rate
FROM trade_journal
GROUP BY strftime('%Y-%m', trade_date)
ORDER BY month DESC;
```

---

## 4.5 데이터 관리 정책

### 4.5.1 백업

```bash
# 일간 백업 스크립트 (cron 등록)
#!/bin/bash
DB_PATH="/home/user/closing-trade-screener/data/screener.db"
BACKUP_DIR="/home/user/closing-trade-screener/backup"
DATE=$(date +%Y%m%d)

sqlite3 $DB_PATH ".backup '$BACKUP_DIR/screener_$DATE.db'"

# 30일 이상 백업 삭제
find $BACKUP_DIR -name "*.db" -mtime +30 -delete
```

### 4.5.2 아카이빙 (1년 초과 데이터)

```sql
-- 1년 초과 스크리닝 데이터 아카이브 테이블로 이동
INSERT INTO archive_screening_items SELECT * FROM screening_items 
WHERE screening_id IN (SELECT id FROM screenings WHERE screen_date < DATE('now', '-1 year'));

DELETE FROM screening_items 
WHERE screening_id IN (SELECT id FROM screenings WHERE screen_date < DATE('now', '-1 year'));
```

---

## 4.6 문서 이력

| 버전 | 날짜 | 변경 내용 | 작성자 |
|------|------|----------|--------|
| 1.0 | 2025-01-06 | 초안 작성 | Architect AI |

---

**이전 문서:** [03_User_Flows.md](./03_User_Flows.md)  
**다음 문서:** [05_API_Spec.md](./05_API_Spec.md)
