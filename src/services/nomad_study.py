"""
유목민 공부법 서비스 (NomadStudy)
=================================

종가매매 TOP5 종목을 대상으로 기업 분석을 자동 수행합니다.

동작 흐름:
1. 당일 TOP5 종목 조회
2. 각 종목별:
   - 기업 기본정보 수집 (한투 API)
   - 관련 뉴스 수집 (네이버 API)
   - AI 분석 및 요약 (Gemini API)
3. DB 저장 + Discord 알림

스케줄: 매일 17:30 (data_update, learning 이후)

사용:
    from src.services.nomad_study import run_nomad_study
    run_nomad_study()
"""

import logging
import time
from datetime import date, datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

from src.infrastructure.database import get_database
from src.infrastructure.repository import get_repository
from src.adapters.kis_client import get_kis_client
from src.adapters.discord_notifier import get_discord_notifier

# 새로 추가되는 클라이언트들
# from src.adapters.naver_client import get_naver_client
# from src.adapters.gemini_client import get_gemini_client

logger = logging.getLogger(__name__)


@dataclass
class StockStudy:
    """종목 공부 데이터"""
    study_date: date
    stock_code: str
    stock_name: str
    screen_rank: int
    
    # 기업 정보
    market_cap: float = 0.0
    industry: str = ""
    main_business: str = ""
    major_shareholder: str = ""
    shareholder_ratio: float = 0.0
    
    # 재무 지표
    per: float = 0.0
    pbr: float = 0.0
    roe: float = 0.0
    debt_ratio: float = 0.0
    
    # 종가매매 지표
    score_total: float = 0.0
    volume_ratio: float = 0.0
    cci: float = 0.0
    change_rate: float = 0.0
    
    # AI 분석
    news_summary: str = ""
    investment_points: str = ""
    risk_factors: str = ""
    selection_reason: str = ""
    ai_score: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


class NomadStudyService:
    """유목민 공부법 서비스"""
    
    def __init__(self):
        self.repo = get_repository()
        self.kis = get_kis_client()
        self.db = get_database()
        
        # API 클라이언트 (지연 초기화)
        self._naver = None
        self._gemini = None
        
        # 설정
        self.news_days = 7          # 뉴스 수집 기간
        self.api_delay = 0.5        # API 호출 간격
    
    @property
    def naver(self):
        """네이버 클라이언트 (지연 초기화)"""
        if self._naver is None:
            try:
                from src.adapters.naver_client import get_naver_client
                self._naver = get_naver_client()
            except Exception as e:
                logger.warning(f"Naver client 초기화 실패: {e}")
        return self._naver
    
    @property
    def gemini(self):
        """Gemini 클라이언트 (지연 초기화)"""
        if self._gemini is None:
            try:
                from src.adapters.gemini_client import get_gemini_client
                self._gemini = get_gemini_client()
            except Exception as e:
                logger.warning(f"Gemini client 초기화 실패: {e}")
        return self._gemini
    
    def get_today_top5(self, target_date: date = None) -> List[Dict]:
        """오늘의 TOP5 종목 조회
        
        Args:
            target_date: 대상 날짜 (기본: 오늘)
            
        Returns:
            TOP5 종목 리스트
        """
        if target_date is None:
            target_date = date.today()
        
        screening = self.repo.screening.get_screening_by_date(target_date)
        if not screening:
            logger.warning(f"스크리닝 결과 없음: {target_date}")
            return []
        
        items = self.repo.screening.get_top3_items(screening['id'])
        
        # TOP3이지만 실제로는 TOP5까지 저장되어 있음
        # 없으면 전체에서 상위 5개
        if len(items) < 5:
            all_items = self.repo.screening.get_screening_items(screening['id'])
            items = all_items[:5]
        
        logger.info(f"TOP5 조회: {len(items)}개 종목")
        return items
    
    def get_company_info(self, stock_code: str) -> Dict:
        """기업 정보 조회 (한투 API)
        
        Args:
            stock_code: 종목코드
            
        Returns:
            기업 정보 딕셔너리
        """
        info = {
            "market_cap": 0.0,
            "industry": "",
            "main_business": "",
            "major_shareholder": "",
            "shareholder_ratio": 0.0,
            "per": 0.0,
            "pbr": 0.0,
            "roe": 0.0,
            "debt_ratio": 0.0,
        }
        
        try:
            # 한투 API로 기업정보 조회
            # TODO: kis_client에 get_company_info 메서드 추가 필요
            # 현재는 기본값 반환
            
            # 시세 정보에서 일부 데이터 추출
            prices = self.kis.get_daily_prices(stock_code, count=1)
            if prices:
                # 거래대금으로 시총 추정 (정확하지 않음)
                pass
            
        except Exception as e:
            logger.warning(f"기업 정보 조회 실패 [{stock_code}]: {e}")
        
        return info
    
    def get_stock_news(self, stock_name: str, stock_code: str) -> List[Dict]:
        """종목 관련 뉴스 수집
        
        Args:
            stock_name: 종목명
            stock_code: 종목코드
            
        Returns:
            뉴스 리스트
        """
        if not self.naver:
            return []
        
        try:
            articles = self.naver.search_stock_news(
                stock_name=stock_name,
                stock_code=stock_code,
                days=self.news_days,
            )
            
            return [
                {
                    "title": a.clean_title,
                    "link": a.link,
                    "summary": a.clean_description,
                    "date": a.pub_date.strftime("%Y-%m-%d"),
                }
                for a in articles
            ]
            
        except Exception as e:
            logger.warning(f"뉴스 수집 실패 [{stock_name}]: {e}")
            return []
    
    def analyze_stock(
        self,
        stock_name: str,
        stock_code: str,
        screen_rank: int,
        score_info: Dict,
        company_info: Dict,
        news_list: List[Dict],
    ) -> Dict:
        """AI 분석 수행
        
        Args:
            stock_name: 종목명
            stock_code: 종목코드
            screen_rank: 순위
            score_info: 점수 정보
            company_info: 기업 정보
            news_list: 뉴스 리스트
            
        Returns:
            분석 결과 딕셔너리
        """
        result = {
            "news_summary": "",
            "investment_points": "",
            "risk_factors": "",
            "selection_reason": "",
            "ai_score": "N/A",
        }
        
        if not self.gemini:
            result["news_summary"] = "AI 분석 불가 (API 미설정)"
            return result
        
        try:
            analysis = self.gemini.analyze_stock(
                stock_name=stock_name,
                stock_code=stock_code,
                screen_rank=screen_rank,
                score_info=score_info,
                company_info=company_info,
                news_list=news_list,
            )
            
            result = {
                "news_summary": analysis.news_summary,
                "investment_points": analysis.investment_points,
                "risk_factors": analysis.risk_factors,
                "selection_reason": analysis.selection_reason,
                "ai_score": analysis.overall_score,
            }
            
        except Exception as e:
            logger.warning(f"AI 분석 실패 [{stock_name}]: {e}")
            result["news_summary"] = f"분석 실패: {str(e)[:50]}"
        
        return result
    
    def study_single_stock(self, item: Dict) -> StockStudy:
        """단일 종목 공부
        
        Args:
            item: 스크리닝 아이템
            
        Returns:
            StockStudy 객체
        """
        stock_code = item['stock_code']
        stock_name = item['stock_name']
        
        logger.info(f"📚 종목 공부: {stock_name} ({stock_code})")
        
        # 1. 기업 정보 수집
        company_info = self.get_company_info(stock_code)
        time.sleep(self.api_delay)
        
        # 2. 뉴스 수집
        news_list = self.get_stock_news(stock_name, stock_code)
        time.sleep(self.api_delay)
        
        # 3. 점수 정보 정리
        score_info = {
            "score_total": item.get('score_total', 0),
            "cci": item.get('raw_cci', 0),
            "volume_ratio": 0,  # DB에 없으면 기본값
            "change_rate": item.get('change_rate', 0),
            "consec_days": 0,
            "distance": 0,
        }
        
        # 4. AI 분석
        analysis = self.analyze_stock(
            stock_name=stock_name,
            stock_code=stock_code,
            screen_rank=item.get('rank', 0),
            score_info=score_info,
            company_info=company_info,
            news_list=news_list,
        )
        time.sleep(self.api_delay)
        
        # 5. 결과 조합
        study = StockStudy(
            study_date=date.today(),
            stock_code=stock_code,
            stock_name=stock_name,
            screen_rank=item.get('rank', 0),
            
            market_cap=company_info.get('market_cap', 0),
            industry=company_info.get('industry', ''),
            main_business=company_info.get('main_business', ''),
            major_shareholder=company_info.get('major_shareholder', ''),
            shareholder_ratio=company_info.get('shareholder_ratio', 0),
            
            per=company_info.get('per', 0),
            pbr=company_info.get('pbr', 0),
            roe=company_info.get('roe', 0),
            debt_ratio=company_info.get('debt_ratio', 0),
            
            score_total=score_info.get('score_total', 0),
            volume_ratio=score_info.get('volume_ratio', 0),
            cci=score_info.get('cci', 0),
            change_rate=score_info.get('change_rate', 0),
            
            news_summary=analysis.get('news_summary', ''),
            investment_points=analysis.get('investment_points', ''),
            risk_factors=analysis.get('risk_factors', ''),
            selection_reason=analysis.get('selection_reason', ''),
            ai_score=analysis.get('ai_score', 'N/A'),
        )
        
        return study
    
    def save_study(self, study: StockStudy) -> bool:
        """공부 기록 저장
        
        Args:
            study: StockStudy 객체
            
        Returns:
            저장 성공 여부
        """
        try:
            # UPSERT
            self.db.execute(
                """
                INSERT OR REPLACE INTO nomad_studies (
                    study_date, stock_code, stock_name, screen_rank,
                    market_cap, industry, main_business, 
                    major_shareholder, shareholder_ratio,
                    per, pbr, roe, debt_ratio,
                    score_total, volume_ratio, cci, change_rate,
                    news_summary, investment_points, risk_factors, 
                    selection_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    study.study_date.isoformat(),
                    study.stock_code,
                    study.stock_name,
                    study.screen_rank,
                    study.market_cap,
                    study.industry,
                    study.main_business,
                    study.major_shareholder,
                    study.shareholder_ratio,
                    study.per,
                    study.pbr,
                    study.roe,
                    study.debt_ratio,
                    study.score_total,
                    study.volume_ratio,
                    study.cci,
                    study.change_rate,
                    study.news_summary,
                    study.investment_points,
                    study.risk_factors,
                    study.selection_reason,
                )
            )
            return True
            
        except Exception as e:
            logger.error(f"공부 기록 저장 실패: {e}")
            return False
    
    def send_discord_summary(self, studies: List[StockStudy]) -> bool:
        """Discord로 요약 전송
        
        Args:
            studies: 공부 기록 리스트
            
        Returns:
            전송 성공 여부
        """
        try:
            notifier = get_discord_notifier()
            
            # Embed 생성
            fields = []
            for study in studies:
                field_value = (
                    f"**{study.score_total:.1f}점** | {study.change_rate:+.1f}%\n"
                    f"📰 {study.news_summary[:80]}...\n"
                    f"💡 {study.investment_points[:80]}...\n"
                    f"⚠️ {study.risk_factors[:50]}..."
                )
                
                fields.append({
                    "name": f"#{study.screen_rank} {study.stock_name} ({study.stock_code})",
                    "value": field_value,
                    "inline": False,
                })
            
            embed = {
                "title": f"📚 오늘의 공부 - {date.today().strftime('%Y-%m-%d')}",
                "description": "종가매매 TOP5 종목 분석 요약",
                "color": 3447003,  # 파란색
                "fields": fields,
                "footer": {
                    "text": "NomadStudy v1.0 | 유목민 공부법"
                }
            }
            
            return notifier.send_embed(embed)
            
        except Exception as e:
            logger.error(f"Discord 전송 실패: {e}")
            return False
    
    def run_daily_study(self, target_date: date = None) -> Dict:
        """일일 공부 실행
        
        Args:
            target_date: 대상 날짜 (기본: 오늘)
            
        Returns:
            실행 결과
        """
        logger.info("=" * 60)
        logger.info("📚 유목민 공부법 시작")
        logger.info("=" * 60)
        
        results = {
            'studied': 0,
            'failed': 0,
            'studies': [],
        }
        
        try:
            # 1. TOP5 조회
            top5 = self.get_today_top5(target_date)
            
            if not top5:
                logger.warning("오늘의 TOP5 종목이 없습니다.")
                return results
            
            # 2. 각 종목 공부
            for item in top5[:5]:
                try:
                    study = self.study_single_stock(item)
                    
                    # DB 저장
                    if self.save_study(study):
                        results['studies'].append(study)
                        results['studied'] += 1
                        logger.info(f"  ✅ {study.stock_name}: 저장 완료")
                    else:
                        results['failed'] += 1
                        logger.warning(f"  ❌ {study.stock_name}: 저장 실패")
                    
                except Exception as e:
                    results['failed'] += 1
                    logger.error(f"  ❌ {item.get('stock_name', '?')}: {e}")
            
            # 3. Discord 요약 전송
            if results['studies']:
                self.send_discord_summary(results['studies'])
            
        except Exception as e:
            logger.error(f"공부 실행 오류: {e}")
            import traceback
            traceback.print_exc()
        
        logger.info("=" * 60)
        logger.info(f"📚 공부 완료: 성공 {results['studied']}, 실패 {results['failed']}")
        logger.info("=" * 60)
        
        return results


# ============================================================
# 싱글톤 및 편의 함수
# ============================================================

_service: Optional[NomadStudyService] = None


def get_nomad_study_service() -> NomadStudyService:
    """서비스 인스턴스 반환"""
    global _service
    if _service is None:
        _service = NomadStudyService()
    return _service


def run_nomad_study(target_date: date = None) -> Dict:
    """일일 공부 실행 (스케줄러용)"""
    service = get_nomad_study_service()
    return service.run_daily_study(target_date)


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    
    print("=" * 60)
    print("🧪 유목민 공부법 테스트")
    print("=" * 60)
    
    service = NomadStudyService()
    
    # 테스트 1: TOP5 조회
    print("\n[테스트 1] TOP5 조회")
    top5 = service.get_today_top5()
    for item in top5[:3]:
        print(f"  - {item['stock_name']} ({item['stock_code']}) : {item['score_total']:.1f}점")
    
    # 테스트 2: 단일 종목 공부 (TOP1만)
    if top5:
        print("\n[테스트 2] 단일 종목 공부")
        confirm = input(f"'{top5[0]['stock_name']}' 공부를 실행하시겠습니까? (y/N): ")
        if confirm.lower() == 'y':
            study = service.study_single_stock(top5[0])
            print(f"\n📚 공부 결과:")
            print(f"  종목: {study.stock_name}")
            print(f"  뉴스요약: {study.news_summary[:100]}...")
            print(f"  투자포인트: {study.investment_points[:100]}...")
            print(f"  리스크: {study.risk_factors[:100]}...")
    
    # 테스트 3: 전체 실행
    print("\n[테스트 3] 전체 공부 실행")
    confirm = input("전체 공부를 실행하시겠습니까? (y/N): ")
    if confirm.lower() == 'y':
        result = service.run_daily_study()
        print(f"\n결과: 성공 {result['studied']}, 실패 {result['failed']}")
