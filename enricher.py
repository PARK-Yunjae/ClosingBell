"""
ClosingBell v3.7 universe enricher
===============================================
유니버스 전체(50~80종목)에 거래원+DART+AI를 적용.
매물대는 screener._calc_indicators에서 이미 계산됨.
"""
import logging
from kiwoom_api import KiwoomAPI
from dart_checker import DartChecker
from ai_analyzer import AIAnalyzer

logger = logging.getLogger("closingbell")

# 외국계 증권사 코드 (키움 기준)
FOREIGN_BROKERS = {
    "036": "모건스탠리", "037": "메릴린치", "005": "골드만삭스",
    "010": "UBS", "029": "JP모건", "016": "CLSA", "021": "크레디스위스",
    "052": "맥쿼리", "034": "노무라", "044": "BNP파리바",
    "040": "씨티그룹", "009": "도이치", "053": "바클레이즈",
}

# 비주류 증권사 (세력 매집 패턴에서 자주 등장)
MINOR_BROKERS = {"이베스트", "유안타", "BNK", "부국", "교보", "다올", "하이투자"}


class Enricher:
    """유니버스 전체 종목에 대한 추가 분석"""

    def __init__(self):
        self.dart = DartChecker()
        self.ai = AIAnalyzer()

    def enrich_all(self, scored: list[dict], api: KiwoomAPI) -> list[dict]:
        """
        유니버스 전체에 거래원+DART+AI 분석 적용
        실패해도 기본값으로 채워서 계속 진행
        """
        total = len(scored)
        success = 0
        for i, stock in enumerate(scored):
            try:
                self._enrich_broker(stock, api)
                success += 1
            except Exception as e:
                logger.debug("거래원 실패 [%s]: %s", stock.get("code"), e)
                stock.setdefault("broker_signal", "중립")
                stock.setdefault("broker_score", 0)

        logger.info("거래원 분석: %d/%d 성공", success, total)

        # DART 체크
        dart_ok = 0
        for stock in scored:
            try:
                dart_result = self.dart.check(stock["code"])
                stock["dart_risk"] = dart_result["risk"]
                stock["dart_note"] = dart_result["note"]
                stock["profit_loss"] = dart_result.get("profit_loss", "")
                dart_ok += 1
            except Exception:
                stock.setdefault("dart_risk", "확인불가")
                stock.setdefault("dart_note", "")

        logger.info("DART 체크: %d/%d 성공", dart_ok, total)

        # AI 위험도 (전체)
        ai_ok = 0
        for stock in scored:
            try:
                ai_result = self.ai.analyze(stock)
                stock["ai_action"] = ai_result["action"]
                stock["ai_risk"] = ai_result["risk"]
                stock["ai_summary"] = ai_result["summary"]
                ai_ok += 1
            except Exception:
                stock.setdefault("ai_action", "관망")
                stock.setdefault("ai_risk", "보통")
                stock.setdefault("ai_summary", "분석 실패")

        logger.info("AI 분석: %d/%d 성공", ai_ok, total)

        return scored

    def _enrich_broker(self, stock: dict, api: KiwoomAPI):
        """거래원 분석 — ka10038 + ka10040"""
        code = stock["code"]

        # ka10038: 종목별 증권사순위 (순매수 순)
        ranking = api.get_broker_ranking(code, period="1", sort="2")
        brokers = ranking.get("brokers", [])

        if brokers:
            stock["broker_top_buy"] = brokers[0]["name"]
            stock["broker_top_buy_net"] = brokers[0]["net"]
        else:
            stock["broker_top_buy"] = ""
            stock["broker_top_buy_net"] = 0

        # ka10040: 당일 주요 거래원 (외국계 순매수 합계)
        detail = api.get_broker_detail(code)
        stock["foreign_net"] = detail.get("foreign_net", 0)
        stock["foreign_buy"] = detail.get("foreign_buy_total", 0)
        stock["foreign_sell"] = detail.get("foreign_sell_total", 0)

        # 거래원 신호 판정
        signal, score = self._judge_broker(brokers, detail)
        stock["broker_signal"] = signal
        stock["broker_score"] = score

    def _judge_broker(self, brokers: list, detail: dict) -> tuple[str, float]:
        """
        거래원 종합 판정
        반환: (신호텍스트, 점수0~5)
        """
        score = 0.0
        signals = []

        # 1) 외국계 순매수 여부
        frgn_net = detail.get("foreign_net", 0)
        if frgn_net > 0:
            score += 2.0
            signals.append("외국계 순매수")
        elif frgn_net < 0:
            score -= 0.5

        # 2) TOP 매수 증권사가 외국계인지
        buy_top5 = detail.get("buy_top5", [])
        foreign_buy_count = sum(
            1 for b in buy_top5
            if b.get("code") in FOREIGN_BROKERS or b.get("name") in FOREIGN_BROKERS.values()
        )
        if foreign_buy_count >= 2:
            score += 2.0
            signals.append("외국계 다수 매수")
        elif foreign_buy_count >= 1:
            score += 1.0

        # 3) 비주류 증권사 매집 패턴
        minor_buy = sum(
            1 for b in buy_top5
            if any(m in b.get("name", "") for m in MINOR_BROKERS)
        )
        if minor_buy >= 2:
            score += 1.5
            signals.append("비주류 매집")
        elif minor_buy >= 1:
            score += 0.5

        # 최대 5점 cap
        score = max(0, min(5.0, score))

        if not signals:
            signal_text = "중립"
        elif score >= 3.5:
            signal_text = "매집 신호"
        elif score >= 2.0:
            signal_text = "외국계 관심"
        else:
            signal_text = " + ".join(signals)

        return signal_text, round(score, 1)
