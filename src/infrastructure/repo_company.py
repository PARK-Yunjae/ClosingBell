"""
repo_company: CompanyProfileRepository, TV200SnapshotRepository
"""

import json
import logging
from datetime import date
from typing import List, Optional, Dict

from src.infrastructure.database import get_database, Database

logger = logging.getLogger(__name__)

class CompanyProfileRepository:
    """DART 기업 프로필 캐시 Repository
    
    company_profiles 테이블 관리
    - 기업개황 (DART)
    - 재무요약 (DART)
    - 위험공시 요약
    """
    
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()
        self._ensure_table()
    
    def _ensure_table(self):
        """테이블 생성 확인"""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS company_profiles (
                stock_code TEXT PRIMARY KEY,
                corp_code TEXT,
                corp_name TEXT,
                corp_name_eng TEXT,
                ceo_nm TEXT,
                corp_cls TEXT,
                induty_code TEXT,
                est_dt TEXT,
                acc_mt TEXT,
                fiscal_year TEXT,
                revenue REAL,
                operating_profit REAL,
                net_income REAL,
                total_equity REAL,
                total_assets REAL,
                has_critical_risk INTEGER DEFAULT 0,
                has_high_risk INTEGER DEFAULT 0,
                risk_level TEXT DEFAULT '낮음',
                risk_summary TEXT,
                updated_at TEXT DEFAULT (datetime('now', 'localtime')),
                data_source TEXT DEFAULT 'DART'
            )
        """)
    
    def get_by_code(self, stock_code: str) -> Optional[Dict]:
        """종목코드로 프로필 조회"""
        row = self.db.fetch_one(
            "SELECT * FROM company_profiles WHERE stock_code = ?",
            (stock_code,)
        )
        return dict(row) if row else None
    
    def upsert(self, stock_code: str, profile: Dict) -> bool:
        """프로필 저장/업데이트
        
        Args:
            stock_code: 종목코드
            profile: get_full_company_profile() 결과
        """
        try:
            basic = profile.get('basic') or {}
            financial = profile.get('financial') or {}
            risk = profile.get('risk') or {}
            
            self.db.execute("""
                INSERT INTO company_profiles (
                    stock_code, corp_code, corp_name, corp_name_eng, ceo_nm,
                    corp_cls, induty_code, est_dt, acc_mt,
                    fiscal_year, revenue, operating_profit, net_income,
                    total_equity, total_assets,
                    has_critical_risk, has_high_risk, risk_level, risk_summary,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
                ON CONFLICT(stock_code) DO UPDATE SET
                    corp_code = excluded.corp_code,
                    corp_name = excluded.corp_name,
                    corp_name_eng = excluded.corp_name_eng,
                    ceo_nm = excluded.ceo_nm,
                    corp_cls = excluded.corp_cls,
                    induty_code = excluded.induty_code,
                    est_dt = excluded.est_dt,
                    acc_mt = excluded.acc_mt,
                    fiscal_year = excluded.fiscal_year,
                    revenue = excluded.revenue,
                    operating_profit = excluded.operating_profit,
                    net_income = excluded.net_income,
                    total_equity = excluded.total_equity,
                    total_assets = excluded.total_assets,
                    has_critical_risk = excluded.has_critical_risk,
                    has_high_risk = excluded.has_high_risk,
                    risk_level = excluded.risk_level,
                    risk_summary = excluded.risk_summary,
                    updated_at = datetime('now', 'localtime')
            """, (
                stock_code,
                basic.get('corp_code'),
                basic.get('corp_name'),
                basic.get('corp_name_eng'),
                basic.get('ceo_nm'),
                basic.get('corp_cls'),
                basic.get('induty_code'),
                basic.get('est_dt'),
                basic.get('acc_mt'),
                financial.get('fiscal_year'),
                financial.get('revenue'),
                financial.get('operating_profit'),
                financial.get('net_income'),
                financial.get('total_equity'),
                financial.get('total_assets'),
                1 if risk.get('has_critical_risk') else 0,
                1 if risk.get('has_high_risk') else 0,
                risk.get('risk_level', '낮음'),
                risk.get('summary'),
            ))
            return True
        except Exception as e:
            logger.error(f"프로필 저장 실패 ({stock_code}): {e}")
            return False
    
    def get_all(self, limit: int = 100) -> List[Dict]:
        """전체 프로필 조회"""
        rows = self.db.fetch_all(
            "SELECT * FROM company_profiles ORDER BY updated_at DESC LIMIT ?",
            (limit,)
        )
        return [dict(r) for r in rows]
    
    def get_cached_count(self) -> int:
        """캐시된 프로필 수"""
        row = self.db.fetch_one("SELECT COUNT(*) as cnt FROM company_profiles")
        return row['cnt'] if row else 0
    
    def is_stale(self, stock_code: str, hours: int = 24) -> bool:
        """캐시가 오래되었는지 확인
        
        Args:
            stock_code: 종목코드
            hours: TTL (시간)
        """
        row = self.db.fetch_one(
            """
            SELECT updated_at,
                   (julianday('now', 'localtime') - julianday(updated_at)) * 24 as age_hours
            FROM company_profiles
            WHERE stock_code = ?
            """,
            (stock_code,)
        )
        if not row:
            return True  # 캐시 없음 = stale
        return row['age_hours'] > hours
    
    def delete(self, stock_code: str) -> bool:
        """프로필 삭제"""
        try:
            self.db.execute(
                "DELETE FROM company_profiles WHERE stock_code = ?",
                (stock_code,)
            )
            return True
        except Exception:
            return False


def get_company_profile_repository() -> CompanyProfileRepository:
    """CompanyProfileRepository 인스턴스 반환"""
    return CompanyProfileRepository()


# v6.0 Repository 편의 함수들





# ============================================================
# v8.0: BrokerSignalRepository - 거래원 수급 신호
# ============================================================

class TV200SnapshotRepository:
    """TV200 조건검색 결과 스냅샷 저장소 (v6.3.3)
    
    유니버스 소스 오브 트루스(Source of Truth)를 저장하여
    백필에서 실시간과 동일한 유니버스를 사용할 수 있도록 함
    """
    
    def __init__(self, db: Database = None):
        self.db = db or get_database()
        self._ensure_table()
    
    def _ensure_table(self):
        """테이블이 없으면 생성"""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS tv200_snapshot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                screen_date TEXT NOT NULL,
                run_at TEXT NOT NULL,
                source TEXT DEFAULT 'TV200',
                filter_stage TEXT DEFAULT 'after',
                stock_count INTEGER DEFAULT 0,
                codes_json TEXT,
                names_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(screen_date, filter_stage)
            )
        """)
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_tv200_snapshot_date ON tv200_snapshot(screen_date)"
        )
    
    def save_snapshot(
        self,
        screen_date: str,
        codes: List[str],
        names: Dict[str, str] = None,
        filter_stage: str = 'after',
        source: str = 'TV200',
    ) -> int:
        """TV200 스냅샷 저장
        
        Args:
            screen_date: 스크리닝 기준 날짜 (YYYY-MM-DD)
            codes: 종목코드 리스트
            names: 종목코드 → 종목명 매핑 (선택)
            filter_stage: 'before' (필터 전) 또는 'after' (필터 후)
            source: 소스 (TV200, manual 등)
            
        Returns:
            저장된 row ID (업데이트 시에도 ID 반환)
        """
        import json
        from datetime import datetime
        
        codes_json = json.dumps(codes, ensure_ascii=False)
        names_json = json.dumps(names, ensure_ascii=False) if names else None
        run_at = datetime.now().isoformat()
        
        cursor = self.db.execute(
            """
            INSERT INTO tv200_snapshot 
                (screen_date, run_at, source, filter_stage, stock_count, codes_json, names_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(screen_date, filter_stage) DO UPDATE SET
                run_at = excluded.run_at,
                source = excluded.source,
                stock_count = excluded.stock_count,
                codes_json = excluded.codes_json,
                names_json = excluded.names_json
            """,
            (screen_date, run_at, source, filter_stage, len(codes), codes_json, names_json)
        )
        
        # 저장된 ID 조회
        row = self.db.fetch_one(
            "SELECT id FROM tv200_snapshot WHERE screen_date = ? AND filter_stage = ?",
            (screen_date, filter_stage)
        )
        
        logger.info(f"TV200 스냅샷 저장: {screen_date} ({filter_stage}) - {len(codes)}개")
        return row['id'] if row else 0
    
    def get_snapshot(
        self,
        screen_date: str,
        filter_stage: str = 'after'
    ) -> Optional[Dict]:
        """특정 날짜의 TV200 스냅샷 조회
        
        Args:
            screen_date: 스크리닝 날짜 (YYYY-MM-DD)
            filter_stage: 'before' 또는 'after'
            
        Returns:
            스냅샷 정보 dict 또는 None
        """
        import json
        
        row = self.db.fetch_one(
            """
            SELECT * FROM tv200_snapshot 
            WHERE screen_date = ? AND filter_stage = ?
            """,
            (screen_date, filter_stage)
        )
        
        if not row:
            return None
        
        result = dict(row)
        result['codes'] = json.loads(result['codes_json']) if result['codes_json'] else []
        result['names'] = json.loads(result['names_json']) if result['names_json'] else {}
        
        return result
    
    def get_codes_for_date(
        self,
        screen_date: str,
        filter_stage: str = 'after'
    ) -> List[str]:
        """특정 날짜의 유니버스 코드 리스트만 반환
        
        Args:
            screen_date: 스크리닝 날짜 (YYYY-MM-DD)
            filter_stage: 'before' 또는 'after'
            
        Returns:
            종목코드 리스트 (없으면 빈 리스트)
        """
        snapshot = self.get_snapshot(screen_date, filter_stage)
        return snapshot['codes'] if snapshot else []
    
    def has_snapshot(self, screen_date: str, filter_stage: str = 'after') -> bool:
        """해당 날짜에 스냅샷이 있는지 확인"""
        row = self.db.fetch_one(
            "SELECT 1 FROM tv200_snapshot WHERE screen_date = ? AND filter_stage = ?",
            (screen_date, filter_stage)
        )
        return row is not None
    
    def get_all_dates(self, filter_stage: str = 'after') -> List[str]:
        """스냅샷이 있는 모든 날짜 목록"""
        rows = self.db.fetch_all(
            """
            SELECT screen_date FROM tv200_snapshot 
            WHERE filter_stage = ? 
            ORDER BY screen_date DESC
            """,
            (filter_stage,)
        )
        return [row['screen_date'] for row in rows]
    
    def compare_universe(
        self,
        screen_date: str,
        backfill_codes: List[str]
    ) -> Dict:
        """TV200 유니버스와 백필 유니버스 비교
        
        Args:
            screen_date: 스크리닝 날짜
            backfill_codes: 백필로 재현한 종목코드 리스트
            
        Returns:
            비교 결과 dict
        """
        tv200_codes = self.get_codes_for_date(screen_date)
        
        if not tv200_codes:
            return {
                'tv200_count': 0,
                'backfill_count': len(backfill_codes),
                'common_count': 0,
                'only_in_tv200': [],
                'only_in_backfill': backfill_codes,
                'match_rate': 0.0,
                'has_snapshot': False,
            }
        
        tv200_set = set(tv200_codes)
        backfill_set = set(backfill_codes)
        
        common = tv200_set & backfill_set
        only_tv200 = tv200_set - backfill_set
        only_backfill = backfill_set - tv200_set
        
        match_rate = len(common) / len(tv200_set) * 100 if tv200_set else 0
        
        return {
            'tv200_count': len(tv200_codes),
            'backfill_count': len(backfill_codes),
            'common_count': len(common),
            'only_in_tv200': sorted(list(only_tv200)),
            'only_in_backfill': sorted(list(only_backfill)),
            'match_rate': match_rate,
            'has_snapshot': True,
        }
    
    def get_summary_stats(self) -> Dict:
        """스냅샷 통계"""
        row = self.db.fetch_one(
            """
            SELECT 
                COUNT(DISTINCT screen_date) as total_dates,
                MIN(screen_date) as first_date,
                MAX(screen_date) as last_date,
                AVG(stock_count) as avg_count
            FROM tv200_snapshot
            WHERE filter_stage = 'after'
            """
        )
        return dict(row) if row else {}


def get_tv200_snapshot_repository() -> TV200SnapshotRepository:
    return TV200SnapshotRepository()


# ============================================================
# v6.5 DART 연동: CompanyProfileRepository
# ============================================================
