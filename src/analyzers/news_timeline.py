"""
뉴스/공시 타임라인 분석기 (v9.0)
"""

from dataclasses import dataclass
from typing import List, Dict

from src.services.news_service import search_naver_news
from src.services.dart_service import get_dart_service


@dataclass
class NewsTimelineSummary:
    news: List[Dict]
    disclosures: List[Dict]
    note: str = ""


def analyze_news_timeline(
    stock_code: str,
    stock_name: str,
    days: int = 30,
    news_limit: int = 5,
    disclosure_limit: int = 5,
) -> NewsTimelineSummary:
    news: List[Dict] = []
    disclosures: List[Dict] = []
    note_parts: List[str] = []

    try:
        news = search_naver_news(stock_name, display=news_limit, sort="date") or []
    except Exception:
        note_parts.append("뉴스 조회 실패")

    try:
        dart = get_dart_service()
        disclosures = dart.get_recent_disclosures(stock_code, days=days, limit=disclosure_limit) or []
    except Exception:
        note_parts.append("공시 조회 실패")

    return NewsTimelineSummary(
        news=news,
        disclosures=disclosures,
        note=" / ".join(note_parts),
    )

