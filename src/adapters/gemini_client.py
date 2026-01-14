"""
Google Gemini API 클라이언트
============================

AI 분석 및 요약 생성에 사용합니다.

사용:
    from src.adapters.gemini_client import get_gemini_client
    client = get_gemini_client()
    summary = client.summarize_stock(stock_info, news_list)
"""

import os
import logging
import time
import json
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class StockAnalysis:
    """AI 분석 결과"""
    investment_points: str      # 투자 포인트
    risk_factors: str           # 리스크 요인
    selection_reason: str       # 선정 이유
    news_summary: str           # 뉴스 요약
    overall_score: str          # 종합 평가 (A/B/C/D)
    
    def to_dict(self) -> Dict:
        return {
            "investment_points": self.investment_points,
            "risk_factors": self.risk_factors,
            "selection_reason": self.selection_reason,
            "news_summary": self.news_summary,
            "overall_score": self.overall_score,
        }


class GeminiClient:
    """Google Gemini API 클라이언트"""
    
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
    MODEL = "gemini-2.0-flash"
    
    def __init__(self, api_key: str = None):
        """
        Args:
            api_key: Gemini API 키
        """
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        
        if not self.api_key:
            raise ValueError("Gemini API key not found")
        
        self.call_delay = 1.0  # API 호출 간격 (초)
        self._last_call = 0
        
        # requests 라이브러리 사용
        try:
            import requests
            self.requests = requests
        except ImportError:
            raise ImportError("requests 라이브러리가 필요합니다: pip install requests")
    
    def _make_request(self, prompt: str, max_tokens: int = 2048) -> str:
        """API 요청 실행"""
        # Rate limiting
        elapsed = time.time() - self._last_call
        if elapsed < self.call_delay:
            time.sleep(self.call_delay - elapsed)
        
        url = f"{self.BASE_URL}/{self.MODEL}:generateContent?key={self.api_key}"
        
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": max_tokens,
            }
        }
        
        headers = {"Content-Type": "application/json"}
        
        try:
            response = self.requests.post(url, json=payload, headers=headers, timeout=30)
            self._last_call = time.time()
            
            if response.status_code == 200:
                result = response.json()
                # 응답에서 텍스트 추출
                candidates = result.get("candidates", [])
                if candidates:
                    content = candidates[0].get("content", {})
                    parts = content.get("parts", [])
                    if parts:
                        return parts[0].get("text", "")
                return ""
            else:
                logger.error(f"Gemini API error: {response.status_code}")
                logger.error(f"Response: {response.text}")
                return ""
                
        except Exception as e:
            logger.error(f"Gemini API request failed: {e}")
            return ""
    
    def analyze_stock(
        self,
        stock_name: str,
        stock_code: str,
        screen_rank: int,
        score_info: Dict,
        company_info: Dict,
        news_list: List[Dict],
    ) -> StockAnalysis:
        """종목 분석 및 요약 생성
        
        Args:
            stock_name: 종목명
            stock_code: 종목코드
            screen_rank: 스크리닝 순위
            score_info: 점수 정보 (CCI, 거래량비 등)
            company_info: 기업 정보 (업종, 재무 등)
            news_list: 최근 뉴스 리스트
            
        Returns:
            StockAnalysis 객체
        """
        # 뉴스 텍스트 준비
        news_text = ""
        for i, news in enumerate(news_list[:5], 1):
            news_text += f"{i}. {news.get('title', '')} ({news.get('date', '')})\n"
            news_text += f"   {news.get('summary', '')[:100]}...\n"
        
        if not news_text:
            news_text = "(최근 뉴스 없음)"
        
        prompt = f"""당신은 한국 주식 시장 전문 애널리스트입니다. 
다음 종목에 대해 분석하고 간결하게 요약해주세요.

## 종목 정보
- 종목명: {stock_name} ({stock_code})
- 종가매매 순위: {screen_rank}위

## 당일 기술 지표
- 총점: {score_info.get('score_total', 'N/A')}점
- CCI: {score_info.get('cci', 'N/A')}
- 거래량비: {score_info.get('volume_ratio', 'N/A')}배
- 등락률: {score_info.get('change_rate', 'N/A')}%
- 연속양봉: {score_info.get('consec_days', 'N/A')}일
- 이격도: {score_info.get('distance', 'N/A')}%

## 기업 정보
- 업종: {company_info.get('industry', 'N/A')}
- 주요사업: {company_info.get('main_business', 'N/A')}
- 시가총액: {company_info.get('market_cap', 'N/A')}억원
- PER: {company_info.get('per', 'N/A')}
- 최대주주: {company_info.get('major_shareholder', 'N/A')} ({company_info.get('shareholder_ratio', 'N/A')}%)

## 최근 뉴스
{news_text}

---

다음 형식으로 JSON 응답해주세요:
{{
    "investment_points": "투자 포인트 (2-3문장, 구체적인 호재/성장성)",
    "risk_factors": "리스크 요인 (2-3문장, 주의할 점)",
    "selection_reason": "종가매매 선정 이유 (기술적 분석 관점에서 1-2문장)",
    "news_summary": "뉴스 요약 (최근 이슈 1-2문장)",
    "overall_score": "종합 평가 (A/B/C/D 중 하나)"
}}

JSON만 출력하고 다른 텍스트는 출력하지 마세요.
"""
        
        logger.info(f"AI 분석 요청: {stock_name}")
        
        response = self._make_request(prompt)
        
        if not response:
            return StockAnalysis(
                investment_points="분석 실패",
                risk_factors="분석 실패",
                selection_reason="분석 실패",
                news_summary="분석 실패",
                overall_score="N/A",
            )
        
        # JSON 파싱
        try:
            # 코드 블록 제거
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]
            
            data = json.loads(response)
            
            return StockAnalysis(
                investment_points=data.get("investment_points", ""),
                risk_factors=data.get("risk_factors", ""),
                selection_reason=data.get("selection_reason", ""),
                news_summary=data.get("news_summary", ""),
                overall_score=data.get("overall_score", "N/A"),
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON 파싱 실패: {e}")
            logger.debug(f"응답: {response[:200]}")
            
            # 텍스트 응답 처리
            return StockAnalysis(
                investment_points=response[:200] if response else "분석 실패",
                risk_factors="",
                selection_reason="",
                news_summary="",
                overall_score="N/A",
            )
    
    def summarize_news(self, news_list: List[Dict], stock_name: str) -> str:
        """뉴스 요약
        
        Args:
            news_list: 뉴스 리스트
            stock_name: 종목명
            
        Returns:
            요약 텍스트
        """
        if not news_list:
            return "최근 주요 뉴스 없음"
        
        news_text = "\n".join([
            f"- {n.get('title', '')}"
            for n in news_list[:10]
        ])
        
        prompt = f"""다음은 {stock_name} 관련 최근 뉴스입니다.
핵심 내용을 2-3문장으로 요약해주세요.

{news_text}

요약:"""
        
        return self._make_request(prompt, max_tokens=200).strip()


# 싱글톤 인스턴스
_client: Optional[GeminiClient] = None


def get_gemini_client() -> GeminiClient:
    """Gemini 클라이언트 인스턴스 반환"""
    global _client
    if _client is None:
        _client = GeminiClient()
    return _client


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 60)
    print("🤖 Gemini API 테스트")
    print("=" * 60)
    
    try:
        client = get_gemini_client()
        
        # 테스트 데이터
        score_info = {
            "score_total": 85.5,
            "cci": 175,
            "volume_ratio": 2.3,
            "change_rate": 5.2,
            "consec_days": 2,
            "distance": 4.5,
        }
        
        company_info = {
            "industry": "반도체",
            "main_business": "반도체 장비 제조",
            "market_cap": 3000,
            "per": 15.5,
            "major_shareholder": "홍길동",
            "shareholder_ratio": 30.0,
        }
        
        news_list = [
            {"title": "삼성전자와 신규 계약 체결", "date": "2026-01-14", "summary": "반도체 장비 공급 계약"},
            {"title": "실적 전망 긍정적", "date": "2026-01-13", "summary": "분기 실적 개선 예상"},
        ]
        
        print("\n[테스트] 종목 분석")
        analysis = client.analyze_stock(
            stock_name="테스트종목",
            stock_code="123456",
            screen_rank=1,
            score_info=score_info,
            company_info=company_info,
            news_list=news_list,
        )
        
        print(f"\n투자포인트: {analysis.investment_points}")
        print(f"리스크요인: {analysis.risk_factors}")
        print(f"선정이유: {analysis.selection_reason}")
        print(f"뉴스요약: {analysis.news_summary}")
        print(f"종합평가: {analysis.overall_score}")
        
    except Exception as e:
        print(f"❌ 오류: {e}")
        import traceback
        traceback.print_exc()
