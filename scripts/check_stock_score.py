#!/usr/bin/env python
"""
특정 종목 점수 조회 스크립트

사용법:
    python scripts/check_stock_score.py 006800   # 미래에셋증권
    python scripts/check_stock_score.py 005930   # 삼성전자
    python scripts/check_stock_score.py 005930 000660 006800  # 여러 종목
"""

import sys
import os
import logging
from datetime import date

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.adapters.kis_client import get_kis_client
from src.domain.models import StockData, Weights
from src.domain.score_calculator import ScoreCalculator
from src.domain.indicators import calculate_all_indicators
from src.infrastructure.database import init_database
from src.infrastructure.repository import get_weight_repository
from src.config.constants import MIN_DAILY_DATA_COUNT


def format_price(price: int) -> str:
    """가격 포맷팅"""
    return f"{price:,}원"


def format_change_rate(rate: float) -> str:
    """등락률 포맷팅"""
    sign = "+" if rate >= 0 else ""
    return f"{sign}{rate:.2f}%"


def analyze_stock(stock_code: str, kis_client, weights: Weights) -> dict:
    """종목 분석"""
    stock_code = stock_code.zfill(6)
    
    # 1. 현재가 조회
    current = kis_client.get_current_price(stock_code)
    
    # 2. 일봉 데이터 조회
    prices = kis_client.get_daily_prices(stock_code, count=MIN_DAILY_DATA_COUNT + 5)
    
    if len(prices) < MIN_DAILY_DATA_COUNT:
        return {
            'error': f"데이터 부족: {len(prices)}일 (최소 {MIN_DAILY_DATA_COUNT}일 필요)"
        }
    
    # 3. StockData 생성
    trading_value = current.trading_value / 100_000_000  # 억원
    
    # 종목명 조회 (일봉 API에서 추출하기 어려우므로 간단히 처리)
    stock_name = f"종목{stock_code}"
    
    stock_data = StockData(
        code=stock_code,
        name=stock_name,
        daily_prices=prices,
        current_price=current.price,
        trading_value=trading_value,
    )
    
    # 4. 점수 계산
    calculator = ScoreCalculator(weights)
    score = calculator.calculate_single_score(stock_data)
    
    if score is None:
        return {'error': "점수 계산 실패"}
    
    # 5. 상세 지표 계산
    indicators = calculate_all_indicators(prices)
    
    return {
        'stock_code': stock_code,
        'stock_name': stock_name,
        'current_price': current.price,
        'change_rate': current.change_rate,
        'trading_value': trading_value,
        'score': score,
        'indicators': indicators,
    }


def print_stock_analysis(result: dict):
    """분석 결과 출력"""
    if 'error' in result:
        print(f"\n❌ 에러: {result['error']}")
        return
    
    score = result['score']
    indicators = result['indicators']
    
    print(f"\n{'='*60}")
    print(f"📊 {score.stock_name} ({score.stock_code}) 점수 분석")
    print(f"{'='*60}")
    
    print(f"\n💰 현재가: {format_price(score.current_price)} ({format_change_rate(score.change_rate)})")
    print(f"💵 거래대금: {score.trading_value:.0f}억원")
    
    print(f"\n📈 [점수 상세]")
    print(f"┌{'─'*58}┐")
    print(f"│ 1. CCI 값 점수:      {score.score_cci_value:5.1f}점  (CCI: {indicators.cci:+.1f})")
    print(f"│ 2. CCI 기울기 점수:  {score.score_cci_slope:5.1f}점  (5일 기울기: {indicators.cci_slope:+.2f})")
    print(f"│ 3. MA20 기울기 점수: {score.score_ma20_slope:5.1f}점  (7일 변화: {indicators.ma20_slope:+.2f}%)")
    print(f"│ 4. 양봉 품질 점수:   {score.score_candle:5.1f}점  (윗꼬리: {indicators.candle.upper_wick_ratio*100:.0f}%, MA20 {'위' if indicators.candle.is_above_ma20 else '아래'})")
    print(f"│ 5. 상승률 점수:      {score.score_change:5.1f}점  (당일: {format_change_rate(score.change_rate)})")
    print(f"└{'─'*58}┘")
    
    print(f"\n🏆 총점: {score.score_total:.1f}점")
    
    # 상세 지표 정보
    print(f"\n📉 [기술 지표 상세]")
    print(f"  • CCI(14): {indicators.cci:.1f}")
    print(f"  • MA20: {indicators.ma20:,.0f}원")
    print(f"  • 양봉 여부: {'✅ 양봉' if indicators.candle.is_bullish else '❌ 음봉'}")
    print(f"  • MA20 대비 위치: {indicators.candle.ma20_position:+.2f}%")
    
    # 종가매매 적합성 판단
    print(f"\n🎯 [종가매매 적합성]")
    
    suitability_score = 0
    issues = []
    strengths = []
    
    # CCI 180 근접 여부
    if 160 <= indicators.cci <= 200:
        strengths.append(f"CCI {indicators.cci:.0f} - 180 근접으로 적합")
        suitability_score += 2
    elif indicators.cci > 250:
        issues.append(f"CCI {indicators.cci:.0f} - 과열 구간")
    elif indicators.cci < 100:
        issues.append(f"CCI {indicators.cci:.0f} - 아직 상승 여력")
    else:
        strengths.append(f"CCI {indicators.cci:.0f} - 상승 구간")
        suitability_score += 1
    
    # 기울기
    if indicators.cci_slope > 0:
        strengths.append("CCI 상승 추세")
        suitability_score += 1
    else:
        issues.append("CCI 하락 추세 주의")
    
    if indicators.ma20_slope > 0:
        strengths.append("MA20 상승 추세")
        suitability_score += 1
    else:
        issues.append("MA20 하락 추세 주의")
    
    # 양봉 품질
    if indicators.candle.is_bullish and indicators.candle.upper_wick_ratio < 0.3:
        strengths.append("양봉 + 윗꼬리 짧음")
        suitability_score += 1
    elif not indicators.candle.is_bullish:
        issues.append("음봉")
    
    # MA20 안착
    if indicators.candle.is_above_ma20 and indicators.candle.ma20_position <= 5:
        strengths.append("MA20 적정 위치 안착")
        suitability_score += 1
    elif indicators.candle.ma20_position > 5:
        issues.append("MA20 대비 과열")
    elif not indicators.candle.is_above_ma20:
        issues.append("MA20 아래 위치")
    
    # 결과 출력
    if strengths:
        print(f"  ✅ 강점:")
        for s in strengths:
            print(f"     • {s}")
    
    if issues:
        print(f"  ⚠️ 주의:")
        for i in issues:
            print(f"     • {i}")
    
    # 종합 판단
    if suitability_score >= 5:
        verdict = "🟢 적극 매수 고려"
    elif suitability_score >= 3:
        verdict = "🟡 조건부 매수 검토"
    else:
        verdict = "🔴 관망 권장"
    
    print(f"\n  📌 종합: {verdict}")
    print(f"{'='*60}")


def compare_with_today_top(stock_code: str, kis_client, weights: Weights):
    """오늘의 전체 종목과 비교하여 순위 계산"""
    from src.services.screener_service import ScreenerService
    
    print(f"\n🔍 전체 종목 대비 순위 조회 중...")
    
    # 전체 스크리닝 실행 (알림/저장 없음)
    service = ScreenerService(kis_client=kis_client)
    result = service.run_screening(
        screen_time="check",
        save_to_db=False,
        send_alert=False,
        is_preview=False,
    )
    
    # 순위 찾기
    stock_code = stock_code.zfill(6)
    rank = None
    total = len(result.all_items)
    
    for score in result.all_items:
        if score.stock_code == stock_code:
            rank = score.rank
            break
    
    if rank:
        print(f"\n📊 전체 순위: {rank}위 / {total}개 종목")
        
        # TOP 3 출력
        if result.top3:
            print(f"\n🏆 오늘의 TOP 3:")
            for s in result.top3:
                marker = " ⭐" if s.stock_code == stock_code else ""
                print(f"  {s.rank}. {s.stock_name} ({s.stock_code}) - {s.score_total:.1f}점{marker}")
    else:
        print(f"\n⚠️ 해당 종목({stock_code})이 거래대금 300억 이상 종목에 포함되지 않음")


def main():
    """메인 함수"""
    if len(sys.argv) < 2:
        print("사용법: python scripts/check_stock_score.py <종목코드> [종목코드2] ...")
        print("예시: python scripts/check_stock_score.py 006800")
        print("      python scripts/check_stock_score.py 005930 000660")
        sys.exit(1)
    
    # 로깅 설정
    logging.basicConfig(
        level=logging.WARNING,
        format='%(asctime)s [%(levelname)s] %(message)s',
    )
    
    # DB 초기화
    init_database()
    
    # KIS 클라이언트 및 가중치
    kis_client = get_kis_client()
    weight_repo = get_weight_repository()
    weights = weight_repo.get_weights()
    
    # 각 종목 분석
    stock_codes = sys.argv[1:]
    
    for code in stock_codes:
        try:
            result = analyze_stock(code, kis_client, weights)
            print_stock_analysis(result)
        except Exception as e:
            print(f"\n❌ {code} 분석 실패: {e}")
    
    # 순위 비교 옵션 (첫 번째 종목에 대해서만)
    if len(stock_codes) == 1 and '--rank' in sys.argv:
        compare_with_today_top(stock_codes[0], kis_client, weights)


if __name__ == "__main__":
    main()
