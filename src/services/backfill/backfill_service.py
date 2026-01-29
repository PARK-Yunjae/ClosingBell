"""
ClosingBell v6.3.2 백필 서비스

과거 데이터 백필:
- TOP5 20일 추적 데이터
- 유목민 공부법 (상한가/거래량천만) 데이터

v6.3.2 변경사항:
- TOP5 점수 계산을 ScoreCalculatorV5로 통일 (실시간과 100% 동일)
- 더 이상 backfill/indicators.py의 calculate_score()를 사용하지 않음
- realtime 우선 정책: 백필이 realtime 데이터를 덮어쓰지 않음
"""

import logging
from datetime import date, timedelta
from typing import List, Optional, Dict, Tuple
import pandas as pd

from src.config.backfill_config import BackfillConfig, get_backfill_config
from src.services.backfill.data_loader import (
    load_all_ohlcv,
    load_stock_mapping,
    get_trading_days,
    filter_stocks,
    load_global_index,
)
from src.services.backfill.indicators import (
    calculate_all_indicators,
    calculate_score,
    score_to_grade,
    calculate_global_adjustment,
)
from src.infrastructure.repository import (
    get_top5_history_repository,
    get_top5_prices_repository,
    get_nomad_candidates_repository,
)

logger = logging.getLogger(__name__)


class HistoricalBackfillService:
    """과거 데이터 백필 서비스"""
    
    def __init__(self, config: Optional[BackfillConfig] = None):
        self.config = config or get_backfill_config()
        self.stock_mapping = None
        self.ohlcv_data = None
        self.trading_days = None
        # v6.3.3: 글로벌 데이터 (나스닥, 환율)
        self.nasdaq_data = None
        self.usdkrw_data = None
    
    def load_data(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> bool:
        """데이터 로드
        
        Args:
            start_date: 시작 날짜
            end_date: 종료 날짜
            
        Returns:
            성공 여부
        """
        # 기본 날짜 설정
        if end_date is None:
            end_date = date.today() - timedelta(days=0)  # 어제
        
        if start_date is None:
            start_date = end_date - timedelta(days=60)
        
        logger.info(f"데이터 로드 시작: {start_date} ~ {end_date}")
        
        # 종목 매핑 로드
        self.stock_mapping = load_stock_mapping(self.config)
        if self.stock_mapping.empty:
            logger.error("종목 매핑 로드 실패")
            return False
        
        logger.info(f"종목 매핑 로드: {len(self.stock_mapping)}개")
        
        # 거래일 로드
        self.trading_days = get_trading_days(self.config, start_date, end_date)
        if not self.trading_days:
            logger.error("거래일 조회 실패")
            return False
        
        logger.info(f"거래일: {len(self.trading_days)}일")
        
        # OHLCV 로드 (백필 기간 + 60일 추가 - 지표 계산용)
        extended_start = start_date - timedelta(days=90)
        
        self.ohlcv_data = load_all_ohlcv(
            self.config,
            start_date=extended_start,
            end_date=end_date,
            num_workers=self.config.num_workers,
        )
        
        if not self.ohlcv_data:
            logger.error("OHLCV 로드 실패")
            return False
        
        logger.info(f"OHLCV 로드: {len(self.ohlcv_data)}개 종목")
        
        # v6.3.3: 글로벌 데이터 로드 (나스닥, 환율)
        self.nasdaq_data = load_global_index(self.config, 'NASDAQ')
        if self.nasdaq_data is not None:
            logger.info(f"나스닥 로드: {len(self.nasdaq_data)}일")
        
        # USD/KRW 파일 시도
        self.usdkrw_data = load_global_index(self.config, 'USDKRW')
        if self.usdkrw_data is None:
            # 대체 파일명 시도
            for name in ['USD_KRW', 'usdkrw', 'usd_krw', 'FX']:
                self.usdkrw_data = load_global_index(self.config, name)
                if self.usdkrw_data is not None:
                    break
        
        if self.usdkrw_data is not None:
            logger.info(f"환율 로드: {len(self.usdkrw_data)}일")
        
        return True
    
    def _calculate_daily_scores(self, trade_date: date) -> pd.DataFrame:
        """특정 날짜의 전체 종목 점수 계산 (v6.3.3 통일)
        
        ⚠️ 중요: 
        1. TV200 스냅샷이 있으면 → 스냅샷 코드만 점수 계산 (유니버스 일치)
        2. 스냅샷 없으면 → 모든 OHLCV + filter_stocks (fallback)
        3. 점수 계산은 ScoreCalculatorV5 (실시간과 100% 동일)
        
        Args:
            trade_date: 거래일
            
        Returns:
            점수 DataFrame
        """
        from src.domain.models import DailyPrice, StockData
        from src.domain.score_calculator import ScoreCalculatorV5
        from src.config.constants import MIN_DAILY_DATA_COUNT
        
        calculator = ScoreCalculatorV5()
        
        # v6.3.3: 글로벌 조정값 계산 (해당 날짜 기준)
        global_adjustment = self._get_global_adjustment(trade_date)
        if global_adjustment != 0:
            logger.info(f"[{trade_date}] 글로벌 조정: {global_adjustment:+d}점")
        
        # v6.3.3: TV200 스냅샷 확인 (유니버스 소스 오브 트루스)
        universe_codes = self._get_universe_codes(trade_date)
        use_snapshot = universe_codes is not None
        
        if use_snapshot:
            logger.info(f"[{trade_date}] TV200 스냅샷 사용: {len(universe_codes)}개")
            target_codes = set(universe_codes)
        else:
            logger.info(f"[{trade_date}] TV200 스냅샷 없음 → OHLCV 기반 필터 사용")
            target_codes = set(self.ohlcv_data.keys())
        
        results = []
        
        # 실시간과 동일한 룩백 길이 (MIN_DAILY_DATA_COUNT + 10 = 30봉)
        lookback_days = MIN_DAILY_DATA_COUNT + 10
        
        for code in target_codes:
            if code not in self.ohlcv_data:
                # 스냅샷에는 있지만 OHLCV가 없는 경우 (드묾)
                logger.debug(f"OHLCV 없음: {code}")
                continue
                
            df = self.ohlcv_data[code]
            
            try:
                # 해당 날짜까지의 데이터
                mask = df['date'].dt.date <= trade_date
                df_until = df[mask].copy()
                
                if len(df_until) < MIN_DAILY_DATA_COUNT:
                    continue
                
                # 마지막 행이 해당 날짜인지 확인
                if df_until.iloc[-1]['date'].date() != trade_date:
                    continue
                
                # 실시간과 동일하게 최근 30봉만 사용
                df_recent = df_until.tail(lookback_days)
                
                # DataFrame → List[DailyPrice] 변환
                daily_prices = self._convert_to_daily_prices(df_recent)
                
                if len(daily_prices) < MIN_DAILY_DATA_COUNT:
                    continue
                
                # 종목명/업종 조회
                name_row = self.stock_mapping[self.stock_mapping['code'] == code]
                name = name_row['name'].iloc[0] if len(name_row) > 0 else code
                sector = name_row['sector'].iloc[0] if len(name_row) > 0 and 'sector' in self.stock_mapping.columns else None
                
                # 거래대금 계산 (억원)
                today_row = df_recent.iloc[-1]
                trading_value = today_row['close'] * today_row['volume'] / 100_000_000
                
                # StockData 생성 (실시간과 동일한 구조)
                stock_data = StockData(
                    code=code,
                    name=name,
                    daily_prices=daily_prices,
                    current_price=int(today_row['close']),
                    trading_value=trading_value,
                )
                
                # 🔥 핵심: ScoreCalculatorV5로 점수 계산 (실시간과 100% 동일)
                score_result = calculator.calculate_single_score(stock_data)
                
                if score_result is None:
                    continue
                
                # 글로벌 조정 적용
                final_score = min(100.0, score_result.score_total + global_adjustment)
                
                # 등급 재계산 (글로벌 조정 반영)
                from src.domain.score_calculator import get_grade
                grade = get_grade(final_score)
                
                results.append({
                    'date': trade_date,
                    'code': code,
                    'name': name,
                    'close': int(today_row['close']),
                    'change_rate': score_result.change_rate,
                    'trading_value': trading_value,
                    'volume': int(today_row['volume']),
                    'score': final_score,
                    'grade': grade.value,
                    # ScoreCalculatorV5에서 계산된 지표값 사용
                    'cci': score_result.score_detail.raw_cci,
                    'rsi': score_result.score_detail.raw_rsi,  # v6.5: RSI 저장
                    'disparity_20': score_result.score_detail.raw_distance,
                    'consecutive_up': score_result.score_detail.raw_consec_days,
                    'volume_ratio_5': score_result.score_detail.raw_volume_ratio,
                    # v6.5.2: sector 추가
                    'sector': sector,
                })
                
            except Exception as e:
                logger.debug(f"점수 계산 실패 {code}: {e}")
                continue
        
        df_result = pd.DataFrame(results)
        
        if len(df_result) > 0:
            before_count = len(df_result)
            before_codes = set(df_result['code'].tolist())
            
            # v6.3.3: 스냅샷 사용 시 filter_stocks 스킵 (이미 필터된 유니버스)
            if not use_snapshot:
                # 스냅샷 없을 때만 필터링
                df_result = filter_stocks(df_result, self.config, self.stock_mapping)
                
                after_count = len(df_result)
                after_codes = set(df_result['code'].tolist()) if len(df_result) > 0 else set()
                
                logger.info(f"[{trade_date}] 필터: {before_count}개 → {after_count}개 (제외: {before_count - after_count}개)")
                
                # 상세 저장 (첫 날만)
                if hasattr(self, '_first_day_logged') is False or not self._first_day_logged:
                    self._save_backfill_filter_result(trade_date, before_codes, after_codes, df_result)
                    self._first_day_logged = True
            else:
                logger.info(f"[{trade_date}] 스냅샷 사용 → 필터 스킵: {before_count}개")
        
        return df_result
    
    def _get_universe_codes(self, trade_date: date) -> Optional[List[str]]:
        """해당 날짜의 TV200 유니버스 코드 조회 (v6.3.3)
        
        Returns:
            스냅샷이 있으면 코드 리스트, 없으면 None
        """
        try:
            from src.infrastructure.repository import get_tv200_snapshot_repository
            snapshot_repo = get_tv200_snapshot_repository()
            
            date_str = trade_date.isoformat()
            codes = snapshot_repo.get_codes_for_date(date_str, filter_stage='after')
            
            if codes:
                return codes
            
            # JSON 파일 fallback (스냅샷이 없는 경우)
            import json
            from pathlib import Path
            
            json_path = Path(f"logs/tv200_{date_str}_after_filter.json")
            if json_path.exists():
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if 'stocks' in data:
                        codes = [s['code'] for s in data['stocks']]
                        logger.info(f"[{trade_date}] JSON 스냅샷 사용: {len(codes)}개")
                        return codes
            
            return None
            
        except Exception as e:
            logger.debug(f"TV200 스냅샷 조회 실패 {trade_date}: {e}")
            return None
    
    def _convert_to_daily_prices(self, df: pd.DataFrame) -> List:
        """DataFrame을 List[DailyPrice]로 변환 (v6.3.2)
        
        실시간 kis_client.get_daily_prices()와 동일한 형태로 변환
        
        Args:
            df: OHLCV DataFrame (오래된 순 정렬)
            
        Returns:
            List[DailyPrice]
        """
        from src.domain.models import DailyPrice
        
        daily_prices = []
        
        for _, row in df.iterrows():
            try:
                # 날짜 변환
                row_date = row['date']
                if isinstance(row_date, pd.Timestamp):
                    row_date = row_date.date()
                elif isinstance(row_date, str):
                    row_date = pd.to_datetime(row_date).date()
                
                # 거래대금 계산
                trading_value = row['close'] * row['volume']  # 원 단위
                
                daily_price = DailyPrice(
                    date=row_date,
                    open=int(row['open']),
                    high=int(row['high']),
                    low=int(row['low']),
                    close=int(row['close']),
                    volume=int(row['volume']),
                    trading_value=trading_value,
                )
                daily_prices.append(daily_price)
                
            except Exception as e:
                logger.debug(f"DailyPrice 변환 실패: {e}")
                continue
        
        return daily_prices
    
    def _get_global_adjustment(self, trade_date: date) -> int:
        """해당 날짜의 글로벌 조정값 계산 (v6.3.3)
        
        Args:
            trade_date: 거래일
            
        Returns:
            점수 조정값 (0, 3, 5)
        """
        nasdaq_change = None
        usdkrw_change = None
        
        # 나스닥 전일 대비 변화율 조회
        # 한국시간 기준 거래일 전날의 미국장 마감 데이터
        if self.nasdaq_data is not None:
            # 거래일 또는 그 전날의 데이터 찾기
            mask = self.nasdaq_data['date'].dt.date <= trade_date
            nasdaq_until = self.nasdaq_data[mask]
            if len(nasdaq_until) >= 1:
                nasdaq_change = nasdaq_until.iloc[-1]['change_rate']
        
        # 환율 변화율 조회
        if self.usdkrw_data is not None:
            mask = self.usdkrw_data['date'].dt.date <= trade_date
            usdkrw_until = self.usdkrw_data[mask]
            if len(usdkrw_until) >= 1:
                usdkrw_change = usdkrw_until.iloc[-1]['change_rate']
        
        return calculate_global_adjustment(nasdaq_change, usdkrw_change)
    
    def _save_backfill_filter_result(self, trade_date, before_codes, after_codes, df_result):
        """백필 필터 결과 저장 (v6.3.2)"""
        import json
        from pathlib import Path
        
        try:
            filepath = Path(f"logs/backfill_{trade_date}_filter.json")
            filepath.parent.mkdir(exist_ok=True)
            
            # TOP10 정보
            top10 = []
            if len(df_result) > 0:
                df_sorted = df_result.sort_values('score', ascending=False).head(10)
                for _, row in df_sorted.iterrows():
                    top10.append({
                        'code': row['code'],
                        'name': row['name'],
                        'score': round(row['score'], 2),
                        'change_rate': round(row.get('change_rate', 0), 2),
                        'trading_value': round(row.get('trading_value', 0), 1),
                    })
            
            data = {
                'date': str(trade_date),
                'before_filter': len(before_codes),
                'after_filter': len(after_codes),
                'filtered_out_count': len(before_codes - after_codes),
                'after_codes': sorted(list(after_codes)),
                'top10': top10,
            }
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
            logger.info(f"백필 필터 결과 저장: {filepath}")
            
        except Exception as e:
            logger.warning(f"백필 필터 결과 저장 실패: {e}")
    
    def backfill_top5(
        self,
        days: int = 20,
        end_date: Optional[date] = None,
        dry_run: bool = False,
    ) -> Dict[str, int]:
        """TOP5 백필
        
        Args:
            days: 백필 일수
            end_date: 종료 날짜
            dry_run: True면 DB 저장 안 함
            
        Returns:
            통계 딕셔너리
        """
        if end_date is None:
            end_date = date.today() - timedelta(days=0)
        
        start_date = end_date - timedelta(days=days + 30)  # 여유 추가
        
        # 데이터 로드
        if not self.load_data(start_date, end_date):
            return {'error': 'data_load_failed'}
        
        # 백필 대상 거래일
        target_days = [d for d in self.trading_days if d <= end_date][-days:]
        
        logger.info(f"TOP5 백필 시작: {len(target_days)}일")
        
        stats = {
            'total_days': len(target_days),
            'processed_days': 0,
            'top5_saved': 0,
            'prices_saved': 0,
        }
        
        # Repository
        history_repo = get_top5_history_repository()
        prices_repo = get_top5_prices_repository()
        
        for i, trade_date in enumerate(target_days):
            logger.info(f"[{i+1}/{len(target_days)}] {trade_date} 처리 중...")
            
            # 점수 계산
            df_scores = self._calculate_daily_scores(trade_date)
            
            if len(df_scores) == 0:
                logger.warning(f"{trade_date}: 점수 계산 실패")
                continue
            
            # TOP5 추출 (점수 기준 정렬)
            df_scores = df_scores.sort_values('score', ascending=False)
            top5 = df_scores.head(5)
            
            for rank, (_, row) in enumerate(top5.iterrows(), 1):
                if dry_run:
                    logger.info(f"  #{rank} {row['name']} ({row['code']}) - {row['score']:.1f}점 {row['grade']}등급")
                    continue
                
                # DB 저장
                history_data = {
                    'screen_date': trade_date.isoformat(),
                    'rank': rank,
                    'stock_code': row['code'],
                    'stock_name': row['name'],
                    'screen_price': row['close'],
                    'screen_score': row['score'],
                    'grade': row['grade'],
                    'cci': row.get('cci'),
                    'rsi': row.get('rsi'),
                    'change_rate': row.get('change_rate'),
                    'disparity_20': row.get('disparity_20'),
                    'consecutive_up': row.get('consecutive_up', 0),
                    'volume_ratio_5': row.get('volume_ratio_5'),  # v6.3.2: 이미 151번줄에서 19일 평균값으로 저장됨
                    'data_source': 'backfill',
                    # v6.3.1: 거래대금/거래량
                    'trading_value': row.get('trading_value'),
                    'volume': row.get('volume'),
                    # v6.5.2: sector 추가 (stock_mapping에서 조회)
                    'sector': row.get('sector'),
                    'sector_rank': None,  # 백필에서는 순위 계산 안 함
                    'is_leading_sector': 0,
                }
                
                # v6.3.2: realtime 우선 정책 - realtime이 있으면 덮어쓰지 않음
                history_id = history_repo.upsert_backfill_safe(history_data)
                
                if history_id is None:
                    # realtime 데이터가 이미 존재하여 스킵됨
                    logger.debug(f"realtime 존재로 스킵: {trade_date} {row['code']}")
                    continue
                
                stats['top5_saved'] += 1
                
                # D+1 ~ D+20 가격 저장
                future_days = [d for d in self.trading_days if d > trade_date][:20]
                
                for days_after, future_date in enumerate(future_days, 1):
                    # 해당 날짜의 가격
                    code = row['code']
                    if code not in self.ohlcv_data:
                        continue
                    
                    df_stock = self.ohlcv_data[code]
                    mask = df_stock['date'].dt.date == future_date
                    df_day = df_stock[mask]
                    
                    if len(df_day) == 0:
                        continue
                    
                    day_data = df_day.iloc[0]
                    screen_price = row['close']
                    
                    price_data = {
                        'top5_history_id': history_id,
                        'trade_date': future_date.isoformat(),
                        'days_after': days_after,
                        'open_price': int(day_data['open']),
                        'high_price': int(day_data['high']),
                        'low_price': int(day_data['low']),
                        'close_price': int(day_data['close']),
                        'volume': int(day_data['volume']),
                        'return_from_screen': (day_data['close'] - screen_price) / screen_price * 100,
                        'gap_rate': (day_data['open'] - screen_price) / screen_price * 100,
                        'high_return': (day_data['high'] - screen_price) / screen_price * 100,
                        'low_return': (day_data['low'] - screen_price) / screen_price * 100,
                        'data_source': 'backfill',
                    }
                    
                    prices_repo.insert(price_data)
                    stats['prices_saved'] += 1
                
                # 추적 상태 업데이트
                if len(future_days) >= 20:
                    history_repo.update_status(history_id, 'completed')
                    history_repo.update_tracking_days(history_id, len(future_days), future_days[-1].isoformat())
            
            stats['processed_days'] += 1
        
        logger.info(f"TOP5 백필 완료: {stats}")
        return stats
    
    def backfill_nomad(
        self,
        days: int = 20,
        end_date: Optional[date] = None,
        dry_run: bool = False,
    ) -> Dict[str, int]:
        """유목민 공부법 백필 (상한가/거래량천만)
        
        Args:
            days: 백필 일수
            end_date: 종료 날짜
            dry_run: True면 DB 저장 안 함
            
        Returns:
            통계 딕셔너리
        """
        if end_date is None:
            end_date = date.today() - timedelta(days=0)
        
        start_date = end_date - timedelta(days=days + 30)
        
        # 데이터 로드
        if not self.load_data(start_date, end_date):
            return {'error': 'data_load_failed'}
        
        target_days = [d for d in self.trading_days if d <= end_date][-days:]
        
        logger.info(f"유목민 백필 시작: {len(target_days)}일")
        
        stats = {
            'total_days': len(target_days),
            'processed_days': 0,
            'limit_up': 0,
            'volume_explosion': 0,
        }
        
        # Repository
        nomad_repo = get_nomad_candidates_repository()
        
        for i, trade_date in enumerate(target_days):
            logger.info(f"[{i+1}/{len(target_days)}] {trade_date} 유목민 처리 중...")
            
            candidates = []
            
            for code, df in self.ohlcv_data.items():
                # 해당 날짜 데이터
                mask = df['date'].dt.date == trade_date
                df_day = df[mask]
                
                if len(df_day) == 0:
                    continue
                
                row = df_day.iloc[0]
                
                # 등락률 계산
                prev_mask = df['date'].dt.date < trade_date
                df_prev = df[prev_mask]
                
                if len(df_prev) == 0:
                    continue
                
                prev_close = df_prev.iloc[-1]['close']
                change_rate = (row['close'] - prev_close) / prev_close * 100
                
                # 거래대금 계산
                trading_value = row['close'] * row['volume'] / 100_000_000
                
                # 상한가 확인 (29.5% 이상)
                is_limit_up = change_rate >= self.config.limit_up_threshold
                
                # 거래량천만 확인 (1000만주 이상)
                is_volume_explosion = row['volume'] >= self.config.volume_explosion_shares
                
                if not (is_limit_up or is_volume_explosion):
                    continue
                
                # 종목명 조회
                name_row = self.stock_mapping[self.stock_mapping['code'] == code]
                name = name_row['name'].iloc[0] if len(name_row) > 0 else code
                
                # ETF 등 제외
                skip = False
                for pattern in self.config.exclude_patterns:
                    if pattern.lower() in name.lower():
                        skip = True
                        break
                
                if skip:
                    continue
                
                # 사유 결정
                if is_limit_up and is_volume_explosion:
                    reason = '상한가+거래량'
                elif is_limit_up:
                    reason = '상한가'
                else:
                    reason = '거래량천만'
                
                candidates.append({
                    'study_date': trade_date.isoformat(),
                    'stock_code': code,
                    'stock_name': name,
                    'reason_flag': reason,
                    'close_price': int(row['close']),
                    'change_rate': change_rate,
                    'volume': int(row['volume']),
                    'trading_value': trading_value,
                    'data_source': 'backfill',
                })
                
                if is_limit_up:
                    stats['limit_up'] += 1
                if is_volume_explosion:
                    stats['volume_explosion'] += 1
            
            # DB 저장
            if not dry_run:
                for candidate in candidates:
                    nomad_repo.upsert(candidate)
            else:
                for c in candidates:
                    logger.info(f"  {c['reason_flag']}: {c['stock_name']} ({c['stock_code']}) +{c['change_rate']:.1f}%")
            
            stats['processed_days'] += 1
        
        logger.info(f"유목민 백필 완료: {stats}")
        return stats
    
    def auto_fill_missing(
        self,
        days: int = 30,
    ) -> Dict[str, int]:
        """누락 데이터 자동 채우기
        
        최근 N일 중 데이터가 없는 날짜 자동 백필
        """
        end_date = date.today() - timedelta(days=0)
        start_date = end_date - timedelta(days=days)
        
        # 거래일 조회
        self.trading_days = get_trading_days(self.config, start_date, end_date)
        
        # 기존 데이터 날짜 조회
        history_repo = get_top5_history_repository()
        existing_dates = set(history_repo.get_dates_with_data(days))
        
        # 누락 날짜
        missing_dates = [d for d in self.trading_days if d.isoformat() not in existing_dates]
        
        if not missing_dates:
            logger.info("누락 데이터 없음")
            return {'missing': 0}
        
        logger.info(f"누락 데이터 발견: {len(missing_dates)}일")
        
        # 누락 날짜 백필
        stats = {
            'missing': len(missing_dates),
            'top5_filled': 0,
            'nomad_filled': 0,
        }
        
        for missing_date in missing_dates:
            logger.info(f"자동 채우기: {missing_date}")
            
            # TOP5 백필
            self.backfill_top5(days=1, end_date=missing_date)
            stats['top5_filled'] += 1
            
            # 유목민 백필
            self.backfill_nomad(days=1, end_date=missing_date)
            stats['nomad_filled'] += 1
        
        return stats


# 편의 함수
def backfill_top5(days: int = 20, dry_run: bool = False) -> Dict[str, int]:
    """TOP5 백필 편의 함수"""
    service = HistoricalBackfillService()
    return service.backfill_top5(days=days, dry_run=dry_run)


def backfill_nomad(days: int = 20, dry_run: bool = False) -> Dict[str, int]:
    """유목민 백필 편의 함수"""
    service = HistoricalBackfillService()
    return service.backfill_nomad(days=days, dry_run=dry_run)


def auto_fill_missing(days: int = 30) -> Dict[str, int]:
    """자동 채우기 편의 함수"""
    service = HistoricalBackfillService()
    return service.auto_fill_missing(days=days)