-- v6.3 마이그레이션: 주도섹터 필드 추가
-- 실행: sqlite3 data/screener.db < migrations/v6_3_add_sector_fields.sql

-- closing_top5_history 테이블에 섹터 컬럼 추가
ALTER TABLE closing_top5_history ADD COLUMN sector TEXT;
ALTER TABLE closing_top5_history ADD COLUMN sector_rank INTEGER;
ALTER TABLE closing_top5_history ADD COLUMN is_leading_sector INTEGER DEFAULT 0;

-- 인덱스 추가 (섹터별 분석용)
CREATE INDEX IF NOT EXISTS idx_top5_sector ON closing_top5_history(sector);
CREATE INDEX IF NOT EXISTS idx_top5_leading ON closing_top5_history(is_leading_sector);

-- 확인
SELECT 'v6.3 마이그레이션 완료: sector, sector_rank, is_leading_sector 추가됨' as result;
