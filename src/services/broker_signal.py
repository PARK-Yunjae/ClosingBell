"""
거래원 이상신호 모듈 v8.0
========================
ClosingBell 감시종목 TOP5의 7번째 핵심 지표 (거래원 점수 13점).

v8.0 변경:
  - 외부 보너스(+3/+5/+8) → 내부 핵심 지표 (0~13점)
  - calc_broker_score(): anomaly_score → 0~13 매핑
  - apply_broker_bonus() → 레거시 호환용 유지

거래원 점수 매핑 (0~13):
  anomaly 0~34  → 0점  (정상)
  anomaly 35~49 → 5점  (Watch)
  anomaly 50~69 → 9점  (Alert)
  anomaly 70~100→ 13점 (Critical)
  조회불가/프리뷰 → 6점 (중립)
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


# ── "정상" 대형 리테일 증권사 ──
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


def _is_major_retail(name: str) -> bool:
    for m in MAJOR_RETAIL:
        if m in name or name in m:
            return True
    return False


def _is_foreign(name: str) -> bool:
    for kw in FOREIGN_KEYWORDS:
        if kw in name:
            return True
    return False


# ── 분석 결과 ──

@dataclass
class BrokerAdjustment:
    """거래원 기반 점수 조정"""
    stock_code: str
    anomaly_score: int = 0        # 이상신호 원점수 (0~100)
    bonus: int = 0                # ClosingBell 보너스 (-3 ~ +8)
    tag: str = ""                 # "⚡외국계매집", "⚡비주류집중" 등
    detail: str = ""              # 상세 설명
    anomalies: List[str] = field(default_factory=list)
    
    # 세부 점수
    unusual_score: int = 0        # 비주류 출현
    asymmetry_score: int = 0      # 매수/매도 비대칭
    distribution_score: int = 0   # 분포 이상
    foreign_score: int = 0        # 외국계 집중

    # raw 데이터 (v9.1: 대시보드 시각화용)
    buyers_raw: List[dict] = field(default_factory=list)
    sellers_raw: List[dict] = field(default_factory=list)
    frgn_buy: int = 0
    frgn_sell: int = 0


# ── 핵심: 거래원 분석 엔진 ──

class BrokerAnalyzer:
    """ka10040 데이터 기반 이상 패턴 분석"""
    
    ANOMALY_THRESHOLD = 35   # 이상 신호 최소 점수
    MIN_VOLUME = 50_000      # 최소 매수거래량
    
    @classmethod
    def analyze(cls, stk_cd: str, broker_data: dict) -> Optional[BrokerAdjustment]:
        """
        broker_data 형태:
        {
            "buyers": [{"name": "키움증권", "qty": 100000}, ...],  # Top5
            "sellers": [{"name": "미래에셋", "qty": 80000}, ...],  # Top5
            "frgn_buy": 50000,
            "frgn_sell": -30000,
        }
        """
        buyers = broker_data.get("buyers", [])
        sellers = broker_data.get("sellers", [])
        
        if not buyers or len(buyers) < 2:
            return None
        
        total_buy = sum(b["qty"] for b in buyers)
        if total_buy < cls.MIN_VOLUME:
            return None
        
        adj = BrokerAdjustment(stock_code=stk_cd)
        adj.buyers_raw = buyers
        adj.sellers_raw = sellers
        adj.frgn_buy = broker_data.get("frgn_buy", 0)
        adj.frgn_sell = broker_data.get("frgn_sell", 0)
        
        # 1. 비주류 브로커 출현 (0~30점)
        s1, items1 = cls._check_unusual(buyers, total_buy)
        adj.unusual_score = s1
        adj.anomalies.extend(items1)
        
        # 2. 매수/매도 비대칭 (0~25점)
        s2, items2 = cls._check_asymmetry(buyers, sellers)
        adj.asymmetry_score = s2
        adj.anomalies.extend(items2)
        
        # 3. 분포 이상 (0~25점)
        s3, items3 = cls._check_distribution(buyers, total_buy)
        adj.distribution_score = s3
        adj.anomalies.extend(items3)
        
        # 4. 외국계 집중 (0~20점)
        s4, items4 = cls._check_foreign(
            buyers, total_buy,
            broker_data.get("frgn_buy", 0),
            broker_data.get("frgn_sell", 0),
        )
        adj.foreign_score = s4
        adj.anomalies.extend(items4)
        
        adj.anomaly_score = min(100, s1 + s2 + s3 + s4)
        
        if adj.anomaly_score < cls.ANOMALY_THRESHOLD:
            return None
        
        # 보너스 변환
        if adj.anomaly_score >= 70:
            adj.bonus = 8
        elif adj.anomaly_score >= 50:
            adj.bonus = 5
        else:
            adj.bonus = 3
        
        # 태그 결정 (가장 높은 점수 기반)
        scores = {
            "⚡외국계매집": s4,
            "⚡비주류집중": s1,
            "⚡매수편향": s2,
            "⚡분포이상": s3,
        }
        adj.tag = max(scores, key=scores.get)
        adj.detail = f"{adj.anomaly_score}점 (+{adj.bonus})"
        
        return adj
    
    @classmethod
    def _check_unusual(cls, buyers, total_buy):
        score, items = 0, []
        for i, b in enumerate(buyers[:5]):
            if _is_major_retail(b["name"]):
                continue
            ratio = b["qty"] / total_buy if total_buy > 0 else 0
            rank = i + 1
            if ratio >= 0.15:
                pts = min(30, int(ratio * 100) + (5 - rank) * 3)
                score += pts
                label = "외국계" if _is_foreign(b["name"]) else "비주류"
                items.append(f"{label} {b['name']} #{rank}위 {ratio:.0%}")
            elif ratio >= 0.08:
                pts = min(15, int(ratio * 60) + (5 - rank) * 2)
                score += pts
                items.append(f"비주류 {b['name']} #{rank}위 {ratio:.0%}")
        return min(score, 30), items
    
    @classmethod
    def _check_asymmetry(cls, buyers, sellers):
        score, items = 0, []
        if not sellers or len(sellers) < 2:
            return 0, []
        
        buy_names = set(b["name"] for b in buyers[:5])
        sell_names = set(s["name"] for s in sellers[:5])
        
        buy_only = buy_names - sell_names
        unusual_buy_only = [n for n in buy_only if not _is_major_retail(n)]
        
        if unusual_buy_only:
            score += min(15, len(unusual_buy_only) * 8)
            for n in unusual_buy_only:
                items.append(f"{n} 매수만")
        
        sell_only = sell_names - buy_names
        unusual_sell_only = [n for n in sell_only if not _is_major_retail(n)]
        if unusual_sell_only:
            score += min(10, len(unusual_sell_only) * 5)
        
        overlap = buy_names & sell_names
        if len(overlap) <= 1 and len(buy_names) >= 3:
            score += 10
            items.append(f"매수/매도 겹침 {len(overlap)}개")
        
        return min(score, 25), items
    
    @classmethod
    def _check_distribution(cls, buyers, total_buy):
        score, items = 0, []
        if len(buyers) < 3:
            return 0, []
        
        qtys = [b["qty"] for b in buyers[:5]]
        
        # 극단적 편중
        if len(qtys) >= 2 and qtys[1] > 0:
            ratio_12 = qtys[0] / qtys[1]
            if ratio_12 >= 4.0:
                score += 20
                items.append(f"극단편중 1위/2위={ratio_12:.1f}배")
            elif ratio_12 >= 3.0:
                score += 12
                items.append(f"편중 1위/2위={ratio_12:.1f}배")
        
        # 1위 독식
        top_ratio = qtys[0] / total_buy if total_buy > 0 else 0
        if top_ratio >= 0.50:
            score += 15
            items.append(f"1위 독식 {top_ratio:.0%}")
        elif top_ratio >= 0.40:
            score += 8
        
        # 평탄 분산
        if len(qtys) >= 5 and qtys[4] > 0:
            ratio_15 = qtys[0] / qtys[4]
            if ratio_15 < 1.3:
                score += 10
                items.append(f"평탄분산 1위/5위={ratio_15:.1f}배")
        
        return min(score, 25), items
    
    @classmethod
    def _check_foreign(cls, buyers, total_buy, frgn_buy, frgn_sell):
        score, items = 0, []
        
        frgn_in_top5 = [b for b in buyers[:5] if _is_foreign(b["name"])]
        
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
        
        frgn_net = abs(frgn_buy) - abs(frgn_sell)
        if frgn_net > 0 and total_buy > 0:
            net_ratio = frgn_net / total_buy
            if net_ratio >= 0.25 and not frgn_in_top5:
                score += 12
                items.append(f"외국계 순매수 {net_ratio:.0%}")
        
        return min(score, 20), items


# ── v8.0: anomaly_score → 거래원 점수 (0~13) ──

BROKER_SCORE_NEUTRAL = 6.0  # 조회불가/프리뷰 기본값

def calc_broker_score(anomaly_score: Optional[int]) -> float:
    """
    거래원 anomaly_score(0~100)를 핵심 지표 점수(0~13)로 변환.
    
    매핑:
      0~34  → 0점  (정상: 대형 리테일 위주)
      35~49 → 5점  (Watch: 약한 이상 신호)
      50~69 → 9점  (Alert: 비주류/외국계 뚜렷)
      70~100→ 13점 (Critical: 강한 매집 신호)
      None  → 6점  (중립: 조회불가/프리뷰)
    """
    if anomaly_score is None:
        return BROKER_SCORE_NEUTRAL
    
    if anomaly_score < 35:
        return 0.0
    elif anomaly_score < 50:
        return 5.0
    elif anomaly_score < 70:
        return 9.0
    else:
        return 13.0


def get_broker_tag(anomaly_score: Optional[int]) -> str:
    """anomaly_score에 대한 태그 반환"""
    if anomaly_score is None:
        return "중립"
    if anomaly_score < 35:
        return "정상"
    elif anomaly_score < 50:
        return "Watch"
    elif anomaly_score < 70:
        return "Alert"
    else:
        return "Critical"


# ── API 호출: kiwoom_rest_client 활용 ──

def _parse_int(val) -> int:
    if not val:
        return 0
    try:
        return int(str(val).replace(",", "").replace("+", ""))
    except ValueError:
        return 0


def _fetch_daily_brokers(client, stk_cd: str) -> Optional[dict]:
    """ka10040: 당일주요거래원 Top5 조회"""
    try:
        data = client._request(
            "POST",
            client.ENDPOINTS['rank_info'],
            "ka10040",
            body={"stk_cd": stk_cd},
        )
        
        if not data or data.get("return_code", 0) != 0:
            return None
        
        result = {
            "buyers": [],
            "sellers": [],
            "frgn_buy": _parse_int(data.get("frgn_buy_prsm_sum", "0")),
            "frgn_sell": _parse_int(data.get("frgn_sel_prsm_sum", "0")),
        }
        
        for i in range(1, 6):
            name = data.get(f"buy_trde_ori_{i}", "").strip()
            qty = _parse_int(data.get(f"buy_trde_ori_qty_{i}", "0"))
            if name and qty != 0:
                result["buyers"].append({"name": name, "qty": qty})
            
            name = data.get(f"sel_trde_ori_{i}", "").strip()
            qty = _parse_int(data.get(f"sel_trde_ori_qty_{i}", "0"))
            if name and qty != 0:
                result["sellers"].append({"name": name, "qty": abs(qty)})
        
        return result
    except Exception as e:
        logger.debug(f"ka10040 실패 {stk_cd}: {e}")
        return None


# ── 메인 인터페이스 ──

def get_broker_adjustments(
    stock_codes: List[str],
    client=None,
) -> Dict[str, BrokerAdjustment]:
    """
    ClosingBell Top 후보에 대해 거래원 이상 점수를 계산한다.
    
    Args:
        stock_codes: 종목코드 리스트 (Top20 정도)
        client: KiwoomRestClient 인스턴스 (없으면 자동 생성)
    
    Returns:
        {종목코드: BrokerAdjustment} - 이상 감지된 종목만 포함
    """
    if not stock_codes:
        return {}
    
    if client is None:
        try:
            from src.adapters.kiwoom_rest_client import get_kiwoom_client
            client = get_kiwoom_client()
        except Exception as e:
            logger.error(f"키움 클라이언트 생성 실패: {e}")
            return {}
    
    results = {}
    t0 = time.time()
    
    logger.info(f"🔍 거래원 스캔 시작: {len(stock_codes)}개 종목")
    
    for code in stock_codes:
        broker_data = _fetch_daily_brokers(client, code)
        if not broker_data:
            continue
        
        adj = BrokerAnalyzer.analyze(code, broker_data)
        if adj:
            results[code] = adj
            logger.info(f"  ⚡ {code} → {adj.anomaly_score}점 (+{adj.bonus}) {adj.tag}")
    
    elapsed = time.time() - t0
    logger.info(f"🔍 거래원 스캔 완료: {len(results)}/{len(stock_codes)}개 이상감지 ({elapsed:.1f}초)")
    
    return results


def apply_broker_bonus(
    scores: list,
    top_n: int = 20,
    client=None,
) -> Tuple[list, Dict[str, BrokerAdjustment]]:
    """
    ClosingBell 점수 리스트에 거래원 보너스를 적용한다.
    
    Args:
        scores: StockScore 리스트 (점수순 정렬 상태)
        top_n: 상위 N개만 스캔 (API 절약)
        client: KiwoomRestClient
    
    Returns:
        (재정렬된 scores, 이상감지 결과 dict)
    """
    if not scores:
        return scores, {}
    
    # 상위 N개만 스캔
    candidates = scores[:top_n]
    codes = [s.stock_code for s in candidates]
    
    adjustments = get_broker_adjustments(codes, client)
    
    if not adjustments:
        return scores, {}
    
    # 보너스 적용
    for score in scores:
        adj = adjustments.get(score.stock_code)
        if adj:
            old_score = score.score_total
            score.score_total = min(100, score.score_total + adj.bonus)
            # 메타데이터 저장 (discord embed에서 사용)
            score._broker_adj = adj
            score._broker_bonus = adj.bonus
            logger.info(
                f"  {score.stock_code} {score.stock_name}: "
                f"{old_score:.1f} → {score.score_total:.1f} ({adj.tag})"
            )
    
    # 재정렬
    scores.sort(key=lambda x: x.score_total, reverse=True)
    
    return scores, adjustments