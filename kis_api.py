"""
ClosingBell v2 — 한국투자증권 API 래퍼
"""
import time
import logging
import requests
from datetime import datetime, timedelta
from config import (
    KIS_BASE_URL, KIS_APP_KEY, KIS_APP_SECRET,
    CANO, ACNT_PRDT_CD, KIS_HTS_ID, API_DELAY
)

logger = logging.getLogger("closingbell")


class KisAPI:
    """한국투자증권 OpenAPI 래퍼"""

    def __init__(self):
        self.base = KIS_BASE_URL
        self.token = ""
        self.token_expires = datetime.min

    # ──────────────────────────────────────────────
    # 인증
    # ──────────────────────────────────────────────
    def get_token(self) -> str:
        """접근토큰 발급 (24시간 유효)"""
        if self.token and datetime.now() < self.token_expires:
            return self.token

        url = f"{self.base}/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey": KIS_APP_KEY,
            "appsecret": KIS_APP_SECRET,
        }
        r = requests.post(url, json=body, timeout=10)
        r.raise_for_status()
        data = r.json()
        self.token = data["access_token"]
        self.token_expires = datetime.now() + timedelta(hours=23)
        logger.info("토큰 발급 완료 (만료: %s)", self.token_expires.strftime("%H:%M"))
        return self.token

    def _headers(self, tr_id: str) -> dict:
        """공통 헤더"""
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.get_token()}",
            "appkey": KIS_APP_KEY,
            "appsecret": KIS_APP_SECRET,
            "tr_id": tr_id,
            "custtype": "P",
        }

    def _get(self, path: str, tr_id: str, params: dict) -> dict:
        """GET 요청 + 속도제한"""
        time.sleep(API_DELAY)
        url = f"{self.base}{path}"
        r = requests.get(url, headers=self._headers(tr_id), params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        if data.get("rt_cd") != "0":
            msg = data.get("msg1", "Unknown error")
            logger.warning("API 에러 [%s]: %s", tr_id, msg)
        return data

    # ──────────────────────────────────────────────
    # 조건검색
    # ──────────────────────────────────────────────
    def get_condition_list(self) -> list[dict]:
        """종목조건검색 목록조회 (HHKST03900300)"""
        params = {
            "user_id": KIS_HTS_ID,
        }
        data = self._get(
            "/uapi/domestic-stock/v1/quotations/psearch-title",
            "HHKST03900300",
            params,
        )
        results = []
        for item in data.get("output2", []):
            results.append({
                "seq": item.get("seq", ""),
                "name": item.get("condition_nm", ""),
            })
        return results

    def get_condition_stocks(self, seq: str) -> list[dict]:
        """종목조건검색조회 (HHKST03900400) → 최대 100건"""
        params = {
            "user_id": KIS_HTS_ID,
            "seq": seq,
        }
        data = self._get(
            "/uapi/domestic-stock/v1/quotations/psearch-result",
            "HHKST03900400",
            params,
        )
        results = []
        for item in data.get("output2", []):
            code = item.get("code", "")
            if not code:
                continue
            code = code.strip().zfill(6)

            # 가격: 여러 필드명 시도
            price = (
                _safe_int(item.get("price"))
                or _safe_int(item.get("stck_prpr"))
                or _safe_int(item.get("prpr"))
                or _safe_int(item.get("curr_price"))
            )
            change_rate = (
                _safe_float(item.get("chgrate"))
                or _safe_float(item.get("prdy_ctrt"))
                or _safe_float(item.get("change_rate"))
            )

            results.append({
                "code": code,
                "name": item.get("name", item.get("hts_kor_isnm", "")),
                "price": price,
                "change_rate": change_rate,
                "volume": _safe_int(item.get("acml_vol")) or _safe_int(item.get("vol")),
                "trade_amt": _safe_int(item.get("acml_tr_pbmn")) or _safe_int(item.get("tr_pbmn")),
            })

        # 디버그: 첫 번째 종목 원본 필드 로깅
        raw_items = data.get("output2", [])
        if raw_items:
            logger.info("TV200 응답 필드: %s", list(raw_items[0].keys()))
            first = results[0] if results else {}
            logger.info("첫 종목 파싱: %s %s 가격=%d", first.get("code"), first.get("name"), first.get("price", 0))

        return results

    def find_tv200_seq(self, condition_name: str = "TV200") -> str | None:
        """TV200 조건검색의 seq 번호 찾기"""
        conditions = self.get_condition_list()
        for c in conditions:
            if condition_name.upper() in c["name"].upper():
                logger.info("조건검색 '%s' 발견 (seq=%s)", c["name"], c["seq"])
                return c["seq"]
        logger.warning("조건검색 '%s' 을 찾을 수 없습니다", condition_name)
        return None

    # ──────────────────────────────────────────────
    # 시세
    # ──────────────────────────────────────────────
    def get_daily_prices(self, code: str, start: str, end: str) -> list[dict]:
        """
        국내주식기간별시세 (FHKST03010100)
        start/end: 'YYYYMMDD'
        반환: [{date, open, high, low, close, volume}, ...] 오래된순
        """
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
            "FID_INPUT_DATE_1": start,
            "FID_INPUT_DATE_2": end,
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "0",  # 수정주가
        }
        data = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            "FHKST03010100",
            params,
        )
        rows = []
        for item in data.get("output2", []):
            d = item.get("stck_bsop_date", "")
            if not d:
                continue
            rows.append({
                "date": f"{d[:4]}-{d[4:6]}-{d[6:8]}",
                "open": _safe_int(item.get("stck_oprc")),
                "high": _safe_int(item.get("stck_hgpr")),
                "low": _safe_int(item.get("stck_lwpr")),
                "close": _safe_int(item.get("stck_clpr")),
                "volume": _safe_int(item.get("acml_vol")),
            })
        rows.sort(key=lambda x: x["date"])
        return rows

    def get_current_price(self, code: str) -> dict:
        """주식현재가 시세 (FHKST01010100)"""
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
        }
        data = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            "FHKST01010100",
            params,
        )
        out = data.get("output", {})
        return {
            "price": _safe_int(out.get("stck_prpr")),
            "change_rate": _safe_float(out.get("prdy_ctrt")),
            "volume": _safe_int(out.get("acml_vol")),
            "trade_amt": _safe_int(out.get("acml_tr_pbmn")),
            "high": _safe_int(out.get("stck_hgpr")),
            "low": _safe_int(out.get("stck_lwpr")),
            "open": _safe_int(out.get("stck_oprc")),
            "per": _safe_float(out.get("per")),
            "pbr": _safe_float(out.get("pbr")),
        }

    def get_index_price(self, index_code: str) -> dict:
        """
        국내업종 현재지수 (FHPUP02100000)
        index_code: '0001'=코스피, '1001'=코스닥
        """
        params = {
            "FID_COND_MRKT_DIV_CODE": "U",
            "FID_INPUT_ISCD": index_code,
        }
        data = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-index-price",
            "FHPUP02100000",
            params,
        )
        out = data.get("output", {})
        return {
            "price": _safe_float(out.get("bstp_nmix_prpr")),
            "change_rate": _safe_float(out.get("bstp_nmix_prdy_ctrt")),
        }

    def get_volume_rank(self) -> list[dict]:
        """
        거래량순위 (FHPST01710000) — fallback용, 최대 30건
        """
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD": "0000",
            "FID_DIV_CLS_CODE": "0",
            "FID_BLNG_CLS_CODE": "0",
            "FID_TRGT_CLS_CODE": "111111111",
            "FID_TRGT_EXLS_CLS_CODE": "000000",
            "FID_INPUT_PRICE_1": "",
            "FID_INPUT_PRICE_2": "",
            "FID_VOL_CNT": "",
            "FID_INPUT_DATE_1": "",
        }
        data = self._get(
            "/uapi/domestic-stock/v1/quotations/volume-rank",
            "FHPST01710000",
            params,
        )
        results = []
        for item in data.get("output", []):
            code = item.get("mksc_shrn_iscd", "")
            if not code:
                continue
            results.append({
                "code": code,
                "name": item.get("hts_kor_isnm", ""),
                "price": _safe_int(item.get("stck_prpr")),
                "change_rate": _safe_float(item.get("prdy_ctrt")),
                "volume": _safe_int(item.get("acml_vol")),
                "trade_amt": _safe_int(item.get("acml_tr_pbmn")),
            })
        return results


# ──────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────
def _safe_int(v) -> int:
    try:
        s = str(v).replace(",", "").strip()
        if not s or s == "None":
            return 0
        return int(float(s))
    except (ValueError, TypeError):
        return 0


def _safe_float(v) -> float:
    try:
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return 0.0
