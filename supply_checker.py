"""
ClosingBell v3.8 supply checker (수급 체커)
=============================================
재차거시 중 '거(거래량·수급)' 레이어 구현.

5개 키움 API 데이터를 종합해 종목별 수급 상태를 한줄 요약.
  - 공매도 추이  (ka10014)
  - 대차거래 추이 (ka20068)
  - 신용 매매동향 (ka10013)
  - 투자자별 순매수 (ka10059)
  - 체결강도 (ka10047)

daily_top3 파이프라인에서 DART/뉴스 체크 직후 호출.
"""
import logging
from typing import Optional

from config import (
    SUPPLY_CHECK_ENABLED,
    SUPPLY_SHORT_DAYS,
    SUPPLY_SHORT_INCREASE_THRESH,
    SUPPLY_LOAN_INCREASE_DAYS,
    SUPPLY_CREDIT_HOT_RATIO,
    SUPPLY_STRENGTH_WEAK,
    SUPPLY_STRENGTH_STRONG,
)

logger = logging.getLogger("closingbell")


def check_supply(code: str, api) -> dict:
    """
    종목 수급 종합 분석.

    Returns:
        {
            "short_selling": {"signal": "주의"|"양호"|"중립", "note": str, "score": int},
            "loan":          {"signal": ..., "note": ..., "score": ...},
            "credit":        {"signal": ..., "note": ..., "score": ...},
            "investor":      {"signal": ..., "note": ..., "score": ...},
            "strength":      {"signal": ..., "note": ..., "score": ...},
            "summary_line":  str,   # 웹훅 한줄 표시용
            "total_score":   int,   # 합산 수급 점수 (-10 ~ +10)
        }
    """
    if not SUPPLY_CHECK_ENABLED:
        return _empty_result()

    result = {
        "short_selling": _neutral("공매도"),
        "loan": _neutral("대차"),
        "credit": _neutral("신용"),
        "investor": _neutral("수급"),
        "strength": _neutral("체결강도"),
    }

    # ① 공매도 추이
    try:
        result["short_selling"] = _analyze_short_selling(code, api)
    except Exception as e:
        logger.debug("공매도 체크 실패 [%s]: %s", code, e)

    # ② 대차거래 추이
    try:
        result["loan"] = _analyze_lending(code, api)
    except Exception as e:
        logger.debug("대차 체크 실패 [%s]: %s", code, e)

    # ③ 신용 매매동향
    try:
        result["credit"] = _analyze_credit(code, api)
    except Exception as e:
        logger.debug("신용 체크 실패 [%s]: %s", code, e)

    # ④ 투자자별 순매수
    try:
        result["investor"] = _analyze_investor(code, api)
    except Exception as e:
        logger.debug("투자자 체크 실패 [%s]: %s", code, e)

    # ⑤ 체결강도
    try:
        result["strength"] = _analyze_strength(code, api)
    except Exception as e:
        logger.debug("체결강도 체크 실패 [%s]: %s", code, e)

    # 종합
    total = sum(r.get("score", 0) for r in result.values())
    result["total_score"] = max(-10, min(10, total))
    result["summary_line"] = _build_summary_line(result)

    return result


# ──────────────────────────────────────────────
# 개별 분석 함수
# ──────────────────────────────────────────────

def _analyze_short_selling(code: str, api) -> dict:
    """공매도 비중 추이 분석 (최근 N일)"""
    rows = api.get_short_selling(code, days=SUPPLY_SHORT_DAYS)
    if not rows:
        return _neutral("공매도")

    ratios = [r["short_ratio"] for r in rows if r["short_ratio"] > 0]
    if not ratios:
        return {"signal": "양호", "note": "공매도 없음", "score": 1}

    avg_ratio = sum(ratios) / len(ratios)
    latest = ratios[0] if ratios else 0

    # 추세 판단: 최근 값이 평균 대비 증가세인지
    increasing = len(ratios) >= 2 and ratios[0] > ratios[-1]

    if latest >= SUPPLY_SHORT_INCREASE_THRESH and increasing:
        return {
            "signal": "주의",
            "note": f"공매도 비중 {latest:.1f}% (3일 증가)",
            "score": -2,
        }
    elif latest >= SUPPLY_SHORT_INCREASE_THRESH:
        return {
            "signal": "주의",
            "note": f"공매도 비중 {latest:.1f}%",
            "score": -1,
        }
    elif latest < 2.0:
        return {"signal": "양호", "note": f"공매도 비중 낮음 ({latest:.1f}%)", "score": 1}

    return {"signal": "중립", "note": f"공매도 {latest:.1f}%", "score": 0}


def _analyze_lending(code: str, api) -> dict:
    """대차잔고 증감 추이 분석"""
    rows = api.get_stock_lending(code, days=SUPPLY_LOAN_INCREASE_DAYS)
    if not rows:
        return _neutral("대차")

    changes = [r["change"] for r in rows]
    increase_days = sum(1 for c in changes if c > 0)

    if increase_days >= len(changes) - 1 and len(changes) >= 3:
        return {
            "signal": "주의",
            "note": f"대차잔고 {increase_days}일 연속 증가",
            "score": -2,
        }
    elif increase_days >= len(changes) // 2 + 1:
        return {
            "signal": "주의",
            "note": f"대차잔고 증가세 ({increase_days}/{len(changes)}일)",
            "score": -1,
        }

    decrease_days = sum(1 for c in changes if c < 0)
    if decrease_days >= len(changes) - 1 and len(changes) >= 3:
        return {
            "signal": "양호",
            "note": "대차잔고 감소세",
            "score": 1,
        }

    return {"signal": "중립", "note": "대차잔고 특이 없음", "score": 0}


def _analyze_credit(code: str, api) -> dict:
    """신용잔고율 분석"""
    rows = api.get_credit_trend(code)
    if not rows:
        return _neutral("신용")

    # 잔고율이 있는 행 찾기
    latest_ratio = 0.0
    for r in rows:
        if r["balance_ratio"] > 0:
            latest_ratio = r["balance_ratio"]
            break

    if latest_ratio >= SUPPLY_CREDIT_HOT_RATIO:
        return {
            "signal": "주의",
            "note": f"신용잔고율 {latest_ratio:.1f}% (과열)",
            "score": -2,
        }
    elif latest_ratio >= SUPPLY_CREDIT_HOT_RATIO * 0.6:
        return {
            "signal": "중립",
            "note": f"신용잔고율 {latest_ratio:.1f}%",
            "score": 0,
        }

    return {"signal": "양호", "note": "신용 과열 없음", "score": 0}


def _analyze_investor(code: str, api) -> dict:
    """외인·기관 동반 순매수 여부"""
    rows = api.get_investor_trend(code, days=3)
    if not rows:
        return _neutral("수급")

    latest = rows[0]
    foreign = latest.get("foreign", 0)
    inst = latest.get("institution", 0)

    if foreign > 0 and inst > 0:
        return {
            "signal": "양호",
            "note": "외인·기관 동반 순매수",
            "score": 2,
        }
    elif foreign > 0 or inst > 0:
        who = "외인" if foreign > 0 else "기관"
        return {
            "signal": "양호",
            "note": f"{who} 순매수",
            "score": 1,
        }
    elif foreign < 0 and inst < 0:
        return {
            "signal": "주의",
            "note": "외인·기관 동반 순매도",
            "score": -2,
        }

    return {"signal": "중립", "note": "수급 혼조", "score": 0}


def _analyze_strength(code: str, api) -> dict:
    """체결강도 분석"""
    rows = api.get_execution_strength(code)
    if not rows:
        return _neutral("체결강도")

    latest = rows[0]
    s20 = latest.get("strength_20d", 0)

    if s20 >= SUPPLY_STRENGTH_STRONG:
        return {
            "signal": "양호",
            "note": f"체결강도 {s20:.0f}% (매수 우위)",
            "score": 1,
        }
    elif s20 <= SUPPLY_STRENGTH_WEAK:
        return {
            "signal": "주의",
            "note": f"체결강도 {s20:.0f}% (매도 우위)",
            "score": -1,
        }

    return {"signal": "중립", "note": f"체결강도 {s20:.0f}%", "score": 0}


# ──────────────────────────────────────────────
# 유틸리티
# ──────────────────────────────────────────────

def _neutral(label: str) -> dict:
    return {"signal": "중립", "note": f"{label} 특이 없음", "score": 0}


def _empty_result() -> dict:
    return {
        "short_selling": _neutral("공매도"),
        "loan": _neutral("대차"),
        "credit": _neutral("신용"),
        "investor": _neutral("수급"),
        "strength": _neutral("체결강도"),
        "summary_line": "",
        "total_score": 0,
    }


def _build_summary_line(result: dict) -> str:
    """웹훅용 한줄 수급 요약 생성"""
    parts = []

    # 주의 항목만 우선 표시
    caution_items = []
    good_items = []

    for key in ("short_selling", "loan", "credit", "investor", "strength"):
        item = result.get(key, {})
        sig = item.get("signal", "중립")
        note = item.get("note", "")
        if sig == "주의" and note:
            caution_items.append(note)
        elif sig == "양호" and note:
            good_items.append(note)

    if caution_items:
        parts.append("⚠️ " + " | ".join(caution_items[:3]))
    if good_items:
        parts.append("✅ " + " | ".join(good_items[:2]))

    if not parts:
        return "수급 특이사항 없음"

    return " / ".join(parts)
