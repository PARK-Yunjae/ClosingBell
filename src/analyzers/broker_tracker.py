"""
거래원 추적 분석기 (v9.0)

broker_signals 테이블 데이터를 요약해 최근 이상 징후를 표시합니다.
"""

from dataclasses import dataclass
from typing import List, Dict

from src.infrastructure.repository import get_broker_signal_repository


@dataclass
class BrokerFlowSummary:
    status: str
    tag: str
    max_anomaly: int
    avg_anomaly: float
    recent_rows: List[Dict]
    note: str = ""


def analyze_broker_flow(stock_code: str, limit: int = 5) -> BrokerFlowSummary:
    try:
        repo = get_broker_signal_repository()
        rows = repo.get_signals_by_code(stock_code, limit=limit)
    except Exception:
        return BrokerFlowSummary(
            status="error",
            tag="오류",
            max_anomaly=0,
            avg_anomaly=0.0,
            recent_rows=[],
            note="거래원 DB 조회 실패",
        )

    if not rows:
        return BrokerFlowSummary(
            status="no_data",
            tag="데이터부족",
            max_anomaly=0,
            avg_anomaly=0.0,
            recent_rows=[],
            note="거래원 신호 없음",
        )

    anomalies = [int(r.get("anomaly_score", 0)) for r in rows]
    max_anomaly = max(anomalies) if anomalies else 0
    avg_anomaly = sum(anomalies) / len(anomalies) if anomalies else 0.0
    last_tag = rows[0].get("tag", "") if rows else ""

    trend_note = ""
    if len(anomalies) >= 3:
        if anomalies[0] > anomalies[1] > anomalies[2]:
            trend_note = "최근 3일 이상 신호 약화"
        elif anomalies[0] < anomalies[1] < anomalies[2]:
            trend_note = "최근 3일 이상 신호 강화"

    return BrokerFlowSummary(
        status="ok",
        tag=last_tag or "관측",
        max_anomaly=max_anomaly,
        avg_anomaly=round(avg_anomaly, 1),
        recent_rows=rows,
        note=trend_note,
    )

