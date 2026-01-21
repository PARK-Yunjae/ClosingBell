-- ClosingBell v6.1 Schema Migration
-- 네이버 금융 기업정보 추가 컬럼
-- 실행: sqlite3 data/screener.db < migrations/v6_1_add_company_fields.sql

-- =============================================================================
-- nomad_candidates 테이블에 새 컬럼 추가
-- =============================================================================

-- BPS (주당순자산)
ALTER TABLE nomad_candidates ADD COLUMN bps REAL;

-- 외국인 정보
ALTER TABLE nomad_candidates ADD COLUMN foreign_rate REAL;  -- 외국인 보유율
ALTER TABLE nomad_candidates ADD COLUMN foreign_shares INTEGER;  -- 외국인 보유주수

-- 투자의견
ALTER TABLE nomad_candidates ADD COLUMN analyst_opinion REAL;  -- 투자의견 점수 (1~5)
ALTER TABLE nomad_candidates ADD COLUMN analyst_recommend TEXT;  -- 매수/매도/중립
ALTER TABLE nomad_candidates ADD COLUMN target_price INTEGER;  -- 목표주가

-- 52주 최고/최저
ALTER TABLE nomad_candidates ADD COLUMN high_52w INTEGER;
ALTER TABLE nomad_candidates ADD COLUMN low_52w INTEGER;

-- 시가총액 순위
ALTER TABLE nomad_candidates ADD COLUMN market_cap_rank INTEGER;

-- 추정 PER/EPS (컨센서스)
ALTER TABLE nomad_candidates ADD COLUMN consensus_per REAL;
ALTER TABLE nomad_candidates ADD COLUMN consensus_eps REAL;

-- 배당수익률
ALTER TABLE nomad_candidates ADD COLUMN dividend_yield REAL;

-- 수집 플래그 (이미 있을 수 있음)
-- ALTER TABLE nomad_candidates ADD COLUMN company_info_collected INTEGER DEFAULT 0;
-- ALTER TABLE nomad_candidates ADD COLUMN news_collected INTEGER DEFAULT 0;

-- =============================================================================
-- nomad_news 테이블에 candidate_id 추가 (있으면 무시)
-- =============================================================================
-- ALTER TABLE nomad_news ADD COLUMN candidate_id INTEGER;
