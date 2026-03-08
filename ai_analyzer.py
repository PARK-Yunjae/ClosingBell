"""
ClosingBell v3 — AI 위험도 분석 (Gemini)
=========================================
각 종목에 대해 매수관심/관망/주의 + 위험도 + 한줄 이유 제공.
Gemini flash 모델 사용 (빠르고 저렴).
"""
import logging
import json
import time
import requests
from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger("closingbell")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class AIAnalyzer:
    """Gemini 기반 종목 위험도 한줄 분석"""

    def __init__(self):
        self.api_key = GEMINI_API_KEY
        self.model = GEMINI_MODEL

    def analyze(self, stock: dict) -> dict:
        """
        종목 데이터 → AI 판단
        반환: {"action": "매수관심|관망|주의", "risk": "낮음|보통|높음", "summary": "15자 이내"}
        """
        if not self.api_key:
            return self._rule_based(stock)

        prompt = self._build_prompt(stock)

        try:
            result = self._call_gemini(prompt)
            parsed = self._parse_response(result)
            return parsed
        except Exception as e:
            logger.debug("AI 분석 실패 [%s]: %s", stock.get("code"), e)
            return self._rule_based(stock)

    def _build_prompt(self, stock: dict) -> str:
        return f"""한국 주식 종목의 단기(1~3일) 매매 판단을 해줘.

종목: {stock.get('name', '')} ({stock.get('code', '')})
현재가: {stock.get('price', 0):,}원 ({stock.get('change_rate', 0):+.1f}%)
CCI(14): {stock.get('cci', 0):.0f} | RSI(14): {stock.get('rsi', 0):.0f}
MA20 이격도: {stock.get('ma20_gap', 0):.1f}%
매물대: 위 {stock.get('vp_above_pct', 50):.0f}% / 아래 {stock.get('vp_below_pct', 50):.0f}% ({stock.get('vp_tag', '')})
거래원: {stock.get('broker_signal', '중립')} (외국계순매수: {stock.get('foreign_net', 0)})
DART: {stock.get('dart_risk', '확인불가')} - {stock.get('dart_note', '')}

아래 JSON 형식으로만 답해. 다른 텍스트 없이 JSON만.
{{"action": "매수관심 또는 관망 또는 주의", "risk": "낮음 또는 보통 또는 높음", "summary": "15자 이내 핵심 이유"}}"""

    def _call_gemini(self, prompt: str) -> str:
        """Gemini API 호출"""
        url = GEMINI_URL.format(model=self.model) + f"?key={self.api_key}"

        time.sleep(1.0)  # 속도 제한 (분당 60건)
        resp = requests.post(url, json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 200,
            },
        }, timeout=15)
        resp.raise_for_status()

        data = resp.json()
        # Gemini 응답 구조
        candidates = data.get("candidates", [])
        if not candidates:
            raise ValueError("Gemini 응답 없음")

        text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        return text

    def _parse_response(self, text: str) -> dict:
        """Gemini 응답 JSON 파싱"""
        # ```json ... ``` 감싸기 제거
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        try:
            result = json.loads(text)
            # 유효성 검증
            action = result.get("action", "관망")
            if action not in ("매수관심", "관망", "주의"):
                action = "관망"
            risk = result.get("risk", "보통")
            if risk not in ("낮음", "보통", "높음"):
                risk = "보통"
            summary = result.get("summary", "")[:20]
            return {"action": action, "risk": risk, "summary": summary}
        except (json.JSONDecodeError, KeyError):
            return {"action": "관망", "risk": "보통", "summary": "파싱실패"}

    def _rule_based(self, stock: dict) -> dict:
        """AI 없이 룰 기반 판단 (fallback)"""
        action = "관망"
        risk = "보통"
        reasons = []

        cci = stock.get("cci", 0)
        rsi = stock.get("rsi", 50)
        above = stock.get("vp_above_pct", 50)
        dart_risk = stock.get("dart_risk", "")
        broker = stock.get("broker_signal", "")
        change = stock.get("change_rate", 0)

        # 매수관심 조건
        good = 0
        if 140 <= cci <= 200:
            good += 1
        if 45 <= rsi <= 70:
            good += 1
        if above <= 35:
            good += 1
            reasons.append("매물대 여유")
        if "순매수" in broker or "매집" in broker:
            good += 1
            reasons.append("거래원 양호")
        if dart_risk in ("정상", ""):
            good += 1

        # 주의 조건
        bad = 0
        if cci > 250:
            bad += 1
            reasons.append("CCI 과열")
        if rsi > 75:
            bad += 1
            reasons.append("RSI 과열")
        if above >= 60:
            bad += 1
            reasons.append("매물대 저항")
        if dart_risk == "위험":
            bad += 2
            reasons.append("DART 위험")
        if change > 15:
            bad += 1
            reasons.append("급등 추격")

        if bad >= 2:
            action = "주의"
            risk = "높음"
        elif good >= 3 and bad == 0:
            action = "매수관심"
            risk = "낮음"
        else:
            action = "관망"
            risk = "보통" if bad <= 1 else "높음"

        summary = reasons[0] if reasons else "중립 구간"
        return {"action": action, "risk": risk, "summary": summary[:20]}
