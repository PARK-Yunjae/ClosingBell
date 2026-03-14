"""
ClosingBell v3.8 유튜브 체커 (youtube_checker.py)
===================================================
재차거시 중 '재(재료)' 레이어 — 유튜브 분석.

YouTube Data API v3 기반.
1단계: search.list로 종목 관련 영상 검색 (100쿼터/회)
2단계: videos.list로 조회수·좋아요 통계 (1쿼터/회)

채널 신뢰도 가중치:
  슈카월드 1.0, 삼프로TV 1.0, 전인구경제연구소 0.3 (역지표)

daily_top3 파이프라인에서 TOP3 선정 후 호출 (쿼터 절약).
"""
import logging
import requests
from datetime import datetime, timedelta

from config import (
    YOUTUBE_CHECK_ENABLED,
    YOUTUBE_API_KEY,
    YOUTUBE_SEARCH_DAYS,
    YOUTUBE_MAX_RESULTS,
)

logger = logging.getLogger("closingbell")

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

# 채널 신뢰도 가중치 (조정 가능)
CHANNEL_WEIGHTS = {
    "슈카월드": 1.0,
    "삼프로TV": 1.0,
    "한국경제TV": 0.8,
    "머니투데이": 0.8,
    "이데일리": 0.8,
    "전인구경제연구소": 0.3,  # 역지표 성향
}


def check_youtube(
    stock_name: str,
    products: str = "",
    theme: str = "",
) -> dict:
    """
    유튜브 종목 관련 영상 검색 → 한줄 요약.

    Args:
        stock_name: 종목명 (한글)
        products: 주요 제품/테마 키워드
        theme: 관련 테마명

    Returns:
        {
            "signal": "양호"|"주의"|"중립",
            "note": str,
            "video_count": int,
            "top_title": str,
            "top_channel": str,
            "score": int,       # -1 ~ +1
        }
    """
    if not YOUTUBE_CHECK_ENABLED or not YOUTUBE_API_KEY:
        return _neutral()

    # 검색 쿼리 생성
    queries = _build_queries(stock_name, products, theme)
    if not queries:
        return _neutral()

    all_videos = []
    for q in queries[:2]:  # 최대 2개 쿼리 (쿼터 절약)
        try:
            videos = _search_youtube(q)
            all_videos.extend(videos)
        except Exception as e:
            logger.debug("유튜브 검색 실패 [%s]: %s", q, e)

    if not all_videos:
        return {"signal": "중립", "note": "", "video_count": 0,
                "top_title": "", "top_channel": "", "score": 0}

    # 중복 제거 (videoId 기준)
    seen = set()
    unique = []
    for v in all_videos:
        vid = v.get("video_id", "")
        if vid and vid not in seen:
            seen.add(vid)
            unique.append(v)

    # 통계 조회 (videos.list — 1쿼터/회)
    try:
        unique = _enrich_stats(unique)
    except Exception as e:
        logger.debug("유튜브 통계 조회 실패: %s", e)

    return _analyze_videos(unique, stock_name)


def _build_queries(name: str, products: str, theme: str) -> list[str]:
    """검색 쿼리 조합"""
    queries = [f'"{name}" 주식']

    if products:
        queries.append(f'"{name}" {products.split(",")[0].strip()}')
    elif theme:
        queries.append(f'"{name}" {theme}')

    return queries


def _search_youtube(query: str) -> list[dict]:
    """YouTube search.list (100쿼터/회)"""
    published_after = (
        datetime.now() - timedelta(days=YOUTUBE_SEARCH_DAYS)
    ).strftime("%Y-%m-%dT00:00:00Z")

    resp = requests.get(
        SEARCH_URL,
        params={
            "part": "snippet",
            "q": query,
            "type": "video",
            "order": "relevance",
            "publishedAfter": published_after,
            "regionCode": "KR",
            "relevanceLanguage": "ko",
            "maxResults": YOUTUBE_MAX_RESULTS,
            "key": YOUTUBE_API_KEY,
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    result = []
    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        result.append({
            "video_id": item.get("id", {}).get("videoId", ""),
            "title": snippet.get("title", ""),
            "channel": snippet.get("channelTitle", ""),
            "published": snippet.get("publishedAt", ""),
            "description": snippet.get("description", "")[:200],
            "view_count": 0,
            "like_count": 0,
        })
    return result


def _enrich_stats(videos: list[dict]) -> list[dict]:
    """videos.list로 조회수·좋아요 추가 (1쿼터/회)"""
    video_ids = [v["video_id"] for v in videos if v.get("video_id")]
    if not video_ids:
        return videos

    resp = requests.get(
        VIDEOS_URL,
        params={
            "part": "statistics",
            "id": ",".join(video_ids[:10]),
            "key": YOUTUBE_API_KEY,
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    stats_map = {}
    for item in data.get("items", []):
        vid = item.get("id", "")
        stats = item.get("statistics", {})
        stats_map[vid] = {
            "view_count": int(stats.get("viewCount", "0")),
            "like_count": int(stats.get("likeCount", "0")),
        }

    for v in videos:
        s = stats_map.get(v.get("video_id"), {})
        v["view_count"] = s.get("view_count", 0)
        v["like_count"] = s.get("like_count", 0)

    return videos


def _analyze_videos(videos: list[dict], stock_name: str) -> dict:
    """영상 목록 → 신호 판정"""
    count = len(videos)
    if count == 0:
        return _neutral()

    # 조회수 기준 정렬 (가장 주목받는 영상)
    videos.sort(key=lambda v: v.get("view_count", 0), reverse=True)
    top = videos[0]

    top_title = top.get("title", "")
    if len(top_title) > 50:
        top_title = top_title[:47] + "..."
    top_channel = top.get("channel", "")

    # 채널 신뢰도 가중
    channel_weight = 1.0
    for ch_name, weight in CHANNEL_WEIGHTS.items():
        if ch_name in top_channel:
            channel_weight = weight
            break

    # 영상 많음 = 관심도 높음 (좋은 의미일 수도 나쁜 의미일 수도)
    # 간단하게: 3건 이상이면 주목, 제목에 긍부정 키워드 체크
    positive_kw = {"호재", "급등", "상승", "수주", "계약", "실적", "기대", "추천", "매수"}
    negative_kw = {"악재", "급락", "하락", "위험", "손절", "매도", "폭락", "주의"}

    pos = sum(1 for v in videos if any(kw in v.get("title", "") for kw in positive_kw))
    neg = sum(1 for v in videos if any(kw in v.get("title", "") for kw in negative_kw))

    # 전인구 역지표 처리
    if channel_weight < 0.5 and top.get("view_count", 0) > 10000:
        note = f"📺 {top_channel}: {top_title} (역지표 주의)"
        return {
            "signal": "주의",
            "note": note,
            "video_count": count,
            "top_title": top_title,
            "top_channel": top_channel,
            "score": -1,
        }

    if count >= 5 and neg > pos:
        note = f"📺 영상 {count}건 (부정적 {neg}건)"
        score = -1
        signal = "주의"
    elif count >= 3 and pos > neg:
        note = f"📺 영상 {count}건 — {top_title}"
        score = 1
        signal = "양호"
    elif count >= 1:
        note = f"📺 {top_channel}: {top_title}"
        score = 0
        signal = "중립"
    else:
        return _neutral()

    return {
        "signal": signal,
        "note": note,
        "video_count": count,
        "top_title": top_title,
        "top_channel": top_channel,
        "score": score,
    }


def _neutral() -> dict:
    return {"signal": "중립", "note": "", "video_count": 0,
            "top_title": "", "top_channel": "", "score": 0}
