"""
뉴스 수집 서비스 v6.0
=====================

네이버 뉴스 API + Gemini 요약으로
유목민 공부법 종목의 뉴스를 수집합니다.

- study_date 기준 ±3일 뉴스 검색
- 종목당 10개 뉴스 수집
- Gemini로 요약 및 감성 분석

사용:
    python main.py --run-news
    
    또는 코드에서:
    from src.services.news_service import run_news_collection
    run_news_collection()
"""

import os
import re
import time
import json
import logging
import urllib.request
import urllib.parse
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from html import unescape

from src.services.http_utils import urlopen_with_retry, redact_url, mask_text

from dotenv import load_dotenv

from src.infrastructure.repository import (
    get_nomad_candidates_repository,
    get_nomad_news_repository,
)

logger = logging.getLogger(__name__)

# .env 로드
load_dotenv()

# API 설정
NAVER_CLIENT_ID = os.getenv('NaverAPI_Client_ID', '')
NAVER_CLIENT_SECRET = os.getenv('NaverAPI_Client_Secret', '')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')

# 상수
NEWS_PER_STOCK = 10      # 종목당 뉴스 수
API_DELAY = 0.5          # API 호출 간격 (초)
# Gemini 요약 ON/OFF (비용 절감용)
# False로 설정하면 Gemini API 호출 없이 뉴스 제목+스니펫만 저장
ENABLE_GEMINI_SUMMARY = False  # ⚠️ True면 하루 10만원+ 비용 발생 가능

GEMINI_MODEL = "gemini-2.0-flash"  # 2.5-flash보다 저렴 (무료 티어 있음)

# VI 관련 제외 키워드 (최근 이슈 제외)
EXCLUDE_KEYWORDS = [
    'VI발동', 'VI 발동', '변동성완화장치',
    '투자주의', '투자경고', '투자위험',
    '상한가', '하한가',  # 당일 가격 뉴스 제외
]


def clean_html(text: str) -> str:
    """HTML 태그 및 특수문자 제거"""
    text = re.sub(r'<[^>]+>', '', text)
    text = unescape(text)
    text = text.replace('&quot;', '"')
    text = text.replace('&amp;', '&')
    text = text.strip()
    return text


def should_exclude_news(title: str, description: str) -> bool:
    """VI/당일 이슈 뉴스 제외 여부"""
    content = (title + " " + description).lower()
    for keyword in EXCLUDE_KEYWORDS:
        if keyword.lower() in content:
            return True
    return False


def search_naver_news(query: str, display: int = 30, sort: str = 'date') -> List[Dict]:
    """
    네이버 뉴스 검색 API
    
    Args:
        query: 검색어
        display: 결과 개수 (최대 100)
        sort: 정렬 (date: 최신순, sim: 관련도순)
        
    Returns:
        뉴스 리스트
    """
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        logger.error("네이버 API 키가 설정되지 않았습니다")
        return []
    
    try:
        encText = urllib.parse.quote(query)
        url = f"https://openapi.naver.com/v1/search/news.json?query={encText}&display={display}&sort={sort}"
        
        request = urllib.request.Request(url)
        request.add_header("X-Naver-Client-Id", NAVER_CLIENT_ID)
        request.add_header("X-Naver-Client-Secret", NAVER_CLIENT_SECRET)
        
        safe_url = redact_url(url)
        response = urlopen_with_retry(
            request,
            timeout=10,
            max_retries=2,
            backoff=1.0,
            logger=logger,
            context=f"Naver News {safe_url}",
        )
        if response is None:
            return []
        rescode = response.getcode()
        
        if rescode == 200:
            response_body = response.read()
            data = json.loads(response_body.decode('utf-8'))
            
            news_list = []
            for item in data.get('items', []):
                title = clean_html(item.get('title', ''))
                description = clean_html(item.get('description', ''))
                
                # VI/당일 이슈 뉴스 제외
                if should_exclude_news(title, description):
                    continue
                
                news = {
                    'title': title,
                    'description': description,
                    'link': item.get('link', ''),
                    'originallink': item.get('originallink', ''),
                    'pub_date': item.get('pubDate', ''),
                    'source': extract_source(item.get('originallink', '') or item.get('link', '')),
                }
                news_list.append(news)
            
            return news_list
        else:
            logger.error(f"네이버 API 오류: {rescode}")
            return []
            
    except Exception as e:
        logger.error(f"네이버 뉴스 검색 실패: {mask_text(str(e))}")
        return []


def extract_source(url: str) -> str:
    """URL에서 뉴스 출처 추출"""
    try:
        match = re.search(r'https?://([^/]+)', url)
        if match:
            domain = match.group(1)
            domain = re.sub(r'^(www\.|news\.|m\.)', '', domain)
            
            domain_map = {
                'hankyung.com': '한국경제',
                'mk.co.kr': '매일경제',
                'mt.co.kr': '머니투데이',
                'edaily.co.kr': '이데일리',
                'sedaily.com': '서울경제',
                'fnnews.com': '파이낸셜뉴스',
                'newsis.com': '뉴시스',
                'yna.co.kr': '연합뉴스',
                'yonhapnews.co.kr': '연합뉴스',
                'chosun.com': '조선일보',
                'donga.com': '동아일보',
                'hani.co.kr': '한겨레',
                'khan.co.kr': '경향신문',
                'etnews.com': '전자신문',
                'bloter.net': '블로터',
                'thebusanilbo.com': '부산일보',
                'naver.com': '네이버뉴스',
            }
            for key, value in domain_map.items():
                if key in domain:
                    return value
            return domain
    except:
        pass
    return '기타'


def parse_pub_date(pub_date: str) -> Optional[str]:
    """발행일 파싱 -> YYYY-MM-DD"""
    try:
        # "Tue, 14 Jan 2025 10:30:00 +0900" 형식
        dt = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %z")
        return dt.strftime("%Y-%m-%d")
    except:
        return None


def summarize_with_gemini(stock_name: str, study_date: str, news_list: List[Dict]) -> List[Dict]:
    """
    Gemini로 뉴스 요약 및 감성 분석
    
    Args:
        stock_name: 종목명
        study_date: 급등 날짜
        news_list: 뉴스 리스트
        
    Returns:
        요약된 뉴스 리스트
    """
    if not GEMINI_API_KEY:
        logger.warning("Gemini API 키가 없어 요약 생략")
        for news in news_list:
            news['summary'] = news.get('description', '')[:150]
            news['sentiment'] = 'neutral'
            news['relevance'] = 0.5
        return news_list
    
    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)
    except ImportError:
        logger.warning("google-genai 패키지 없음. pip install google-genai")
        for news in news_list:
            news['summary'] = news.get('description', '')[:150]
            news['sentiment'] = 'neutral'
            news['relevance'] = 0.5
        return news_list
    except Exception as e:
        logger.error(f"Gemini 클라이언트 초기화 실패: {mask_text(str(e))}")
        for news in news_list:
            news['summary'] = news.get('description', '')[:150]
            news['sentiment'] = 'neutral'
            news['relevance'] = 0.5
        return news_list
    
    # 뉴스들을 하나의 프롬프트로 요약
    news_text = ""
    for i, news in enumerate(news_list[:NEWS_PER_STOCK], 1):
        news_text += f"""
[뉴스 {i}]
제목: {news['title']}
내용: {news['description']}
출처: {news['source']}
날짜: {news.get('pub_date', '')}
---
"""
    
    prompt = f"""
'{stock_name}' 종목이 {study_date}에 급등했습니다.
아래 뉴스들을 분석해서 급등 원인과 관련성을 파악해주세요.

{news_text}

각 뉴스에 대해 다음 형식의 JSON 배열만 출력해주세요:
[
  {{
    "index": 1,
    "summary": "핵심 내용 1-2문장 요약 (한국어)",
    "sentiment": "positive/negative/neutral",
    "relevance": 0.0~1.0,
    "category": "실적/테마/섹터/수급/공시/정책/기타"
  }},
  ...
]

주의:
- JSON만 출력, 다른 텍스트 없이
- sentiment는 주가에 미치는 영향 기준
- relevance는 급등과의 관련성 (1.0=직접적 원인, 0.0=무관)
- 불확실하면 relevance 낮게
"""
    
    try:
        max_retries = 2
        response = None
        for attempt in range(max_retries + 1):
            try:
                # max_output_tokens 설정으로 JSON 잘림 방지
                response = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config={
                        'max_output_tokens': 4096,  # 뉴스 요약용 (여유있게)
                        'temperature': 0.3,
                    },
                )
                break
            except Exception as e:
                if attempt < max_retries:
                    wait_time = 2 ** attempt
                    logger.warning(f"Gemini 요청 실패, {wait_time}초 후 재시도: {mask_text(str(e))}")
                    time.sleep(wait_time)
                    continue
                raise

        if response is None:
            raise RuntimeError("Gemini 응답 없음")
        
        result_text = response.text
        
        # JSON 파싱
        if "```json" in result_text:
            json_str = result_text.split("```json")[1].split("```")[0]
        elif "```" in result_text:
            json_str = result_text.split("```")[1].split("```")[0]
        else:
            json_str = result_text
        
        summaries = json.loads(json_str.strip())
        
        # 결과 병합
        for summary in summaries:
            idx = summary.get('index', 0) - 1
            if 0 <= idx < len(news_list):
                news_list[idx]['summary'] = summary.get('summary', news_list[idx].get('description', '')[:150])
                news_list[idx]['sentiment'] = summary.get('sentiment', 'neutral')
                news_list[idx]['relevance'] = summary.get('relevance', 0.5)
                news_list[idx]['category'] = summary.get('category', '기타')
        
        logger.info(f"  ✅ Gemini 요약 완료")
        return news_list
        
    except Exception as e:
        logger.error(f"Gemini 요약 실패: {mask_text(str(e))}")
        for news in news_list:
            news['summary'] = news.get('description', '')[:150]
            news['sentiment'] = 'neutral'
            news['relevance'] = 0.5
        return news_list


def collect_news_for_candidate(candidate: Dict) -> Dict:
    """
    단일 종목의 뉴스 수집
    
    Args:
        candidate: nomad_candidates 레코드
        
    Returns:
        수집 결과 {'collected': int, 'saved': int}
    """
    stock_code = candidate['stock_code']
    stock_name = candidate['stock_name']
    candidate_id = candidate['id']
    study_date = candidate['study_date']
    
    logger.info(f"  📰 {stock_name} ({stock_code}) - {study_date}")
    
    result = {'collected': 0, 'saved': 0}
    
    # 1. 네이버 뉴스 검색 (종목명 + 주식) - 50개 검색해서 10개 선별
    query = f"{stock_name} 주식"
    news_list = search_naver_news(query, display=50, sort='date')
    
    if not news_list:
        logger.warning(f"  ⚠️ {stock_name}: 뉴스 없음")
        # 뉴스 없어도 수집 완료 표시
        candidates_repo = get_nomad_candidates_repository()
        candidates_repo.update_news_collected(candidate_id, news_count=0)
        return result
    
    # 2. study_date 기준으로 필터링 (±2년 = 730일)
    try:
        target_date = datetime.strptime(study_date, "%Y-%m-%d").date()
    except:
        target_date = date.today()
    
    filtered_news = []
    for news in news_list:
        news_date_str = parse_pub_date(news.get('pub_date', ''))
        if news_date_str:
            try:
                news_date = datetime.strptime(news_date_str, "%Y-%m-%d").date()
                # ±2년 이내 뉴스 (730일)
                days_diff = abs((news_date - target_date).days)
                if days_diff <= 730:
                    news['news_date'] = news_date_str
                    news['days_diff'] = days_diff
                    filtered_news.append(news)
            except:
                pass
    
    # 날짜 차이순 정렬 (급등일에 가까운 순)
    filtered_news.sort(key=lambda x: x.get('days_diff', 999))
    
    # 최소 10개 보장: 부족하면 날짜 필터 없이 보충
    if len(filtered_news) < NEWS_PER_STOCK:
        logger.info(f"  ⚠️ {len(filtered_news)}개 < {NEWS_PER_STOCK}개, 추가 검색...")
        
        # 이미 있는 URL 제외하고 추가
        existing_urls = {n.get('link', '') for n in filtered_news}
        for news in news_list:
            if len(filtered_news) >= NEWS_PER_STOCK:
                break
            if news.get('link', '') not in existing_urls:
                news['news_date'] = parse_pub_date(news.get('pub_date', '')) or study_date
                news['days_diff'] = 999  # 날짜 불확실
                filtered_news.append(news)
    
    filtered_news = filtered_news[:NEWS_PER_STOCK]
    
    if not filtered_news:
        logger.warning(f"  ⚠️ {stock_name}: 뉴스 없음 - 최신 뉴스로 대체")
        # 날짜 필터링 없이 최신 뉴스로 대체
        filtered_news = news_list[:NEWS_PER_STOCK]
        for news in filtered_news:
            news['news_date'] = parse_pub_date(news.get('pub_date', '')) or study_date
    
    result['collected'] = len(filtered_news)
    logger.info(f"  📥 {len(filtered_news)}개 뉴스 수집")
    
    time.sleep(API_DELAY)
    
    # 3. Gemini 요약 (선택적 - 비용 절감)
    if ENABLE_GEMINI_SUMMARY:
        filtered_news = summarize_with_gemini(stock_name, study_date, filtered_news)
        time.sleep(API_DELAY)
    else:
        # Gemini 없이 스니펫을 요약으로 사용
        for news in filtered_news:
            news['summary'] = news.get('snippet', '')[:300]
    
    # 4. DB 저장
    news_repo = get_nomad_news_repository()
    
    for news in filtered_news:
        try:
            news_data = {
                'study_date': study_date,
                'stock_code': stock_code,
                'news_date': news.get('news_date', study_date),
                'news_title': news.get('title', '')[:200],
                'news_source': news.get('source', ''),
                'news_url': news.get('originallink') or news.get('link', ''),
                'summary': news.get('summary', '')[:500],
            }
            
            news_repo.insert(news_data)
            result['saved'] += 1
            
        except Exception as e:
            logger.error(f"  뉴스 저장 실패: {e}")
    
    # 5. candidate 업데이트 (news_collected = 1, news_count)
    candidates_repo = get_nomad_candidates_repository()
    candidates_repo.update_news_collected(candidate_id, news_count=result['saved'])
    
    logger.info(f"  ✅ {result['saved']}개 저장 완료")
    
    return result


def collect_news_for_candidates(
    target_date: Optional[date] = None,
    limit: int = 600,
) -> Dict:
    """
    유목민 후보들의 뉴스 수집
    
    Args:
        target_date: 대상 날짜 (None이면 뉴스 미수집 전체)
        limit: 최대 종목 수
        
    Returns:
        수집 결과 통계
    """
    logger.info("=" * 60)
    logger.info("📰 유목민 뉴스 수집 시작")
    logger.info("=" * 60)
    
    # API 키 확인
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        logger.error("❌ 네이버 API 키가 설정되지 않았습니다")
        print("\n❌ 네이버 API 키가 설정되지 않았습니다")
        print("   .env 파일에 NaverAPI_Client_ID, NaverAPI_Client_Secret 설정 필요")
        return {'error': 'no_naver_api_key'}
    
    if not GEMINI_API_KEY:
        logger.warning("⚠️ Gemini API 키 없음 - 요약 없이 진행")
        print("⚠️ Gemini API 키 없음 - 요약 없이 진행됩니다")
    else:
        print("✅ Gemini API: 설정됨")
    
    print("✅ 네이버 API: 설정됨")
    
    candidates_repo = get_nomad_candidates_repository()
    
    # 뉴스 미수집 후보 조회
    if target_date:
        candidates = candidates_repo.get_by_date(target_date.isoformat())
        candidates = [c for c in candidates if not c.get('news_collected')]
    else:
        candidates = candidates_repo.get_uncollected_news(limit=limit)
    
    if not candidates:
        logger.info("📭 뉴스 수집할 후보 없음")
        print("\n📭 뉴스 수집할 후보가 없습니다.")
        return {'total': 0, 'collected': 0, 'saved': 0}
    
    logger.info(f"📋 뉴스 수집 대상: {len(candidates)}개 종목")
    print(f"\n📋 뉴스 수집 대상: {len(candidates)}개 종목\n")
    
    stats = {'total': len(candidates), 'collected': 0, 'saved': 0}
    
    for i, candidate in enumerate(candidates[:limit]):
        print(f"[{i+1}/{min(len(candidates), limit)}] {candidate['stock_name']} ({candidate['study_date']})")
        
        result = collect_news_for_candidate(candidate)
        
        stats['collected'] += result.get('collected', 0)
        stats['saved'] += result.get('saved', 0)
        
        time.sleep(API_DELAY)
    
    logger.info("=" * 60)
    logger.info(f"📰 뉴스 수집 완료: {stats['saved']}개 저장")
    logger.info("=" * 60)
    
    return stats


def run_news_collection() -> Dict:
    """
    뉴스 수집 실행 (스케줄러용)
    
    오늘의 유목민 후보들의 뉴스를 수집합니다.
    """
    return collect_news_for_candidates(limit=600)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    )
    
    print("=" * 60)
    print("📰 유목민 뉴스 수집 테스트")
    print("=" * 60)
    
    result = run_news_collection()
    
    print("\n" + "=" * 60)
    print("📋 수집 결과")
    print("=" * 60)
    print(f"  대상 종목: {result.get('total', 0)}개")
    print(f"  수집 뉴스: {result.get('collected', 0)}개")
    print(f"  저장 완료: {result.get('saved', 0)}개")
