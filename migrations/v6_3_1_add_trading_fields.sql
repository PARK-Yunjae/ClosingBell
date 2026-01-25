-- v6.3.1 마이그레이션: 거래대금/거래량 필드 추가
-- 실행: sqlite3 data/screener.db < migrations/v6_3_1_add_trading_fields.sql

-- closing_top5_history 테이블에 거래 컬럼 추가
ALTER TABLE closing_top5_history ADD COLUMN trading_value REAL;
ALTER TABLE closing_top5_history ADD COLUMN volume INTEGER;

-- 확인
SELECT 'v6.3.1 마이그레이션 완료: trading_value, volume 추가됨' as result;
