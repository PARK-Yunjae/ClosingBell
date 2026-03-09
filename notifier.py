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
        nasdaq_warn = market.get("nasdaq_warning", False)
        lines.append(
            f"📊 코스피 {market.get('kospi', 0):,.0f} "
            f"({market.get('kospi_change', 0):+.1f}%) | "
            f"나스닥 {market.get('nasdaq_change', 0):+.1f}%"
            + (" 🔴" if nasdaq_warn else "")
        )
        if nasdaq_warn:
            lines.append("⚠️ **나스닥 급락 — 전종목 5점 감점, 보수 모드(TOP2)**")
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

            # 거래량 폭발 표시
            vol_ratio = stock.get("vol_ratio", 1.0)
            if vol_ratio >= 2.0:
                lines.append(f"　📊 거래량 ×{vol_ratio:.1f} (평균 대비)")

            # 과열 경고
            if stock.get("overheat"):
                lines.append("　🔥 **과열 주의** — 2~3위 우선 검토 권장")

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
        lines.append("")
        lines.append("⚠️ **워치리스트 등록 완료 — 즉시 매수 금지**")
        lines.append("D+1 승률 42% → 눌림목 신호(14:50 웹훅) 대기")

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

    def send_daily_picks(self, picks: list[dict]):
        """매일 15시 매수 후보 TOP3 — 무조건 발송 (DART+뉴스 포함)"""
        if not picks:
            # 감시 종목 없으면 관망 메시지
            self._send(content=(
                "🎯 **ClosingBell** — 활성 감시 종목 없음\n"
                "내일 스크리닝 후 워치리스트 등록 예정"
            ))
            return

        lines = ["🎯 **오늘의 매수 후보 TOP3**", ""]

        # A등급 강조 (상단에)
        a_list = [s["name"] for s in picks if s.get("conviction") == "A"]
        if a_list:
            lines.append(f"⚡ **A등급 {len(a_list)}건: {', '.join(a_list)}** ← 매수 우선")
        else:
            lines.append("💤 **A등급 없음 — 오늘은 관망**")
        lines.append("")

        for i, sig in enumerate(picks):
            name = sig.get("name", sig.get("code", ""))
            price = sig.get("current_price", 0)
            sig_type = sig.get("signal_type", "")
            change = sig.get("price_change_from_screen", 0)
            conv = sig.get("conviction", "C")
            rank = sig.get("rank", "?")
            days = sig.get("days_elapsed", 0)
            exp_wr = sig.get("expected_wr", 0)
            exp_ret = sig.get("expected_ret", 0)
            rank_note = sig.get("rank_note", "")
            in_window = sig.get("in_window", False)
            c_score = sig.get("conviction_score", 0)
            sweet = sig.get("sweet_spot_day", "?")

            # DART + 뉴스
            dart_risk = sig.get("dart_risk", "확인불가")
            dart_note = sig.get("dart_note", "")
            news_risk = sig.get("news_risk", "확인불가")
            news_summary = sig.get("news_summary", "")
            risk_flags = sig.get("risk_flags", [])

            medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."
            conv_emoji = {"A": "🟢", "B": "🟡", "C": "⚪"}.get(conv, "⚪")
            sweet_mark = " ★" if days == sweet and in_window else ""
            dart_e = {"정상": "✅", "양호": "✅", "주의": "⚠️", "위험": "❌"}.get(dart_risk, "❓")
            news_e = {"양호": "✅", "주의": "⚠️", "위험": "❌"}.get(news_risk, "❓")

            wl_date = sig.get("watchlist_date", "")
            date_short = wl_date[5:] if wl_date else ""  # "03/06"
            lines.append(f"{medal} {conv_emoji} **[{conv}] {date_short} #{rank} {name}** ({c_score}점)")
            lines.append(f"　💰 {price:,}원 ({change:+.1f}%) | D+{days}{sweet_mark}")
            if sig_type:
                lines.append(f"　📍 {sig_type}")
            lines.append(f"　📊 기대승률 {exp_wr}% / {exp_ret:+.1f}%")

            # 위험 정보
            dart_text = f"{dart_risk}"
            if dart_note:
                dart_text += f"({dart_note})"
            lines.append(f"　📋 공시: {dart_text} {dart_e} | 뉴스: {news_summary} {news_e}")

            if risk_flags:
                lines.append(f"　⚠️ {', '.join(risk_flags)}")

            if rank_note:
                lines.append(f"　💡 {rank_note}")
            lines.append("")

        if not a_list:
            lines.append("관망 권장 — 조건 좋은 종목이 나타날 때까지 대기")

        a_count = len(a_list)
        color = 0x00B894 if a_count >= 2 else (0x3498DB if a_count == 1 else 0x95A5A6)

        embed = {
            "title": f"🎯 ClosingBell — 매수 후보 ({datetime.now().strftime('%m/%d %H:%M')})",
            "description": "\n".join(lines),
            "color": color,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._send(embeds=[embed])

    def send_shutdown(self, message: str = ""):
        now = datetime.now().strftime("%H:%M")
        self._send(content=f"✅ ClosingBell v3 종료 ({now}) {message}")

    def send_pullback_signals(self, signals: list[dict]):
        """눌림목 진입 신호 알림 (확신도 등급 + 순위별 가이드)"""
        if not signals:
            return

        lines = ["🎯 **눌림목 진입 신호 감지!**", ""]

        for sig in signals:
            name = sig.get("name", sig.get("code", ""))
            price = sig.get("current_price", 0)
            sig_type = sig.get("signal_type", "")
            change = sig.get("price_change_from_screen", 0)
            conv = sig.get("conviction", "C")
            rank = sig.get("rank", "?")
            days = sig.get("days_elapsed", 0)
            exp_wr = sig.get("expected_wr", 0)
            exp_ret = sig.get("expected_ret", 0)
            rank_note = sig.get("rank_note", "")

            conv_emoji = {"A": "🟢🟢🟢", "B": "🟢🟢", "C": "🟡"}.get(conv, "🟡")
            conv_label = {"A": "강력 매수", "B": "관심 매수", "C": "참고"}.get(conv, "참고")

            lines.append(f"{conv_emoji} **[{conv}등급] #{rank}위 {name}**")
            lines.append(f"　💰 {price:,}원 (스크리닝 대비 {change:+.1f}%)")
            lines.append(f"　📍 {sig_type} | D+{days}")
            lines.append(f"　📊 기대승률 {exp_wr}% / 평균수익 {exp_ret:+.1f}%")
            lines.append(f"　▶ **{conv_label}** | {rank_note}")
            lines.append("")

        # A등급이 있으면 상단에 요약
        a_count = sum(1 for s in signals if s.get("conviction") == "A")
        if a_count > 0:
            a_names = [s["name"] for s in signals if s["conviction"] == "A"]
            lines.insert(2, f"⚡ **A등급 {a_count}건: {', '.join(a_names)}** ← 매수 우선")
            lines.insert(3, "")

        lines.append("⏰ 14:50 최종 체크 | closingbell.streamlit.app")

        color = 0x00B894 if a_count > 0 else (0xF39C12 if signals else 0x95A5A6)

        embed = {
            "title": f"🎯 ClosingBell — 눌림목 신호 ({datetime.now().strftime('%m/%d %H:%M')})",
            "description": "\n".join(lines),
            "color": color,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._send(embeds=[embed])

    def send_error(self, error_msg: str):
        self._send(content=f"❌ ClosingBell 에러: {error_msg}")