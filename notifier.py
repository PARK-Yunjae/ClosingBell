"""
Discord notifications for ClosingBell v4.0
==========================================
읽기 쉬운 한국어 웹훅 — "그래서 사?"에 바로 답하는 구조.

변경 이력:
  v3.7.1 — 한줄 액션 라벨 추가, 용어 한국어화, D+1 감점 표시
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

from config import (
    DISCORD_PICK_TOP_N,
    DISCORD_SCREEN_TOP_N,
    DISCORD_WEBHOOK_URL,
    NOTIFIER_RECENT_SESSIONS,
)
from storage import save_notification_event

logger = logging.getLogger("closingbell")
TRACKING_PATH = Path(__file__).parent / "data" / "performance" / "tracking.json"

# ════════════════════════════════════════════
# 용어 매핑 — 시스템 용어 → 사람이 읽는 말
# ════════════════════════════════════════════
REGIME_KR = {
    "rising": "상승세",
    "chaotic": "혼조세 (변동 큼)",
    "weak": "약세",
    "mixed": "보통",
    "unknown": "-",
}

SIGNAL_KR = {
    "MA5터치": "5일선 근접",
    "거래량감소": "거래량 줄어듦",
    "BB하단": "볼린저 하단 근접",
    "가격조정": "가격 눌림",
    "깊은조정": "큰 폭 하락",
    "CCI냉각": "과열 해소",
    "RSI과매도": "과매도 구간",
}

RANK_NOTE_KR = {
    "빠른 반등형": "빠른 반등형 — 눌림목 오면 바로 진입",
    "느린 회복형": "느린 회복형 — 며칠 기다렸다 진입",
    "깊은 조정 후 반등형": "깊은 조정형 — 충분히 빠진 후 진입",
}

GRADE_EMOJI = {"A": "🥇", "B": "🥈", "C": "🥉"}
GRADE_LABEL = {"A": "강력", "B": "보통", "C": "약함"}
ACTION_ICON = {"매수관심": "🟢", "관망": "🟡", "주의": "🔴"}
RISK_ICON = {"정상": "🟢", "양호": "🟢", "보통": "🟡", "주의": "🟠", "위험": "🔴", "확인불가": "⚪"}
GRADE_COLOR = {"A": 0x0F9D58, "B": 0x1A73E8, "C": 0x7F8C8D}
ACTION_COLOR = {"green": 0x0F9D58, "yellow": 0xF1C40F, "red": 0xE74C3C}

SUMMARY_COLOR = 0x143A52
WARNING_COLOR = 0xE67E22
ERROR_COLOR = 0xC0392B
NEUTRAL_COLOR = 0x7F8C8D


# ════════════════════════════════════════════
# 유틸리티
# ════════════════════════════════════════════
def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe(value, fallback: str = "-") -> str:
    text = str(value).strip() if value is not None else ""
    return text if text else fallback


def _clip(text: str, limit: int = 300) -> str:
    text = _safe(text, "")
    if len(text) <= limit:
        return text or "-"
    return f"{text[: limit - 1].rstrip()}…"


def _won(value) -> str:
    try:
        return f"{int(round(float(value))):,}원"
    except Exception:
        return "-"


def _score(value) -> str:
    try:
        num = float(value)
        return f"{num:.0f}점" if num == int(num) else f"{num:.1f}점"
    except Exception:
        return "-"


def _pct(value, digits: int = 1) -> str:
    try:
        return f"{float(value):+.{digits}f}%"
    except Exception:
        return "-"


def _signal_kr(raw: str) -> str:
    """시스템 시그널 -> 사람이 읽는 말"""
    if not raw or raw == "-":
        return "조건 재확인"
    parts = raw.split("+")
    return " + ".join(SIGNAL_KR.get(p.strip(), p.strip()) for p in parts)


def _regime_kr(raw: str) -> str:
    return REGIME_KR.get(raw, raw or "-")


def _field(name: str, value: str, inline: bool = False) -> dict:
    return {"name": name, "value": _clip(value, 1000), "inline": inline}


def _pick_color(picks: list[dict]) -> int:
    for p in picks:
        action = p.get("action", {})
        if action.get("color") == "green":
            return ACTION_COLOR["green"]
    if any(p.get("conviction") == "A" for p in picks):
        return GRADE_COLOR["A"]
    if any(p.get("conviction") == "B" for p in picks):
        return GRADE_COLOR["B"]
    return GRADE_COLOR["C"]


# ════════════════════════════════════════════
# Notifier 클래스
# ════════════════════════════════════════════
class Notifier:
    """Discord 웹훅 알림 발송."""

    def __init__(self):
        self.url = DISCORD_WEBHOOK_URL

    def _send(
        self,
        content: str = "",
        embeds: list[dict] | None = None,
        *,
        event_type: str = "generic",
        ref_date: str | None = None,
    ) -> None:
        if not self.url:
            logger.debug("Discord webhook is not configured")
            save_notification_event(
                event_type,
                {"content": content[:2000], "embeds": embeds or []},
                status="disabled",
                ref_date=ref_date,
            )
            return

        payload = {}
        if content:
            payload["content"] = content[:2000]
        if embeds:
            payload["embeds"] = embeds[:10]

        try:
            response = requests.post(self.url, json=payload, timeout=10)
            status = "sent" if response.status_code in (200, 204) else "failed"
            if status == "failed":
                logger.warning("Discord webhook failed: %s %s", response.status_code, response.text[:200])
            save_notification_event(
                event_type, payload,
                status=status, ref_date=ref_date,
                response_code=response.status_code,
            )
        except Exception as exc:
            logger.warning("Discord webhook error: %s", exc)
            save_notification_event(
                event_type, {**payload, "error": str(exc)},
                status="error", ref_date=ref_date,
            )

    # ─────────────────────────────────────
    # 최근 성과 스냅샷
    # ─────────────────────────────────────
    def _recent_screen_snapshot(self, sessions: int = NOTIFIER_RECENT_SESSIONS) -> str:
        if not TRACKING_PATH.exists():
            return ""
        try:
            payload = json.loads(TRACKING_PATH.read_text(encoding="utf-8"))
            records = payload.get("records", [])
        except Exception:
            return ""

        d1_rows = [row for row in records if row.get("track_day") == 1 and row.get("rec_date")]
        if not d1_rows:
            return ""

        unique_dates = sorted({row["rec_date"] for row in d1_rows}, reverse=True)[:sessions]
        rows = [row for row in d1_rows if row["rec_date"] in set(unique_dates)]
        if not rows:
            return ""

        wins = sum(1 for row in rows if row.get("win"))
        win_rate = (wins / len(rows)) * 100 if rows else 0
        avg_return = sum(float(row.get("return_pct", 0) or 0) for row in rows) / len(rows)
        return (
            f"최근 {len(unique_dates)}일 실적: "
            f"{wins}/{len(rows)}승 ({win_rate:.1f}%) | 평균수익 {_pct(avg_return, 2)}"
        )

    # ═══════════════════════════════════════
    # 일일 매수 추천 (15:00 웹훅)
    # ═══════════════════════════════════════
    def _daily_pick_summary_embed(self, picks: list[dict]) -> dict:
        grade_counts = Counter(p.get("conviction", "C") for p in picks)
        top = picks[0]
        recent = self._recent_screen_snapshot()

        # 상단 — 1순위 액션 라벨
        top_action = top.get("action", {})
        action_line = f"{top_action.get('label', '관심')} — {top_action.get('detail', '')}"

        # 시장 지수 한줄 (코스피/코스닥/나스닥)
        ms = top.get("market_snapshot", {})
        market_parts = []
        if ms.get("kospi"):
            market_parts.append(f"코스피 {ms['kospi']:,.0f} ({_pct(ms.get('kospi_change'))})")
        if ms.get("kosdaq"):
            market_parts.append(f"코스닥 {ms['kosdaq']:,.0f} ({_pct(ms.get('kosdaq_change'))})")
        nasdaq_chg = ms.get("nasdaq_change", 0)
        if nasdaq_chg:
            market_parts.append(f"나스닥(전일) {_pct(nasdaq_chg)}")
        market_line = "📈 " + " | ".join(market_parts) if market_parts else ""

        lines = [
            action_line,
            "",
        ]
        if market_line:
            lines.append(market_line)
        # 장세 프리셋 표시
        regime = top.get("market_regime", "")
        regime_display = {"rising": "🟢 공격장", "mixed": "🟡 중립장", "weak": "🔴 방어장", "chaotic": "🌪️ 혼란장"}.get(regime, "")
        if regime_display:
            lines.append(f"🌡 장세: {regime_display}")
        macro_note = _safe(top.get("macro_risk_note"), "")
        if macro_note and macro_note != "-":
            lines.append(f"⚠️ 거시 경고: {macro_note}")
        event_warning = _safe(top.get("event_warning"), "")
        if event_warning and event_warning != "-":
            lines.append(f"📅 이벤트: {event_warning}")
        lines += [
            f"후보 {len(picks)}개 | "
            f"A {grade_counts.get('A', 0)}건 / B {grade_counts.get('B', 0)}건 / C {grade_counts.get('C', 0)}건",
            f"1순위 {top.get('name', '-')} | 등급 {top.get('conviction', 'C')} | D+{top.get('days_elapsed', '-')}일째 추적",
        ]
        if recent:
            lines.append(f"📊 {recent}")

        # 공통 리스크
        common_risks = Counter(
            flag for pick in picks
            for flag in pick.get("risk_flags", [])
            if str(flag).strip()
            and str(flag).strip() not in {"수급양호"}
        )
        risk_text = ", ".join(f"{n}" for n, _ in common_risks.most_common(3)) if common_risks else "없음"

        # 시장 핫 테마 (있으면)
        market_themes = _safe(picks[0].get("market_themes") if picks else "", "")

        fields = [
            _field("등급 분포", f"A {grade_counts.get('A', 0)} / B {grade_counts.get('B', 0)} / C {grade_counts.get('C', 0)}", True),
            _field("주의사항", risk_text, True),
        ]
        if market_themes and market_themes != "-":
            fields.append(_field("🔥 오늘의 테마", market_themes, False))

        return {
            "title": f"🎯 클로징벨 매수 추천 ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
            "description": "\n".join(lines),
            "color": _pick_color(picks),
            "fields": fields,
            "timestamp": _utc_now_iso(),
        }

    def _daily_pick_embed(self, order: int, pick: dict) -> dict:
        name = _safe(pick.get("name", pick.get("code")))
        code = _safe(pick.get("code"), "")
        conv = _safe(pick.get("conviction"), "C")
        days = pick.get("days_elapsed", 0)
        sweet = pick.get("sweet_spot_day", "-")

        # ★ 한줄 액션 (가장 중요한 정보)
        action = pick.get("action", {})
        action_line = f"{action.get('label', '관심')} {action.get('detail', '')}"

        # 시그널 한국어
        signal_kr = _signal_kr(pick.get("signal_type", ""))

        # 기업 정보 (업종 + 제품 + 대주주)
        company_parts = []
        sector = _safe(pick.get("sector"), "")
        industry = _safe(pick.get("industry"), "")
        main_products = _safe(pick.get("main_products"), "")
        holder_tag = _safe(pick.get("holder_tag"), "")
        if sector and sector != "-":
            company_parts.append(f"🏭 {sector}")
        if industry and industry != "-" and industry != sector:
            company_parts.append(f"· {industry}")

        desc_lines = [
            action_line,
            "",
            f"📍 {signal_kr}",
        ]
        if company_parts:
            desc_lines.append(" ".join(company_parts))
        if main_products and main_products != "-":
            desc_lines.append(f"🔧 주요 제품: {_clip(main_products, 60)}")
        if holder_tag and holder_tag != "-":
            desc_lines.append(f"👤 {holder_tag}")

        # 📰 핵심 뉴스 한줄 (항상 표시)
        news_highlight = _safe(pick.get("news_highlight"), "")
        if news_highlight and news_highlight != "-":
            desc_lines.append(f"📰 {news_highlight}")
        else:
            desc_lines.append("📰 관련 뉴스 없음")

        # 📅 캘린더 이벤트 (있으면 상단에)
        event_warning = _safe(pick.get("event_warning"), "")
        if event_warning and event_warning != "-":
            desc_lines.append(f"📅 {event_warning}")

        # 📊 수급 한줄 (공매도·대차·투자자 등)
        supply_line = _safe(pick.get("supply_line"), "")
        if supply_line and supply_line != "-":
            desc_lines.append(f"💹 {supply_line}")

        # 🔥 테마 강도 (종목이 속한 테마)
        theme_line = _safe(pick.get("theme_line"), "")
        if theme_line and theme_line != "-":
            desc_lines.append(theme_line)

        # 🌍 외신 (있으면)
        foreign_note = _safe(pick.get("foreign_news_note"), "")
        if foreign_note and foreign_note != "-":
            desc_lines.append(f"🌍 {foreign_note}")

        # 📺 유튜브 (있으면)
        youtube_note = _safe(pick.get("youtube_note"), "")
        if youtube_note and youtube_note != "-":
            desc_lines.append(youtube_note)

        # 가격 + 추적
        price_lines = [
            f"현재가 {_won(pick.get('current_price'))}",
            f"스크리닝 이후 {_pct(pick.get('price_change_from_screen'))}",
        ]

        # 판단 (ABC만 표시, 점수 비노출)
        timing_text = f"D+{days}일째" + (f" (최적 D+{sweet})" if days != sweet else " 최적 타이밍")
        judge_lines = [
            f"등급 {GRADE_EMOJI.get(conv, '🥉')} {conv} ({GRADE_LABEL.get(conv, conv)})",
            f"추적 {timing_text}",
        ]

        # 리스크 (간결하게)
        risk_parts = []
        dart_risk = _safe(pick.get("dart_risk"), "확인불가")
        dart_note = _safe(pick.get("dart_note"), "")
        news_risk = _safe(pick.get("news_risk"), "확인불가")
        news_summary = _clip(pick.get("news_summary", "") or "", 100)

        risk_parts.append(
            f"공시 {RISK_ICON.get(dart_risk, '⚪')} {dart_risk}"
            + (f" ({dart_note})" if dart_note and dart_note != "-" else "")
        )
        risk_parts.append(
            f"뉴스 {RISK_ICON.get(news_risk, '⚪')} {news_risk}"
            + (f" ({news_summary})" if news_summary and news_summary != "-" else "")
        )

        # 리스크 플래그 번역
        FLAG_KR = {
            "D+1이른진입": "⏳ 아직 이르다",
            "과열": "🔥 과열 상태",
            "급락": "📉 급락 주의",
            "DART위험": "",
            "DART주의": "",
            "뉴스위험": "",
            "뉴스주의": "📰 뉴스 주의",
            "약세장": "📉 시장 약세",
            "상승장보수": "📈 상승장 보수 접근",
            "이벤트주의": "📅 이벤트 주의",
            "대주주투매": "⚠️ 대주주 매도",
            "저지분소형주": "소형주 (저지분)",
            "정치위기TOP1만": "🏛️ 정치 위기 모드",
            "수급위험": "💹 수급 위험",
            "수급주의": "💹 수급 악화",
            "수급양호": "✅ 수급 양호",
            "외신경고": "🌍 거시 경고",
            "테마과열": "📺 테마 과열",
        }
        risk_flags = pick.get("risk_flags", [])
        if risk_flags:
            readable = [FLAG_KR.get(f, f) for f in risk_flags if FLAG_KR.get(f, f)]
            if readable:
                risk_parts.append("⚠️ " + " | ".join(readable))

        # 참고 메모 (패턴 + 시장)
        memo_parts = []
        rank_note = pick.get("rank_note", "")
        if rank_note:
            memo_parts.append(RANK_NOTE_KR.get(rank_note, rank_note))
        regime = pick.get("market_regime", "")
        if regime and regime != "-":
            memo_parts.append(f"시장: {_regime_kr(regime)}")

        color = ACTION_COLOR.get(action.get("color", "yellow"), GRADE_COLOR.get(conv, GRADE_COLOR["C"]))

        embed = {
            "title": f"#{order} [{conv}] {name} ({code})",
            "description": "\n".join(desc_lines),
            "color": color,
            "fields": [
                _field("💰 가격", "\n".join(price_lines), True),
                _field("📊 판단", "\n".join(judge_lines), True),
                _field("🛡️ 리스크", "\n".join(risk_parts), False),
            ],
            "timestamp": _utc_now_iso(),
        }
        if memo_parts:
            embed["fields"].append(_field("💡 참고", "\n".join(memo_parts), False))

        return embed

    # ═══════════════════════════════════════
    # 장마감 스크리닝 (15:40 웹훅)
    # ═══════════════════════════════════════
    def _screen_summary_embed(self, result: dict) -> dict:
        market = result.get("market", {})
        themes = result.get("theme_summary", [])[:3]
        prev_returns = result.get("prev_returns", [])[:3]

        market_lines = [
            f"코스피 {_safe(market.get('kospi'))} ({_pct(market.get('kospi_change'))})",
            f"나스닥 {_pct(market.get('nasdaq_change'))}",
        ]
        if market.get("nasdaq_warning"):
            market_lines.append("⚠️ 미국 약세 경고")

        theme_text = "\n".join(
            f"{item.get('name', '-')} {_pct(item.get('change_rate'))}" for item in themes
        ) or "-"

        prev_text = "\n".join(
            f"{item.get('name', '-')} {_pct(item.get('return_pct'))}" for item in prev_returns
        ) or "-"

        return {
            "title": f"📋 클로징벨 스크리닝 ({result.get('date', '-')})",
            "description": (
                f"유니버스 {result.get('universe_count', 0)}종목 | "
                f"관심 {len(result.get('top', []))}종목"
            ),
            "color": WARNING_COLOR if market.get("nasdaq_warning") else SUMMARY_COLOR,
            "fields": [
                _field("📈 시장", "\n".join(market_lines), True),
                _field("🔥 테마", theme_text, True),
                _field("📊 전일 추천 결과", prev_text, False),
            ],
            "timestamp": _utc_now_iso(),
        }

    def _screen_stock_embed(self, order: int, stock: dict) -> dict:
        action = _safe(stock.get("ai_action"), "관망")
        action_icon = ACTION_ICON.get(action, "🟡")
        risk = _safe(stock.get("ai_risk"), "보통")

        company_parts = []
        sector = _safe(stock.get("sector"), "")
        industry = _safe(stock.get("industry"), "")
        holder_tag = _safe(stock.get("holder_tag"), "")
        if sector and sector != "-":
            company_parts.append(f"🏭 {sector}")
        if industry and industry != "-" and industry != sector:
            company_parts.append(f"· {industry}")
        if holder_tag and holder_tag != "-":
            company_parts.append(f"👤 {holder_tag}")

        desc_lines = [
            f"{action_icon} {action} | 리스크 {RISK_ICON.get(risk, '⚪')} {risk}",
            f"점수 {_score(stock.get('score'))} | 거래 신호 {_safe(stock.get('vp_tag'), '-')}",
        ]
        if company_parts:
            desc_lines.append(" ".join(company_parts))

        broker_bits = [stock.get("broker_signal", ""), stock.get("broker_top_buy", "")]
        broker_text = " | ".join(bit for bit in broker_bits if str(bit).strip()) or "-"

        return {
            "title": f"#{order} {stock.get('name', '-')} ({stock.get('code', '-')})",
            "description": "\n".join(desc_lines),
            "color": WARNING_COLOR if stock.get("overheat") else SUMMARY_COLOR,
            "fields": [
                _field(
                    "💰 가격",
                    "\n".join([
                        f"현재가 {_won(stock.get('price'))}",
                        f"등락률 {_pct(stock.get('change_rate'))}",
                        f"거래량 x{_safe(stock.get('vol_ratio'), '-')}",
                    ]),
                    True,
                ),
                _field("수급", broker_text, True),
                _field(
                    "📊 지표",
                    f"CCI {_safe(stock.get('cci'))} | RSI {_safe(stock.get('rsi'))} | MA20 {_pct(stock.get('ma20_gap'))}",
                    False,
                ),
                _field(
                    "🛡️ 공시/뉴스",
                    "\n".join([
                        f"공시 {RISK_ICON.get(_safe(stock.get('dart_risk')), '⚪')} {_safe(stock.get('dart_risk'), '확인불가')}"
                        + (f" ({_clip(stock.get('dart_note', ''), 80)})" if stock.get("dart_note") else ""),
                        _clip(stock.get("ai_summary", "") or "", 150),
                    ]),
                    False,
                ),
            ],
            "timestamp": _utc_now_iso(),
        }

    # ═══════════════════════════════════════
    # 공개 메서드
    # ═══════════════════════════════════════
    def send_recommendation(self, result: dict) -> None:
        """v3 15:40 스크리닝 웹훅 (v4에서는 main.py에서 호출 안 함. 필요시 재활용 가능)"""
        if result.get("skipped"):
            reason = _safe(result.get("reason"), "사유 없음")
            embed = {
                "title": f"📋 클로징벨 스크리닝 건너뜀 ({result.get('date', '-')})",
                "description": f"사유: {reason}",
                "color": WARNING_COLOR,
                "timestamp": _utc_now_iso(),
            }
            self._send(embeds=[embed], event_type="screen_skip", ref_date=result.get("date"))
            return

        top = result.get("top", [])
        embeds = [self._screen_summary_embed(result)]
        event_warning = result.get("market", {}).get("event_warning", "")
        if event_warning:
            embeds.append({
                "title": "📅 오늘의 시장 이벤트",
                "description": event_warning,
                "color": WARNING_COLOR,
                "timestamp": _utc_now_iso(),
            })
        embeds.extend(
            self._screen_stock_embed(idx, stock)
            for idx, stock in enumerate(top[:DISCORD_SCREEN_TOP_N], start=1)
        )
        self._send(embeds=embeds, event_type="screen_recommendation", ref_date=result.get("date"))

    def send_daily_picks(self, picks: list[dict], pick_date: str | None = None) -> None:
        if not picks:
            embed = {
                "title": f"🎯 클로징벨 매수 추천 ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
                "description": "오늘은 매수 조건을 만족한 종목이 없습니다.\n관망하는 것도 전략입니다.",
                "color": NEUTRAL_COLOR,
                "timestamp": _utc_now_iso(),
            }
            self._send(embeds=[embed], event_type="daily_picks", ref_date=pick_date)
            return

        embeds = [self._daily_pick_summary_embed(picks)]
        embeds.extend(
            self._daily_pick_embed(idx, pick)
            for idx, pick in enumerate(picks[:DISCORD_PICK_TOP_N], start=1)
        )
        self._send(embeds=embeds, event_type="daily_picks", ref_date=pick_date)

    def send_shutdown(self, message: str = "") -> None:
        now = datetime.now().strftime("%H:%M")
        content = f"클로징벨 종료 ({now})"
        if message:
            content = f"{content} | {message}"
        self._send(content=content, event_type="shutdown")

    def send_pullback_signals(self, signals: list[dict]) -> None:
        if not signals:
            return

        title = f"🔔 클로징벨 눌림목 신호 ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
        summary = {
            "title": title,
            "description": (
                f"신호 {len(signals)}개 감지 | "
                f"A {sum(1 for s in signals if s.get('conviction') == 'A')}건 / "
                f"B {sum(1 for s in signals if s.get('conviction') == 'B')}건 / "
                f"C {sum(1 for s in signals if s.get('conviction') == 'C')}건"
            ),
            "color": _pick_color(signals),
            "timestamp": _utc_now_iso(),
        }
        embeds = [summary]
        embeds.extend(
            self._daily_pick_embed(idx, signal)
            for idx, signal in enumerate(signals[:DISCORD_PICK_TOP_N], start=1)
        )
        self._send(embeds=embeds, event_type="pullback_signals", ref_date=datetime.now().strftime("%Y-%m-%d"))

    def send_error(self, error_msg: str) -> None:
        embed = {
            "title": "⚠️ 클로징벨 오류",
            "description": _clip(error_msg, 1500),
            "color": ERROR_COLOR,
            "timestamp": _utc_now_iso(),
        }
        self._send(embeds=[embed], event_type="error")
