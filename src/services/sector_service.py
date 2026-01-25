"""
주도섹터 서비스 v6.3
====================

당일 TV200 유니버스에서 섹터별 강도를 분석하고
주도섹터(상위 3개)를 식별합니다.

사용:
    from src.services.sector_service import SectorService
    
    sector_svc = SectorService()
    leading_sectors = sector_svc.calculate_leading_sectors(candidates)
    sector_info = sector_svc.get_sector_info(stock_code, stock_sector)
"""

import logging
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class SectorStats:
    """섹터 통계"""
    name: str
    stock_count: int
    avg_change_rate: float
    total_trading_value: float  # 억원
    rank: int = 0
    is_leading: bool = False


@dataclass 
class StockSectorInfo:
    """종목의 섹터 정보"""
    sector: str
    sector_rank: int
    is_leading_sector: bool


class SectorService:
    """주도섹터 분석 서비스"""
    
    def __init__(self, leading_count: int = 3, min_stocks_per_sector: int = 3):
        """
        Args:
            leading_count: 주도섹터로 선정할 개수 (기본 3개)
            min_stocks_per_sector: 섹터당 최소 종목 수 (이하면 제외)
        """
        self.leading_count = leading_count
        self.min_stocks_per_sector = min_stocks_per_sector
        
        # 캐시 (당일 1회만 계산)
        self._cached_date: Optional[str] = None
        self._cached_stats: Dict[str, SectorStats] = {}
        self._cached_leading: Set[str] = set()
    
    def calculate_leading_sectors(
        self, 
        candidates: List[Dict],
        cache_date: Optional[str] = None
    ) -> Dict[str, SectorStats]:
        """주도섹터 계산
        
        Args:
            candidates: 스크리닝 후보 종목 리스트
                [{code, name, sector, change_rate, trading_value, ...}, ...]
            cache_date: 캐시용 날짜 (같은 날짜면 재계산 안 함)
        
        Returns:
            섹터별 통계 딕셔너리 {섹터명: SectorStats}
        """
        # 캐시 확인
        if cache_date and cache_date == self._cached_date and self._cached_stats:
            logger.debug(f"주도섹터 캐시 사용: {cache_date}")
            return self._cached_stats
        
        if not candidates:
            logger.warning("주도섹터 계산: 후보 종목 없음")
            return {}
        
        # 섹터별 집계
        sector_data = defaultdict(lambda: {
            'stocks': [],
            'change_rates': [],
            'trading_values': [],
        })
        
        for stock in candidates:
            sector = stock.get('sector') or stock.get('industry') or 'Unknown'
            
            # 섹터명 정규화
            sector = self._normalize_sector(sector)
            
            if sector == 'Unknown':
                continue
            
            change_rate = stock.get('change_rate', 0)
            trading_value = stock.get('trading_value', 0)  # 억원
            
            sector_data[sector]['stocks'].append(stock.get('code'))
            sector_data[sector]['change_rates'].append(change_rate or 0)
            sector_data[sector]['trading_values'].append(trading_value or 0)
        
        # 섹터별 통계 계산
        sector_stats = {}
        
        for sector, data in sector_data.items():
            stock_count = len(data['stocks'])
            
            # 최소 종목 수 체크
            if stock_count < self.min_stocks_per_sector:
                continue
            
            avg_change = sum(data['change_rates']) / stock_count if stock_count > 0 else 0
            total_value = sum(data['trading_values'])
            
            sector_stats[sector] = SectorStats(
                name=sector,
                stock_count=stock_count,
                avg_change_rate=avg_change,
                total_trading_value=total_value,
            )
        
        # 평균 등락률 기준 정렬 및 순위 부여
        sorted_sectors = sorted(
            sector_stats.values(),
            key=lambda x: x.avg_change_rate,
            reverse=True
        )
        
        leading_sectors = set()
        
        for i, stats in enumerate(sorted_sectors, 1):
            stats.rank = i
            stats.is_leading = (i <= self.leading_count)
            
            if stats.is_leading:
                leading_sectors.add(stats.name)
        
        # 캐시 저장
        if cache_date:
            self._cached_date = cache_date
            self._cached_stats = sector_stats
            self._cached_leading = leading_sectors
        
        logger.info(f"주도섹터 계산 완료: {len(sector_stats)}개 섹터, "
                   f"주도섹터: {list(leading_sectors)[:3]}")
        
        return sector_stats
    
    def get_sector_info(
        self, 
        stock_code: str, 
        stock_sector: str,
        sector_stats: Optional[Dict[str, SectorStats]] = None
    ) -> StockSectorInfo:
        """종목의 섹터 정보 조회
        
        Args:
            stock_code: 종목 코드
            stock_sector: 종목의 섹터명
            sector_stats: 섹터 통계 (없으면 캐시 사용)
        
        Returns:
            StockSectorInfo
        """
        stats = sector_stats or self._cached_stats
        
        sector = self._normalize_sector(stock_sector)
        
        if sector in stats:
            s = stats[sector]
            return StockSectorInfo(
                sector=sector,
                sector_rank=s.rank,
                is_leading_sector=s.is_leading,
            )
        
        # 섹터 정보 없음
        return StockSectorInfo(
            sector=sector,
            sector_rank=99,
            is_leading_sector=False,
        )
    
    def get_leading_sectors(self) -> List[str]:
        """현재 캐시된 주도섹터 목록"""
        return list(self._cached_leading)
    
    def get_sector_ranking(self, top_n: int = 10) -> List[SectorStats]:
        """섹터 순위 조회"""
        sorted_sectors = sorted(
            self._cached_stats.values(),
            key=lambda x: x.rank
        )
        return sorted_sectors[:top_n]
    
    def _normalize_sector(self, sector: str) -> str:
        """섹터명 정규화"""
        if not sector:
            return 'Unknown'
        
        sector = sector.strip()
        
        # 일반적인 정규화 (필요시 매핑 추가)
        normalize_map = {
            '전기,전자': '전기·전자',
            '전기/전자': '전기·전자',
            '전기전자': '전기·전자',
            '의약품': '제약',
            '의약': '제약',
            '반도체와반도체장비': '반도체',
            '소프트웨어': 'IT 서비스',
            'SW': 'IT 서비스',
        }
        
        return normalize_map.get(sector, sector)
    
    def format_leading_sectors_text(self, max_show: int = 3) -> str:
        """주도섹터 텍스트 포맷 (Discord 등에서 사용)"""
        if not self._cached_stats:
            return "주도섹터: 데이터 없음"
        
        sorted_sectors = self.get_sector_ranking(max_show)
        
        parts = []
        for s in sorted_sectors:
            emoji = "🔥" if s.is_leading else ""
            parts.append(f"{emoji}{s.name}({s.avg_change_rate:+.1f}%)")
        
        return " > ".join(parts)


# 싱글톤 인스턴스
_sector_service: Optional[SectorService] = None


def get_sector_service() -> SectorService:
    """섹터 서비스 싱글톤"""
    global _sector_service
    if _sector_service is None:
        _sector_service = SectorService()
    return _sector_service
