"""
ClosingBell v3 — 디스코드 웹훅 (2층 구조)
==========================================
공유용: 이모지+한글, CCI/RSI 영어 없음, 행동 신호등
본인용: JSON 로그에 상세 데이터
"""
import logging
import requests
from datetime import datetime
from config import DISCORD_WEBHOOK_URL

logger = logging.getLogger("closingbell")

# 행동별 이모지
ACTION_EMOJI = {"매수관심": "🟢", "관망": "🟡", "주의": "🔴"}
RISK_EMOJI = {"낮음": "✅", "보통": "⚠️", "높음": "🚫"}
# DART 상태
DART_EMOJI = {"정상": "✅", "주의": "⚠️", "위험": "❌", "확인불가": "❓"}
# 매물대
VP_EMOJI = {"위 매물 적음": "✅", "매물대 중립": "➖", "위 저항 강함": "❌", "데이터부족": "❓"}


class Notifier:
    """디스코드 웹훅 — 공유용 쉬운 알림"""

    def __init__(self):
        self.url = DISCORD_WEBHOOK_URL

    def _send(self, content: str = "", embeds: list = None):
        if not self.url:
            logger.debug("웹훅 URL 미설정")
            return
        payload = {}
        if content:
            payload["content"] = content
        if embeds:
            payload["embeds"] = embeds
        try:
            r = requests.post(self.url, json=payload, timeout=10)
            if r.status_code in (200, 204):
                logger.info("디스코드 전송 완료")
            else:
                logger.warning("디스코드 실패: %d", r.status_code)
        except Exception as e:
            logger.warning("디스코드 에러: %s", e)

    def send_recommendation(self, result: dict):
        """TOP3 추천 — 공유용 쉬운 버전"""
        if result.get("skipped"):
            self._send(content=(
                f"🔕 **ClosingBell v3** — {result['date']}\n"
                f"스크리닝 스킵: {result.get('reason', '')}"
            ))
            return

        market = result.get("market", {})
        top = result.get("top", [])
        prev_returns = result.get("prev_returns", [])

        lines = []

        # ── 시장 현황 (간결) ──
        lines.append(
            f"📊 코스피 {market.get('kospi', 0):,.0f} "
            f"({market.get('kospi_change', 0):+.1f}%) | "
            f"나스닥 {market.get('nasdaq_change', 0):+.1f}%"
        )
        lines.append("")

        # ── TOP3 종목 카드 ──
        medals = ["🥇", "🥈", "🥉"]
        for i, stock in enumerate(top):
            medal = medals[i] if i < len(medals) else f"{i+1}."
            action = stock.get("ai_action", "관망")
            risk = stock.get("ai_risk", "보통")
            a_emoji = ACTION_EMOJI.get(action, "🟡")
            r_emoji = RISK_EMOJI.get(risk, "⚠️")

            lines.append(f"{medal} **{stock['name']}**")
            lines.append(
                f"　💰 {stock['price']:,}원 ({stock['change_rate']:+.1f}%) | "
                f"**{stock['score']}점**"
            )

            # 매물대
            vp_tag = stock.get("vp_tag", "")
            vp_e = VP_EMOJI.get(vp_tag, "➖")
            lines.append(f"　📍 매물대: {vp_tag} {vp_e}")

            # 거래원
            broker_sig = stock.get("broker_signal", "중립")
            broker_e = "✅" if "매수" in broker_sig or "매집" in broker_sig else "➖"
            if stock.get("broker_top_buy"):
                lines.append(
                    f"　🏦 거래원: {broker_sig} {broker_e} "
                    f"(매수1위: {stock['broker_top_buy']})"
                )
            else:
                lines.append(f"　🏦 거래원: {broker_sig} {broker_e}")

            # DART
            dart_risk = stock.get("dart_risk", "확인불가")
            dart_e = DART_EMOJI.get(dart_risk, "❓")
            dart_note = stock.get("dart_note", "")
            pl = stock.get("profit_loss", "")
            dart_text = f"{dart_risk}"
            if pl:
                dart_text += f", {pl}"
            if dart_note:
                dart_text += f" ({dart_note})"
            lines.append(f"　📋 공시: {dart_text} {dart_e}")

            # 행동 + AI 한줄
            summary = stock.get("ai_summary", "")
            lines.append(
                f"　▶ **{action}** {a_emoji} | 위험도 {risk} {r_emoji}"
            )
            if summary:
                lines.append(f"　💡 *\"{summary}\"*")
            lines.append("")

        # ── 주도테마 ──
        themes = result.get("theme_summary", [])
        if themes:
            theme_text = " | ".join(
                f"{'🔥' if t['change_rate'] > 2 else '⚡'} {t['name']} "
                f"({t['change_rate']:+.1f}%)"
                for t in themes[:3]
            )
            lines.append(f"━━ 주도테마 ━━")
            lines.append(theme_text)
            lines.append("")

        # ── 전일 성과 ──
        if prev_returns:
            wins = sum(1 for r in prev_returns if r["return_pct"] > 0)
            total = len(prev_returns)
            details = ", ".join(
                f"{r['name']} {r['return_pct']:+.1f}%"
                for r in prev_returns
            )
            lines.append(f"📈 전일 성과: {wins}/{total} 상승 ({details})")
            lines.append("")

        lines.append(
            f"유니버스 {result.get('universe_count', 0)}종목 | "
            f"🌐 closingbell.streamlit.app"
        )

        # 색상: 전체적으로 긍정이면 초록, 주의 많으면 노랑
        caution_count = sum(1 for s in top if s.get("ai_action") == "주의")
        color = 0xE74C3C if caution_count >= 2 else (0xF39C12 if caution_count >= 1 else 0x00B894)

        embed = {
            "title": f"🔔 ClosingBell v3 — {result['date']}",
            "description": "\n".join(lines),
            "color": color,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._send(embeds=[embed])

    def send_shutdown(self, message: str = ""):
        now = datetime.now().strftime("%H:%M")
        self._send(content=f"✅ ClosingBell v3 종료 ({now}) {message}")

    def send_error(self, error_msg: str):
        self._send(content=f"❌ ClosingBell 에러: {error_msg}")
