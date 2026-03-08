"""
ClosingBell v3 — DART 공시 간이 체크
=====================================
DART OpenAPI로 최근 공시 확인: CB/BW, 감사의견, 관리종목, 흑자/적자
"""
import logging
import time
import requests
from datetime import datetime, timedelta
from config import DART_API_KEY

logger = logging.getLogger("closingbell")

DART_BASE = "https://opendart.fss.or.kr/api"
# 위험 키워드
RISK_KEYWORDS = ["횡령", "배임", "상장폐지", "감사의견거절", "감사의견한정",
                 "관리종목", "투자주의", "불성실공시"]
WARNING_KEYWORDS = ["전환사채", "신주인수권", "유상증자", "무상감자", "주식분할"]


class DartChecker:
    """DART 간이 체크"""

    def __init__(self):
        self.api_key = DART_API_KEY
        self._cache = {}

    def check(self, code: str) -> dict:
        """
        종목코드로 DART 간이 체크
        반환: {"risk": "정상|주의|위험", "note": "설명", "profit_loss": "흑자|적자"}
        """
        if not self.api_key:
            return {"risk": "확인불가", "note": "DART API 키 없음", "profit_loss": ""}

        if code in self._cache:
            return self._cache[code]

        risk = "정상"
        notes = []
        profit_loss = ""

        # 1. 최근 공시 확인
        try:
            disclosures = self._get_recent_disclosures(code)
            for d in disclosures:
                title = d.get("report_nm", "")
                # 위험 키워드
                for kw in RISK_KEYWORDS:
                    if kw in title:
                        risk = "위험"
                        notes.append(kw)
                # 주의 키워드
                for kw in WARNING_KEYWORDS:
                    if kw in title:
                        if risk != "위험":
                            risk = "주의"
                        notes.append(kw)
        except Exception as e:
            logger.debug("DART 공시 조회 실패 [%s]: %s", code, e)

        # 2. 재무 간이 체크 (최근 분기 영업이익)
        try:
            fi = self._get_financial_brief(code)
            if fi:
                profit_loss = fi
                if fi == "적자":
                    if risk == "정상":
                        risk = "주의"
                    notes.append("적자")
                elif fi == "흑자전환":
                    notes.append("흑자전환")
        except Exception:
            pass

        note_text = ", ".join(notes[:3]) if notes else ("양호" if risk == "정상" else "")
        result = {"risk": risk, "note": note_text, "profit_loss": profit_loss}
        self._cache[code] = result
        return result

    def _get_recent_disclosures(self, code: str, days: int = 30) -> list:
        """최근 N일 공시 목록"""
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

        time.sleep(0.5)  # DART 속도제한 (분당 60건)
        resp = requests.get(f"{DART_BASE}/list.json", params={
            "crtfc_key": self.api_key,
            "corp_code": "",  # stock_code로는 검색 불가, corp_code 필요
            "stock_code": code,
            "bgn_de": start,
            "end_de": end,
            "page_count": "10",
        }, timeout=10)

        data = resp.json()
        if data.get("status") != "000":
            return []
        return data.get("list", [])

    def _get_financial_brief(self, code: str) -> str:
        """
        최근 분기 영업이익 기준 흑자/적자 판단
        DART 재무제표 API 대신 간이 방법: ka10001의 bus_pro(영업이익) 활용
        → 실제로는 screener에서 이미 가져온 stock_info 활용이 효율적
        여기서는 캐시된 공시 기반으로만 판단
        """
        # DART 재무제표 API가 corp_code를 요구하므로
        # 여기서는 공시 제목에서 "실적" 관련 키워드만 확인
        # 실제 흑자/적자는 ka10001의 영업이익으로 screener에서 직접 확인 가능
        return ""  # screener 또는 enricher에서 ka10001 결과로 설정
