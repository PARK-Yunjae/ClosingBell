-- v6.3.2: 종가매매 TOP5 AI 분석 필드 추가
-- 실행: python -c "import sqlite3; c=sqlite3.connect('data/screener.db'); c.executescript(open('migrations/v6_3_2_add_top5_ai.sql').read())"

ALTER TABLE closing_top5_history ADD COLUMN ai_summary TEXT;
ALTER TABLE closing_top5_history ADD COLUMN ai_risk_level TEXT;
ALTER TABLE closing_top5_history ADD COLUMN ai_recommendation TEXT;
