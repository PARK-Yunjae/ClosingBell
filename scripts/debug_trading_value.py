#!/usr/bin/env python
"""
거래대금 API 디버깅 스크립트

확인 사항:
1. API 응답 개수
2. 거래대금 단위 확인
3. KOSPI/KOSDAQ 별도 조회 테스트
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import json
from src.adapters.kis_client import get_kis_client
from src.config.settings import settings


def debug_volume_rank():
    """거래대금 순위 API 디버깅"""
    client = get_kis_client()
    
    # 토큰 확보
    token = client._get_token()
    
    print("=" * 60)
    print("🔍 거래대금 순위 API 디버깅")
    print("=" * 60)
    
    # 1. 전체 시장 조회 (현재 코드)
    print("\n[1] 전체 시장 (FID_COND_MRKT_DIV_CODE = J)")
    test_api_call(client, token, "J", "전체")
    
    # 2. KOSPI만 조회
    print("\n[2] KOSPI (FID_COND_MRKT_DIV_CODE = 1)")
    test_api_call(client, token, "1", "KOSPI")
    
    # 3. KOSDAQ만 조회
    print("\n[3] KOSDAQ (FID_COND_MRKT_DIV_CODE = 2)")
    test_api_call(client, token, "2", "KOSDAQ")


def test_api_call(client, token, market_code: str, market_name: str):
    """API 호출 테스트"""
    url = f"{settings.kis.base_url}/uapi/domestic-stock/v1/quotations/volume-rank"
    
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": settings.kis.app_key,
        "appsecret": settings.kis.app_secret,
        "tr_id": "FHPST01710000",
        "custtype": "P",
    }
    
    params = {
        "FID_COND_MRKT_DIV_CODE": market_code,
        "FID_COND_SCR_DIV_CODE": "20101",  # 전일 기준
        "FID_INPUT_ISCD": "0000",
        "FID_DIV_CLS_CODE": "0",
        "FID_BLNG_CLS_CODE": "0",
        "FID_TRGT_CLS_CODE": "111111111",  # 전체
        "FID_TRGT_EXLS_CLS_CODE": "0000000000",
        "FID_INPUT_PRICE_1": "",
        "FID_INPUT_PRICE_2": "",
        "FID_VOL_CNT": "",
        "FID_INPUT_DATE_1": "",
    }
    
    response = requests.get(url, headers=headers, params=params, timeout=10)
    data = response.json()
    
    if data.get("rt_cd") != "0":
        print(f"  ❌ API 에러: {data.get('msg1')}")
        return
    
    output = data.get("output", [])
    print(f"  📊 반환 종목 수: {len(output)}개")
    
    if not output:
        return
    
    # 상위 5개 종목 출력
    print(f"\n  상위 5개 종목:")
    for i, item in enumerate(output[:5]):
        code = item.get("mksc_shrn_iscd", "")
        name = item.get("hts_kor_isnm", "")
        trading_value_raw = item.get("acml_tr_pbmn", "0")
        price = item.get("stck_prpr", "0")
        
        # 거래대금 원본값
        trading_value_int = int(trading_value_raw)
        trading_value_eok = trading_value_int / 100_000_000  # 억원
        
        print(f"  {i+1}. {name}({code})")
        print(f"     현재가: {int(price):,}원")
        print(f"     거래대금 원본: {trading_value_raw}")
        print(f"     거래대금 (억원): {trading_value_eok:,.0f}억")
    
    # 300억 이상 종목 수
    count_300 = sum(1 for item in output 
                   if int(item.get("acml_tr_pbmn", 0)) / 100_000_000 >= 300)
    print(f"\n  📈 300억 이상 종목: {count_300}개 / {len(output)}개")


def debug_single_stock():
    """삼성전자 단일 종목 거래대금 확인"""
    client = get_kis_client()
    
    print("\n" + "=" * 60)
    print("🔍 삼성전자(005930) 거래대금 단위 확인")
    print("=" * 60)
    
    current = client.get_current_price("005930")
    
    print(f"\n현재가: {current.price:,}원")
    print(f"등락률: {current.change_rate:+.2f}%")
    print(f"거래량: {current.volume:,}주")
    print(f"거래대금 (원본): {current.trading_value:,.0f}")
    print(f"거래대금 (억원): {current.trading_value / 100_000_000:,.0f}억")
    
    # 예상 거래대금 계산
    estimated = current.price * current.volume
    print(f"\n[검증] 현재가 × 거래량 = {estimated:,.0f}")
    print(f"[검증] 억원 환산 = {estimated / 100_000_000:,.0f}억")


if __name__ == "__main__":
    debug_volume_rank()
    debug_single_stock()
