"""
Discord notifications for ClosingBell.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

from config import DASHBOARD_URL, DISCORD_WEBHOOK_URL
from storage import save_notification_event

logger = logging.getLogger("closingbell")
TRACKING_PATH = Path(__file__).parent / "data" / "performance" / "tracking.json"

ACTION_LABEL = {
    "매수관심": "매수관심",
    "관망": "관망",
    "주의": "주의",
}
ACTION_ICON = {
    "매수관심": "🟢",
    "관망": "🟡",
    "주의": "🔴",
}
RISK_ICON = {
    "정상": "🟢",
    "양호": "🟢",
    "보통": "🟡",
    "주의": "🟠",
    "위험": "🔴",
    "확인불가": "⚪",
}
GRADE_COLOR = {
    "A": 0x0F9D58,
    "B": 0x1A73E8,
    "C": 0x7F8C8D,
}
SUMMARY_COLOR = 0x143A52
WARNING_COLOR = 0xE67E22
ERROR_COLOR = 0xC0392B
NEUTRAL_COLOR = 0x7F8C8D


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_text(value, fallback: str = "-") -> str:
    text = str(value).strip() if value is not None else ""
    return text if text else fallback


def _clip(text: str, limit: int = 300) -> str:
    text = _safe_text(text, "")
    if len(text) <= limit:
        return text or "-"
    return f"{text[: limit - 1].rstrip()}…"


def _fmt_won(value) -> str:
    try:
        return f"{int(round(float(value))):,}원"
    except Exception:
        return "-"


def _fmt_score(value) -> str:
    try:
        num = float(value)
        return f"{num:.1f}" if num % 1 else f"{int(num)}"
    except Exception:
        return "-"


def _fmt_pct(value, digits: int = 1) -> str:
    try:
        return f"{float(value):+.{digits}f}%"
    except Exception:
        return "-"


def _fmt_wr(value) -> str:
    try:
        return f"{float(value):.0f}%"
    except Exception:
        return "-"


def _risk_line(label: str, level: str, detail: str = "") -> str:
    icon = RISK_ICON.get(level, "⚪")
    if detail:
        return f"{label}: {icon} {level} ({_clip(detail, 80)})"
    return f"{label}: {icon} {level}"


def _pick_color(picks: list[dict]) -> int:
    if any(p.get("conviction") == "A" for p in picks):
        return GRADE_COLOR["A"]
    if any(p.get("conviction") == "B" for p in picks):
        return GRADE_COLOR["B"]
    return GRADE_COLOR["C"]


def _field(name: str, value: str, inline: bool = False) -> dict:
    return {"name": name, "value": _clip(value, 1000), "inline": inline}


class Notifier:
    """Send Discord webhook notifications."""

    def __init__(self):
        self.url = DISCORD_WEBHOOK_URL
        self.dashboard_url = DASHBOARD_URL

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
            if response.status_code not in (200, 204):
                logger.warning("Discord webhook failed: %s %s", response.status_code, response.text[:200])
                save_notification_event(
                    event_type,
                    payload,
                    status="failed",
                    ref_date=ref_date,
                    response_code=response.status_code,
                )
            else:
                save_notification_event(
                    event_type,
                    payload,
                    status="sent",
                    ref_date=ref_date,
                    response_code=response.status_code,
                )
        except Exception as exc:
            logger.warning("Discord webhook error: %s", exc)
            save_notification_event(
                event_type,
                {**payload, "error": str(exc)},
                status="error",
                ref_date=ref_date,
            )

    def _recent_screen_snapshot(self, sessions: int = 20) -> str:
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
        date_set = set(unique_dates)
        rows = [row for row in d1_rows if row["rec_date"] in date_set]
        if not rows:
            return ""

        wins = sum(1 for row in rows if row.get("win"))
        win_rate = (wins / len(rows)) * 100 if rows else 0
        avg_return = sum(float(row.get("return_pct", 0) or 0) for row in rows) / len(rows)
        return (
            f"최근 {len(unique_dates)}거래일 스크리닝 D+1: "
            f"{wins}/{len(rows)}승 ({win_rate:.1f}%) | 평균 {_fmt_pct(avg_return, 2)}"
        )

    def _common_risks(self, picks: list[dict]) -> str:
        counter = Counter(
            flag
            for pick in picks
            for flag in pick.get("risk_flags", [])
            if str(flag).strip()
        )
        if not counter:
            return "없음"
        return ", ".join(f"{name} x{count}" for name, count in counter.most_common(3))

    def _daily_pick_summary_embed(self, picks: list[dict]) -> dict:
        grade_counts = Counter(p.get("conviction", "C") for p in picks)
        avg_score = sum(float(p.get("conviction_score", 0) or 0) for p in picks) / max(len(picks), 1)
        top = picks[0]
        recent = self._recent_screen_snapshot()

        lines = [
            f"매수 후보 `{len(picks)}개` | A `{grade_counts['A']}` / B `{grade_counts['B']}` / C `{grade_counts['C']}`",
            f"상단 후보 `{top.get('name', '-')}` | 확신점수 `{_fmt_score(top.get('conviction_score'))}` | 감시 D+{top.get('days_elapsed', '-')}",
            f"공통 리스크 `{self._common_risks(picks)}`",
            f"[Dashboard]({self.dashboard_url})",
        ]
        if recent:
            lines.insert(3, recent)

        return {
            "title": f"ClosingBell | 일일 매수 추천 ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
            "description": "\n".join(lines),
            "color": _pick_color(picks),
            "fields": [
                _field("평균 확신점수", _fmt_score(avg_score), True),
                _field("최상단 신호", _safe_text(top.get("signal_type"), "조건 재확인"), True),
                _field("권장 메모", "A등급 우선, C등급은 관망 보조로 해석", False),
            ],
            "timestamp": _utc_now_iso(),
        }

    def _daily_pick_embed(self, order: int, pick: dict) -> dict:
        name = _safe_text(pick.get("name", pick.get("code")))
        code = _safe_text(pick.get("code"), "")
        conviction = _safe_text(pick.get("conviction"), "C")
        signal_type = _safe_text(pick.get("signal_type"), "조건 재확인")
        watchlist_date = _safe_text(pick.get("watchlist_date"), "-")
        sweet_spot = pick.get("sweet_spot_day", "-")
        in_window = "예" if pick.get("in_window") else "아니오"
        risk_flags = ", ".join(pick.get("risk_flags", [])) or "없음"
        news_summary = _clip(pick.get("news_summary", "") or "", 120)
        note_parts = [
            _safe_text(pick.get("rank_note"), ""),
            news_summary if news_summary != "-" else "",
        ]
        note = "\n".join(part for part in note_parts if part) or "-"

        embed = {
            "title": f"#{order} [{conviction}] {name} ({code})",
            "description": (
                f"{signal_type}\n"
                f"스크리닝 #{pick.get('rank', '-')} | 감시 D+{pick.get('days_elapsed', '-')} | sweet spot D+{sweet_spot}"
            ),
            "color": GRADE_COLOR.get(conviction, GRADE_COLOR["C"]),
            "fields": [
                _field(
                    "Entry",
                    "\n".join(
                        [
                            f"현재가 {_fmt_won(pick.get('current_price'))}",
                            f"스크리닝 대비 {_fmt_pct(pick.get('price_change_from_screen'))}",
                            f"감시 시작 {watchlist_date}",
                        ]
                    ),
                    True,
                ),
                _field(
                    "Edge",
                    "\n".join(
                        [
                            f"확신점수 {_fmt_score(pick.get('conviction_score'))}",
                            f"예상 승률 {_fmt_wr(pick.get('expected_wr'))}",
                            f"예상 수익 {_fmt_pct(pick.get('expected_ret'))}",
                            f"윈도우 진입 {in_window}",
                        ]
                    ),
                    True,
                ),
                _field(
                    "Risk",
                    "\n".join(
                        [
                            _risk_line("DART", _safe_text(pick.get("dart_risk"), "확인불가"), pick.get("dart_note", "")),
                            _risk_line("뉴스", _safe_text(pick.get("news_risk"), "확인불가"), pick.get("news_summary", "")),
                            f"리스크 플래그: {risk_flags}",
                        ]
                    ),
                    False,
                ),
                _field("Note", note, False),
            ],
            "footer": {"text": f"Dashboard: {self.dashboard_url}"},
            "timestamp": _utc_now_iso(),
        }
        return embed

    def _screen_summary_embed(self, result: dict) -> dict:
        market = result.get("market", {})
        themes = result.get("theme_summary", [])[:3]
        prev_returns = result.get("prev_returns", [])[:3]

        market_text = "\n".join(
            [
                f"코스피 {_fmt_score(market.get('kospi'))} ({_fmt_pct(market.get('kospi_change'))})",
                f"나스닥 {_fmt_pct(market.get('nasdaq_change'))}",
                "미국 약세 경고" if market.get("nasdaq_warning") else "미국 약세 경고 없음",
            ]
        )
        theme_text = "\n".join(
            f"{item.get('name', '-')} {_fmt_pct(item.get('change_rate'))}" for item in themes
        ) or "-"
        prev_text = "\n".join(
            f"{item.get('name', '-')} {_fmt_pct(item.get('return_pct'))}" for item in prev_returns
        ) or "-"

        return {
            "title": f"ClosingBell | 장마감 스크리닝 ({result.get('date', '-')})",
            "description": (
                f"유니버스 `{result.get('universe_count', 0)}개` | "
                f"관심종목 `{len(result.get('top', []))}개`\n"
                f"[Dashboard]({self.dashboard_url})"
            ),
            "color": WARNING_COLOR if market.get("nasdaq_warning") else SUMMARY_COLOR,
            "fields": [
                _field("Market", market_text, True),
                _field("Leading Themes", theme_text, True),
                _field("전일 추천 추적", prev_text, False),
            ],
            "timestamp": _utc_now_iso(),
        }

    def _screen_stock_embed(self, order: int, stock: dict) -> dict:
        action = _safe_text(stock.get("ai_action"), "관망")
        action_icon = ACTION_ICON.get(action, "🟡")
        risk = _safe_text(stock.get("ai_risk"), "보통")

        broker_bits = [stock.get("broker_signal", ""), stock.get("broker_top_buy", "")]
        broker_text = " | ".join(bit for bit in broker_bits if str(bit).strip()) or "-"
        indicators = [
            f"CCI {_fmt_score(stock.get('cci'))}",
            f"RSI {_fmt_score(stock.get('rsi'))}",
            f"MA20 괴리 {_fmt_pct(stock.get('ma20_gap'))}",
        ]

        return {
            "title": f"#{order} {stock.get('name', '-')} ({stock.get('code', '-')})",
            "description": (
                f"{action_icon} {ACTION_LABEL.get(action, action)} | "
                f"AI risk {RISK_ICON.get(risk, '⚪')} {risk}\n"
                f"점수 {_fmt_score(stock.get('score'))} | 거래대금 신호 {_safe_text(stock.get('vp_tag'), '-')}"
            ),
            "color": WARNING_COLOR if stock.get("overheat") else SUMMARY_COLOR,
            "fields": [
                _field(
                    "Price",
                    "\n".join(
                        [
                            f"현재가 {_fmt_won(stock.get('price'))}",
                            f"등락률 {_fmt_pct(stock.get('change_rate'))}",
                            f"거래량 배수 {_fmt_score(stock.get('vol_ratio'))}",
                        ]
                    ),
                    True,
                ),
                _field("Flow", broker_text, True),
                _field(
                    "Signals",
                    "\n".join(indicators),
                    True,
                ),
                _field(
                    "DART / AI",
                    "\n".join(
                        [
                            _risk_line("DART", _safe_text(stock.get("dart_risk"), "확인불가"), stock.get("dart_note", "")),
                            _clip(stock.get("ai_summary", "") or "", 180),
                        ]
                    ),
                    False,
                ),
            ],
            "footer": {"text": f"Dashboard: {self.dashboard_url}"},
            "timestamp": _utc_now_iso(),
        }

    def send_recommendation(self, result: dict) -> None:
        if result.get("skipped"):
            reason = _safe_text(result.get("reason"), "사유 없음")
            embed = {
                "title": f"ClosingBell | 장마감 스크리닝 스킵 ({result.get('date', '-')})",
                "description": f"사유: {reason}\n[Dashboard]({self.dashboard_url})",
                "color": WARNING_COLOR,
                "timestamp": _utc_now_iso(),
            }
            self._send(embeds=[embed], event_type="screen_skip", ref_date=result.get("date"))
            return

        top = result.get("top", [])
        embeds = [self._screen_summary_embed(result)]
        embeds.extend(self._screen_stock_embed(idx, stock) for idx, stock in enumerate(top[:5], start=1))
        self._send(embeds=embeds, event_type="screen_recommendation", ref_date=result.get("date"))

    def send_daily_picks(self, picks: list[dict], pick_date: str | None = None) -> None:
        if not picks:
            embed = {
                "title": f"ClosingBell | 일일 매수 추천 ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
                "description": (
                    "오늘은 활성 워치리스트에서 매수 조건을 만족한 종목이 없습니다.\n"
                    f"[Dashboard]({self.dashboard_url})"
                ),
                "color": NEUTRAL_COLOR,
                "timestamp": _utc_now_iso(),
            }
            self._send(embeds=[embed], event_type="daily_picks", ref_date=pick_date)
            return

        embeds = [self._daily_pick_summary_embed(picks)]
        embeds.extend(self._daily_pick_embed(idx, pick) for idx, pick in enumerate(picks[:5], start=1))
        self._send(embeds=embeds, event_type="daily_picks", ref_date=pick_date)

    def send_shutdown(self, message: str = "") -> None:
        now = datetime.now().strftime("%H:%M")
        content = f"ClosingBell 종료 ({now})"
        if message:
            content = f"{content} | {message}"
        self._send(content=content, event_type="shutdown")

    def send_pullback_signals(self, signals: list[dict]) -> None:
        if not signals:
            return

        title = f"ClosingBell | 눌림목 진입 신호 ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
        summary = {
            "title": title,
            "description": (
                f"신호 `{len(signals)}개` 감지 | "
                f"A `{sum(1 for s in signals if s.get('conviction') == 'A')}` / "
                f"B `{sum(1 for s in signals if s.get('conviction') == 'B')}` / "
                f"C `{sum(1 for s in signals if s.get('conviction') == 'C')}`\n"
                f"[Dashboard]({self.dashboard_url})"
            ),
            "color": _pick_color(signals),
            "timestamp": _utc_now_iso(),
        }
        embeds = [summary]
        embeds.extend(self._daily_pick_embed(idx, signal) for idx, signal in enumerate(signals[:5], start=1))
        self._send(embeds=embeds, event_type="pullback_signals", ref_date=datetime.now().strftime("%Y-%m-%d"))

    def send_error(self, error_msg: str) -> None:
        embed = {
            "title": "ClosingBell | Error",
            "description": _clip(error_msg, 1500),
            "color": ERROR_COLOR,
            "timestamp": _utc_now_iso(),
        }
        self._send(embeds=[embed], event_type="error")
