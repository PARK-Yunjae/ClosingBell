"""
ClosingBell v3.5 — 뉴스 체커
==============================
네이버 뉴스 API로 종목별 최근 뉴스 수집 → Gemini로 위험 요약.
daily_top3()에서 호출.

네이버 API 발급: https://developers.naver.com/apps/#/register
"""
import logging
import requests
from config import NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger("closingbell")


def get_news(stock_name: str, count: int = 5) -> list[dict]:
    """
    네이버 뉴스 API로 종목 관련 최근 뉴스 조회.
    반환: [{"title": "...", "description": "...", "link": "...", "pubDate": "..."}]
    """
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return []

    try:
        # 종목명에서 불필요한 접미사 제거
        query = stock_name.replace("우B", "").replace("우", "").strip()

        r = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            params={"query": query, "display": count, "sort": "date"},
            headers={
                "X-Naver-Client-Id": NAVER_CLIENT_ID,
                "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
            },
            timeout=5,
        )
        if r.status_code != 200:
            logger.debug("네이버 뉴스 API 실패 [%s]: %d", stock_name, r.status_code)
            return []

        items = r.json().get("items", [])
        # HTML 태그 제거
        import re
        for item in items:
            item["title"] = re.sub(r"<[^>]+>", "", item.get("title", ""))
            item["description"] = re.sub(r"<[^>]+>", "", item.get("description", ""))

        return items

    except Exception as e:
        logger.debug("네이버 뉴스 조회 실패 [%s]: %s", stock_name, e)
        return []


def summarize_news(stock_name: str, news_items: list[dict]) -> dict:
    """
    Gemini로 뉴스 위험도 요약.
    반환: {"risk": "양호|주의|위험", "summary": "한줄요약"}
    """
    if not news_items:
        return {"risk": "확인불가", "summary": "뉴스 없음"}

    if not GEMINI_API_KEY:
        # Gemini 없으면 뉴스 제목만으로 간단 판단
        return _simple_judge(news_items)

    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(GEMINI_MODEL)

        news_text = "\n".join(
            f"- {item['title']}" for item in news_items[:5]
        )

        prompt = f"""다음은 '{stock_name}' 관련 최근 뉴스 제목입니다:
{news_text}

이 종목의 단기 매수 관점에서 위험도를 판단해주세요.
반드시 아래 JSON 형식으로만 응답:
{{"risk": "양호|주의|위험", "summary": "15자 이내 한줄 요약"}}

판단 기준:
- 양호: 긍정적이거나 중립적 뉴스
- 주의: 실적 악화, 소송, 경영진 변동 등
- 위험: 상장폐지, 거래정지, 횡령, 분식회계 등"""

        response = model.generate_content(prompt)
        text = response.text.strip()

        # JSON 파싱
        import json
        # ```json ... ``` 감싸기 제거
        if "```" in text:
            text = text.split("```")[1].replace("json", "").strip()
        result = json.loads(text)
        return {
            "risk": result.get("risk", "확인불가"),
            "summary": result.get("summary", "")[:30],
        }

    except Exception as e:
        logger.debug("Gemini 뉴스 요약 실패 [%s]: %s", stock_name, e)
        return _simple_judge(news_items)


def _simple_judge(news_items: list[dict]) -> dict:
    """Gemini 없을 때 키워드 기반 간단 판단"""
    danger_keywords = [
        "상장폐지", "거래정지", "횡령", "분식", "감사의견", "관리종목",
        "검찰", "수사", "벌금", "소송패소", "부도", "파산",
    ]
    caution_keywords = [
        "하락", "급락", "실적악화", "적자전환", "유상증자", "감자",
        "소송", "리콜", "제재", "과징금", "영업정지",
    ]

    all_text = " ".join(
        f"{item['title']} {item['description']}" for item in news_items
    )

    for kw in danger_keywords:
        if kw in all_text:
            return {"risk": "위험", "summary": f"{kw} 관련 뉴스"}

    caution_count = sum(1 for kw in caution_keywords if kw in all_text)
    if caution_count >= 2:
        return {"risk": "주의", "summary": "부정적 뉴스 다수"}
    elif caution_count >= 1:
        return {"risk": "주의", "summary": "일부 부정적 뉴스"}

    return {"risk": "양호", "summary": "특이사항 없음"}


def check_stock_news(stock_name: str) -> dict:
    """
    종목 뉴스 위험 체크 (원스톱).
    반환: {"risk": "양호|주의|위험", "summary": "...", "news_count": N}
    """
    news = get_news(stock_name)
    result = summarize_news(stock_name, news)
    result["news_count"] = len(news)
    return result
