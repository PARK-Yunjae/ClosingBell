"""
공통 뉴스 유틸리티

중복 제거:
- _check_recent_news: pullback_scanner.py
- fetch_naver_news: top5_ai_service.py
- 인라인 호출: enrichment_service.py, healthcheck_service.py
"""

import re
import logging
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def _strip_html(text: str) -> str:
    """HTML 태그 제거"""
    return re.sub(r'<[^>]+>', '', text)


def check_recent_news(stock_name: str, days: int = 3) -> Tuple[bool, str]:
    """최근 N일 뉴스 존재 여부 + 대표 헤드라인

    Args:
        stock_name: 종목명
        days: 조회 기간 (일)

    Returns:
        (뉴스존재여부, 대표헤드라인)
    """
    try:
        from src.services.news_service import search_naver_news, parse_pub_date

        query = f"{stock_name} 주식"
        news_list = search_naver_news(query, display=5, sort='date')

        if not news_list:
            return False, ""

        # 최근 N일 이내 뉴스 필터
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        for n in news_list:
            pub = n.get("pub_date", "")
            news_date = n.get("news_date", "")
            if not news_date and pub:
                try:
                    news_date = parse_pub_date(pub) or ""
                except Exception:
                    pass
            if news_date and news_date >= cutoff:
                headline = _strip_html(n.get("title", ""))[:60]
                return True, headline

        # 날짜 파싱 실패 시 뉴스 존재 자체로 판단
        if news_list:
            headline = _strip_html(news_list[0].get("title", ""))[:60]
            return True, headline
        return False, ""
    except Exception as e:
        logger.debug(f"뉴스 조회 실패 ({stock_name}): {e}")
        return False, ""


def fetch_news_headlines(stock_name: str, limit: int = 5) -> List[Dict]:
    """네이버 뉴스 헤드라인 수집 (메모리만, DB 저장 X)

    Args:
        stock_name: 종목명
        limit: 최대 뉴스 수

    Returns:
        [{'title': str, 'url': str}, ...]
    """
    try:
        from src.services.news_service import search_naver_news

        query = f"{stock_name} 주식"
        news_list = search_naver_news(query, display=limit, sort='date')

        if not news_list:
            return []

        return [
            {
                'title': _strip_html(n.get('title', '')),
                'url': n.get('link', ''),
            }
            for n in news_list[:limit]
        ]
    except Exception as e:
        logger.warning(f"뉴스 수집 실패 ({stock_name}): {e}")
        return []
