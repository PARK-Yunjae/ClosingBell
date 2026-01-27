"""
EnrichmentService v6.5

TOP5 종목에 기업정보/공시/뉴스를 한 번에 붙이는 서비스

기능:
- DART 기업개황 + 재무제표 + 위험공시
- 네이버 뉴스 헤드라인
- PER/PBR/ROE 계산
- 병렬 처리 (속도 최적화)
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from src.config.constants import get_top_n_count

logger = logging.getLogger(__name__)


# ============================================================
# 데이터 모델
# ============================================================

@dataclass
class CompanyProfile:
    """DART 기업 프로필"""
    corp_code: str = ""
    corp_name: str = ""
    ceo_nm: str = ""
    corp_cls: str = ""  # Y:유가, K:코스닥
    induty_code: str = ""
    est_dt: str = ""
    acc_mt: str = ""
    
    @property
    def market_name(self) -> str:
        return {'Y': '유가증권', 'K': '코스닥', 'N': '코넥스'}.get(self.corp_cls, '-')


@dataclass
class FinancialSummary:
    """DART 재무 요약"""
    fiscal_year: str = ""
    revenue: float = 0.0           # 매출액 (억원)
    operating_profit: float = 0.0  # 영업이익 (억원)
    net_income: float = 0.0        # 순이익 (억원)
    total_equity: float = 0.0      # 자본총계 (억원)
    total_assets: float = 0.0      # 자산총계 (억원)


@dataclass
class RiskInfo:
    """DART 위험공시 정보"""
    has_critical_risk: bool = False
    has_high_risk: bool = False
    risk_level: str = "낮음"
    risk_disclosures: List[Dict] = field(default_factory=list)
    summary: str = ""


@dataclass
class NewsItem:
    """뉴스 아이템"""
    title: str
    source: str = ""
    pub_date: str = ""
    link: str = ""


@dataclass
class CalculatedMetrics:
    """계산된 지표 (PER/PBR/ROE)"""
    per: Optional[float] = None
    pbr: Optional[float] = None
    roe: Optional[float] = None
    
    @staticmethod
    def calculate(market_cap: float, net_income: float, total_equity: float) -> 'CalculatedMetrics':
        """PER/PBR/ROE 계산
        
        Args:
            market_cap: 시가총액 (억원)
            net_income: 순이익 (억원)
            total_equity: 자본총계 (억원)
        """
        per = None
        pbr = None
        roe = None
        
        # PER = 시가총액 / 순이익
        if net_income and net_income > 0:
            per = round(market_cap / net_income, 2)
        
        # PBR = 시가총액 / 자본총계
        if total_equity and total_equity > 0:
            pbr = round(market_cap / total_equity, 2)
        
        # ROE = 순이익 / 자본총계 * 100
        if total_equity and total_equity > 0 and net_income:
            roe = round((net_income / total_equity) * 100, 2)
        
        return CalculatedMetrics(per=per, pbr=pbr, roe=roe)


@dataclass
class EnrichedStock:
    """Enrichment 결과가 붙은 종목"""
    
    # 원본 스크리닝 데이터
    stock_code: str
    stock_name: str
    rank: int = 0
    screen_score: float = 0.0
    grade: str = ""
    screen_price: int = 0
    change_rate: float = 0.0
    market_cap: float = 0.0       # 시가총액 (억원)
    trading_value: float = 0.0    # 거래대금 (억원)
    
    # 기술적 지표
    cci: float = 0.0
    disparity_20: float = 0.0
    consecutive_up: int = 0
    volume_ratio: float = 0.0
    
    # 섹터 정보
    sector: str = ""
    is_leading_sector: bool = False
    sector_rank: int = 99
    
    # Enrichment 결과
    company_profile: Optional[CompanyProfile] = None
    financial: Optional[FinancialSummary] = None
    risk: Optional[RiskInfo] = None
    news: List[NewsItem] = field(default_factory=list)
    calculated: Optional[CalculatedMetrics] = None
    
    # 메타
    enriched_at: str = ""
    enrich_errors: List[str] = field(default_factory=list)
    
    @classmethod
    def from_stock_score(cls, score: Any, rank: int = 0) -> 'EnrichedStock':
        """StockScoreV5에서 EnrichedStock 생성"""
        return cls(
            stock_code=getattr(score, 'stock_code', '') or getattr(score, 'code', ''),
            stock_name=getattr(score, 'stock_name', '') or getattr(score, 'name', ''),
            rank=rank,
            screen_score=getattr(score, 'screen_score', 0) or getattr(score, 'score', 0),
            grade=getattr(score, 'grade', ''),
            screen_price=getattr(score, 'screen_price', 0) or getattr(score, 'price', 0),
            change_rate=getattr(score, 'change_rate', 0.0),
            market_cap=getattr(score, 'market_cap', 0.0),
            trading_value=getattr(score, 'trading_value', 0.0),
            cci=getattr(score, 'cci', 0.0),
            disparity_20=getattr(score, 'disparity_20', 0.0),
            consecutive_up=getattr(score, 'consecutive_up', 0),
            volume_ratio=getattr(score, 'volume_ratio', 0.0),
            sector=getattr(score, 'sector', ''),
            is_leading_sector=getattr(score, 'is_leading_sector', False),
            sector_rank=getattr(score, 'sector_rank', 99),
        )
    
    def to_dict(self) -> Dict:
        """딕셔너리 변환"""
        return {
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'rank': self.rank,
            'screen_score': self.screen_score,
            'grade': self.grade,
            'screen_price': self.screen_price,
            'change_rate': self.change_rate,
            'market_cap': self.market_cap,
            'trading_value': self.trading_value,
            'cci': self.cci,
            'disparity_20': self.disparity_20,
            'consecutive_up': self.consecutive_up,
            'sector': self.sector,
            'is_leading_sector': self.is_leading_sector,
            'sector_rank': self.sector_rank,
            # Enrichment
            'company_profile': self.company_profile.__dict__ if self.company_profile else None,
            'financial': self.financial.__dict__ if self.financial else None,
            'risk': {
                'has_critical_risk': self.risk.has_critical_risk,
                'has_high_risk': self.risk.has_high_risk,
                'risk_level': self.risk.risk_level,
                'summary': self.risk.summary,
            } if self.risk else None,
            'news': [{'title': n.title, 'source': n.source} for n in self.news[:3]],
            'calculated': self.calculated.__dict__ if self.calculated else None,
            'enriched_at': self.enriched_at,
        }


# ============================================================
# EnrichmentService
# ============================================================

class EnrichmentService:
    """TOP5 종목에 기업정보/공시/뉴스를 붙이는 서비스"""
    
    def __init__(self, max_workers: int = 5, timeout: int = 30):
        """
        Args:
            max_workers: 병렬 처리 스레드 수
            timeout: 개별 작업 타임아웃 (초)
        """
        self.max_workers = max_workers
        self.timeout = timeout
        
        # 서비스 로드 (lazy)
        self._dart = None
        self._news_available = False
        
    @property
    def dart(self):
        """DART 서비스 (lazy load)"""
        if self._dart is None:
            try:
                from src.services.dart_service import get_dart_service
                self._dart = get_dart_service()
            except ImportError:
                logger.warning("dart_service 로드 실패")
                self._dart = None
        return self._dart
    
    def enrich_single(self, stock: EnrichedStock) -> EnrichedStock:
        """단일 종목 Enrichment
        
        Args:
            stock: EnrichedStock 객체
        
        Returns:
            Enrichment 결과가 추가된 EnrichedStock
        """
        stock.enriched_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 1. DART 기업정보 + 재무 + 위험공시
        if self.dart:
            try:
                profile = self.dart.get_full_company_profile(
                    stock.stock_code, 
                    stock.stock_name,
                    include_risk=True,
                    cache_to_db=True
                )
                
                # 기업개황
                basic = profile.get('basic')
                if basic:
                    stock.company_profile = CompanyProfile(
                        corp_code=basic.get('corp_code', ''),
                        corp_name=basic.get('corp_name', stock.stock_name),
                        ceo_nm=basic.get('ceo_nm', ''),
                        corp_cls=basic.get('corp_cls', ''),
                        induty_code=basic.get('induty_code', ''),
                        est_dt=basic.get('est_dt', ''),
                        acc_mt=basic.get('acc_mt', ''),
                    )
                
                # 재무요약
                fin = profile.get('financial')
                if fin:
                    stock.financial = FinancialSummary(
                        fiscal_year=fin.get('fiscal_year', ''),
                        revenue=fin.get('revenue') or 0.0,
                        operating_profit=fin.get('operating_profit') or 0.0,
                        net_income=fin.get('net_income') or 0.0,
                        total_equity=fin.get('total_equity') or 0.0,
                        total_assets=fin.get('total_assets') or 0.0,
                    )
                    
                    # PER/PBR/ROE 계산
                    if stock.market_cap > 0:
                        stock.calculated = CalculatedMetrics.calculate(
                            market_cap=stock.market_cap,
                            net_income=stock.financial.net_income,
                            total_equity=stock.financial.total_equity,
                        )
                
                # 위험공시
                risk = profile.get('risk')
                if risk:
                    stock.risk = RiskInfo(
                        has_critical_risk=risk.get('has_critical_risk', False),
                        has_high_risk=risk.get('has_high_risk', False),
                        risk_level=risk.get('risk_level', '낮음'),
                        risk_disclosures=risk.get('risk_disclosures', []),
                        summary=risk.get('summary', ''),
                    )
                    
            except Exception as e:
                logger.warning(f"DART Enrichment 실패 ({stock.stock_code}): {e}")
                stock.enrich_errors.append(f"DART: {str(e)[:50]}")
        
        # 2. 뉴스 수집
        try:
            from src.services.news_service import search_naver_news
            
            news_list = search_naver_news(stock.stock_name, display=5, sort='date')
            stock.news = [
                NewsItem(
                    title=n.get('title', ''),
                    source=n.get('source', ''),
                    pub_date=n.get('pub_date', ''),
                    link=n.get('link', ''),
                )
                for n in news_list[:3]
            ]
        except ImportError:
            logger.debug("news_service 로드 실패")
        except Exception as e:
            logger.warning(f"뉴스 수집 실패 ({stock.stock_code}): {e}")
            stock.enrich_errors.append(f"News: {str(e)[:50]}")
        
        return stock
    
    def enrich_top5(self, scores: List[Any], parallel: bool = True, max_stocks: int = None) -> List[EnrichedStock]:
        """TOP5 종목에 풀 정보 추가
        
        Args:
            scores: StockScoreV5 리스트 (또는 유사 객체)
            parallel: 병렬 처리 여부
            max_stocks: 최대 종목 수 (None이면 설정에서)
        
        Returns:
            EnrichedStock 리스트
        """
        if not scores:
            return []
        
        # ★ P0-B: TOP_N_COUNT 설정 통일
        top_n = max_stocks if max_stocks else get_top_n_count()
        
        # EnrichedStock 변환
        enriched_stocks = [
            EnrichedStock.from_stock_score(score, rank=i+1)
            for i, score in enumerate(scores[:top_n])
        ]
        
        logger.info(f"🔍 Enrichment 시작: {len(enriched_stocks)}개 종목")
        
        if parallel and len(enriched_stocks) > 1:
            # 병렬 처리
            results = []
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_stock = {
                    executor.submit(self.enrich_single, stock): stock
                    for stock in enriched_stocks
                }
                
                for future in as_completed(future_to_stock, timeout=self.timeout):
                    try:
                        result = future.result(timeout=10)
                        results.append(result)
                    except Exception as e:
                        stock = future_to_stock[future]
                        logger.error(f"Enrichment 실패 ({stock.stock_code}): {e}")
                        stock.enrich_errors.append(f"Parallel: {str(e)[:50]}")
                        results.append(stock)
            
            # 순위 순서로 정렬
            results.sort(key=lambda x: x.rank)
            enriched_stocks = results
        else:
            # 순차 처리
            enriched_stocks = [self.enrich_single(stock) for stock in enriched_stocks]
        
        # 결과 로깅
        success_count = sum(1 for s in enriched_stocks if not s.enrich_errors)
        logger.info(f"✅ Enrichment 완료: {success_count}/{len(enriched_stocks)} 성공")
        
        return enriched_stocks
    
    def format_for_ai_prompt(self, enriched_stocks: List[EnrichedStock]) -> str:
        """AI 프롬프트용 전체 포맷
        
        Args:
            enriched_stocks: EnrichedStock 리스트
        
        Returns:
            AI 프롬프트에 추가할 문자열
        """
        lines = []
        
        for stock in enriched_stocks:
            lines.append(f"\n{'='*50}")
            lines.append(f"[{stock.rank}] {stock.stock_name} ({stock.stock_code})")
            lines.append(f"{'='*50}")
            
            # 기본 정보
            lines.append(f"• 점수: {stock.screen_score:.1f}점 ({stock.grade}등급)")
            lines.append(f"• 현재가: {stock.screen_price:,}원 ({stock.change_rate:+.1f}%)")
            lines.append(f"• 시가총액: {stock.market_cap:,.0f}억원")
            lines.append(f"• 거래대금: {stock.trading_value:,.0f}억원")
            
            # 기술적 지표
            lines.append(f"\n[기술적 지표]")
            lines.append(f"• CCI: {stock.cci:.0f}")
            lines.append(f"• 이격도(20): {stock.disparity_20:.1f}%")
            lines.append(f"• 연속양봉: {stock.consecutive_up}일")
            
            # 섹터
            if stock.sector:
                sector_str = f"🔥 {stock.sector} (#{stock.sector_rank})" if stock.is_leading_sector else stock.sector
                lines.append(f"• 섹터: {sector_str}")
            
            # 기업개황 (DART)
            if stock.company_profile:
                cp = stock.company_profile
                lines.append(f"\n[DART 기업개황]")
                lines.append(f"• 시장: {cp.market_name}")
                lines.append(f"• 대표자: {cp.ceo_nm}")
                lines.append(f"• 업종코드: {cp.induty_code}")
                lines.append(f"• 설립일: {cp.est_dt}")
            
            # 재무요약 (DART)
            if stock.financial:
                fin = stock.financial
                lines.append(f"\n[DART 재무 - {fin.fiscal_year}년]")
                if fin.revenue:
                    lines.append(f"• 매출액: {fin.revenue:,.0f}억원")
                if fin.operating_profit:
                    lines.append(f"• 영업이익: {fin.operating_profit:,.0f}억원")
                if fin.net_income:
                    lines.append(f"• 순이익: {fin.net_income:,.0f}억원")
            
            # 계산 지표
            if stock.calculated:
                calc = stock.calculated
                lines.append(f"\n[밸류에이션]")
                if calc.per:
                    lines.append(f"• PER: {calc.per:.1f}")
                if calc.pbr:
                    lines.append(f"• PBR: {calc.pbr:.2f}")
                if calc.roe:
                    lines.append(f"• ROE: {calc.roe:.1f}%")
            
            # 위험공시 (DART)
            if stock.risk:
                risk = stock.risk
                lines.append(f"\n[DART 공시]")
                if risk.has_critical_risk:
                    lines.append(f"⚠️ 위험 공시 발견! (위험도: 높음)")
                    for d in risk.risk_disclosures[:2]:
                        lines.append(f"  - {d.get('date')}: {d.get('title')}")
                elif risk.has_high_risk:
                    lines.append(f"⚠️ 주의 공시 (위험도: 보통)")
                    for d in risk.risk_disclosures[:2]:
                        lines.append(f"  - {d.get('date')}: {d.get('title')}")
                else:
                    lines.append(f"✅ 최근 30일 위험 공시 없음")
            
            # 뉴스
            if stock.news:
                lines.append(f"\n[최근 뉴스]")
                for news in stock.news[:3]:
                    lines.append(f"• {news.title[:50]}...")
        
        return "\n".join(lines)


# ============================================================
# 편의 함수
# ============================================================

def get_enrichment_service() -> EnrichmentService:
    """EnrichmentService 인스턴스 반환"""
    return EnrichmentService()


def enrich_top5_stocks(scores: List[Any]) -> List[EnrichedStock]:
    """TOP5 종목 Enrichment (편의 함수)
    
    Args:
        scores: StockScoreV5 리스트
    
    Returns:
        EnrichedStock 리스트
    """
    service = get_enrichment_service()
    return service.enrich_top5(scores)


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    
    # 테스트용 더미 데이터
    class DummyScore:
        def __init__(self, code, name, score):
            self.stock_code = code
            self.stock_name = name
            self.screen_score = score
            self.grade = 'S' if score >= 90 else 'A'
            self.screen_price = 50000
            self.change_rate = 5.0
            self.market_cap = 10000  # 1조원
            self.trading_value = 500  # 500억
            self.cci = 150
            self.disparity_20 = 5.0
            self.consecutive_up = 2
            self.sector = "반도체"
            self.is_leading_sector = True
            self.sector_rank = 1
    
    # 테스트 종목
    test_scores = [
        DummyScore('005930', '삼성전자', 95.0),
        DummyScore('000660', 'SK하이닉스', 92.0),
        DummyScore('035720', '카카오', 88.0),
    ]
    
    print("\n" + "="*60)
    print("EnrichmentService 테스트")
    print("="*60)
    
    # Enrichment 실행
    service = EnrichmentService()
    enriched = service.enrich_top5(test_scores, parallel=True)
    
    # 결과 출력
    for stock in enriched:
        print(f"\n--- {stock.rank}. {stock.stock_name} ---")
        print(f"  점수: {stock.screen_score}점 ({stock.grade})")
        
        if stock.company_profile:
            print(f"  시장: {stock.company_profile.market_name}")
            print(f"  대표자: {stock.company_profile.ceo_nm}")
        
        if stock.financial:
            print(f"  매출액: {stock.financial.revenue:,.0f}억원")
            print(f"  영업이익: {stock.financial.operating_profit:,.0f}억원")
        
        if stock.calculated:
            print(f"  PER: {stock.calculated.per}, PBR: {stock.calculated.pbr}")
        
        if stock.risk:
            print(f"  위험도: {stock.risk.risk_level}")
        
        if stock.news:
            print(f"  뉴스: {len(stock.news)}건")
            for n in stock.news[:2]:
                print(f"    - {n.title[:40]}...")
        
        if stock.enrich_errors:
            print(f"  ⚠️ 에러: {stock.enrich_errors}")
    
    # AI 프롬프트 테스트
    print("\n" + "="*60)
    print("AI 프롬프트 포맷 테스트")
    print("="*60)
    prompt = service.format_for_ai_prompt(enriched[:1])
    print(prompt)
