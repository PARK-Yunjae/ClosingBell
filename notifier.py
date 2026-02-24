"""
ClosingBell v2 — 디스코드 웹훅 알림
"""
import logging
import requests
from datetime import datetime
from config import DISCORD_WEBHOOK_URL

logger = logging.getLogger("closingbell")


class Notifier:
    """디스코드 웹훅 알림"""

    def __init__(self):
        self.url = DISCORD_WEBHOOK_URL

    def _send(self, content: str = "", embeds: list = None):
        """웹훅 전송"""
        if not self.url:
            logger.debug("디스코드 웹훅 URL 미설정 → 스킵")
            return

        payload = {}
        if content:
            payload["content"] = content
        if embeds:
            payload["embeds"] = embeds

        try:
            r = requests.post(self.url, json=payload, timeout=10)
            if r.status_code in (200, 204):
                logger.info("디스코드 알림 전송 완료")
            else:
                logger.warning("디스코드 전송 실패: %d", r.status_code)
        except Exception as e:
            logger.warning("디스코드 전송 에러: %s", e)

    def send_recommendation(self, result: dict):
        """TOP5 추천 알림"""
        if result.get("skipped"):
            self._send(content=(
                f"🔕 **ClosingBell v2** — {result['date']}\n"
                f"스크리닝 스킵: {result.get('reason', '알 수 없음')}"
            ))
            return

        market = result.get("market", {})
        top5 = result.get("top5", [])

        # 시장 현황
        lines = [
            f"📊 **시장**: 코스피 {market.get('kospi', 0):,.0f} "
            f"({market.get('kospi_change', 0):+.2f}%) | "
            f"코스닥 {market.get('kosdaq', 0):,.0f} "
            f"({market.get('kosdaq_change', 0):+.2f}%)",
            f"📈 **나스닥(전일)**: {market.get('nasdaq', 0):,.0f} "
            f"({market.get('nasdaq_change', 0):+.2f}%)",
            "",
        ]

        # TOP5
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        for i, stock in enumerate(top5):
            medal = medals[i] if i < len(medals) else f"{i+1}."
            cci_arrow = "↑" * stock.get("cci_slope", 0) or "→"
            ma_arrow = "↑" if stock.get("ma20_slope", 0) > 0 else "→"

            lines.append(
                f"{medal} **{stock['name']}** ({stock['code']}) — "
                f"**{stock['score']}점**"
            )
            lines.append(
                f"　💰 {stock['price']:,}원 ({stock['change_rate']:+.1f}%) | "
                f"CCI {stock['cci']:.0f} | 이격도 {stock['ma20_gap']:.1f}% | "
                f"CCI{cci_arrow} | MA{ma_arrow}"
            )

        lines.append("")
        lines.append(
            f"유니버스 {result.get('universe_count', 0)}종목 | "
            f"🌐 closingbell.streamlit.app"
        )

        embed = {
            "title": f"🔔 ClosingBell v2 — {result['date']}",
            "description": "\n".join(lines),
            "color": 0x00B894,  # 초록
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._send(embeds=[embed])

    def send_shutdown(self, message: str = ""):
        """종료 알림"""
        now = datetime.now().strftime("%H:%M")
        self._send(content=f"✅ ClosingBell v2 종료 ({now}) {message}")

    def send_error(self, error_msg: str):
        """에러 알림"""
        self._send(content=f"❌ ClosingBell 에러: {error_msg}")
