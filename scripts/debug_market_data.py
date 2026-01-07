# scripts/debug_market_data.py
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))

from src.adapters.kis_client import get_kis_client
from src.config.settings import settings
import logging

# 로그 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_market_data():
    client = get_kis_client()
    
    # 300억 설정
    min_value = 300 
    
    print(f"\n🔍 [진단] 거래대금 {min_value}억 이상 종목 조회 테스트")
    print("="*60)
    
    # 1. 원본 데이터 조회 (필터링 전 raw data 개수 확인)
    # KIS Client 내부 로직을 일부 우회하거나 로깅을 강화해야 하지만, 
    # 여기서는 결과만 봅니다.
    
    stocks = client.get_top_trading_value_stocks(min_trading_value=min_value, limit=200)
    
    print(f"\n📊 최종 감지된 종목 수: {len(stocks)}개")
    print("-" * 60)
    
    # 상위 10개만 출력
    for i, stock in enumerate(stocks[:10]):
        print(f"{i+1}. {stock.name} ({stock.code}) - {stock.market}")
        
    print("\n👉 HTS/MTS의 '거래대금 상위' 창과 위 리스트 개수를 비교해보세요.")
    print("   만약 개수가 현저히 적다면 src/adapters/kis_client.py의")
    print("   _get_volume_rank_by_market 함수에서 limit을 100 -> 200으로 늘려야 합니다.")

if __name__ == "__main__":
    check_market_data()