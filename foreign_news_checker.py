"""
ClosingBell v3.8 외신 체커 (foreign_news_checker.py)
=====================================================
재차거시 중 '재(재료)' 레이어 — 외신 분석.

NewsAPI (/v2/everything) 기반.
종목명 영문 + 제품/고객사 키워드로 최근 기사를 검색하고
건수·최근성·긍부정 비율로 한줄 요약 생성.

daily_top3 파이프라인에서 TOP3 선정 후 호출 (API 절약).

제한사항:
  - Developer 플랜: 24시간 지연, 1개월 범위, 하루 100요청
  - TOP3에만 호출 → 하루 3~9요청 (키워드 조합 수에 따라)
"""
import logging
import requests
from datetime import datetime, timedelta

from config import (
    FOREIGN_NEWS_ENABLED,
    FOREIGN_NEWS_API_KEY,
    FOREIGN_NEWS_DAYS,
    FOREIGN_NEWS_MAX_RESULTS,
)

logger = logging.getLogger("closingbell")

NEWSAPI_URL = "https://newsapi.org/v2/everything"


def check_foreign_news(
    stock_name_en: str,
    aliases: list[str] | None = None,
    products: str = "",
    customer: str = "",
) -> dict:
    """
    외신 검색 → 한줄 요약.

    Args:
        stock_name_en: 종목명 영문 (ex: "Doosan Enerbility")
        aliases: 별칭 리스트 (ex: ["Doosan Heavy", "두산에너빌리티"])
        products: 주요 제품 영문 (ex: "nuclear turbine")
        customer: 주요 고객사 (ex: "Samsung")

    Returns:
        {
            "signal": "양호"|"주의"|"중립",
            "note": str,
            "hits": int,
            "score": int,       # -2 ~ +2
        }
    """
    if not FOREIGN_NEWS_ENABLED or not FOREIGN_NEWS_API_KEY:
        return _neutral()

    # 검색 쿼리 생성
    queries = _build_queries(stock_name_en, aliases, products, customer)
    if not queries:
        return _neutral()

    all_articles = []
    for q in queries[:3]:  # 최대 3개 쿼리 (API 절약)
        try:
            articles = _search_newsapi(q)
            all_articles.extend(articles)
        except Exception as e:
            logger.debug("외신 검색 실패 [%s]: %s", q, e)

    if not all_articles:
        return {"signal": "중립", "note": "외신 뚜렷한 재료 없음", "hits": 0, "score": 0}

    # 중복 제거 (URL 기준)
    seen = set()
    unique = []
    for a in all_articles:
        url = a.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(a)

    return _analyze_articles(unique)


def _build_queries(name_en: str, aliases: list[str] | None,
                   products: str, customer: str) -> list[str]:
    """검색 쿼리 조합 생성"""
    queries = []

    if name_en:
        queries.append(f'"{name_en}"')

    if aliases:
        for alias in aliases[:2]:
            queries.append(f'"{alias}"')

    # 제품/고객사 조합 (있을 때만)
    if name_en and products:
        queries.append(f'"{name_en}" AND ({products})')
    if name_en and customer:
        queries.append(f'"{name_en}" AND "{customer}"')

    return queries


def _search_newsapi(query: str) -> list[dict]:
    """NewsAPI 검색"""
    from_date = (datetime.now() - timedelta(days=FOREIGN_NEWS_DAYS)).strftime("%Y-%m-%d")

    resp = requests.get(
        NEWSAPI_URL,
        params={
            "q": query,
            "from": from_date,
            "sortBy": "relevancy",
            "pageSize": FOREIGN_NEWS_MAX_RESULTS,
            "language": "en",
            "apiKey": FOREIGN_NEWS_API_KEY,
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != "ok":
        return []

    return data.get("articles", [])


def _analyze_articles(articles: list[dict]) -> dict:
    """기사 목록 → 신호 판정"""
    hits = len(articles)

    if hits == 0:
        return {"signal": "중립", "note": "외신 뚜렷한 재료 없음", "hits": 0, "score": 0}

    # 제목 기반 간이 센티먼트 (정교한 분석은 Gemini로 확장 가능)
    positive_kw = {"order", "contract", "deal", "partnership", "surge", "growth",
                   "profit", "revenue", "upgrade", "bullish", "record", "award"}
    negative_kw = {"loss", "decline", "lawsuit", "investigation", "recall",
                   "warning", "downgrade", "bearish", "risk", "debt", "default"}

    pos_count = 0
    neg_count = 0
    titles = []

    for a in articles:
        title = (a.get("title") or "").lower()
        titles.append(a.get("title", ""))

        if any(kw in title for kw in positive_kw):
            pos_count += 1
        if any(kw in title for kw in negative_kw):
            neg_count += 1

    # 가장 최신 기사 제목 (한줄 표시용)
    latest_title = titles[0] if titles else ""
    if len(latest_title) > 60:
        latest_title = latest_title[:57] + "..."

    # 신호 판정
    if neg_count > pos_count and neg_count >= 2:
        return {
            "signal": "주의",
            "note": f"외신 부정적 기사 {neg_count}건 — {latest_title}",
            "hits": hits,
            "score": -2,
        }
    elif pos_count > neg_count and pos_count >= 2:
        return {
            "signal": "양호",
            "note": f"외신 긍정적 기사 {pos_count}건 — {latest_title}",
            "hits": hits,
            "score": 2,
        }
    elif hits >= 3:
        return {
            "signal": "중립",
            "note": f"외신 기사 {hits}건 — {latest_title}",
            "hits": hits,
            "score": 0,
        }

    return {
        "signal": "중립",
        "note": f"외신 기사 {hits}건",
        "hits": hits,
        "score": 0,
    }


def _neutral() -> dict:
    return {"signal": "중립", "note": "", "hits": 0, "score": 0}
