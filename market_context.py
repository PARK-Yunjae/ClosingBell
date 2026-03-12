"""
ClosingBell v3.6 — 시장 컨텍스트 (캘린더 + 지분 변동 + 기업 정보)
================================================================
screener, watchlist_monitor, notifier에서 공통으로 사용하는
시장 이벤트/대주주 변동/기업 설명 데이터를 제공.

사용법:
    from market_context import MarketContext
    ctx = MarketContext()
    ctx.get_events("2025-03-13")      # → [{"type":"quad_witching", ...}]
    ctx.get_holder_change("090710")    # → -7.8
    ctx.get_company_brief("005930")    # → "반도체 | 전자부품, 컴퓨터, 영상, 음향 및 통신장비 제조업"
    ctx.should_skip_screening()        # → True (정치위기 등)
    ctx.get_score_adjustment()         # → -3 (FOMC)
"""
import json
import logging
from datetime import datetime, timedelta
from functools import lru_cache

import pandas as pd

from config import (
    FOMC_PENALTY,
    HOLDER_DUMP_THRESHOLD,
    HOLDER_LOW_PENALTY,
    HOLDER_LOW_PRICE_MAX,
    HOLDER_LOW_THRESH,
    MAJOR_HOLDER_CSV,
    MARKET_CALENDAR_PATH,
    MAPPING_CSV,
    POLITICAL_CRISIS_MODE,
)

logger = logging.getLogger("closingbell")

CALENDAR_PATH = MARKET_CALENDAR_PATH
HOLDER_CSV = MAJOR_HOLDER_CSV

# ══════════════════════════════════════════════════════════════
# 시장 이벤트 캘린더
# ══════════════════════════════════════════════════════════════
# JSON 파일이 없을 때 사용하는 기본 이벤트 (날짜가 고정인 것만)
# 실제 운영에서는 data/reference/market_calendar.json을 사용
DEFAULT_EVENTS = [
    # 2025 FOMC
    {"date": "2025-03-19", "type": "fomc", "name": "FOMC", "impact": "high"},
    {"date": "2025-05-07", "type": "fomc", "name": "FOMC", "impact": "high"},
    {"date": "2025-06-18", "type": "fomc", "name": "FOMC(점도표)", "impact": "high"},
    {"date": "2025-07-30", "type": "fomc", "name": "FOMC", "impact": "high"},
    {"date": "2025-09-17", "type": "fomc", "name": "FOMC(점도표)", "impact": "high"},
    {"date": "2025-10-29", "type": "fomc", "name": "FOMC", "impact": "high"},
    {"date": "2025-12-10", "type": "fomc", "name": "FOMC(점도표)", "impact": "high"},
    # 2026 FOMC
    {"date": "2026-01-28", "type": "fomc", "name": "FOMC", "impact": "high"},
    {"date": "2026-03-18", "type": "fomc", "name": "FOMC(점도표)", "impact": "high"},
    {"date": "2026-05-06", "type": "fomc", "name": "FOMC", "impact": "high"},
    {"date": "2026-06-17", "type": "fomc", "name": "FOMC(점도표)", "impact": "high"},
    # 감사보고서 마감
    {"date": "2025-03-31", "type": "audit", "name": "사업보고서 마감", "impact": "high"},
    {"date": "2026-03-31", "type": "audit", "name": "사업보고서 마감", "impact": "high"},
    # 정치 (수동 추가 필요 — 예측 불가)
    {"date": "2025-06-03", "type": "political_election", "name": "지방선거", "impact": "high"},
]

def _political_crisis_adjustment() -> float:
    mode = str(POLITICAL_CRISIS_MODE).strip().lower()
    if mode in {"top1", "skip", "block"}:
        return -999.0
    if mode in {"off", "none", "0"}:
        return 0.0
    try:
        return float(mode)
    except ValueError:
        return -999.0


# 이벤트 유형별 점수 조정
EVENT_SCORE_ADJ = {
    "fomc": -float(FOMC_PENALTY),
    "political": _political_crisis_adjustment(),
    "political_critical": _political_crisis_adjustment(),   # 스크리닝 스킵 (보수모드)
    "political_election": -2.0,
    "earnings": -3.0,
    "earnings_deadline": -3.0,
    "audit": -1.0,
    "quad_witching": 0.0,         # 중립
    "options_expiry": 0.0,        # 오히려 좋지만 가산점은 아직 안 줌
    "bok": -1.0,
    "bok": -1.0,
    "msci": -1.0,
    "seasonal": 0.0,
    "seasonal_yearend": 0.0,
    "seasonal_newyear": 0.0,
    "geopolitical_tariff": -2.0,
}


class MarketContext:
    """시장 컨텍스트: 캘린더 + 지분 변동 + 기업 정보"""

    def __init__(self):
        self._events = self._load_events()
        self._event_map = self._build_event_map()
        self._holder_change = {}
        self._holder_level = {}
        self._company_info = {}
        self._load_holder()
        self._load_company_info()

    # ──────────────────────────────────────────
    # 캘린더 이벤트
    # ──────────────────────────────────────────
    def _load_events(self) -> list:
        if CALENDAR_PATH.exists():
            try:
                events = json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))
                logger.info("캘린더 로드: %d개 이벤트", len(events))
                return events
            except Exception:
                pass
        logger.info("캘린더 기본값 사용: %d개 이벤트", len(DEFAULT_EVENTS))
        return DEFAULT_EVENTS

    def _build_event_map(self, window: int = 1) -> dict:
        """날짜 → 이벤트 리스트 (±window일)"""
        m = {}
        for ev in self._events:
            try:
                center = datetime.strptime(ev["date"], "%Y-%m-%d").date()
            except (ValueError, KeyError):
                continue
            for delta in range(-window, window + 1):
                d = (center + timedelta(days=delta)).strftime("%Y-%m-%d")
                if d not in m:
                    m[d] = []
                m[d].append({**ev, "distance": delta})
        return m

    def get_events(self, date_str: str) -> list:
        """특정 날짜의 이벤트 목록"""
        return self._event_map.get(str(date_str)[:10], [])

    def get_event_types(self, date_str: str) -> set:
        """특정 날짜의 이벤트 유형 집합"""
        return {e["type"] for e in self.get_events(date_str)}

    def get_score_adjustment(self, date_str: str = None) -> float:
        """이벤트 기반 점수 조정값 (합산)"""
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")
        types = self.get_event_types(date_str)
        adj = 0.0
        for t in types:
            a = EVENT_SCORE_ADJ.get(t, 0.0)
            if a == -999:
                return -999  # 스킵 신호
            adj += a
        return adj

    def should_conservative(self, date_str: str = None) -> bool:
        """보수 모드 여부 (정치위기 등)"""
        return self.get_score_adjustment(date_str) == -999

    def get_event_warning(self, date_str: str = None) -> str:
        """웹훅/대시보드용 경고 문구"""
        events = self.get_events(date_str or datetime.now().strftime("%Y-%m-%d"))
        if not events:
            return ""
        names = [e["name"] for e in events if e.get("distance", 0) == 0]
        if not names:
            names = [f"{e['name']}(±1일)" for e in events[:2]]
        return " | ".join(names)

    # ──────────────────────────────────────────
    # 대주주 지분 변동
    # ──────────────────────────────────────────
    def _load_holder(self):
        if not HOLDER_CSV.exists():
            logger.debug("major_holder.csv 없음 — 지분 필터 비활성")
            return

        try:
            h = pd.read_csv(HOLDER_CSV, dtype={"code": str}, encoding="utf-8-sig")
            h["code"] = h["code"].str.zfill(6)
            h["total_pct"] = h["total_pct"].clip(upper=100)

            # 최신 지분율
            latest = h.sort_values("year", ascending=False).drop_duplicates("code", keep="first")
            self._holder_level = latest.set_index("code")["total_pct"].to_dict()

            # 변동율 (2개년 필요)
            years = sorted(h["year"].unique())
            if len(years) >= 2:
                old_yr, new_yr = years[-2], years[-1]
                h_old = h[h["year"] == old_yr].set_index("code")["total_pct"]
                h_new = h[h["year"] == new_yr].set_index("code")["total_pct"]
                both = pd.DataFrame({"old": h_old, "new": h_new}).dropna()
                both["chg"] = both["new"] - both["old"]
                self._holder_change = both["chg"].to_dict()

            logger.info("지분 데이터: %d종목 수준, %d종목 변동",
                        len(self._holder_level), len(self._holder_change))
        except Exception as e:
            logger.warning("지분 데이터 로드 실패: %s", e)

    def get_holder_change(self, code: str) -> float | None:
        """대주주 지분 변동(%p). None이면 데이터 없음."""
        return self._holder_change.get(code.strip().zfill(6))

    def get_holder_level(self, code: str) -> float | None:
        """현재 대주주 지분율(%). None이면 데이터 없음."""
        return self._holder_level.get(code.strip().zfill(6))

    def is_dumping(self, code: str, threshold: float | None = None) -> bool:
        """대주주 투매 종목인지 (기본: config 기준)"""
        chg = self.get_holder_change(code)
        if chg is None:
            return False
        if threshold is None:
            threshold = HOLDER_DUMP_THRESHOLD
        return chg <= threshold

    def holder_tag(self, code: str, price: float = 0) -> str:
        """웹훅/대시보드용 지분 태그"""
        chg = self.get_holder_change(code)
        lvl = self.get_holder_level(code)
        parts = []

        if chg is not None:
            if chg <= HOLDER_DUMP_THRESHOLD:
                parts.append(f"⚠️투매({chg:+.0f}%p)")
            elif chg <= -5:
                parts.append(f"지분감소({chg:+.0f}%p)")
            elif chg >= 3:
                parts.append(f"지분증가({chg:+.0f}%p)")

        if lvl is not None:
            if lvl < 20:
                parts.append(f"기관분산형({lvl:.0f}%)")
            elif lvl < HOLDER_LOW_THRESH and price > 0 and price <= HOLDER_LOW_PRICE_MAX:
                parts.append(f"잡주저지분({lvl:.0f}%)")

        return " ".join(parts)

    def stock_score_context(self, code: str, price: float = 0, date_str: str | None = None) -> dict:
        """Return reusable score adjustments and risk flags for one stock."""
        code = code.strip().zfill(6)
        date_str = date_str or datetime.now().strftime("%Y-%m-%d")
        event_adj = self.get_score_adjustment(date_str)
        conservative = event_adj == -999
        holder_penalty = 0.0
        flags: list[str] = []

        if self.is_dumping(code):
            flags.append("대주주투매")

        lvl = self.get_holder_level(code)
        if lvl is not None and 0 < price <= HOLDER_LOW_PRICE_MAX and lvl < HOLDER_LOW_THRESH:
            holder_penalty = -float(HOLDER_LOW_PENALTY)
            flags.append("저지분소형주")

        if conservative:
            flags.append("정치위기")
            effective_event_adj = 0.0
        else:
            effective_event_adj = float(event_adj)
            if effective_event_adj < 0 and self.get_event_types(date_str):
                flags.append("이벤트주의")

        return {
            "date": date_str,
            "skip": self.is_dumping(code),
            "conservative": conservative,
            "event_warning": self.get_event_warning(date_str),
            "event_adj": effective_event_adj,
            "holder_penalty": holder_penalty,
            "score_adj": effective_event_adj + holder_penalty,
            "holder_pct": lvl,
            "holder_change": self.get_holder_change(code),
            "flags": flags,
        }

    # ──────────────────────────────────────────
    # 기업 정보 (업종 + 간략 설명)
    # ──────────────────────────────────────────
    def _load_company_info(self):
        try:
            df = pd.read_csv(MAPPING_CSV, dtype={"code": str}, encoding="utf-8-sig")
            df["code"] = df["code"].str.zfill(6)
            for _, row in df.iterrows():
                code = row["code"]
                self._company_info[code] = {
                    "name": row.get("name", ""),
                    "market": row.get("market", ""),
                    "sector": row.get("sector", ""),
                    "industry": row.get("industry", ""),
                }
            logger.debug("기업정보: %d종목", len(self._company_info))
        except Exception as e:
            logger.debug("stock_mapping 로드 실패: %s", e)

    def get_company_brief(self, code: str) -> str:
        """업종 | 세부업종 형태의 간략 설명"""
        code = code.strip().zfill(6)
        info = self._company_info.get(code, {})
        sector = info.get("sector", "")
        industry = info.get("industry", "")
        if sector and industry:
            return f"{sector} | {industry}"
        return sector or industry or ""

    def get_company_info(self, code: str) -> dict:
        """기업 정보 전체"""
        return self._company_info.get(code.strip().zfill(6), {})

    # ──────────────────────────────────────────
    # 종합 컨텍스트 (웹훅/대시보드용)
    # ──────────────────────────────────────────
    def stock_context(self, code: str, price: float = 0) -> dict:
        """종목 하나의 전체 컨텍스트"""
        code = code.strip().zfill(6)
        info = self.get_company_info(code)
        return {
            "brief": self.get_company_brief(code),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "holder_pct": self.get_holder_level(code),
            "holder_change": self.get_holder_change(code),
            "holder_tag": self.holder_tag(code, price),
            "is_dumping": self.is_dumping(code),
        }

    def today_context(self, date_str: str = None) -> dict:
        """오늘의 시장 컨텍스트"""
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")
        events = self.get_events(date_str)
        return {
            "date": date_str,
            "events": events,
            "event_warning": self.get_event_warning(date_str),
            "score_adj": self.get_score_adjustment(date_str),
            "conservative": self.should_conservative(date_str),
        }


@lru_cache(maxsize=1)
def get_market_context() -> MarketContext:
    return MarketContext()


def clear_market_context_cache() -> None:
    get_market_context.cache_clear()
