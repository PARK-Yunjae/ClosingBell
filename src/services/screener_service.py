"""
스크리닝 서비스 v6.5

책임:
- 스크리닝 플로우 제어
- 유니버스 조회 → 데이터 수집 → 점수 계산 → 저장 → 알림
- 최소한의 하드필터 (데이터부족, 하락종목만 제외)
- 나머지 조건은 모두 점수로 반영 (소프트 필터)
- 글로벌 지표 필터 (나스닥/환율)

v6.5 변경사항:
- Top5Pipeline 연동 (Enrichment + AI 배치)
- DART 기업정보/재무/위험공시 통합
- AI 배치 호출 (5회 → 1회)
- 기존 방식 fallback 유지

v6.4 변경사항:
- TV200 조건검색 유지 (HTS와 동일)
- TV200 스냅샷을 DB에 저장하여 백필에서 재사용
- 백필: 스냅샷 있으면 사용, 없으면 OHLCV 기반 필터 (fallback)
- 시간이 지나면 스냅샷이 쌓여서 백필도 100% 일치

v6.3 변경사항:
- CCI 하드 필터 비활성화 (999로 설정, 점수제에서 자연 감점)
- TV200 백필 필터와 일치 (거래대금 100억+, 등락률 0.1~30%)
"""

import os
import time
import logging
from datetime import date
from pathlib import Path
from typing import List, Optional, Dict

from src.config.settings import settings
from src.config.constants import get_top_n_count, MIN_DAILY_DATA_COUNT
from src.utils.stock_filters import filter_universe_stocks
from src.domain.models import StockData, ScreeningResult, ScreeningStatus
from src.domain.score_calculator import (
    ScoreCalculatorV5,
    StockScoreV5,
    format_discord_embed,
)
from src.adapters.kis_client import get_kis_client, KISClient
from src.adapters.discord_notifier import get_discord_notifier, DiscordNotifier
from src.infrastructure.repository import (
    get_screening_repository,
    ScreeningRepository,
)
from src.services.sector_service import get_sector_service, SectorService
from src.infrastructure.database import init_database

logger = logging.getLogger(__name__)


# ============================================================
# v6.2 설정값
# ============================================================

# CCI 하드 필터: 비활성화 (점수제에서 자연스럽게 반영됨)
# 백필/TV200과 일치시키기 위해 999로 설정
CCI_HARD_LIMIT = 999

# 시가총액 분류 기준 (라벨 표시용, 점수 가산 없음)
# (최소, 최대, 미사용, 라벨)
MARKET_CAP_TIERS = [
    (100000, float('inf'), 0, "mega"),    # 10조+
    (30000, 100000, 0, "large"),          # 3조~10조
    (10000, 30000, 0, "mid"),             # 1조~3조
    (3000, 10000, 0, "small"),            # 3천억~1조
    (0, 3000, 0, "micro"),                # 3천억 미만
]

# 대기업 기준 시가총액 (1조원 = 10000억)
LARGE_CAP_THRESHOLD = 10000


def get_market_cap_label(market_cap: float) -> str:
    """시가총액 라벨 반환 (점수 가산 없음)
    
    Returns:
        라벨 문자열 (mega/large/mid/small/micro/unknown)
    """
    if market_cap is None or market_cap <= 0:
        return "unknown"
    
    for min_cap, max_cap, _, label in MARKET_CAP_TIERS:
        if min_cap <= market_cap < max_cap:
            return label
    return "unknown"


def filter_by_cci(scores: list, limit: int = CCI_HARD_LIMIT) -> tuple:
    """CCI 과열 종목 필터링
    
    Returns:
        (filtered_scores, filtered_out_count)
    """
    filtered = []
    filtered_out = 0
    
    for s in scores:
        cci = s.score_detail.raw_cci
        if cci is not None and cci > limit:
            filtered_out += 1
            logger.debug(f"CCI 필터: {s.stock_name} CCI={cci:.0f} (>{limit})")
        else:
            filtered.append(s)
    
    if filtered_out > 0:
        logger.info(f"CCI 하드필터: {filtered_out}개 제외 (CCI > {limit})")
    
    return filtered, filtered_out


class ScreenerService:
    """스크리닝 서비스 v6.3 (단순 선형 점수제)"""
    
    def __init__(
        self,
        kis_client: Optional[KISClient] = None,
        discord_notifier: Optional[DiscordNotifier] = None,
        screening_repo: Optional[ScreeningRepository] = None,
    ):
        self.kis_client = kis_client or get_kis_client()
        self.discord_notifier = discord_notifier or get_discord_notifier()
        self.screening_repo = screening_repo or get_screening_repository()
        self.calculator = ScoreCalculatorV5()
        
        logger.info("ScreenerService 초기화")
    
    def run_screening(
        self,
        screen_time: str = "15:00",
        save_to_db: bool = True,
        send_alert: bool = True,
        is_preview: bool = False,
    ) -> Dict:
        """스크리닝 실행"""
        start_time = time.time()
        screen_date = date.today()
        
        logger.info(f"스크리닝 시작: {screen_date} {screen_time}")
        
        try:
            # 0. 글로벌 지표 조회 (v5.4)
            global_adjustment = 0
            global_info = ""
            try:
                from src.data.index_monitor import get_global_indicators
                global_ind = get_global_indicators()
                global_adjustment = global_ind.get_score_adjustment()
                
                if global_ind.nasdaq_change is not None:
                    global_info = f"나스닥 {global_ind.nasdaq_change:+.1f}%({global_ind.nasdaq_trend})"
                    if global_ind.usdkrw_change is not None:
                        global_info += f" / 환율 {global_ind.usdkrw_change:+.1f}%({global_ind.fx_trend})"
                    
                    if global_adjustment != 0:
                        global_info += f" → 점수 {global_adjustment:+d}점"
                    
                    logger.info(f"글로벌 지표: {global_info}")
            except Exception as e:
                logger.warning(f"글로벌 지표 조회 실패: {e}")
            
            # 1. 유니버스 조회
            stocks = self._get_universe()
            if not stocks:
                return self._empty_result(screen_date, screen_time, start_time, 
                                         is_preview, "유니버스 비어있음")
            
            logger.info(f"유니버스: {len(stocks)}개")
            
            # 2. 데이터 수집 (최소 하드필터만)
            stock_data_list = self._collect_data(stocks)
            if not stock_data_list:
                return self._empty_result(screen_date, screen_time, start_time,
                                         is_preview, "수집된 종목 없음")
            
            logger.info(f"데이터 수집: {len(stock_data_list)}개")
            
            # 3. 점수 계산
            scores = self.calculator.calculate_scores(stock_data_list)
            
            # 3-1. 글로벌 지표 점수 조정 (v5.4)
            if global_adjustment != 0:
                for score in scores:
                    score.score_total = min(100, score.score_total + global_adjustment)
                    # grade/sell_strategy는 score_total 기반 property로 자동 계산됨
                logger.info(f"글로벌 점수 조정: {global_adjustment:+d}점 적용")
            
            # ================================================
            # v6.2: CCI 하드 필터 적용
            # ================================================
            scores_filtered, cci_filtered_count = filter_by_cci(scores, CCI_HARD_LIMIT)
            
            # ================================================
            # v6.2: 시가총액 정보 로드 (점수 가산 없음, 대기업 표시용)
            # ================================================
            market_cap_info = self._load_market_cap_info(scores_filtered)
            
            # ★ P0-B: TOP_N_COUNT를 settings에서 가져오도록 통일
            top_n_count = get_top_n_count()
            
            # TOP5 선정 (필터링된 목록에서)
            top_n = self.calculator.select_top_n(scores_filtered, top_n_count)
            
            # v6.2: 대기업 TOP5 별도 추출
            large_cap_top5 = [s for s in scores_filtered 
                            if getattr(s, '_market_cap', 0) >= LARGE_CAP_THRESHOLD][:top_n_count]
            
            # ================================================
            # v6.3: 주도섹터 계산
            # ================================================
            sector_service = get_sector_service()
            sector_mapping = self._load_sector_mapping()
            
            # 후보 종목들로 주도섹터 계산
            candidates_for_sector = []
            for score in scores_filtered:
                sector = sector_mapping.get(score.stock_code, 'Unknown')
                candidates_for_sector.append({
                    'code': score.stock_code,
                    'name': score.stock_name,
                    'sector': sector,
                    'change_rate': score.change_rate,
                    'trading_value': getattr(score, '_trading_value', 0),
                })
            
            sector_stats = sector_service.calculate_leading_sectors(
                candidates_for_sector, 
                cache_date=screen_date.isoformat()
            )
            
            # TOP5에 섹터 정보 추가
            for score in top_n:
                sector = sector_mapping.get(score.stock_code, 'Unknown')
                sector_info = sector_service.get_sector_info(score.stock_code, sector, sector_stats)
                score._sector = sector_info.sector
                score._sector_rank = sector_info.sector_rank
                score._is_leading_sector = sector_info.is_leading_sector
            
            leading_sectors_text = sector_service.format_leading_sectors_text()
            logger.info(f"주도섹터: {leading_sectors_text}")
            
            execution_time = time.time() - start_time
            
            result = {
                "screen_date": screen_date,
                "screen_time": screen_time,
                "total_count": len(scores),
                "filtered_count": len(scores_filtered),  # v6.2
                "cci_filtered_out": cci_filtered_count,  # v6.2
                "top_n": top_n,
                "large_cap_top5": large_cap_top5,  # v6.2: 대기업 TOP5
                "all_scores": scores_filtered,  # 필터링된 목록
                "execution_time_sec": execution_time,
                "status": "SUCCESS",
                "is_preview": is_preview,
                "error_message": None,
                "global_info": global_info,  # v5.4
                "market_cap_info": market_cap_info,  # v6.2
                "leading_sectors_text": leading_sectors_text,  # v6.3
                "sector_stats": sector_stats,  # v6.3
            }
            
            # 4. DB 저장
            if save_to_db and not is_preview:
                self._save_result(result)
            
            # 5. 알림 발송
            if send_alert:
                self._send_alert(result, is_preview)
            
            # 6. 콘솔 출력
            self._print_results(top_n)
            
            logger.info(f"스크리닝 완료: {execution_time:.1f}초")
            return result
            
        except Exception as e:
            logger.error(f"스크리닝 에러: {e}")
            import traceback
            traceback.print_exc()
            
            if send_alert:
                try:
                    self.discord_notifier.send_error_alert(e, "스크리닝 에러")
                except:
                    pass
            
            return self._empty_result(screen_date, screen_time, start_time,
                                     is_preview, str(e))
    
    def _get_universe(self) -> List:
        """유니버스 조회 (TV200 조건검색)
        
        v6.4: 
        - TV200 조건검색 사용 (HTS와 동일)
        - 결과를 스냅샷으로 저장하여 백필에서 재사용
        - 스냅샷이 쌓이면 백필과 100% 일치
        """
        condition_name = os.getenv("CONDITION_NAME", "TV200")
        min_candidates = int(os.getenv("MIN_CANDIDATES", "30"))
        
        stocks = []
        
        try:
            # TV200 조건검색
            stocks_raw = self.kis_client.get_condition_universe(
                condition_name=condition_name,
                limit=500,
            )
            
            if stocks_raw:
                # 원본 결과 저장 (비교 분석용)
                self._save_tv200_result(stocks_raw, "before_filter")
                
                # 필터링 (ETF/스팩 등 제외)
                stocks, _ = filter_universe_stocks(stocks_raw, log_details=True)
                logger.info(f"TV200 조건검색 결과: {len(stocks)}개")
                
                # 필터 후 결과 저장 (스냅샷 - 백필에서 사용)
                self._save_tv200_result(stocks, "after_filter")
                
        except Exception as e:
            logger.error(f"TV200 조건검색 실패: {e}")
        
        # Fallback (종목 부족 시 거래대금 API)
        if len(stocks) < min_candidates:
            logger.warning(f"TV200 결과 부족 ({len(stocks)}개), 거래대금 API fallback")
            try:
                fallback = self.kis_client.get_top_trading_value_stocks(
                    min_trading_value=settings.screening.min_trading_value,
                    limit=200,
                )
                if fallback:
                    filtered, _ = filter_universe_stocks(fallback, log_details=True)
                    existing = {s.code for s in stocks}
                    for s in filtered:
                        if s.code not in existing:
                            stocks.append(s)
                    logger.info(f"Fallback 후: {len(stocks)}개")
            except Exception as e:
                logger.error(f"Fallback 실패: {e}")
        
        return stocks
    
    def _save_tv200_result(self, stocks: List, stage: str = "raw"):
        """TV200 결과 DB 스냅샷 저장 (v6.4 - JSON 파일 저장 제거)
        
        Args:
            stocks: 종목 리스트
            stage: 저장 단계 (before_filter, after_filter)
        """
        from datetime import datetime
        
        try:
            # v6.3.3: 실제 거래일 기준 날짜 사용 (휴일 대응)
            screen_date = self._get_actual_trading_date()
            today_str = screen_date.isoformat() if hasattr(screen_date, 'isoformat') else str(screen_date)
            
            # 코드/이름 추출
            codes = []
            names_dict = {}
            
            for s in stocks:
                code = s.code if hasattr(s, 'code') else str(s)
                name = getattr(s, 'name', '')
                codes.append(code)
                names_dict[code] = name
            
            # v6.3.3: DB 스냅샷 저장 (JSON 파일 저장 제거)
            if stage == 'after_filter':
                filter_stage = 'after'
            elif stage == 'before_filter':
                filter_stage = 'before'
            else:
                filter_stage = stage
            
            try:
                from src.infrastructure.repository import get_tv200_snapshot_repository
                snapshot_repo = get_tv200_snapshot_repository()
                snapshot_repo.save_snapshot(
                    screen_date=today_str,
                    codes=codes,
                    names=names_dict,
                    filter_stage=filter_stage,
                    source='TV200',
                )
                logger.info(f"TV200 스냅샷 저장: {today_str} {filter_stage} ({len(stocks)}개)")
            except Exception as e:
                logger.warning(f"TV200 스냅샷 DB 저장 실패: {e}")
            
        except Exception as e:
            logger.warning(f"TV200 결과 저장 실패: {e}")
    
    def _get_actual_trading_date(self) -> date:
        """실제 거래일 반환 (v6.3.3)
        
        휴일에 실행해도 가장 최근 거래일을 반환합니다.
        """
        from datetime import datetime, timedelta
        
        today = datetime.now().date()
        
        # 주말 체크 (0=월, 6=일)
        while today.weekday() >= 5:  # 토, 일
            today -= timedelta(days=1)
        
        # TODO: 공휴일 체크는 추후 추가
        # 현재는 주말만 처리
        
        return today
    
    def _collect_data(self, stocks: List) -> List[StockData]:
        """데이터 수집 (최소 하드필터)"""
        stock_data_list = []
        
        for i, stock in enumerate(stocks):
            try:
                daily_prices = self.kis_client.get_daily_prices(
                    stock.code,
                    count=MIN_DAILY_DATA_COUNT + 10,
                )
                
                if len(daily_prices) < MIN_DAILY_DATA_COUNT:
                    continue
                
                today = daily_prices[-1]
                yesterday = daily_prices[-2]
                change_rate = ((today.close - yesterday.close) / yesterday.close) * 100
                
                # 하락종목 제외 (종가매매는 상승종목 대상)
                if change_rate < 0:
                    continue
                
                # 거래대금 계산 (여러 소스에서 시도)
                trading_value = 0.0
                market_cap = 0.0  # v6.5: 시총 추가
                
                # 1차: 일봉 데이터에서
                if today.trading_value > 0:
                    trading_value = today.trading_value / 100_000_000
                
                # 2차: 현재가 API에서 (거래대금 + 시총)
                if trading_value <= 0 or market_cap <= 0:
                    try:
                        current_data = self.kis_client.get_current_price(stock.code)
                        if current_data:
                            if current_data.trading_value > 0 and trading_value <= 0:
                                trading_value = current_data.trading_value / 100_000_000
                            # v6.5: 시총 가져오기 (억원 단위)
                            if hasattr(current_data, 'market_cap') and current_data.market_cap > 0:
                                market_cap = current_data.market_cap
                    except Exception as e:
                        logger.debug(f"현재가 조회 실패: {stock.code} - {e}")
                
                # 3차: 조건검색 결과에서
                if trading_value <= 0 and hasattr(stock, 'trading_value') and stock.trading_value > 0:
                    trading_value = stock.trading_value
                
                # 4차: 거래량 × 종가로 추정
                if trading_value <= 0 and today.volume > 0:
                    trading_value = (today.volume * today.close) / 100_000_000
                
                stock_data = StockData(
                    code=stock.code,
                    name=stock.name,
                    daily_prices=daily_prices,
                    current_price=today.close,
                    trading_value=trading_value,
                    market_cap=market_cap,  # v6.5: 시총 전달
                )
                stock_data_list.append(stock_data)
                
                if (i + 1) % 20 == 0:
                    logger.info(f"진행: {i + 1}/{len(stocks)}")
                    
            except Exception as e:
                logger.debug(f"수집 실패: {stock.code} - {e}")
        
        return stock_data_list
    
    def _load_market_cap_info(self, scores: list) -> dict:
        """v6.2: 시가총액 정보 로드 (점수 가산 없음, 대기업 표시용)
        
        Returns:
            통계 정보 dict
        """
        stats = {"mega": 0, "large": 0, "mid": 0, "small": 0, "micro": 0, "unknown": 0}
        
        try:
            import sqlite3
            
            db_path = os.path.join(os.path.dirname(__file__), '../../data/screener.db')
            if not os.path.exists(db_path):
                db_path = 'data/screener.db'
            
            market_caps = {}
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT stock_code, market_cap FROM nomad_candidates WHERE market_cap > 0")
                for code, cap in cursor.fetchall():
                    market_caps[code] = cap
                conn.close()
            except Exception as e:
                logger.warning(f"시가총액 DB 조회 실패: {e}")
            
            # 시가총액 정보만 저장 (점수 가산 없음)
            for score in scores:
                market_cap = market_caps.get(score.stock_code, 0)
                label = get_market_cap_label(market_cap)
                
                # 시가총액 정보 저장 (대기업 필터용)
                score._market_cap = market_cap
                score._market_cap_label = label
                stats[label] += 1
            
            logger.info(f"시가총액 정보 로드: {stats}")
            return stats
            
        except Exception as e:
            logger.warning(f"시가총액 정보 로드 실패: {e}")
            return stats
    
    def _load_sector_mapping(self) -> Dict[str, str]:
        """v6.3: stock_mapping.csv에서 종목코드 → 섹터 매핑 로드"""
        try:
            import pandas as pd
            from pathlib import Path
            
            # stock_mapping.csv 경로
            mapping_paths = [
                Path(r"C:\Coding\data\stock_mapping.csv"),
                Path("data/stock_mapping.csv"),
                Path(__file__).parent.parent.parent / "data" / "stock_mapping.csv",
            ]
            
            for path in mapping_paths:
                if path.exists():
                    df = pd.read_csv(path, encoding='utf-8-sig')
                    df.columns = df.columns.str.lower()
                    
                    if 'code' in df.columns and 'sector' in df.columns:
                        # 코드 6자리 패딩
                        df['code'] = df['code'].astype(str).str.zfill(6)
                        mapping = dict(zip(df['code'], df['sector']))
                        logger.debug(f"섹터 매핑 로드: {len(mapping)}종목 from {path}")
                        return mapping
            
            logger.warning("stock_mapping.csv를 찾을 수 없음")
            return {}
            
        except Exception as e:
            logger.warning(f"섹터 매핑 로드 실패: {e}")
            return {}
    
    def _empty_result(self, screen_date, screen_time, start_time, 
                      is_preview, error_msg) -> Dict:
        """빈 결과"""
        return {
            "screen_date": screen_date,
            "screen_time": screen_time,
            "total_count": 0,
            "top_n": [],
            "all_scores": [],
            "execution_time_sec": time.time() - start_time,
            "status": "FAILED",
            "is_preview": is_preview,
            "error_message": error_msg,
        }
    
    def _save_result(self, result: Dict):
        """DB 저장 (기존 테이블 + v6.0 TOP5 테이블)"""
        try:
            from src.domain.models import StockScore, ScoreDetail
            
            # v5 → 레거시 변환
            legacy_scores = []
            for s in result["all_scores"]:
                d = s.score_detail
                legacy = StockScore(
                    stock_code=s.stock_code,
                    stock_name=s.stock_name,
                    current_price=s.current_price,
                    change_rate=s.change_rate,
                    trading_value=s.trading_value,
                    score_detail=ScoreDetail(
                        cci_value=d.cci_score / 1.5,
                        cci_slope=d.distance_score / 1.5,
                        ma20_slope=d.ma20_3day_bonus * 3.33,
                        candle=d.candle_score / 1.5,
                        change=d.change_score / 1.5,
                        raw_cci=d.raw_cci,
                        raw_ma20=d.raw_ma20,
                    ),
                    score_total=s.score_total,
                    rank=s.rank,
                )
                legacy_scores.append(legacy)
            
            legacy_result = ScreeningResult(
                screen_date=result["screen_date"],
                screen_time=result["screen_time"],
                total_count=result["total_count"],
                top3=legacy_scores[:5],
                all_items=legacy_scores,
                execution_time_sec=result["execution_time_sec"],
                status=ScreeningStatus.SUCCESS,
            )
            
            screening_id = self.screening_repo.save_screening(legacy_result)
            logger.info(f"DB 저장: ID={screening_id}")
            
            # ================================================
            # v6.0: closing_top5_history 테이블에도 저장
            # ================================================
            self._save_top5_history(result)
            
        except Exception as e:
            logger.error(f"DB 저장 실패: {e}")
    
    def _save_top5_history(self, result: Dict):
        """v6.0: TOP5를 closing_top5_history에 저장
        
        v6.3.1: 실시간 데이터 우선 - 저장 전 해당 날짜 기존 데이터 삭제
        """
        try:
            from src.infrastructure.repository import get_top5_history_repository
            
            top5_repo = get_top5_history_repository()
            top_n = result.get("top_n", [])
            screen_date = result["screen_date"]
            
            if not top_n:
                logger.info("TOP5 비어있음 - 저장 스킵")
                return
            
            # v6.3.1: 실시간 데이터 우선 - 기존 데이터 삭제 후 새로 저장
            # (백필 데이터가 있어도 실시간 데이터로 덮어쓰기)
            deleted = top5_repo.delete_by_date(screen_date.isoformat())
            if deleted > 0:
                logger.info(f"기존 TOP5 삭제: {deleted}건 (실시간 데이터로 교체)")
            
            for score in top_n:
                d = score.score_detail
                
                history_data = {
                    'screen_date': screen_date.isoformat(),
                    'rank': score.rank,
                    'stock_code': score.stock_code,
                    'stock_name': score.stock_name,
                    'screen_price': score.current_price,
                    'screen_score': score.score_total,
                    'grade': score.grade.value,
                    'cci': d.raw_cci,
                    'rsi': getattr(d, 'raw_rsi', None),
                    'change_rate': score.change_rate,
                    'disparity_20': d.raw_distance,
                    'consecutive_up': d.raw_consec_days,
                    'volume_ratio_5': d.raw_volume_ratio,
                    'data_source': 'realtime',
                    # v6.3: 주도섹터 정보
                    'sector': getattr(score, '_sector', None),
                    'sector_rank': getattr(score, '_sector_rank', None),
                    'is_leading_sector': 1 if getattr(score, '_is_leading_sector', False) else 0,
                    # v6.3.1: 거래대금/거래량
                    'trading_value': score.trading_value,
                    'volume': getattr(score, '_volume', None),
                }
                
                history_id = top5_repo.upsert(history_data)
                logger.debug(f"TOP5 저장: #{score.rank} {score.stock_name} (id={history_id})")
            
            logger.info(f"TOP5 저장 완료: {len(top_n)}개")
            
        except Exception as e:
            logger.error(f"TOP5 저장 실패: {e}")
    
    def _send_alert(self, result: Dict, is_preview: bool):
        """알림 발송 (종가매매 TOP5) v6.5 - DART+AI 배치 통합"""
        try:
            top_n = result["top_n"]
            cci_filtered = result.get("cci_filtered_out", 0)
            large_cap_top5 = result.get("large_cap_top5", [])
            leading_sectors_text = result.get("leading_sectors_text", "")
            
            # 종가매매 TOP5 발송
            if not top_n:
                self.discord_notifier.send_message("📊 종가매매: 적합한 종목 없음")
                return
            
            # ============================================================
            # v6.5: 새 파이프라인 시도 (Enrichment + AI 배치)
            # ============================================================
            try:
                from src.services.top5_pipeline import Top5Pipeline
                
                run_type = "preview" if is_preview else "main"
                pipeline = Top5Pipeline(
                    use_enrichment=True,
                    use_ai=True,
                    save_to_db=not is_preview,  # 메인만 DB 저장
                )
                
                # 파이프라인에서 Discord 발송하지 않고 Embed만 생성
                pipeline._discord_notifier = False  # False로 설정하면 자동 생성 안 함
                
                logger.info(f"🚀 v6.5 파이프라인 시작 ({run_type})")
                
                pipeline_result = pipeline.process_top5(
                    scores=top_n,
                    run_type=run_type,
                    leading_sectors_text=leading_sectors_text,
                )
                
                ai_results = pipeline_result.get('ai_results', {})
                
                # CCI 필터 정보 추가
                title = "[프리뷰] 종가매매 TOP5" if is_preview else "종가매매 TOP5"
                if cci_filtered > 0:
                    title += f" (CCI과열 {cci_filtered}개 제외)"
                
                # v6.5 Embed Builder 사용
                from src.services.discord_embed_builder import DiscordEmbedBuilder
                embed_builder = DiscordEmbedBuilder()
                # ★ EnrichedStock 사용 (DART 정보 포함)
                enriched_stocks = pipeline_result.get('enriched_stocks', [])
                stocks_for_embed = enriched_stocks if enriched_stocks else top_n
                embed = embed_builder.build_top5_embed(
                    stocks=stocks_for_embed,
                    title=title,
                    leading_sectors_text=leading_sectors_text,
                    ai_results=ai_results if ai_results else None,
                    run_type=run_type,
                )
                
                success = self.discord_notifier.send_embed(embed)
                if success:
                    ai_count = len(ai_results) if ai_results else 0
                    enriched_count = len(pipeline_result.get('enriched_stocks', []))
                    logger.info(f"✅ v6.5 Discord 발송 완료 (Enriched: {enriched_count}, AI: {ai_count})")
                else:
                    logger.warning("Discord 발송 실패")
                
            except ImportError as e:
                logger.warning(f"v6.5 파이프라인 미설치, 기존 방식으로 fallback: {e}")
                self._send_alert_legacy(top_n, cci_filtered, leading_sectors_text, is_preview)
            except Exception as e:
                logger.warning(f"v6.5 파이프라인 실패, 기존 방식으로 fallback: {e}")
                self._send_alert_legacy(top_n, cci_filtered, leading_sectors_text, is_preview)
            
            # v6.2: 대기업 TOP5 별도 발송 (있는 경우)
            if large_cap_top5 and not is_preview:
                self._send_large_cap_alert(large_cap_top5)
                
        except Exception as e:
            logger.error(f"알림 에러: {e}")
    
    def _send_alert_legacy(self, top_n: list, cci_filtered: int, leading_sectors_text: str, is_preview: bool):
        """v6.4 방식 알림 (fallback용)"""
        try:
            # v6.4: AI 분석 실행 (종목당 5~10초, 총 30초~1분)
            ai_results = {}
            try:
                from src.services.webhook_ai_helper import analyze_top5_for_webhook
                logger.info("🤖 웹훅용 AI 분석 시작 (legacy)...")
                ai_results = analyze_top5_for_webhook(top_n)
                logger.info(f"🤖 AI 분석 완료: {len(ai_results)}개")
            except Exception as e:
                logger.warning(f"AI 분석 실패 (웹훅은 계속 발송): {e}")
            
            # v6.4: AI 결과 포함 Embed 생성
            title = "[프리뷰] 종가매매 TOP5" if is_preview else "🔔 종가매매 TOP5"
            if cci_filtered > 0:
                title += f" (CCI과열 {cci_filtered}개 제외)"
            
            # AI 결과가 있으면 AI 포함 버전, 없으면 기존 버전
            if ai_results:
                from src.domain.score_calculator_patch import format_discord_embed_with_ai
                embed = format_discord_embed_with_ai(
                    top_n, 
                    title=title,
                    leading_sectors_text=leading_sectors_text,
                    ai_results=ai_results,
                )
            else:
                embed = format_discord_embed(
                    top_n, 
                    title=title,
                    leading_sectors_text=leading_sectors_text,
                )
            
            success = self.discord_notifier.send_embed(embed)
            if success:
                logger.info("종가매매 Discord 발송 완료 (legacy)" + (" (AI 포함)" if ai_results else ""))
            else:
                logger.warning("종가매매 Discord 발송 실패")
                
        except Exception as e:
            logger.error(f"Legacy 알림 에러: {e}")
    
    def _send_large_cap_alert(self, large_cap_stocks: list):
        """v6.2: 대기업 TOP5 별도 알림"""
        try:
            if not large_cap_stocks:
                return
            
            # 간단한 텍스트 형식으로 발송
            lines = ["🏢 **대기업 TOP5** (시총 1조+)\n"]
            for i, s in enumerate(large_cap_stocks[:5], 1):
                market_cap = getattr(s, '_market_cap', 0)
                cap_str = f"{market_cap/10000:.1f}조" if market_cap >= 10000 else f"{market_cap:.0f}억"
                lines.append(f"#{i} {s.stock_name} | {s.score_total:.1f}점 | 시총 {cap_str}")
            
            self.discord_notifier.send_message("\n".join(lines))
            logger.info("대기업 TOP5 알림 발송 완료")
            
        except Exception as e:
            logger.warning(f"대기업 알림 실패: {e}")
    
    def _print_results(self, top_n: List[StockScoreV5]):
        """콘솔 출력 v6.2"""
        print("\n" + "=" * 60)
        print("🔔 종가매매 TOP5")
        print("=" * 60)
        
        if not top_n:
            print("적합한 종목 없음")
            return
        
        for s in top_n:
            d = s.score_detail
            st = s.sell_strategy
            grade_emoji = {"S": "🏆", "A": "🥇", "B": "🥈", "C": "🥉", "D": "⚠️"}
            
            # v6.2: 시가총액 정보 추가
            market_cap = getattr(s, '_market_cap', 0)
            cap_str = ""
            if market_cap > 0:
                if market_cap >= 10000:
                    cap_str = f" | 시총 {market_cap/10000:.1f}조"
                else:
                    cap_str = f" | 시총 {market_cap:.0f}억"
            
            print(f"\n#{s.rank} {s.stock_name} ({s.stock_code}){cap_str}")
            print(f"   {s.score_total:.1f}점 {grade_emoji[s.grade.value]}{s.grade.value}")
            print(f"   현재가: {s.current_price:,}원 ({s.change_rate:+.1f}%)")
            print(f"   CCI: {d.raw_cci:.0f} | 이격도: {d.raw_distance:.1f}%")
            print(f"   거래량: {d.raw_volume_ratio:.1f}배 | 연속: {d.raw_consec_days}일")
            print(f"   매도: 시초 {st.open_sell_ratio}% / 목표 +{st.target_profit}%")
        
        print("\n" + "=" * 60)


# 편의 함수
def run_screening(
    screen_time: str = "15:00",
    save_to_db: bool = True,
    send_alert: bool = True,
    is_preview: bool = False,
) -> Dict:
    """스크리닝 실행"""
    service = ScreenerService()
    return service.run_screening(screen_time, save_to_db, send_alert, is_preview)


def run_main_screening() -> Dict:
    """메인 스크리닝 (settings.screening.screening_time_main 사용)"""
    return run_screening(
        screen_time=settings.screening.screening_time_main,
        save_to_db=True,
        send_alert=True,
        is_preview=False,
    )


def run_preview_screening() -> Dict:
    """프리뷰 스크리닝 (settings.screening.screening_time_preview 사용)"""
    return run_screening(
        screen_time=settings.screening.screening_time_preview,
        save_to_db=False,
        send_alert=True,
        is_preview=True,
    )


if __name__ == "__main__":
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    )
    
    try:
        init_database()
    except:
        pass
    
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"
    
    if mode == "main":
        result = run_main_screening()
    elif mode == "preview":
        result = run_preview_screening()
    else:
        result = run_screening(save_to_db=False, send_alert=False)
    
    print(f"\n상태: {result['status']}")
    print(f"분석: {result['total_count']}개")
    print(f"시간: {result['execution_time_sec']:.1f}초")