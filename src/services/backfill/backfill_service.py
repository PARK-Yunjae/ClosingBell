"""
ClosingBell v6.0 백필 서비스

과거 데이터 백필:
- TOP5 20일 추적 데이터
- 유목민 공부법 (상한가/거래량천만) 데이터
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
)
from src.services.backfill.indicators import (
    calculate_all_indicators,
    calculate_score,
    score_to_grade,
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
            end_date = date.today() - timedelta(days=1)  # 어제
        
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
        
        return True
    
    def _calculate_daily_scores(self, trade_date: date) -> pd.DataFrame:
        """특정 날짜의 전체 종목 점수 계산
        
        Args:
            trade_date: 거래일
            
        Returns:
            점수 DataFrame
        """
        results = []
        
        for code, df in self.ohlcv_data.items():
            # 해당 날짜까지의 데이터
            mask = df['date'].dt.date <= trade_date
            df_until = df[mask].copy()
            
            if len(df_until) < 20:  # 최소 20일 필요
                continue
            
            # 지표 계산
            df_with_indicators = calculate_all_indicators(df_until)
            
            # 마지막 행 (해당 날짜)
            last_row = df_with_indicators.iloc[-1]
            
            if last_row['date'].date() != trade_date:
                continue  # 해당 날짜 데이터 없음
            
            # 점수 계산
            score = calculate_score(last_row)
            grade = score_to_grade(score)
            
            # 종목명 조회
            name_row = self.stock_mapping[self.stock_mapping['code'] == code]
            name = name_row['name'].iloc[0] if len(name_row) > 0 else code
            
            results.append({
                'date': trade_date,
                'code': code,
                'name': name,
                'close': int(last_row['close']),
                'change_rate': last_row['change_rate'],
                'trading_value': last_row.get('trading_value', 0),
                'volume': int(last_row['volume']),
                'score': score,
                'grade': grade,
                'cci': last_row.get('cci'),
                'rsi': last_row.get('rsi'),
                'disparity_20': last_row.get('disparity_20'),
                'consecutive_up': int(last_row.get('consecutive_up', 0)),
                'volume_ratio_5': last_row.get('volume_ratio_5'),
            })
        
        df_result = pd.DataFrame(results)
        
        if len(df_result) > 0:
            # 필터링
            df_result = filter_stocks(df_result, self.config, self.stock_mapping)
        
        return df_result
    
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
            end_date = date.today() - timedelta(days=1)
        
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
                    'volume_ratio_5': row.get('volume_ratio_5'),
                    'data_source': 'backfill',
                }
                
                history_id = history_repo.upsert(history_data)
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
            end_date = date.today() - timedelta(days=1)
        
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
        end_date = date.today() - timedelta(days=1)
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
