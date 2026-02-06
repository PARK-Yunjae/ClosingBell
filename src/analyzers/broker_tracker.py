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
        # 온라인 fallback: ka10040 당일 거래원 조회
        try:
            from datetime import date
            from src.adapters.kiwoom_rest_client import get_kiwoom_client
            from src.services.broker_signal import (
                BrokerAnalyzer,
                _fetch_daily_brokers,
                calc_broker_score,
            )

            client = get_kiwoom_client()
            broker_data = _fetch_daily_brokers(client, stock_code)
            if broker_data:
                adj = BrokerAnalyzer.analyze(stock_code, broker_data)
                anomaly = adj.anomaly_score if adj else 0
                tag = adj.tag if adj else "정상"
                note = "온라인(ka10040) 조회 결과"
                if adj is None:
                    note = "온라인(ka10040) 조회: 임계치 미만"
                row = {
                    "screen_date": date.today().isoformat(),
                    "stock_code": stock_code,
                    "anomaly_score": anomaly,
                    "broker_score": calc_broker_score(anomaly),
                    "tag": tag,
                }
                return BrokerFlowSummary(
                    status="ok",
                    tag=tag,
                    max_anomaly=anomaly,
                    avg_anomaly=float(anomaly),
                    recent_rows=[row],
                    note=note,
                )
        except Exception:
            pass

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
