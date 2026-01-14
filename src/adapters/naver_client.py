"""
네이버 뉴스 검색 API 클라이언트
================================

종목 관련 뉴스를 검색하고 수집합니다.

사용:
    from src.adapters.naver_client import get_naver_client
    client = get_naver_client()
    news = client.search_news("삼성전자", days=7)
"""

import os
import logging
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass
import urllib.request
import urllib.parse
import json

logger = logging.getLogger(__name__)


@dataclass
class NewsArticle:
    """뉴스 기사 데이터"""
    title: str
    link: str
    description: str
    pub_date: datetime
    source: str = ""
    
    @property
    def clean_title(self) -> str:
        """HTML 태그 제거된 제목"""
        import re
        return re.sub('<[^<]+?>', '', self.title).strip()
    
    @property
    def clean_description(self) -> str:
        """HTML 태그 제거된 설명"""
        import re
        return re.sub('<[^<]+?>', '', self.description).strip()


class NaverClient:
    """네이버 검색 API 클라이언트"""
    
    BASE_URL = "https://openapi.naver.com/v1/search/news.json"
    
    def __init__(self, client_id: str = None, client_secret: str = None):
        """
        Args:
            client_id: 네이버 API Client ID
            client_secret: 네이버 API Client Secret
        """
        self.client_id = client_id or os.getenv("NaverAPI_Client_ID")
        self.client_secret = client_secret or os.getenv("NaverAPI_Client_Secret")
        
        if not self.client_id or not self.client_secret:
            raise ValueError("Naver API credentials not found")
        
        self.call_delay = 0.1  # API 호출 간격 (초)
        self._last_call = 0
    
    def _make_request(self, params: Dict) -> Dict:
        """API 요청 실행"""
        # Rate limiting
        elapsed = time.time() - self._last_call
        if elapsed < self.call_delay:
            time.sleep(self.call_delay - elapsed)
        
        # URL 생성
        query_string = urllib.parse.urlencode(params)
        url = f"{self.BASE_URL}?{query_string}"
        
        # 요청 헤더
        request = urllib.request.Request(url)
        request.add_header("X-Naver-Client-Id", self.client_id)
        request.add_header("X-Naver-Client-Secret", self.client_secret)
        
        try:
            response = urllib.request.urlopen(request)
            self._last_call = time.time()
            
            if response.getcode() == 200:
                return json.loads(response.read().decode('utf-8'))
            else:
                logger.error(f"Naver API error: {response.getcode()}")
                return {}
                
        except Exception as e:
            logger.error(f"Naver API request failed: {e}")
            return {}
    
    def search_news(
        self,
        query: str,
        days: int = 7,
        max_results: int = 20,
        sort: str = "date",
    ) -> List[NewsArticle]:
        """뉴스 검색
        
        Args:
            query: 검색어 (종목명 또는 키워드)
            days: 최근 N일 이내 뉴스
            max_results: 최대 결과 수 (최대 100)
            sort: 정렬 방식 ('sim': 유사도, 'date': 날짜)
            
        Returns:
            뉴스 기사 리스트
        """
        logger.info(f"뉴스 검색: {query} (최근 {days}일)")
        
        params = {
            "query": query,
            "display": min(max_results, 100),
            "start": 1,
            "sort": sort,
        }
        
        result = self._make_request(params)
        
        if not result or "items" not in result:
            logger.warning(f"검색 결과 없음: {query}")
            return []
        
        # 날짜 필터링
        cutoff_date = datetime.now() - timedelta(days=days)
        articles = []
        
        for item in result["items"]:
            try:
                # pubDate 파싱 (예: "Thu, 14 Jan 2026 10:30:00 +0900")
                pub_date_str = item.get("pubDate", "")
                pub_date = self._parse_date(pub_date_str)
                
                if pub_date and pub_date >= cutoff_date:
                    article = NewsArticle(
                        title=item.get("title", ""),
                        link=item.get("originallink") or item.get("link", ""),
                        description=item.get("description", ""),
                        pub_date=pub_date,
                    )
                    articles.append(article)
                    
            except Exception as e:
                logger.debug(f"뉴스 파싱 실패: {e}")
                continue
        
        logger.info(f"검색 결과: {len(articles)}건 (총 {result.get('total', 0)}건 중)")
        return articles
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """날짜 문자열 파싱"""
        formats = [
            "%a, %d %b %Y %H:%M:%S %z",  # Thu, 14 Jan 2026 10:30:00 +0900
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        
        return None
    
    def search_stock_news(
        self,
        stock_name: str,
        stock_code: str = None,
        days: int = 7,
    ) -> List[NewsArticle]:
        """종목 관련 뉴스 검색 (여러 키워드 조합)
        
        Args:
            stock_name: 종목명
            stock_code: 종목코드 (선택)
            days: 최근 N일
            
        Returns:
            중복 제거된 뉴스 리스트
        """
        all_articles = []
        seen_links = set()
        
        # 검색어 조합
        queries = [
            stock_name,
            f"{stock_name} 주가",
            f"{stock_name} 실적",
        ]
        
        if stock_code:
            queries.append(stock_code)
        
        for query in queries:
            articles = self.search_news(query, days=days, max_results=10)
            
            for article in articles:
                if article.link not in seen_links:
                    seen_links.add(article.link)
                    all_articles.append(article)
        
        # 날짜 역순 정렬
        all_articles.sort(key=lambda x: x.pub_date, reverse=True)
        
        return all_articles[:20]  # 최대 20건
    
    def extract_keywords(self, articles: List[NewsArticle], top_n: int = 10) -> List[str]:
        """뉴스에서 키워드 추출 (단순 빈도 기반)
        
        Args:
            articles: 뉴스 리스트
            top_n: 상위 N개 키워드
            
        Returns:
            키워드 리스트
        """
        from collections import Counter
        import re
        
        # 불용어
        stopwords = {
            '있다', '없다', '하다', '되다', '이다', '것', '수', '등', '및', '년', '월', '일',
            '오늘', '내일', '지난', '이번', '관련', '대한', '위해', '통해', '따라', '대해',
            '증권', '주식', '투자', '시장', '기업', '회사', '매수', '매도', '상승', '하락',
        }
        
        # 텍스트 추출
        text = " ".join([
            a.clean_title + " " + a.clean_description
            for a in articles
        ])
        
        # 단어 추출 (한글 2글자 이상)
        words = re.findall(r'[가-힣]{2,}', text)
        
        # 불용어 제거 및 빈도 계산
        word_counts = Counter(
            word for word in words
            if word not in stopwords
        )
        
        return [word for word, _ in word_counts.most_common(top_n)]


# 싱글톤 인스턴스
_client: Optional[NaverClient] = None


def get_naver_client() -> NaverClient:
    """네이버 클라이언트 인스턴스 반환"""
    global _client
    if _client is None:
        _client = NaverClient()
    return _client


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 60)
    print("🔍 네이버 뉴스 API 테스트")
    print("=" * 60)
    
    try:
        client = get_naver_client()
        
        # 테스트 1: 단순 검색
        print("\n[테스트 1] 삼성전자 뉴스 검색")
        news = client.search_news("삼성전자", days=3, max_results=5)
        for i, article in enumerate(news, 1):
            print(f"  {i}. {article.clean_title[:50]}...")
            print(f"     {article.pub_date.strftime('%Y-%m-%d %H:%M')}")
        
        # 테스트 2: 종목 뉴스 검색
        print("\n[테스트 2] 종목 뉴스 검색 (복합)")
        news = client.search_stock_news("삼성전자", "005930", days=7)
        print(f"  총 {len(news)}건 수집")
        
        # 테스트 3: 키워드 추출
        print("\n[테스트 3] 키워드 추출")
        keywords = client.extract_keywords(news, top_n=10)
        print(f"  키워드: {', '.join(keywords)}")
        
    except Exception as e:
        print(f"❌ 오류: {e}")
