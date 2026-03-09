"""
ClosingBell v3.5 — DART 공시 체크
====================================
DART OpenAPI로 최근 공시 확인.
종목코드(6자리) → DART 고유번호(8자리) 매핑 포함.

DART corpCode.xml 자동 다운로드 → 종목코드 매핑 구축 → 7일 캐시.
"""
import io
import json
import logging
import time
import zipfile
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from config import DART_API_KEY, PROJECT_DIR

logger = logging.getLogger("closingbell")

DART_BASE = "https://opendart.fss.or.kr/api"
CORP_MAP_CACHE = PROJECT_DIR / "data" / "dart_corp_map.json"

# 위험 키워드
RISK_KEYWORDS = ["횡령", "배임", "상장폐지", "감사의견거절", "감사의견한정",
                 "관리종목", "투자주의", "불성실공시"]
WARNING_KEYWORDS = ["전환사채", "신주인수권", "유상증자", "무상감자", "주식분할"]


class DartChecker:
    """DART 공시 체크 (corp_code 매핑 포함)"""

    def __init__(self):
        self.api_key = DART_API_KEY
        self._cache = {}
        self._corp_map = {}
        self._load_corp_map()

    # ──────────────────────────────────────────
    # corp_code 매핑
    # ──────────────────────────────────────────
    def _load_corp_map(self):
        """캐시된 매핑 로드 (7일 이상이면 재다운로드)"""
        if CORP_MAP_CACHE.exists():
            try:
                age = (datetime.now() - datetime.fromtimestamp(
                    CORP_MAP_CACHE.stat().st_mtime)).days
                if age <= 7:
                    self._corp_map = json.loads(
                        CORP_MAP_CACHE.read_text(encoding="utf-8"))
                    logger.debug("DART corp_map 캐시: %d종목", len(self._corp_map))
                    return
            except Exception:
                pass

        self._download_corp_map()

    def _download_corp_map(self):
        """DART corpCode.xml 다운로드 → stock_code→corp_code 매핑"""
        if not self.api_key:
            return

        try:
            logger.info("DART corp_code 매핑 다운로드...")
            resp = requests.get(
                f"{DART_BASE}/corpCode.xml",
                params={"crtfc_key": self.api_key},
                timeout=30,
            )
            if resp.status_code != 200:
                logger.warning("DART corpCode.xml 실패: %d", resp.status_code)
                return

            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                xml_data = zf.read(zf.namelist()[0])

            root = ET.fromstring(xml_data)
            mapping = {}
            for corp in root.findall("list"):
                corp_code = corp.findtext("corp_code", "").strip()
                stock_code = corp.findtext("stock_code", "").strip()
                if stock_code and corp_code:
                    mapping[stock_code] = corp_code

            self._corp_map = mapping
            logger.info("DART corp_map: %d종목", len(mapping))

            CORP_MAP_CACHE.parent.mkdir(parents=True, exist_ok=True)
            CORP_MAP_CACHE.write_text(
                json.dumps(mapping, ensure_ascii=False), encoding="utf-8")

        except Exception as e:
            logger.warning("DART corp_map 실패: %s", e)

    def _get_corp_code(self, stock_code: str) -> str:
        """종목코드(6자리) → DART 고유번호(8자리)"""
        stock_code = stock_code.strip().zfill(6)
        corp_code = self._corp_map.get(stock_code, "")
        if not corp_code and not self._corp_map:
            self._download_corp_map()
            corp_code = self._corp_map.get(stock_code, "")
        return corp_code

    # ──────────────────────────────────────────
    # 공시 체크
    # ──────────────────────────────────────────
    def check(self, code: str) -> dict:
        """
        종목코드로 DART 공시 체크.
        반환: {"risk": "정상|주의|위험|확인불가", "note": "...", "profit_loss": ""}
        """
        if not self.api_key:
            return {"risk": "확인불가", "note": "API키없음", "profit_loss": ""}

        if code in self._cache:
            return self._cache[code]

        corp_code = self._get_corp_code(code)
        if not corp_code:
            logger.debug("DART corp_code 없음 [%s]", code)
            return {"risk": "확인불가", "note": "매핑없음", "profit_loss": ""}

        risk = "정상"
        notes = []

        try:
            disclosures = self._get_disclosures(corp_code)
            for d in disclosures:
                title = d.get("report_nm", "")
                for kw in RISK_KEYWORDS:
                    if kw in title:
                        risk = "위험"
                        notes.append(kw)
                for kw in WARNING_KEYWORDS:
                    if kw in title:
                        if risk != "위험":
                            risk = "주의"
                        notes.append(kw)
        except Exception as e:
            logger.debug("DART 조회 실패 [%s]: %s", code, e)

        # 중복 제거
        note_text = ", ".join(dict.fromkeys(notes))[:50] if notes else (
            "양호" if risk == "정상" else "")
        result = {"risk": risk, "note": note_text, "profit_loss": ""}
        self._cache[code] = result
        return result

    def _get_disclosures(self, corp_code: str, days: int = 30) -> list:
        """최근 N일 공시 (corp_code 기반 — 정상 작동)"""
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

        time.sleep(0.5)
        try:
            resp = requests.get(f"{DART_BASE}/list.json", params={
                "crtfc_key": self.api_key,
                "corp_code": corp_code,
                "bgn_de": start,
                "end_de": end,
                "page_count": "10",
            }, timeout=10)

            data = resp.json()
            status = data.get("status", "")

            if status == "000":
                return data.get("list", [])
            elif status == "013":
                return []
            else:
                logger.debug("DART [%s] status=%s: %s",
                             corp_code, status, data.get("message", ""))
                return []

        except requests.Timeout:
            logger.warning("DART 타임아웃 [%s]", corp_code)
            return []
        except Exception as e:
            logger.debug("DART 요청 실패 [%s]: %s", corp_code, e)
            return []
