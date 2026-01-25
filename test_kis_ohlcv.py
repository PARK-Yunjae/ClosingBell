# test_kis_period.py
from src.adapters.kis_client import KISClient
from datetime import datetime

client = KISClient()

# 기간별 시세 API 직접 호출 테스트
endpoint = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
tr_id = "FHKST03010100"

params = {
    "FID_COND_MRKT_DIV_CODE": "J",
    "FID_INPUT_ISCD": "005930",
    "FID_INPUT_DATE_1": "20160101",  # 시작일
    "FID_INPUT_DATE_2": "20260125",  # 종료일
    "FID_PERIOD_DIV_CODE": "D",
    "FID_ORG_ADJ_PRC": "0",
}

data = client._request("GET", endpoint, tr_id, params=params)
output = data.get("output2", [])

print(f"조회된 일수: {len(output)}")
if output:
    print(f"첫 데이터: {output[-1]}")
    print(f"마지막 데이터: {output[0]}")