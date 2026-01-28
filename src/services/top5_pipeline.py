"""
TOP5 통합 파이프라인 v6.5

12:00 프리뷰 + 15:00 메인 통합

사용법:
    from src.services.top5_pipeline import Top5Pipeline
    
    pipeline = Top5Pipeline()
    
    # 12:00 프리뷰
    pipeline.run_preview()
    
    # 15:00 메인
    pipeline.run_main()
"""

import logging
from datetime import datetime, date
from typing import List, Dict, Optional, Any, Tuple

from src.config.constants import get_top_n_count

logger = logging.getLogger(__name__)


class Top5Pipeline:
    """TOP5 통합 파이프라인
    
    12:00 프리뷰: 스크리닝 → Enrichment → AI → 웹훅
    15:00 메인: 스크리닝 → Enrichment → AI → 웹훅 + DB 저장
    """
    
    def __init__(
        self,
        use_enrichment: bool = True,
        use_ai: bool = True,
        save_to_db: bool = True,
        top_n_count: int = None,  # ★ P0-B: 설정에서 가져오도록
    ):
        """
        Args:
            use_enrichment: DART/뉴스 정보 추가 여부
            use_ai: AI 분석 사용 여부
            save_to_db: DB 저장 여부
            top_n_count: TOP N 종목 수 (None이면 설정에서 가져옴)
        """
        self.use_enrichment = use_enrichment
        self.use_ai = use_ai
        self.save_to_db = save_to_db
        
        # ★ P0-B: TOP_N_COUNT 설정 통일
        self.top_n_count = top_n_count if top_n_count else get_top_n_count()
        
        # 서비스 (lazy load)
        self._enrichment_service = None
        self._ai_pipeline = None
        self._embed_builder = None
        self._discord_notifier = None
    
    @property
    def enrichment_service(self):
        if self._enrichment_service is None:
            try:
                from src.services.enrichment_service import EnrichmentService
                self._enrichment_service = EnrichmentService()
            except ImportError:
                logger.warning("EnrichmentService 로드 실패")
        return self._enrichment_service
    
    @property
    def ai_pipeline(self):
        if self._ai_pipeline is None:
            try:
                from src.services.ai_pipeline import AIPipeline
                self._ai_pipeline = AIPipeline()
            except ImportError:
                logger.warning("AIPipeline 로드 실패")
        return self._ai_pipeline
    
    @property
    def embed_builder(self):
        if self._embed_builder is None:
            try:
                from src.services.discord_embed_builder import DiscordEmbedBuilder
                self._embed_builder = DiscordEmbedBuilder()
            except ImportError:
                logger.warning("DiscordEmbedBuilder 로드 실패")
        return self._embed_builder
    
    @property
    def discord_notifier(self):
        # _discord_notifier가 False면 비활성화 (외부에서 발송 시)
        if self._discord_notifier is False:
            return None
        if self._discord_notifier is None:
            try:
                from src.adapters.discord_notifier import get_discord_notifier
                self._discord_notifier = get_discord_notifier()
            except ImportError:
                logger.warning("DiscordNotifier 로드 실패")
        return self._discord_notifier
    
    def process_top5(
        self,
        scores: List[Any],
        run_type: str = "main",  # main / preview
        leading_sectors_text: str = None,
        screen_date: date = None,
    ) -> Dict:
        """TOP5 처리 파이프라인
        
        Args:
            scores: StockScoreV5 리스트 (스크리닝 결과)
            run_type: 실행 타입 (main: 15:00, preview: 12:00)
            leading_sectors_text: 주도섹터 텍스트
            screen_date: 스크리닝 날짜
        
        Returns:
            {
                'enriched_stocks': EnrichedStock 리스트,
                'ai_results': AI 분석 결과,
                'embed': Discord Embed,
                'saved_to_db': bool,
            }
        """
        if not scores:
            logger.warning("TOP5 처리할 종목이 없습니다")
            return {'enriched_stocks': [], 'ai_results': {}, 'embed': None, 'saved_to_db': False}
        
        screen_date = screen_date or date.today()
        is_preview = run_type == "preview"
        
        logger.info(f"{'🔮 프리뷰' if is_preview else '🔔 메인'} TOP5 파이프라인 시작: {len(scores)}개")
        
        result = {
            'enriched_stocks': [],
            'ai_results': {},
            'embed': None,
            'saved_to_db': False,
        }
        
        # ============================================================
        # 1. Enrichment (DART + 뉴스)
        # ============================================================
        enriched_stocks = None
        if self.use_enrichment and self.enrichment_service:
            try:
                logger.info("📊 Enrichment 시작...")
                enriched_stocks = self.enrichment_service.enrich_top5(scores[:self.top_n_count])
                result['enriched_stocks'] = enriched_stocks
                logger.info(f"✅ Enrichment 완료: {len(enriched_stocks)}개")
            except Exception as e:
                logger.warning(f"Enrichment 실패 (계속 진행): {e}")
        
        # ============================================================
        # 2. AI 분석 (배치) - 중복 호출 방지
        # ============================================================
        ai_results = {}
        if self.use_ai and self.ai_pipeline:
            try:
                logger.info("🤖 AI 배치 분석 시작...")
                
                # ★ P0-A: AI 중복 호출 방지 - 이미 분석된 종목 스킵
                stocks_to_analyze = []
                already_analyzed = {}
                
                try:
                    from src.infrastructure.repository import get_top5_history_repository
                    repo = get_top5_history_repository()
                    
                    for stock in (enriched_stocks if enriched_stocks else scores[:self.top_n_count]):
                        stock_code = getattr(stock, 'stock_code', '')
                        
                        # DB에서 이미 AI 분석이 있는지 확인
                        if repo.has_ai_analysis(screen_date.isoformat(), stock_code):
                            # 기존 AI 결과 로드
                            existing = repo.db.fetch_one(
                                "SELECT ai_recommendation, ai_risk_level, ai_summary FROM closing_top5_history WHERE screen_date = ? AND stock_code = ?",
                                (screen_date.isoformat(), stock_code)
                            )
                            if existing:
                                already_analyzed[stock_code] = {
                                    'recommendation': existing.get('ai_recommendation', '관망'),
                                    'risk_level': existing.get('ai_risk_level', '보통'),
                                    'summary': existing.get('ai_summary', ''),
                                    'investment_point': '',
                                    'risk_factor': '',
                                }
                                logger.info(f"  ⏭️ {stock_code} - AI 이미 분석됨 (스킵)")
                        else:
                            stocks_to_analyze.append(stock)
                except Exception as e:
                    logger.debug(f"AI 캐시 체크 실패 (전체 분석 진행): {e}")
                    stocks_to_analyze = enriched_stocks if enriched_stocks else scores[:self.top_n_count]
                
                # 새로 분석할 종목만 AI 호출
                if stocks_to_analyze:
                    logger.info(f"  🔍 새로 분석할 종목: {len(stocks_to_analyze)}개")
                    ai_analysis = self.ai_pipeline.analyze_batch(stocks_to_analyze)
                    
                    # 딕셔너리로 변환
                    for ai_result in ai_analysis:
                        ai_results[ai_result.stock_code] = {
                            'recommendation': ai_result.recommendation,
                            'risk_level': ai_result.risk_level,
                            'summary': ai_result.summary,
                            'investment_point': ai_result.investment_point,
                            'risk_factor': ai_result.risk_factor,
                        }
                else:
                    logger.info(f"  ✅ 모든 종목 AI 이미 분석됨 (API 호출 스킵)")
                
                # 기존 분석 결과 병합
                ai_results.update(already_analyzed)
                
                result['ai_results'] = ai_results
                logger.info(f"✅ AI 분석 완료: {len(ai_results)}개 (새로 분석: {len(stocks_to_analyze)}개)")
                
            except Exception as e:
                logger.warning(f"AI 분석 실패 (계속 진행): {e}")
        
        # ============================================================
        # 3. Discord Embed 생성
        # ============================================================
        embed = None
        if self.embed_builder:
            try:
                title = "종가매매 TOP5"
                if is_preview:
                    title = "[프리뷰] 종가매매 TOP5"
                
                # ★ EnrichedStock 사용 (DART/재무 정보 포함)
                stocks_for_embed = enriched_stocks if enriched_stocks else scores[:self.top_n_count]
                
                embed = self.embed_builder.build_top5_embed(
                    stocks=stocks_for_embed,
                    title=title,
                    leading_sectors_text=leading_sectors_text,
                    ai_results=ai_results if ai_results else None,
                    run_type=run_type,
                )
                result['embed'] = embed
                
            except Exception as e:
                logger.warning(f"Embed 생성 실패: {e}")
        
        # ============================================================
        # 4. Discord 웹훅 발송
        # ============================================================
        if embed and self.discord_notifier:
            try:
                success = self.discord_notifier.send_embed(embed)
                if success:
                    logger.info(f"✅ 웹훅 발송 완료 ({run_type})")
                else:
                    logger.warning("웹훅 발송 실패")
            except Exception as e:
                logger.warning(f"웹훅 발송 실패: {e}")
        
        # ============================================================
        # 5. DB 저장 (메인 실행 시에만)
        # ============================================================
        if self.save_to_db and run_type == "main":
            try:
                saved = self._save_to_db(
                    scores=scores[:self.top_n_count],
                    enriched_stocks=enriched_stocks,
                    ai_results=ai_results,
                    screen_date=screen_date,
                )
                result['saved_to_db'] = saved
                if saved:
                    logger.info("✅ DB 저장 완료")
            except Exception as e:
                logger.warning(f"DB 저장 실패: {e}")
        
        return result
    
    def _save_to_db(
        self,
        scores: List[Any],
        enriched_stocks: List[Any],
        ai_results: Dict[str, Dict],
        screen_date: date,
    ) -> bool:
        """TOP5 AI 결과만 DB에 저장 (기존 데이터 덮어쓰기 방지)
        
        Note:
            - 기본 저장은 screener_service._save_top5_history()가 담당
            - 여기서는 AI 분석 결과만 업데이트 (sector/theme 등 덮어쓰기 방지)
        """
        try:
            from src.infrastructure.repository import get_top5_history_repository
            repo = get_top5_history_repository()
            
            updated_count = 0
            for i, score in enumerate(scores[:self.top_n_count]):
                stock_code = getattr(score, 'stock_code', '')
                
                # AI 결과가 있는 경우만 업데이트
                if stock_code in ai_results:
                    ai = ai_results[stock_code]
                    
                    success = repo.update_ai_fields(
                        screen_date=screen_date.isoformat(),
                        stock_code=stock_code,
                        ai_summary=ai.get('summary', ''),
                        ai_risk_level=ai.get('risk_level', ''),
                        ai_recommendation=ai.get('recommendation', ''),
                    )
                    
                    if success:
                        updated_count += 1
            
            logger.info(f"AI 필드 업데이트 완료: {updated_count}/{len(scores[:self.top_n_count])}개")
            return updated_count > 0
            
        except Exception as e:
            logger.error(f"AI 필드 업데이트 실패: {e}")
            return False
    
    def _get_grade_value(self, grade) -> str:
        """등급 값 추출"""
        if hasattr(grade, 'value'):
            return grade.value
        return str(grade) if grade else "-"
    
    def _get_cci(self, score) -> float:
        """CCI 값 추출"""
        # score_detail에서
        score_detail = getattr(score, 'score_detail', None)
        if score_detail:
            return getattr(score_detail, 'raw_cci', 0)
        # 직접 속성에서
        return getattr(score, 'cci', 0)
    
    # ============================================================
    # 편의 메서드
    # ============================================================
    
    def run_preview(self, scores: List[Any], leading_sectors_text: str = None) -> Dict:
        """12:00 프리뷰 실행"""
        return self.process_top5(
            scores=scores,
            run_type="preview",
            leading_sectors_text=leading_sectors_text,
        )
    
    def run_main(self, scores: List[Any], leading_sectors_text: str = None) -> Dict:
        """15:00 메인 실행"""
        return self.process_top5(
            scores=scores,
            run_type="main",
            leading_sectors_text=leading_sectors_text,
        )


# ============================================================
# 편의 함수
# ============================================================

def get_top5_pipeline() -> Top5Pipeline:
    """Top5Pipeline 인스턴스 반환"""
    return Top5Pipeline()


def run_top5_preview(scores: List[Any], leading_sectors_text: str = None) -> Dict:
    """12:00 프리뷰 실행 (편의 함수)"""
    pipeline = Top5Pipeline(save_to_db=False)
    return pipeline.run_preview(scores, leading_sectors_text)


def run_top5_main(scores: List[Any], leading_sectors_text: str = None) -> Dict:
    """15:00 메인 실행 (편의 함수)"""
    pipeline = Top5Pipeline(save_to_db=True)
    return pipeline.run_main(scores, leading_sectors_text)


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    
    # 테스트용 더미 데이터
    class DummyScoreDetail:
        raw_cci = 165
        raw_distance = 5.2
        raw_volume_ratio = 1.5
        raw_consec_days = 2
        is_cci_rising = True
        is_ma20_3day_up = True
        is_high_eq_close = False
    
    class DummySellStrategy:
        open_sell_ratio = 30
        target_profit = 4
        stop_loss = -3
    
    class DummyScore:
        def __init__(self, code, name, score):
            self.stock_code = code
            self.stock_name = name
            self.score_total = score
            self.grade = 'S' if score >= 85 else 'A'
            self.current_price = 55000
            self.change_rate = 3.5
            self.trading_value = 1500
            self._market_cap = 42000
            self.score_detail = DummyScoreDetail()
            self.sell_strategy = DummySellStrategy()
            self._sector = "반도체"
            self._is_leading_sector = True
            self._sector_rank = 1
    
    test_scores = [
        DummyScore('005930', '삼성전자', 93.5),
        DummyScore('000660', 'SK하이닉스', 88.2),
        DummyScore('035720', '카카오', 82.0),
        DummyScore('051910', 'LG화학', 78.5),
        DummyScore('035420', 'NAVER', 75.0),
    ]
    
    print("="*60)
    print("Top5Pipeline 테스트")
    print("="*60)
    
    # 프리뷰 모드로 테스트 (DB 저장 안 함)
    pipeline = Top5Pipeline(
        use_enrichment=True,
        use_ai=True,
        save_to_db=False,  # 테스트에서는 저장 안 함
    )
    
    # Discord 웹훅은 실제 발송하지 않도록 비활성화
    pipeline._discord_notifier = None
    
    result = pipeline.run_preview(
        test_scores,
        leading_sectors_text="1. 반도체 (+5.2%) | 2. 2차전지 (+3.1%)"
    )
    
    print(f"\n📊 결과:")
    print(f"  Enriched: {len(result['enriched_stocks'])}개")
    print(f"  AI 분석: {len(result['ai_results'])}개")
    print(f"  Embed 생성: {'✅' if result['embed'] else '❌'}")
    print(f"  DB 저장: {'✅' if result['saved_to_db'] else '❌'}")
    
    if result['ai_results']:
        print(f"\n🤖 AI 분석 결과:")
        for code, ai in result['ai_results'].items():
            print(f"  {code}: {ai.get('recommendation')} | {ai.get('risk_level')} | {ai.get('summary', '')[:30]}...")
    
    print("\n" + "="*60)