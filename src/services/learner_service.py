"""
학습 서비스 v5.2
================

TOP5 스크리닝 결과의 익일 성과를 수집하고,
상관관계 분석을 통해 가중치를 자동 조정합니다.

동작 흐름:
1. 매일 17:00 익일 결과 수집 (data_updater 16:30 후)
2. 30일치 데이터로 상관관계 분석
3. 상관관계 높은 지표에 가중치 증가
4. weight_config 업데이트

사용:
    from src.services.learner_service import run_daily_learning
    run_daily_learning()
"""

import logging
import time
from datetime import date, timedelta
from typing import Dict, List, Optional
import statistics

from src.infrastructure.database import get_database
from src.infrastructure.repository import (
    get_repository,
    get_screening_repository,
    get_next_day_repository,
)
from src.adapters.kis_client import get_kis_client

logger = logging.getLogger(__name__)


class LearnerService:
    """학습 서비스"""
    
    def __init__(self):
        self.repo = get_repository()
        self.kis = get_kis_client()
        
        # 학습 설정
        self.min_samples = 30          # 최소 샘플 수
        self.learning_rate = 0.1       # 가중치 조정 비율
        self.correlation_threshold = 0.05  # 의미있는 상관관계 임계값
        self.api_delay = 0.3           # API 호출 간격
    
    def collect_next_day_results(self, target_date: date = None) -> Dict:
        """익일 결과 수집
        
        Args:
            target_date: 스크리닝 날짜 (기본: 어제)
            
        Returns:
            수집 결과 {'collected': int, 'failed': int, 'skipped': int}
        """
        if target_date is None:
            target_date = date.today() - timedelta(days=1)
        
        logger.info(f"📊 익일 결과 수집 시작: {target_date}")
        
        # 해당 날짜의 스크리닝 종목 조회 (익일 결과 없는 것만)
        # top3_only=True: is_top3=1인 종목만 (실제로는 TOP5가 저장됨)
        items = self.repo.screening.get_items_without_next_day_result(
            screen_date=target_date,
            top3_only=True,
        )
        
        if not items:
            logger.info(f"  수집할 종목 없음 (이미 수집됨 또는 스크리닝 없음)")
            return {'collected': 0, 'failed': 0, 'skipped': 0}
        
        logger.info(f"  수집 대상: {len(items)}개 종목")
        
        results = {'collected': 0, 'failed': 0, 'skipped': 0}
        
        for item in items:
            try:
                code = item['stock_code']
                name = item['stock_name']
                yesterday_close = item['current_price']  # 스크리닝 당시 종가
                
                # 익일 시고저종 조회
                prices = self.kis.get_daily_prices(code, count=5)
                
                if not prices:
                    logger.warning(f"  ⚠️ {code} {name}: 가격 데이터 없음")
                    results['failed'] += 1
                    continue
                
                # 스크리닝 다음 거래일 찾기
                # prices[0]이 가장 최근, prices[-1]이 가장 과거
                next_day_price = None
                for price in prices:
                    if price.date > target_date:
                        next_day_price = price
                        break
                
                if next_day_price is None:
                    logger.debug(f"  ⏭️ {code} {name}: 익일 데이터 없음 (아직)")
                    results['skipped'] += 1
                    continue
                
                # 수익률 계산
                gap_rate = ((next_day_price.open - yesterday_close) / yesterday_close) * 100
                day_return = ((next_day_price.close - yesterday_close) / yesterday_close) * 100
                high_change = ((next_day_price.high - yesterday_close) / yesterday_close) * 100
                low_change = ((next_day_price.low - yesterday_close) / yesterday_close) * 100
                volatility = ((next_day_price.high - next_day_price.low) / next_day_price.low) * 100 if next_day_price.low > 0 else 0
                
                # DB 저장
                self.repo.save_next_day_result(
                    stock_code=code,
                    screen_date=target_date,
                    gap_rate=gap_rate,
                    day_return=day_return,
                    volatility=volatility,
                    next_open=next_day_price.open,
                    next_close=next_day_price.close,
                    next_high=next_day_price.high,
                    next_low=next_day_price.low,
                    high_change_rate=high_change,
                )
                
                # 결과 로그
                win_emoji = "✅" if day_return > 0 else "❌"
                logger.info(f"  {win_emoji} {code} {name}: 갭 {gap_rate:+.1f}%, 종가 {day_return:+.1f}%, 고가 {high_change:+.1f}%")
                results['collected'] += 1
                
                time.sleep(self.api_delay)
                
            except Exception as e:
                logger.error(f"  ✗ {item['stock_code']}: {e}")
                results['failed'] += 1
        
        logger.info(f"📊 익일 결과 수집 완료: 성공 {results['collected']}, 실패 {results['failed']}, 스킵 {results['skipped']}")
        return results
    
    def collect_multiple_days(self, days: int = 7) -> Dict:
        """최근 N일간 익일 결과 수집 (누락분 보완)
        
        Args:
            days: 수집할 과거 일수
            
        Returns:
            총 수집 결과
        """
        logger.info(f"📊 최근 {days}일간 익일 결과 수집")
        
        total = {'collected': 0, 'failed': 0, 'skipped': 0}
        
        today = date.today()
        for i in range(1, days + 1):
            target_date = today - timedelta(days=i)
            
            # 주말 스킵
            if target_date.weekday() >= 5:
                continue
            
            result = self.collect_next_day_results(target_date)
            total['collected'] += result['collected']
            total['failed'] += result['failed']
            total['skipped'] += result['skipped']
        
        logger.info(f"📊 총 수집 결과: 성공 {total['collected']}, 실패 {total['failed']}, 스킵 {total['skipped']}")
        return total
    
    def calculate_correlations(self, days: int = 30) -> Dict[str, float]:
        """점수-수익률 상관관계 계산
        
        Args:
            days: 분석 기간
            
        Returns:
            지표별 상관계수 {'score_cci_value': 0.15, ...}
        """
        data = self.repo.get_screening_with_next_day(days=days)
        
        if len(data) < self.min_samples:
            logger.warning(f"⚠️ 샘플 부족: {len(data)}개 < {self.min_samples}개 필요")
            return {}
        
        logger.info(f"📈 상관관계 분석: {len(data)}개 샘플 ({days}일)")
        
        # 지표별 상관계수 계산
        correlations = {}
        
        # DB 컬럼명 → 표시 이름
        indicators = [
            ('score_total', '총점'),
            ('score_cci_value', 'CCI'),
            ('score_cci_slope', '이격도'),
            ('score_ma20_slope', 'MA20'),
            ('score_candle', '캔들'),
            ('score_change', '등락률'),
        ]
        
        # 수익률 (종가 기준)
        returns = [d['day_change_rate'] for d in data]
        
        logger.info("  지표별 상관계수:")
        for db_col, name in indicators:
            try:
                values = [d.get(db_col, 0) or 0 for d in data]
                corr = self._pearson_correlation(values, returns)
                correlations[db_col] = round(corr, 4)
                
                # 상관관계 강도 표시
                if abs(corr) >= 0.1:
                    strength = "🔥 강함"
                elif abs(corr) >= 0.05:
                    strength = "✅ 보통"
                else:
                    strength = "⚪ 약함"
                
                logger.info(f"    {name:>8}: {corr:+.4f} {strength}")
                
            except Exception as e:
                logger.error(f"    {name}: 계산 실패 - {e}")
                correlations[db_col] = 0.0
        
        return correlations
    
    def _pearson_correlation(self, x: List[float], y: List[float]) -> float:
        """피어슨 상관계수 계산"""
        n = len(x)
        if n < 2:
            return 0.0
        
        try:
            mean_x = statistics.mean(x)
            mean_y = statistics.mean(y)
            
            numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
            
            std_x = statistics.stdev(x)
            std_y = statistics.stdev(y)
            
            if std_x == 0 or std_y == 0:
                return 0.0
            
            denominator = (n - 1) * std_x * std_y
            
            return numerator / denominator if denominator != 0 else 0.0
            
        except Exception:
            return 0.0
    
    def update_weights(self, correlations: Dict[str, float]) -> bool:
        """가중치 업데이트
        
        상관관계가 높은 지표는 가중치 증가
        상관관계가 낮은 지표는 가중치 감소
        
        Args:
            correlations: 지표별 상관계수
            
        Returns:
            업데이트 성공 여부
        """
        if not correlations:
            logger.warning("⚠️ 상관관계 데이터 없음 - 가중치 업데이트 스킵")
            return False
        
        # score_total은 제외 (개별 지표만)
        correlations = {k: v for k, v in correlations.items() if k != 'score_total'}
        
        current_weights = self.repo.get_current_weights()
        if not current_weights:
            logger.warning("⚠️ 현재 가중치 없음 - 업데이트 스킵")
            return False
        
        logger.info("📝 가중치 업데이트:")
        new_weights = {}
        
        for indicator, corr in correlations.items():
            # indicator 이름 매핑 (DB 컬럼 → weight_config 키)
            weight_key = indicator.replace('score_', '')
            old_weight = current_weights.get(weight_key, 1.0)
            
            # 상관계수 기반 조정
            if abs(corr) > self.correlation_threshold:
                # 양의 상관: 가중치 증가, 음의 상관: 가중치 감소
                adjustment = corr * self.learning_rate
                new_weight = old_weight * (1 + adjustment)
                
                # 가중치 범위 제한 (0.5 ~ 5.0)
                new_weight = max(0.5, min(5.0, new_weight))
            else:
                new_weight = old_weight
            
            new_weights[weight_key] = round(new_weight, 3)
            
            change = ((new_weight - old_weight) / old_weight) * 100 if old_weight > 0 else 0
            if abs(change) > 0.1:
                logger.info(f"    {weight_key}: {old_weight:.3f} → {new_weight:.3f} ({change:+.1f}%)")
        
        # DB 업데이트
        try:
            self.repo.update_weights(new_weights)
            self.repo.save_weight_history(
                weights=new_weights,
                correlations=correlations,
                reason="자동 학습 (30일 상관관계)",
            )
            logger.info("✅ 가중치 업데이트 완료")
            return True
            
        except Exception as e:
            logger.error(f"❌ 가중치 업데이트 실패: {e}")
            return False
    
    def get_performance_summary(self, days: int = 30) -> Dict:
        """성과 요약
        
        Args:
            days: 분석 기간
            
        Returns:
            성과 통계
        """
        data = self.repo.get_next_day_results(days=days)
        
        if not data:
            return {}
        
        returns = [d['day_change_rate'] for d in data]
        gap_rates = [d['gap_rate'] for d in data]
        high_changes = [d.get('high_change_rate', 0) or 0 for d in data]
        
        win_count = sum(1 for r in returns if r > 0)
        
        summary = {
            'total_trades': len(data),
            'win_count': win_count,
            'win_rate': (win_count / len(data)) * 100 if data else 0,
            'avg_return': statistics.mean(returns) if returns else 0,
            'avg_gap': statistics.mean(gap_rates) if gap_rates else 0,
            'avg_high': statistics.mean(high_changes) if high_changes else 0,
            'max_return': max(returns) if returns else 0,
            'min_return': min(returns) if returns else 0,
        }
        
        return summary
    
    def run_daily_learning(self) -> Dict:
        """일일 학습 실행
        
        스케줄러에서 매일 17:00에 호출
        
        Returns:
            실행 결과
        """
        logger.info("=" * 60)
        logger.info("📚 일일 학습 시작")
        logger.info("=" * 60)
        
        results = {
            'next_day_collected': 0,
            'correlations': {},
            'weights_updated': False,
            'performance': {},
        }
        
        try:
            # 1. 익일 결과 수집 (어제 스크리닝 → 오늘 결과)
            logger.info("\n[1단계] 익일 결과 수집")
            collection = self.collect_next_day_results()
            results['next_day_collected'] = collection['collected']
            
            # 2. 누락분 보완 (최근 7일)
            if collection['collected'] == 0:
                logger.info("\n[1-1단계] 누락분 보완 수집")
                backup = self.collect_multiple_days(days=7)
                results['next_day_collected'] = backup['collected']
            
            # 3. 상관관계 분석
            logger.info("\n[2단계] 상관관계 분석")
            correlations = self.calculate_correlations(days=30)
            results['correlations'] = correlations
            
            # 4. 가중치 업데이트
            logger.info("\n[3단계] 가중치 업데이트")
            if correlations:
                results['weights_updated'] = self.update_weights(correlations)
            else:
                logger.info("  상관관계 데이터 부족 - 스킵")
            
            # 5. 성과 요약
            logger.info("\n[4단계] 성과 요약")
            performance = self.get_performance_summary(days=30)
            results['performance'] = performance
            
            if performance:
                logger.info(f"  총 매매: {performance['total_trades']}건")
                logger.info(f"  승률: {performance['win_rate']:.1f}% ({performance['win_count']}/{performance['total_trades']})")
                logger.info(f"  평균 수익률: {performance['avg_return']:+.2f}%")
                logger.info(f"  평균 갭: {performance['avg_gap']:+.2f}%")
                logger.info(f"  평균 고가: {performance['avg_high']:+.2f}%")
            
        except Exception as e:
            logger.error(f"❌ 학습 실행 오류: {e}")
            import traceback
            traceback.print_exc()
        
        logger.info("\n" + "=" * 60)
        logger.info("📚 일일 학습 완료")
        logger.info(f"   익일 결과 수집: {results['next_day_collected']}건")
        logger.info(f"   가중치 업데이트: {'✅ 완료' if results['weights_updated'] else '⏭️ 스킵'}")
        logger.info("=" * 60)
        
        return results


# ============================================================
# 싱글톤 및 편의 함수
# ============================================================

_learner: Optional[LearnerService] = None


def get_learner() -> LearnerService:
    """학습 서비스 인스턴스 반환"""
    global _learner
    if _learner is None:
        _learner = LearnerService()
    return _learner


def run_daily_learning() -> Dict:
    """일일 학습 실행 (스케줄러용)"""
    learner = get_learner()
    return learner.run_daily_learning()


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    
    print("=" * 60)
    print("🧪 학습 서비스 테스트")
    print("=" * 60)
    
    learner = LearnerService()
    
    # 테스트 1: 성과 요약
    print("\n[테스트 1] 성과 요약")
    performance = learner.get_performance_summary(days=30)
    if performance:
        print(f"  총 매매: {performance['total_trades']}건")
        print(f"  승률: {performance['win_rate']:.1f}%")
        print(f"  평균 수익률: {performance['avg_return']:+.2f}%")
    else:
        print("  데이터 없음")
    
    # 테스트 2: 상관관계 분석
    print("\n[테스트 2] 상관관계 분석")
    correlations = learner.calculate_correlations(days=30)
    if correlations:
        for k, v in correlations.items():
            print(f"  {k}: {v:+.4f}")
    else:
        print("  데이터 부족")
    
    # 테스트 3: 전체 학습 실행
    print("\n[테스트 3] 전체 학습 실행")
    confirm = input("전체 학습을 실행하시겠습니까? (y/N): ")
    if confirm.lower() == 'y':
        result = learner.run_daily_learning()
        print(f"\n결과: {result}")
