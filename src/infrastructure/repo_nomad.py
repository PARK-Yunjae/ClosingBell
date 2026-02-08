"""
repo_nomad: NomadCandidatesRepository, NomadNewsRepository
"""

import json
import logging
from datetime import date
from typing import List, Optional, Dict

from src.infrastructure.database import get_database, Database

logger = logging.getLogger(__name__)

class NomadCandidatesRepository:
    """nomad_candidates 테이블 CRUD"""
    
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()
    
    def upsert(self, data: dict) -> int:
        """후보 삽입/갱신"""
        existing = self.db.fetch_one(
            "SELECT id FROM nomad_candidates WHERE study_date = ? AND stock_code = ?",
            (data['study_date'], data['stock_code'])
        )
        
        if existing:
            self.db.execute(
                """
                UPDATE nomad_candidates SET
                    stock_name = ?, reason_flag = ?, close_price = ?, change_rate = ?,
                    volume = ?, trading_value = ?, data_source = ?
                WHERE id = ?
                """,
                (
                    data['stock_name'], data['reason_flag'], data['close_price'],
                    data['change_rate'], data['volume'], data['trading_value'],
                    data.get('data_source', 'realtime'), existing['id']
                )
            )
            return existing['id']
        else:
            cursor = self.db.execute(
                """
                INSERT INTO nomad_candidates
                (study_date, stock_code, stock_name, reason_flag, close_price, change_rate,
                 volume, trading_value, data_source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data['study_date'], data['stock_code'], data['stock_name'],
                    data['reason_flag'], data['close_price'], data['change_rate'],
                    data['volume'], data['trading_value'],
                    data.get('data_source', 'realtime')
                )
            )
            return cursor.lastrowid
    
    def insert(self, data: dict) -> int:
        """후보 삽입 (upsert 별칭) - nomad_collector 호환용"""
        return self.upsert(data)
    
    def get_by_date(self, study_date: str) -> List[dict]:
        """특정 날짜의 후보"""
        rows = self.db.fetch_all(
            "SELECT * FROM nomad_candidates WHERE study_date = ? ORDER BY change_rate DESC",
            (study_date,)
        )
        return [dict(row) for row in rows]
    
    def get_by_date_and_reason(self, study_date: str, reason_flag: str) -> List[dict]:
        """날짜 + 사유로 조회"""
        rows = self.db.fetch_all(
            "SELECT * FROM nomad_candidates WHERE study_date = ? AND reason_flag = ? ORDER BY change_rate DESC",
            (study_date, reason_flag)
        )
        return [dict(row) for row in rows]
    
    def get_by_date_and_code(self, study_date: str, stock_code: str) -> Optional[dict]:
        """특정 종목 조회"""
        row = self.db.fetch_one(
            "SELECT * FROM nomad_candidates WHERE study_date = ? AND stock_code = ?",
            (study_date, stock_code)
        )
        return dict(row) if row else None
    
    def update_company_info(self, study_date: str, stock_code: str, info: dict):
        """기업 정보 업데이트"""
        self.db.execute(
            """
            UPDATE nomad_candidates SET
                market = ?, sector = ?, market_cap = ?, per = ?, pbr = ?,
                eps = ?, roe = ?, business_summary = ?, establishment_date = ?,
                ceo_name = ?, revenue = ?, operating_profit = ?
            WHERE study_date = ? AND stock_code = ?
            """,
            (
                info.get('market'), info.get('sector'), info.get('market_cap'),
                info.get('per'), info.get('pbr'), info.get('eps'), info.get('roe'),
                info.get('business_summary'), info.get('establishment_date'),
                info.get('ceo_name'), info.get('revenue'), info.get('operating_profit'),
                study_date, stock_code
            )
        )
    
    def update_news_status(self, study_date: str, stock_code: str, status: str, count: int):
        """뉴스 상태 업데이트"""
        self.db.execute(
            "UPDATE nomad_candidates SET news_status = ?, news_count = ? WHERE study_date = ? AND stock_code = ?",
            (status, count, study_date, stock_code)
        )
    
    def update_ai_summary_by_date(self, study_date: str, stock_code: str, summary: str):
        """AI 요약 업데이트 (날짜+종목코드 기준)"""
        self.db.execute(
            "UPDATE nomad_candidates SET ai_summary = ? WHERE study_date = ? AND stock_code = ?",
            (summary, study_date, stock_code)
        )
    
    def get_dates_with_data(self, days: int = 60) -> List[str]:
        """데이터가 있는 날짜 목록"""
        rows = self.db.fetch_all(
            "SELECT DISTINCT study_date FROM nomad_candidates ORDER BY study_date DESC LIMIT ?",
            (days,)
        )
        return [row['study_date'] for row in rows]
    
    def get_uncollected_news(self, limit: int = 20) -> List[dict]:
        """뉴스 미수집 후보 조회"""
        rows = self.db.fetch_all(
            """
            SELECT * FROM nomad_candidates 
            WHERE news_collected = 0 OR news_collected IS NULL
            ORDER BY study_date DESC, change_rate DESC
            LIMIT ?
            """,
            (limit,)
        )
        return [dict(row) for row in rows]
    
    def delete_by_date(self, study_date: str):
        """특정 날짜의 후보 삭제 (재수집용)
        
        Args:
            study_date: 삭제할 날짜 (YYYY-MM-DD)
        """
        # 관련 뉴스도 함께 삭제
        self.db.execute(
            "DELETE FROM nomad_news WHERE study_date = ?",
            (study_date,)
        )
        self.db.execute(
            "DELETE FROM nomad_candidates WHERE study_date = ?",
            (study_date,)
        )
        logger.info(f"  날짜 {study_date} 데이터 삭제 완료")
    
    def update_news_collected(self, candidate_id: int, news_count: int = 0):
        """뉴스 수집 완료 표시 (news_count 업데이트 포함)
        
        Args:
            candidate_id: 후보 ID
            news_count: 수집된 뉴스 개수 (0이면 nomad_news 테이블에서 카운트)
        """
        if news_count == 0:
            # study_date, stock_code로 실제 뉴스 개수 조회
            candidate = self.db.fetch_one(
                "SELECT study_date, stock_code FROM nomad_candidates WHERE id = ?",
                (candidate_id,)
            )
            if candidate:
                count_row = self.db.fetch_one(
                    "SELECT COUNT(*) as cnt FROM nomad_news WHERE study_date = ? AND stock_code = ?",
                    (candidate['study_date'], candidate['stock_code'])
                )
                news_count = count_row['cnt'] if count_row else 0
        
        self.db.execute(
            """UPDATE nomad_candidates 
               SET news_collected = 1, news_count = ?, news_status = 'collected', updated_at = CURRENT_TIMESTAMP 
               WHERE id = ?""",
            (news_count, candidate_id)
        )
    
    def get_uncollected_company_info(self, limit: int = 20) -> List[dict]:
        """기업정보 미수집 후보 조회"""
        rows = self.db.fetch_all(
            """
            SELECT * FROM nomad_candidates 
            WHERE company_info_collected = 0 OR company_info_collected IS NULL
            ORDER BY study_date DESC, change_rate DESC
            LIMIT ?
            """,
            (limit,)
        )
        return [dict(row) for row in rows]
    
    def update_company_info_by_id(self, candidate_id: int, info: dict):
        """기업 정보 업데이트 (ID 기준) - v6.1 확장"""
        self.db.execute(
            """
            UPDATE nomad_candidates SET
                -- 기본 정보
                market = ?, sector = ?, market_cap = ?, market_cap_rank = ?,
                -- 밸류에이션
                per = ?, pbr = ?, eps = ?, bps = ?, roe = ?,
                -- 컨센서스
                consensus_per = ?, consensus_eps = ?,
                -- 외국인
                foreign_rate = ?, foreign_shares = ?,
                -- 투자의견
                analyst_opinion = ?, analyst_recommend = ?, target_price = ?,
                -- 52주
                high_52w = ?, low_52w = ?,
                -- 배당
                dividend_yield = ?,
                -- 기업상세
                business_summary = ?, establishment_date = ?,
                ceo_name = ?, revenue = ?, operating_profit = ?,
                -- 메타
                company_info_collected = 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                # 기본 정보
                info.get('market'), info.get('sector'), info.get('market_cap'), info.get('market_cap_rank'),
                # 밸류에이션
                info.get('per'), info.get('pbr'), info.get('eps'), info.get('bps'), info.get('roe'),
                # 컨센서스
                info.get('consensus_per'), info.get('consensus_eps'),
                # 외국인
                info.get('foreign_rate'), info.get('foreign_shares'),
                # 투자의견
                info.get('analyst_opinion'), info.get('analyst_recommend'), info.get('target_price'),
                # 52주
                info.get('high_52w'), info.get('low_52w'),
                # 배당
                info.get('dividend_yield'),
                # 기업상세
                info.get('business_summary'), info.get('establishment_date'),
                info.get('ceo_name'), info.get('revenue'), info.get('operating_profit'),
                # ID
                candidate_id
            )
        )
    
    def update_company_info_by_code(self, stock_code: str, info: dict):
        """기업 정보 업데이트 (종목코드 기준) - v6.2"""
        self.db.execute(
            """
            UPDATE nomad_candidates SET
                market = ?, sector = ?, market_cap = ?, market_cap_rank = ?,
                per = ?, pbr = ?, eps = ?, bps = ?, roe = ?,
                consensus_per = ?, consensus_eps = ?,
                foreign_rate = ?, foreign_shares = ?,
                analyst_opinion = ?, analyst_recommend = ?, target_price = ?,
                high_52w = ?, low_52w = ?,
                dividend_yield = ?,
                business_summary = ?, establishment_date = ?,
                ceo_name = ?, revenue = ?, operating_profit = ?,
                company_info_collected = 1, updated_at = CURRENT_TIMESTAMP
            WHERE stock_code = ?
            """,
            (
                info.get('market'), info.get('sector'), info.get('market_cap'), info.get('market_cap_rank'),
                info.get('per'), info.get('pbr'), info.get('eps'), info.get('bps'), info.get('roe'),
                info.get('consensus_per'), info.get('consensus_eps'),
                info.get('foreign_rate'), info.get('foreign_shares'),
                info.get('analyst_opinion'), info.get('analyst_recommend'), info.get('target_price'),
                info.get('high_52w'), info.get('low_52w'),
                info.get('dividend_yield'),
                info.get('business_summary'), info.get('establishment_date'),
                info.get('ceo_name'), info.get('revenue'), info.get('operating_profit'),
                stock_code
            )
        )
    
    def update_ai_summary(self, candidate_id: int, summary: str):
        """AI 요약 업데이트 (ID 기준) - v6.2"""
        self.db.execute(
            "UPDATE nomad_candidates SET ai_summary = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (summary, candidate_id)
        )
    
    def search_occurrences(self, query: str, limit: int = 200) -> List[dict]:
        """종목 검색 - 유목민 출현 기록 조회 (v6.3.2)
        
        종목코드 또는 종목명으로 검색하여 해당 종목이 유목민에 등장한 날짜들을 반환
        
        Args:
            query: 종목코드(6자리) 또는 종목명 일부
            limit: 최대 결과 수
            
        Returns:
            출현 기록 리스트 (최신 날짜 순)
        """
        # 6자리 숫자면 종목코드로 검색
        if query.isdigit() and len(query) == 6:
            rows = self.db.fetch_all(
                """
                SELECT study_date, stock_code, stock_name, reason_flag, 
                       close_price, change_rate, volume, trading_value, data_source
                FROM nomad_candidates 
                WHERE stock_code = ?
                ORDER BY study_date DESC
                LIMIT ?
                """,
                (query, limit)
            )
        else:
            # 종목명으로 검색 (LIKE)
            rows = self.db.fetch_all(
                """
                SELECT study_date, stock_code, stock_name, reason_flag, 
                       close_price, change_rate, volume, trading_value, data_source
                FROM nomad_candidates 
                WHERE stock_name LIKE ?
                ORDER BY study_date DESC
                LIMIT ?
                """,
                (f'%{query}%', limit)
            )
        
        return [dict(row) for row in rows]


class NomadNewsRepository:
    """nomad_news 테이블 CRUD (v6.0)"""
    
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()
    
    def insert(self, data: dict) -> int:
        """뉴스 삽입 (study_date + stock_code 사용)"""
        # study_date, stock_code 필수
        study_date = data.get('study_date') or data.get('news_date')
        stock_code = data.get('stock_code')
        news_url = data.get('news_url') or data.get('url', '')
        
        if not study_date or not stock_code:
            raise ValueError("study_date, stock_code 필수")
        
        # 중복 체크 (study_date + stock_code + url)
        existing = self.db.fetch_one(
            "SELECT id FROM nomad_news WHERE study_date = ? AND stock_code = ? AND url = ?",
            (study_date, stock_code, news_url)
        )
        
        if existing:
            return existing['id']
        
        cursor = self.db.execute(
            """
            INSERT INTO nomad_news
            (study_date, stock_code, title, publisher, published_at, url, snippet)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                study_date,
                stock_code,
                data.get('news_title') or data.get('title', '')[:200],
                data.get('news_source') or data.get('publisher', ''),
                data.get('published_at') or data.get('news_date'),
                news_url,
                data.get('summary') or data.get('snippet', ''),
            )
        )
        return cursor.lastrowid
    
    def get_by_candidate_id(self, candidate_id: int) -> List[dict]:
        """후보 ID로 뉴스 조회 (deprecated - get_by_candidate 사용)"""
        # candidate_id로 study_date, stock_code 조회
        candidate = self.db.fetch_one(
            "SELECT study_date, stock_code FROM nomad_candidates WHERE id = ?",
            (candidate_id,)
        )
        if not candidate:
            return []
        return self.get_by_candidate(candidate['study_date'], candidate['stock_code'])
    
    def get_by_candidate(self, study_date: str, stock_code: str) -> List[dict]:
        """후보의 뉴스 조회 (날짜+종목코드)"""
        # nomad_news 테이블에서 직접 조회 (candidate_id 없이)
        rows = self.db.fetch_all(
            "SELECT * FROM nomad_news WHERE study_date = ? AND stock_code = ? ORDER BY published_at DESC",
            (study_date, stock_code)
        )
        
        if not rows:
            return []
        
        # 필드명 호환 매핑 (대시보드용)
        result = []
        for row in rows:
            item = dict(row)
            # 호환성 필드 추가
            item['news_title'] = item.get('title', '')
            item['news_url'] = item.get('url', '')
            item['news_source'] = item.get('publisher', '')
            item['news_date'] = item.get('published_at', '')
            item['summary'] = item.get('snippet', '')
            item['sentiment'] = '중립'  # 기본값
            result.append(item)
        
        return result
    
    def count_by_candidate(self, study_date: str, stock_code: str) -> int:
        """후보의 뉴스 개수"""
        row = self.db.fetch_one(
            "SELECT COUNT(*) as cnt FROM nomad_news WHERE study_date = ? AND stock_code = ?",
            (study_date, stock_code)
        )
        return row['cnt'] if row else 0
    
    def get_summary_stats(self) -> dict:
        """뉴스 통계"""
        row = self.db.fetch_one(
            """
            SELECT 
                COUNT(*) as total_news,
                COUNT(DISTINCT candidate_id) as candidates_with_news,
                SUM(CASE WHEN sentiment = 'positive' THEN 1 ELSE 0 END) as positive,
                SUM(CASE WHEN sentiment = 'negative' THEN 1 ELSE 0 END) as negative,
                SUM(CASE WHEN sentiment = 'neutral' THEN 1 ELSE 0 END) as neutral
            FROM nomad_news
            """
        )
        return dict(row) if row else {}


# ============================================================
# TV200 스냅샷 Repository (v6.3.3)
# ============================================================


def get_nomad_candidates_repository() -> NomadCandidatesRepository:
    return NomadCandidatesRepository()


def get_nomad_news_repository() -> NomadNewsRepository:
    return NomadNewsRepository()

