#!/usr/bin/env python3
"""
거래원 이상분포 스캐너 v3.0
============================
"정상 피라미드 패턴"에서 벗어나는 종목을 찾는다.

정상 패턴: 대형 리테일 증권사(키움, 미래에셋, 삼성, 한투, NH, KB, 신한)가
  매수/매도 양쪽에서 피라미드형으로 내려가는 분포.
  
이상 패턴:
  1) 비주류 브로커 출현: 소형/외국계 증권사가 Top5에 큰 물량으로 등장
  2) 매수/매도 비대칭: 매수상위와 매도상위 브로커 구성이 크게 다름
  3) 역피라미드/평탄화: 1위와 5위 차이가 비정상적으로 작음 (분산 매수)
  4) 극단적 편중: 1위가 2위의 3배 이상 (한 곳이 독식)

사용법:
  python test_broker_signal.py                    # 전체 스캔
  python test_broker_signal.py --save             # CSV 저장
  python test_broker_signal.py --test 005930      # 종목 테스트
  python test_broker_signal.py --top N            # 상위 N개 스캔 (기본 500)
"""

import os
import sys
import json
import time
import math
import logging
import argparse
import csv
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

# ── 설정 ─────────────────────────────────────────────────────
load_dotenv()

API_BASE = "https://api.kiwoom.com"
APP_KEY = os.getenv("KIWOOM_APPKEY", "")
SECRET_KEY = os.getenv("KIWOOM_SECRETKEY", "")
TOKEN_CACHE = Path(".cache/kiwoom_token.json")
DATA_DIR = Path("data")

RATE_LIMIT_INTERVAL = 0.18  # 초당 ~5.5건 (429 방지)

# 스캔 파라미터
PRICE_MIN = 2000
PRICE_MAX = 10000

# ── "정상" 대형 리테일 증권사 (이 증권사들이 Top5에 있으면 정상) ──
MAJOR_RETAIL = {
    "키움증권", "미래에셋", "삼  성", "한국투자증권", "NH투자증권",
    "KB증권", "신한투자증권", "하나증권", "메리츠", "대  신",
    "유안타증권", "한화투자증권", "교보증권", "DB금융투자",
    "현대차증권", "SK증권", "이베스트투자증권", "LS증권",
    "부국증권", "유진투자증권", "토  스", "카카오페이증권",
    "삼성증권", "한국투자", "KB", "NH투자", "신한투자",
}

# 외국계 증권사 키워드
FOREIGN_KEYWORDS = {
    "모건스탠리", "모건", "CS", "UBS", "CLSA", "골드만", "JP모간",
    "메릴린치", "BNP", "도이치", "씨티", "크레디", "맥쿼리",
    "노무라", "BOA", "바클레이", "HSBC", "소시에테", "제프리",
    "다이와", "스탠리", "유비에스", "골드만삭스",
}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger(__name__)


# ── 토큰 관리 ────────────────────────────────────────────────

class TokenManager:
    def __init__(self):
        self.token = None
        self.expires_at = None
        TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load_cache()
    
    def _load_cache(self):
        if TOKEN_CACHE.exists():
            try:
                data = json.loads(TOKEN_CACHE.read_text())
                if datetime.fromisoformat(data["expires_at"]) > datetime.now():
                    self.token = data["token"]
                    self.expires_at = datetime.fromisoformat(data["expires_at"])
                    log.info(f"캐시 토큰 로드 (만료: {self.expires_at.strftime('%H:%M:%S')})")
            except Exception:
                pass
    
    def _save_cache(self):
        TOKEN_CACHE.write_text(json.dumps({
            "token": self.token,
            "expires_at": self.expires_at.isoformat()
        }, ensure_ascii=False))
    
    def get_token(self) -> str:
        if self.token and self.expires_at and self.expires_at > datetime.now():
            return self.token
        
        log.info("토큰 발급 중...")
        resp = requests.post(f"{API_BASE}/oauth2/token", json={
            "grant_type": "client_credentials",
            "appkey": APP_KEY,
            "secretkey": SECRET_KEY,
        }, headers={"Content-Type": "application/json"})
        resp.raise_for_status()
        data = resp.json()
        
        self.token = data["token"]
        self.expires_at = datetime.now() + timedelta(hours=23)
        self._save_cache()
        log.info("토큰 발급 완료")
        return self.token


# ── API 클라이언트 ────────────────────────────────────────────

class KiwoomClient:
    def __init__(self):
        self.tm = TokenManager()
        self.session = requests.Session()
        self.last_call = 0
        self.call_count = 0
        self.error_count = 0
    
    def _rate_limit(self):
        elapsed = time.time() - self.last_call
        if elapsed < RATE_LIMIT_INTERVAL:
            time.sleep(RATE_LIMIT_INTERVAL - elapsed)
        self.last_call = time.time()
    
    def _call(self, api_id: str, endpoint: str, body: dict,
              cont_yn: str = None, next_key: str = None,
              _retry: int = 0) -> tuple:
        """API 호출. (data, resp_headers) 반환. 429시 자동 재시도."""
        self._rate_limit()
        self.call_count += 1
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "api-id": api_id,
            "authorization": f"Bearer {self.tm.get_token()}",
        }
        if cont_yn:
            headers["cont-yn"] = cont_yn
        if next_key:
            headers["next-key"] = next_key
        
        try:
            resp = self.session.post(
                f"{API_BASE}{endpoint}",
                json=body,
                headers=headers,
                timeout=10
            )
            
            # 429 Too Many Requests → 재시도
            if resp.status_code == 429 and _retry < 2:
                wait = 0.5 + _retry * 0.5  # 0.5초, 1.0초
                log.warning(f"[{api_id}] 429 → {wait}초 대기 후 재시도 ({_retry+1}/2)")
                time.sleep(wait)
                return self._call(api_id, endpoint, body, cont_yn, next_key, _retry + 1)
            
            resp.raise_for_status()
            data = resp.json()
            
            if data.get("return_code", 0) != 0:
                log.warning(f"[{api_id}] API 오류: {data.get('return_msg', 'unknown')}")
                self.error_count += 1
                return None, {}
            
            # 응답 헤더에서 연속조회 정보 추출
            resp_headers = {
                "cont-yn": resp.headers.get("cont-yn", "N"),
                "next-key": resp.headers.get("next-key", ""),
            }
            return data, resp_headers
        except Exception as e:
            log.error(f"[{api_id}] 요청 실패: {e}")
            self.error_count += 1
            return None, {}
    
    # ── ka10032: 거래대금 상위 (연속조회 지원) ──
    def get_top_volume(self, mrkt_tp: str = "000", max_pages: int = 10) -> list:
        """거래대금 상위. 연속조회로 여러 페이지 수집."""
        all_items = []
        cont_yn = None
        next_key = None
        
        for page in range(1, max_pages + 1):
            body = {
                "mrkt_tp": mrkt_tp,
                "mang_stk_incls": "0",
                "stex_tp": "1",
            }
            data, resp_h = self._call("ka10032", "/api/dostk/rkinfo", body,
                                       cont_yn=cont_yn, next_key=next_key)
            if not data:
                break
            
            items = data.get("trde_prica_upper", [])
            if items:
                all_items.extend(items)
                log.info(f"  ka10032 p{page}: {len(items)}건 (누적 {len(all_items)})")
            else:
                break
            
            # 연속조회 판단
            if resp_h.get("cont-yn") == "Y" and resp_h.get("next-key"):
                cont_yn = "Y"
                next_key = resp_h["next-key"]
            else:
                break
        
        return all_items
    
    # ── ka10040: 당일 주요 거래원 ──
    def get_daily_brokers(self, stk_cd: str) -> dict:
        """당일주요거래원 - Top5 매수/매도 + 외국계 추정합"""
        data, _ = self._call("ka10040", "/api/dostk/rkinfo", {"stk_cd": stk_cd})
        if not data:
            return None
        
        result = {
            "buyers": [],
            "sellers": [],
            "frgn_buy": self._parse_int(data.get("frgn_buy_prsm_sum", "0")),
            "frgn_sell": self._parse_int(data.get("frgn_sel_prsm_sum", "0")),
        }
        
        for i in range(1, 6):
            name = data.get(f"buy_trde_ori_{i}", "").strip()
            qty = self._parse_int(data.get(f"buy_trde_ori_qty_{i}", "0"))
            code = data.get(f"buy_trde_ori_cd_{i}", "000")
            if name and qty != 0:
                result["buyers"].append({"name": name, "code": code, "qty": qty})
            
            name = data.get(f"sel_trde_ori_{i}", "").strip()
            qty = self._parse_int(data.get(f"sel_trde_ori_qty_{i}", "0"))
            code = data.get(f"sel_trde_ori_cd_{i}", "000")
            if name and qty != 0:
                result["sellers"].append({"name": name, "code": code, "qty": abs(qty)})
        
        return result
    
    # ── ka10038: 종목별 증권사 순위 (전체 리스트) ──
    def get_broker_ranking(self, stk_cd: str, qry_tp: str = "2") -> dict:
        """종목별증권사순위. qry_tp: 2=순매수순"""
        today = datetime.now().strftime("%Y%m%d")
        body = {
            "stk_cd": stk_cd,
            "strt_dt": today,
            "end_dt": today,
            "qry_tp": qry_tp,
            "dt": "1",
        }
        data, _ = self._call("ka10038", "/api/dostk/rkinfo", body)
        if not data:
            return None
        
        result = {
            "total_buy": self._parse_int(data.get("rank_1", "0")),
            "total_sell": self._parse_int(data.get("rank_2", "0")),
            "total_net": self._parse_int(data.get("rank_3", "0")),
            "brokers": []
        }
        
        for item in data.get("stk_sec_rank", []):
            result["brokers"].append({
                "rank": int(item.get("rank", 0)),
                "name": item.get("mmcm_nm", "").strip(),
                "buy_qty": self._parse_int(item.get("buy_qty", "0")),
                "sell_qty": abs(self._parse_int(item.get("sell_qty", "0"))),
                "net_buy": self._parse_int(item.get("acc_netprps_qty", "0")),
            })
        
        return result
    
    # ── ka10002: 주식거래원 (종목명/현재가 보완용) ──
    def get_stock_broker_info(self, stk_cd: str) -> dict:
        data, _ = self._call("ka10002", "/api/dostk/stkinfo", {"stk_cd": stk_cd})
        if not data:
            return None
        return {
            "stk_nm": data.get("stk_nm", ""),
            "cur_prc": abs(self._parse_int(data.get("cur_prc", "0"))),
            "flu_rt": data.get("flu_rt", "0"),
        }
    
    @staticmethod
    def _parse_int(val) -> int:
        if not val:
            return 0
        try:
            return int(str(val).replace(",", "").replace("+", ""))
        except ValueError:
            return 0


# ── 이상분포 분석 엔진 ───────────────────────────────────────

class AnomalyAnalyzer:
    """
    정상 피라미드 패턴 vs 이상 패턴 분석.
    
    점수 체계 (0~100):
      - 비주류 브로커 출현 (0~30점)
      - 매수/매도 비대칭 (0~25점)
      - 분포 이상 (0~25점) 
      - 외국계 집중 (0~20점)
    
    40점 이상이면 "이상 신호"로 판정.
    """
    
    ANOMALY_THRESHOLD = 35  # 이상 신호 최소 점수
    MIN_VOLUME = 100_000    # 최소 매수거래량 (너무 적으면 의미 없음)
    
    @staticmethod
    def is_major_retail(name: str) -> bool:
        """대형 리테일 증권사인지 판단"""
        for m in MAJOR_RETAIL:
            if m in name or name in m:
                return True
        return False
    
    @staticmethod
    def is_foreign(name: str) -> bool:
        for kw in FOREIGN_KEYWORDS:
            if kw in name:
                return True
        return False
    
    @classmethod
    def analyze(cls, stk_cd: str, stk_nm: str, cur_prc: int,
                broker_data: dict) -> dict:
        """
        ka10040 데이터 기반 종합 이상분포 분석.
        
        Returns: {
            "score": 총점 (0~100),
            "anomalies": [이상 항목 리스트],
            "detail": {세부 점수},
            ...
        }
        """
        buyers = broker_data.get("buyers", [])
        sellers = broker_data.get("sellers", [])
        
        if not buyers or len(buyers) < 2:
            return None
        
        total_buy = sum(b["qty"] for b in buyers)
        if total_buy < cls.MIN_VOLUME:
            return None
        
        total_sell = sum(s["qty"] for s in sellers) if sellers else 0
        
        score = 0
        anomalies = []
        detail = {}
        
        # ── 1. 비주류 브로커 출현 (0~30점) ──
        unusual_score, unusual_items = cls._check_unusual_brokers(buyers, total_buy)
        score += unusual_score
        detail["비주류출현"] = unusual_score
        anomalies.extend(unusual_items)
        
        # ── 2. 매수/매도 비대칭 (0~25점) ──
        asym_score, asym_items = cls._check_asymmetry(buyers, sellers)
        score += asym_score
        detail["매수매도비대칭"] = asym_score
        anomalies.extend(asym_items)
        
        # ── 3. 분포 이상 — 피라미드 깨짐 (0~25점) ──
        dist_score, dist_items = cls._check_distribution(buyers, total_buy)
        score += dist_score
        detail["분포이상"] = dist_score
        anomalies.extend(dist_items)
        
        # ── 4. 외국계 집중 (0~20점) ──
        frgn_score, frgn_items = cls._check_foreign(
            buyers, total_buy, broker_data.get("frgn_buy", 0),
            broker_data.get("frgn_sell", 0)
        )
        score += frgn_score
        detail["외국계집중"] = frgn_score
        anomalies.extend(frgn_items)
        
        if score < cls.ANOMALY_THRESHOLD:
            return None
        
        # 매수상위 요약
        buy_summary = ", ".join(
            f"{'⚡' if not cls.is_major_retail(b['name']) else ''}"
            f"{b['name']}({b['qty']:,})"
            for b in buyers[:5]
        )
        sell_summary = ", ".join(
            f"{s['name']}({s['qty']:,})"
            for s in sellers[:5]
        ) if sellers else "-"
        
        return {
            "code": stk_cd,
            "name": stk_nm,
            "price": cur_prc,
            "score": min(score, 100),
            "anomalies": anomalies,
            "detail": detail,
            "buy_summary": buy_summary,
            "sell_summary": sell_summary,
            "total_buy": total_buy,
            "total_sell": total_sell,
            "frgn_buy": broker_data.get("frgn_buy", 0),
            "frgn_sell": broker_data.get("frgn_sell", 0),
        }
    
    @classmethod
    def _check_unusual_brokers(cls, buyers: list, total_buy: int) -> tuple:
        """비주류 브로커가 Top5에 큰 물량으로 있는지"""
        score = 0
        items = []
        
        for i, b in enumerate(buyers[:5]):
            if cls.is_major_retail(b["name"]):
                continue
            
            ratio = b["qty"] / total_buy if total_buy > 0 else 0
            rank = i + 1
            
            # 순위가 높을수록, 비중이 클수록 이상
            if ratio >= 0.15:
                pts = min(30, int(ratio * 100) + (5 - rank) * 3)
                score += pts
                is_frgn = cls.is_foreign(b["name"])
                label = "외국계" if is_frgn else "비주류"
                items.append(
                    f"{label} {b['name']} #{rank}위 {ratio:.0%} ({b['qty']:,}주)"
                )
            elif ratio >= 0.08:
                pts = min(15, int(ratio * 60) + (5 - rank) * 2)
                score += pts
                items.append(
                    f"비주류 {b['name']} #{rank}위 {ratio:.0%}"
                )
        
        return min(score, 30), items
    
    @classmethod
    def _check_asymmetry(cls, buyers: list, sellers: list) -> tuple:
        """매수상위와 매도상위 브로커 구성이 다른지"""
        score = 0
        items = []
        
        if not sellers or len(sellers) < 2:
            return 0, []
        
        buy_names = set(b["name"] for b in buyers[:5])
        sell_names = set(s["name"] for s in sellers[:5])
        
        # 매수에만 있는 브로커 (매도에는 없음)
        buy_only = buy_names - sell_names
        sell_only = sell_names - buy_names
        
        # 비주류가 매수에만 있으면 더 이상
        unusual_buy_only = [n for n in buy_only if not cls.is_major_retail(n)]
        unusual_sell_only = [n for n in sell_only if not cls.is_major_retail(n)]
        
        if unusual_buy_only:
            score += min(15, len(unusual_buy_only) * 8)
            for n in unusual_buy_only:
                items.append(f"{n} 매수만 (매도Top5에 없음)")
        
        if unusual_sell_only:
            score += min(10, len(unusual_sell_only) * 5)
            for n in unusual_sell_only:
                items.append(f"{n} 매도만 (매수Top5에 없음)")
        
        # 겹치는 브로커가 적을수록 비대칭
        overlap = buy_names & sell_names
        if len(overlap) <= 1 and len(buy_names) >= 3:
            score += 10
            items.append(f"매수/매도 겹침 {len(overlap)}/{min(len(buy_names),len(sell_names))}개")
        
        return min(score, 25), items
    
    @classmethod
    def _check_distribution(cls, buyers: list, total_buy: int) -> tuple:
        """피라미드 분포 이상 검사"""
        score = 0
        items = []
        
        if len(buyers) < 3:
            return 0, []
        
        qtys = [b["qty"] for b in buyers[:5]]
        
        # (a) 극단적 편중: 1위가 2위의 3배 이상
        if len(qtys) >= 2 and qtys[1] > 0:
            ratio_12 = qtys[0] / qtys[1]
            if ratio_12 >= 4.0:
                score += 20
                items.append(f"극단편중: 1위/2위 = {ratio_12:.1f}배")
            elif ratio_12 >= 3.0:
                score += 12
                items.append(f"편중: 1위/2위 = {ratio_12:.1f}배")
        
        # (b) 1위 비중이 전체의 50% 이상
        top_ratio = qtys[0] / total_buy if total_buy > 0 else 0
        if top_ratio >= 0.50:
            score += 15
            items.append(f"1위 독식: {top_ratio:.0%}")
        elif top_ratio >= 0.40:
            score += 8
            items.append(f"1위 과점: {top_ratio:.0%}")
        
        # (c) 평탄화: 1위~5위 차이가 비정상적으로 작음 (모두 비슷하면 분산매수)
        # 정상: 1위가 5위의 2~4배. 비정상: 1.3배 미만
        if len(qtys) >= 5 and qtys[4] > 0:
            ratio_15 = qtys[0] / qtys[4]
            if ratio_15 < 1.3:
                score += 10
                items.append(f"평탄분산: 1위/5위 = {ratio_15:.1f}배")
        
        return min(score, 25), items
    
    @classmethod
    def _check_foreign(cls, buyers: list, total_buy: int,
                       frgn_buy: int, frgn_sell: int) -> tuple:
        """외국계 집중 매수"""
        score = 0
        items = []
        
        # Top5 중 외국계
        frgn_in_top5 = []
        for b in buyers[:5]:
            if cls.is_foreign(b["name"]):
                frgn_in_top5.append(b)
        
        if frgn_in_top5:
            frgn_qty = sum(b["qty"] for b in frgn_in_top5)
            frgn_ratio = frgn_qty / total_buy if total_buy > 0 else 0
            
            if frgn_ratio >= 0.20:
                score += 20
                names = ", ".join(b["name"] for b in frgn_in_top5)
                items.append(f"외국계 Top5 진입: {names} ({frgn_ratio:.0%})")
            elif frgn_ratio >= 0.10:
                score += 10
                names = ", ".join(b["name"] for b in frgn_in_top5)
                items.append(f"외국계 매수: {names} ({frgn_ratio:.0%})")
        
        # 외국계 추정합 기반
        frgn_net = abs(frgn_buy) - abs(frgn_sell)
        if frgn_net > 0 and total_buy > 0:
            net_ratio = frgn_net / total_buy
            if net_ratio >= 0.25 and not frgn_in_top5:
                score += 12
                items.append(f"외국계 순매수 {net_ratio:.0%}")
        
        return min(score, 20), items
    
    @classmethod
    def analyze_ka10038(cls, stk_cd: str, stk_nm: str, cur_prc: int,
                         ranking: dict) -> dict:
        """ka10038 정밀분석 — 전체 브로커 순위로 추가 이상 탐지"""
        brokers = ranking.get("brokers", [])
        if not brokers:
            return None
        
        net_buyers = [b for b in brokers if b["net_buy"] > 0]
        net_sellers = [b for b in brokers if b["net_buy"] < 0]
        
        if not net_buyers:
            return None
        
        total_net = sum(b["net_buy"] for b in net_buyers)
        if total_net < 50_000:
            return None
        
        score = 0
        anomalies = []
        
        # 순매수 Top 브로커가 비주류인지
        for b in net_buyers[:3]:
            if not cls.is_major_retail(b["name"]):
                ratio = b["net_buy"] / total_net if total_net > 0 else 0
                if ratio >= 0.15:
                    is_frgn = cls.is_foreign(b["name"])
                    label = "외국계" if is_frgn else "비주류"
                    score += 20
                    anomalies.append(
                        f"[순매수] {label} {b['name']} #{b['rank']}위 "
                        f"순매수:{b['net_buy']:+,} ({ratio:.0%})"
                    )
        
        # 순매수 집중도 (HHI 기반)
        if len(net_buyers) >= 2:
            shares = [b["net_buy"] / total_net for b in net_buyers[:5] if total_net > 0]
            hhi = sum(s**2 for s in shares)
            if hhi >= 0.40:  # 매우 집중
                score += 15
                anomalies.append(f"순매수 고집중 HHI={hhi:.2f}")
            elif hhi >= 0.25:
                score += 8
                anomalies.append(f"순매수 집중 HHI={hhi:.2f}")
        
        if score < 15:
            return None
        
        summary = ", ".join(
            f"{'⚡' if not cls.is_major_retail(b['name']) else ''}"
            f"{b['name']}(순:{b['net_buy']:+,})"
            for b in net_buyers[:5]
        )
        
        return {
            "code": stk_cd,
            "name": stk_nm,
            "price": cur_prc,
            "score": min(score, 50),
            "anomalies": anomalies,
            "net_buy_summary": summary,
            "total_net": total_net,
        }


# ── 메인 스캐너 ──────────────────────────────────────────────

class BrokerScanner:
    def __init__(self):
        self.client = KiwoomClient()
        self.analyzer = AnomalyAnalyzer()
    
    def test_single(self, stk_cd: str):
        """단일 종목 테스트"""
        print(f"\n{'='*65}")
        print(f"  종목 이상분포 테스트: {stk_cd}")
        print(f"{'='*65}")
        
        # ka10002: 기본정보
        info = self.client.get_stock_broker_info(stk_cd)
        stk_nm = info["stk_nm"] if info else stk_cd
        cur_prc = info["cur_prc"] if info else 0
        flu_rt = info["flu_rt"] if info else "?"
        print(f"\n  {stk_nm} | {cur_prc:,}원 ({flu_rt}%)")
        
        # ka10040: 당일 거래원
        print(f"\n[ka10040] 당일 거래원")
        daily = self.client.get_daily_brokers(stk_cd)
        if daily:
            print(f"  {'매수상위':<12s} {'수량':>12s}   {'매도상위':<12s} {'수량':>12s}")
            print(f"  {'─'*12} {'─'*12}   {'─'*12} {'─'*12}")
            for i in range(5):
                b = daily["buyers"][i] if i < len(daily["buyers"]) else None
                s = daily["sellers"][i] if i < len(daily["sellers"]) else None
                bl = f"  {'⚡' if b and not self.analyzer.is_major_retail(b['name']) else '  '}" \
                     f"{b['name']:<10s} {b['qty']:>12,}" if b else f"  {'':12s} {'':>12s}"
                sl = f"   {s['name']:<12s} {s['qty']:>12,}" if s else ""
                print(f"{bl}{sl}")
            
            frgn_net = daily["frgn_buy"] + daily["frgn_sell"]
            print(f"\n  외국계: 매수 {daily['frgn_buy']:+,} / 매도 {daily['frgn_sell']:+,} / 순 {frgn_net:+,}")
            
            # 이상분포 분석
            result = self.analyzer.analyze(stk_cd, stk_nm, cur_prc, daily)
            if result:
                print(f"\n  ✅ 이상 점수: {result['score']}점")
                for k, v in result["detail"].items():
                    bar = "█" * (v // 2) if v > 0 else ""
                    print(f"    {k:<12s} {v:>3d}점 {bar}")
                print(f"\n  이상 항목:")
                for a in result["anomalies"]:
                    print(f"    🔍 {a}")
            else:
                print(f"\n  ✅ 정상 패턴 (이상 없음)")
        
        # ka10038: 증권사 순위
        print(f"\n[ka10038] 증권사 순위 (순매수순)")
        ranking = self.client.get_broker_ranking(stk_cd)
        if ranking:
            print(f"  전체 매수:{ranking['total_buy']:+,} 매도:{ranking['total_sell']:+,} 순:{ranking['total_net']:+,}")
            print(f"\n  {'#':>3s} {'증권사':<12s} {'매수':>10s} {'매도':>10s} {'순매수':>10s}")
            print(f"  {'─'*3} {'─'*12} {'─'*10} {'─'*10} {'─'*10}")
            for b in ranking["brokers"][:10]:
                mark = "⚡" if not self.analyzer.is_major_retail(b["name"]) else "  "
                print(f"  {mark}{b['rank']:>2d} {b['name']:<10s} "
                      f"{b['buy_qty']:>+10,} {-b['sell_qty']:>+10,} {b['net_buy']:>+10,}")
            
            r38 = self.analyzer.analyze_ka10038(stk_cd, stk_nm, cur_prc, ranking)
            if r38:
                print(f"\n  ✅ ka10038 이상 점수: {r38['score']}점")
                for a in r38["anomalies"]:
                    print(f"    🔍 {a}")
        
        print(f"\n총 API: {self.client.call_count}건 / 오류: {self.client.error_count}건")
    
    def scan(self, top_n: int = 500, save: bool = False):
        """전체 스캔"""
        t0 = time.time()
        now = datetime.now()
        
        print(f"\n{'='*70}")
        print(f"  거래원 이상분포 스캐너 v3.0")
        print(f"  {now.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  대상: {PRICE_MIN}~{PRICE_MAX}원, 거래대금 상위 (최대 {top_n}개)")
        print(f"  이상 기준: {AnomalyAnalyzer.ANOMALY_THRESHOLD}점 이상")
        print(f"{'='*70}")
        
        # 1. 유니버스
        universe = self._build_universe(top_n)
        if not universe:
            print("\n유니버스 구축 실패")
            return
        
        # 2. ka10040 스캔
        print(f"\n[스캔] {len(universe)}개 종목 분석 중...")
        results = []
        flagged_codes = set()
        
        for i, stock in enumerate(universe):
            if (i + 1) % 50 == 0:
                el = time.time() - t0
                eta = el / (i + 1) * (len(universe) - i - 1)
                log.info(f"  {i+1}/{len(universe)} ({el:.0f}s, ETA {eta:.0f}s)")
            
            daily = self.client.get_daily_brokers(stock["code"])
            if not daily:
                continue
            
            result = self.analyzer.analyze(
                stock["code"], stock["name"], stock["price"], daily
            )
            if result:
                results.append(result)
                flagged_codes.add(stock["code"])
                log.info(f"  🔍 {stock['code']} {stock['name']} → {result['score']}점 "
                        f"{', '.join(result['anomalies'][:2])}")
        
        # 3. 플래그 종목 ka10038 정밀분석
        ka38_results = []
        if flagged_codes:
            log.info(f"\n[정밀] {len(flagged_codes)}개 종목 ka10038 분석...")
            for stock in universe:
                if stock["code"] not in flagged_codes:
                    continue
                ranking = self.client.get_broker_ranking(stock["code"])
                if ranking:
                    r38 = self.analyzer.analyze_ka10038(
                        stock["code"], stock["name"], stock["price"], ranking
                    )
                    if r38:
                        ka38_results.append(r38)
        
        total_time = time.time() - t0
        
        # 결과 출력
        self._print_results(results, ka38_results, universe, total_time)
        
        if save and results:
            self._save_csv(results, ka38_results)
    
    def _build_universe(self, top_n: int) -> list:
        """유니버스 구축 (연속조회)"""
        log.info("유니버스 구축...")
        
        # 필요 페이지 수 추정 (100건/페이지, 2000~10000원은 ~10% 비율)
        est_pages = min(max(top_n // 10, 3), 10)
        raw = self.client.get_top_volume(max_pages=est_pages)
        
        if not raw:
            return []
        
        log.info(f"원시 {len(raw)}건에서 가격 필터...")
        
        universe = []
        for item in raw:
            code = str(item.get("stk_cd", "")).strip()
            name = str(item.get("stk_nm", "")).strip()
            price = abs(KiwoomClient._parse_int(item.get("cur_prc", "0")))
            
            if not code or not name:
                continue
            if PRICE_MIN <= price <= PRICE_MAX:
                universe.append({"code": code, "name": name, "price": price})
        
        if len(universe) > top_n:
            universe = universe[:top_n]
        
        log.info(f"유니버스: {len(universe)}개 ({PRICE_MIN}~{PRICE_MAX}원)")
        return universe
    
    def _print_results(self, results: list, ka38_results: list,
                       universe: list, elapsed: float):
        """결과 출력"""
        print(f"\n{'='*70}")
        print(f"  스캔 결과")
        print(f"{'='*70}")
        print(f"  스캔: {len(universe)}개 | API: {self.client.call_count}건 | "
              f"시간: {elapsed:.1f}초 | 오류: {self.client.error_count}건")
        print(f"  이상 감지: {len(results)}개 종목")
        
        if not results:
            print(f"\n  ⚠ 이상 패턴 종목 없음 (기준: {AnomalyAnalyzer.ANOMALY_THRESHOLD}점)")
            return
        
        # 점수순 정렬
        results.sort(key=lambda x: x["score"], reverse=True)
        
        print(f"\n  {'─'*66}")
        print(f"  {'#':>2s} {'점수':>4s} {'종목코드':<8s} {'종목명':<14s} {'가격':>7s} {'이상 항목'}")
        print(f"  {'─'*66}")
        
        for i, r in enumerate(results):
            top_anomaly = r["anomalies"][0] if r["anomalies"] else ""
            print(f"  {i+1:2d}. {r['score']:3d}점 {r['code']:<8s} {r['name']:<14s} "
                  f"{r['price']:>6,}원 {top_anomaly}")
            
            # 세부 점수 바 차트
            detail_str = " | ".join(f"{k}:{v}" for k, v in r["detail"].items() if v > 0)
            print(f"      [{detail_str}]")
            
            # 추가 이상 항목
            for a in r["anomalies"][1:]:
                print(f"      🔍 {a}")
            
            # 매수/매도 요약
            print(f"      매수: {r['buy_summary']}")
            if r.get("sell_summary"):
                print(f"      매도: {r['sell_summary']}")
            print()
        
        # ka10038 추가 결과
        if ka38_results:
            print(f"\n  ── ka10038 정밀분석 추가 이상 ──")
            for r in ka38_results:
                print(f"  {r['code']} {r['name']} +{r['score']}점")
                for a in r["anomalies"]:
                    print(f"    🔍 {a}")
                print(f"    순매수: {r['net_buy_summary']}")
    
    def _save_csv(self, results: list, ka38_results: list):
        """CSV 저장"""
        now = datetime.now().strftime("%Y%m%d_%H%M")
        path = DATA_DIR / f"broker_anomaly_{now}.csv"
        
        fields = ["code", "name", "price", "score", "anomalies",
                  "비주류출현", "매수매도비대칭", "분포이상", "외국계집중",
                  "buy_summary", "sell_summary", "total_buy", "frgn_buy"]
        
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for r in results:
                row = {
                    "code": r["code"],
                    "name": r["name"],
                    "price": r["price"],
                    "score": r["score"],
                    "anomalies": " | ".join(r["anomalies"]),
                    "buy_summary": r["buy_summary"],
                    "sell_summary": r.get("sell_summary", ""),
                    "total_buy": r["total_buy"],
                    "frgn_buy": r.get("frgn_buy", 0),
                }
                row.update(r.get("detail", {}))
                writer.writerow(row)
        
        print(f"\n  💾 저장: {path}")
        log.info(f"저장 완료: {path} ({len(results)}건)")


# ── 엔트리포인트 ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="거래원 이상분포 스캐너 v3.0")
    parser.add_argument("--test", type=str, help="종목 테스트 (ex: 005930)")
    parser.add_argument("--save", action="store_true", help="CSV 저장")
    parser.add_argument("--top", type=int, default=500, help="최대 스캔 수 (기본 500)")
    args = parser.parse_args()
    
    if not APP_KEY or not SECRET_KEY:
        print("오류: .env에 KIWOOM_APPKEY, KIWOOM_SECRETKEY 설정 필요")
        sys.exit(1)
    
    scanner = BrokerScanner()
    
    if args.test:
        scanner.test_single(args.test)
    else:
        scanner.scan(top_n=args.top, save=args.save)


if __name__ == "__main__":
    main()
