"""
AI Pipeline v7.0

TOP5 종목 배치 분석 (5종목 1회 호출)

특징:
- EnrichmentService와 연동
- 5종목 JSON 배열로 한 번에 분석
- 비용 절감 (5회 → 1회)
- DART 위험공시 반영
"""

import os
import json
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


# ============================================================
# 결과 모델
# ============================================================

@dataclass
class AIAnalysisResult:
    """AI 분석 결과"""
    stock_code: str
    stock_name: str = ""
    recommendation: str = ""      # 매수/관망/매도
    risk_level: str = ""          # 낮음/보통/높음
    summary: str = ""             # 핵심 요약 (30자 이내)
    investment_point: str = ""    # 투자 포인트
    risk_factor: str = ""         # 리스크 요인
    confidence: float = 0.0       # 신뢰도 (0~1)
    
    # 메타
    analyzed_at: str = ""
    model_used: str = ""
    error: str = ""
    
    def to_dict(self) -> Dict:
        return {
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'recommendation': self.recommendation,
            'risk_level': self.risk_level,
            'summary': self.summary,
            'investment_point': self.investment_point,
            'risk_factor': self.risk_factor,
            'confidence': self.confidence,
            'analyzed_at': self.analyzed_at,
            'model_used': self.model_used,
        }


# ============================================================
# 프롬프트 템플릿
# ============================================================

BATCH_PROMPT_TEMPLATE = """
당신은 한국 주식 종가매매 전문 분석가입니다.
다음 {count}개 종목을 분석하고 JSON 배열로 응답하세요.

=== 분석 규칙 ===
1. DART 위험공시가 있으면 반드시 "매도", risk_level="높음"
2. CCI > 220 과열구간이면 "관망" 또는 "매도" 권장
3. 주도섹터(is_leading_sector=true)면 가점
4. 거래대금 500억 미만이면 유동성 리스크 언급
5. summary는 30자 이내로 핵심만

=== 종목 데이터 ===
{stock_data}

=== 출력 형식 ===
다음 JSON 배열 형식으로만 응답하세요. 다른 텍스트 없이 JSON만 출력하세요.

[
  {{
    "stock_code": "종목코드",
    "recommendation": "매수|관망|매도",
    "risk_level": "낮음|보통|높음",
    "summary": "핵심 요약 30자 이내",
    "investment_point": "투자 포인트 1문장",
    "risk_factor": "리스크 요인 1문장",
    "confidence": 0.0~1.0
  }},
  ...
]
"""

STOCK_DATA_TEMPLATE = """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[{rank}] {stock_name} ({stock_code})
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 스크리닝 결과
• 점수: {score:.1f}점 ({grade}등급)
• 현재가: {price:,}원 ({change_rate:+.1f}%)
• 시가총액: {market_cap}
• 거래대금: {trading_value}

📈 기술적 지표
• CCI: {cci:.0f} {cci_warning}
• 이격도(20): {disparity:.1f}%
• 연속양봉: {consecutive_up}일
• 거래량비율: {volume_ratio:.1f}%

🏭 섹터
• {sector_display}

💰 재무 ({fiscal_year}년)
{financial_info}

⚠️ DART 공시
{dart_info}

📰 최근 뉴스
{news_info}
"""


# ============================================================
# AI Pipeline
# ============================================================

class AIPipeline:
    """TOP5 AI 분석 파이프라인 (배치 호출)"""
    
    # Gemini 출력 토큰 제한 (JSON 잘림 방지)
    MAX_OUTPUT_TOKENS = 8192  # 5종목 배치 분석용 (여유있게)
    
    def __init__(self, model: str = None):
        """
        Args:
            model: Gemini 모델명
        """
        import os
        from dotenv import load_dotenv
        load_dotenv()
        
        if model is None:
            model = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')
        
        self.model = model
        self._client = None 
    
    @property
    def client(self):
        """Gemini 클라이언트 (lazy load)"""
        if self._client is None:
            try:
                from google import genai
                from dotenv import load_dotenv
                
                load_dotenv()
                api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
                
                if not api_key:
                    logger.warning("Gemini API 키가 설정되지 않았습니다")
                    return None
                
                self._client = genai.Client(api_key=api_key)
            except ImportError:
                logger.error("google-genai 패키지가 설치되지 않았습니다")
                return None
        return self._client
    
    def _format_market_cap(self, value: float) -> str:
        """시가총액 포맷"""
        if not value:
            return "-"
        if value >= 10000:
            return f"{value/10000:.1f}조"
        return f"{value:,.0f}억"
    
    def _format_trading_value(self, value: float) -> str:
        """거래대금 포맷"""
        if not value:
            return "-"
        if value >= 1000:
            return f"{value/1000:.1f}조"
        return f"{value:,.0f}억"
    
    def _format_stock_data(self, stock: Any, rank: int) -> str:
        """단일 종목 데이터 포맷"""
        
        # 기본 정보
        stock_code = getattr(stock, 'stock_code', '')
        stock_name = getattr(stock, 'stock_name', '')
        score = getattr(stock, 'screen_score', 0)
        grade = getattr(stock, 'grade', '-')
        price = getattr(stock, 'screen_price', 0)
        change_rate = getattr(stock, 'change_rate', 0)
        market_cap = getattr(stock, 'market_cap', 0)
        trading_value = getattr(stock, 'trading_value', 0)
        
        # 기술적 지표
        cci = getattr(stock, 'cci', 0)
        disparity = getattr(stock, 'disparity_20', 0)
        consecutive_up = getattr(stock, 'consecutive_up', 0)
        volume_ratio = getattr(stock, 'volume_ratio', 0)
        
        # CCI 경고
        cci_warning = "⚠️과열" if cci > 220 else ("🔥강세" if cci > 100 else "")
        
        # 섹터
        sector = getattr(stock, 'sector', '-')
        is_leading = getattr(stock, 'is_leading_sector', False)
        sector_rank = getattr(stock, 'sector_rank', 99)
        sector_display = f"🔥 주도섹터: {sector} (#{sector_rank}위)" if is_leading else f"{sector}"
        
        # 재무 정보 (EnrichedStock에서)
        fiscal_year = "-"
        financial_info = "• 정보 없음"
        
        financial = getattr(stock, 'financial', None)
        if financial:
            fiscal_year = getattr(financial, 'fiscal_year', '-')
            revenue = getattr(financial, 'revenue', 0)
            op = getattr(financial, 'operating_profit', 0)
            net = getattr(financial, 'net_income', 0)
            
            financial_lines = []
            if revenue:
                financial_lines.append(f"• 매출액: {revenue:,.0f}억원")
            if op:
                financial_lines.append(f"• 영업이익: {op:,.0f}억원")
            if net:
                financial_lines.append(f"• 순이익: {net:,.0f}억원")
            
            # 계산된 지표
            calculated = getattr(stock, 'calculated', None)
            if calculated:
                per = getattr(calculated, 'per', None)
                pbr = getattr(calculated, 'pbr', None)
                roe = getattr(calculated, 'roe', None)
                if per:
                    financial_lines.append(f"• PER: {per:.1f}")
                if pbr:
                    financial_lines.append(f"• PBR: {pbr:.2f}")
                if roe:
                    financial_lines.append(f"• ROE: {roe:.1f}%")
            
            financial_info = "\n".join(financial_lines) if financial_lines else "• 정보 없음"
        
        # DART 위험공시
        dart_info = "✅ 최근 30일 위험 공시 없음"
        risk = getattr(stock, 'risk', None)
        if risk:
            if getattr(risk, 'has_critical_risk', False):
                dart_info = "🚫 위험 공시 발견! (정리매매/관리종목/상장폐지 위험)\n"
                for d in getattr(risk, 'risk_disclosures', [])[:2]:
                    dart_info += f"  - {d.get('date')}: {d.get('title')}\n"
                dart_info += "→ 반드시 '매도' 권장"
            elif getattr(risk, 'has_high_risk', False):
                dart_info = "⚠️ 주의 공시 (유상증자/희석 위험)\n"
                for d in getattr(risk, 'risk_disclosures', [])[:2]:
                    dart_info += f"  - {d.get('date')}: {d.get('title')}\n"
        
        # 뉴스
        news_info = "• 뉴스 없음"
        news_list = getattr(stock, 'news', [])
        if news_list:
            news_lines = []
            for n in news_list[:3]:
                title = getattr(n, 'title', '')[:40]
                news_lines.append(f"• {title}...")
            news_info = "\n".join(news_lines)
        
        return STOCK_DATA_TEMPLATE.format(
            rank=rank,
            stock_name=stock_name,
            stock_code=stock_code,
            score=score,
            grade=grade,
            price=price,
            change_rate=change_rate,
            market_cap=self._format_market_cap(market_cap),
            trading_value=self._format_trading_value(trading_value),
            cci=cci,
            cci_warning=cci_warning,
            disparity=disparity,
            consecutive_up=consecutive_up,
            volume_ratio=volume_ratio,
            sector_display=sector_display,
            fiscal_year=fiscal_year,
            financial_info=financial_info,
            dart_info=dart_info,
            news_info=news_info,
        )
    
    def analyze_batch(self, stocks: List[Any]) -> List[AIAnalysisResult]:
        """배치 분석 (5종목 1회 호출)
        
        Args:
            stocks: EnrichedStock 리스트 (또는 유사 객체)
        
        Returns:
            AIAnalysisResult 리스트
        """
        if not stocks:
            return []
        
        if not self.client:
            logger.error("Gemini 클라이언트 초기화 실패")
            return [
                AIAnalysisResult(
                    stock_code=getattr(s, 'stock_code', ''),
                    stock_name=getattr(s, 'stock_name', ''),
                    error="Gemini 클라이언트 초기화 실패"
                )
                for s in stocks
            ]
        
        # 종목 데이터 포맷
        stock_data_parts = []
        for i, stock in enumerate(stocks[:5]):
            stock_data_parts.append(self._format_stock_data(stock, i + 1))
        
        stock_data = "\n".join(stock_data_parts)
        
        # 프롬프트 생성
        prompt = BATCH_PROMPT_TEMPLATE.format(
            count=len(stocks[:5]),
            stock_data=stock_data,
        )
        
        logger.info(f"🤖 AI 배치 분석 시작: {len(stocks[:5])}개 종목")
        
        try:
            # Gemini API 호출 (max_output_tokens 설정으로 JSON 잘림 방지)
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={
                    'max_output_tokens': self.MAX_OUTPUT_TOKENS,
                    'temperature': 0.3,  # 일관된 분석을 위해 낮게 설정
                },
            )
            
            result_text = response.text.strip()
            
            # JSON 추출
            if '```json' in result_text:
                result_text = result_text.split('```json')[1].split('```')[0]
            elif '```' in result_text:
                result_text = result_text.split('```')[1].split('```')[0]
            
            result_text = result_text.strip()
            
            # JSON 파싱
            results_json = json.loads(result_text)
            
            if not isinstance(results_json, list):
                results_json = [results_json]
            
            # 결과 매핑
            analyzed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            results = []
            
            # stock_code로 매핑
            result_map = {r.get('stock_code'): r for r in results_json}
            
            for stock in stocks[:5]:
                stock_code = getattr(stock, 'stock_code', '')
                stock_name = getattr(stock, 'stock_name', '')
                
                ai_result = result_map.get(stock_code, {})
                
                results.append(AIAnalysisResult(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    recommendation=ai_result.get('recommendation', '관망'),
                    risk_level=ai_result.get('risk_level', '보통'),
                    summary=ai_result.get('summary', '')[:50],
                    investment_point=ai_result.get('investment_point', ''),
                    risk_factor=ai_result.get('risk_factor', ''),
                    confidence=float(ai_result.get('confidence', 0.5)),
                    analyzed_at=analyzed_at,
                    model_used=self.model,
                ))
            
            logger.info(f"✅ AI 배치 분석 완료: {len(results)}개")
            return results
            
        except json.JSONDecodeError as e:
            logger.error(f"AI 응답 JSON 파싱 실패: {e}")
            logger.debug(f"응답 텍스트: {result_text[:500]}")
            
            # Fallback: 기본값 반환
            return [
                AIAnalysisResult(
                    stock_code=getattr(s, 'stock_code', ''),
                    stock_name=getattr(s, 'stock_name', ''),
                    recommendation='관망',
                    risk_level='보통',
                    summary='분석 실패',
                    error=f"JSON 파싱 오류: {str(e)[:50]}",
                    analyzed_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    model_used=self.model,
                )
                for s in stocks[:5]
            ]
            
        except Exception as e:
            logger.error(f"AI 배치 분석 실패: {e}")
            
            return [
                AIAnalysisResult(
                    stock_code=getattr(s, 'stock_code', ''),
                    stock_name=getattr(s, 'stock_name', ''),
                    recommendation='관망',
                    risk_level='보통',
                    summary='분석 실패',
                    error=str(e)[:100],
                    analyzed_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    model_used=self.model,
                )
                for s in stocks[:5]
            ]
    
    def analyze_single(self, stock: Any) -> AIAnalysisResult:
        """단일 종목 분석 (fallback용)"""
        results = self.analyze_batch([stock])
        return results[0] if results else AIAnalysisResult(
            stock_code=getattr(stock, 'stock_code', ''),
            error="분석 실패"
        )


# ============================================================
# 통합 함수
# ============================================================

def analyze_top5_with_ai(enriched_stocks: List[Any]) -> List[Dict]:
    """TOP5 종목 AI 분석 (편의 함수)
    
    Args:
        enriched_stocks: EnrichedStock 리스트
    
    Returns:
        AI 분석 결과 딕셔너리 리스트
    """
    pipeline = AIPipeline()
    results = pipeline.analyze_batch(enriched_stocks)
    
    # EnrichedStock에 AI 결과 첨부
    for stock, ai_result in zip(enriched_stocks, results):
        stock.ai_recommendation = ai_result.recommendation
        stock.ai_risk_level = ai_result.risk_level
        stock.ai_summary = ai_result.summary
    
    return [r.to_dict() for r in results]


def get_ai_pipeline() -> AIPipeline:
    """AIPipeline 인스턴스 반환"""
    return AIPipeline()


# ============================================================
# 테스트
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    
    # 테스트용 더미 데이터 (EnrichedStock 유사)
    class DummyFinancial:
        def __init__(self):
            self.fiscal_year = "2024"
            self.revenue = 2796048
            self.operating_profit = 65670
            self.net_income = 154873
    
    class DummyRisk:
        def __init__(self, critical=False):
            self.has_critical_risk = critical
            self.has_high_risk = False
            self.risk_level = "높음" if critical else "낮음"
            self.risk_disclosures = []
    
    class DummyNews:
        def __init__(self, title):
            self.title = title
    
    class DummyCalculated:
        def __init__(self):
            self.per = 12.5
            self.pbr = 1.2
            self.roe = 15.3
    
    class DummyStock:
        def __init__(self, code, name, score, critical_risk=False):
            self.stock_code = code
            self.stock_name = name
            self.screen_score = score
            self.grade = 'S' if score >= 90 else 'A'
            self.screen_price = 55000
            self.change_rate = 3.5
            self.market_cap = 4200000  # 420조
            self.trading_value = 15000  # 1.5조
            self.cci = 165 if score >= 90 else 120
            self.disparity_20 = 5.2
            self.consecutive_up = 2
            self.volume_ratio = 150.0
            self.sector = "반도체"
            self.is_leading_sector = True
            self.sector_rank = 1
            self.financial = DummyFinancial()
            self.risk = DummyRisk(critical_risk)
            self.calculated = DummyCalculated()
            self.news = [
                DummyNews("AI 반도체 수요 급증, 실적 기대감 상승"),
                DummyNews("외국인 순매수 지속...기관도 동참"),
            ]
    
    # 테스트 종목
    test_stocks = [
        DummyStock('005930', '삼성전자', 93.5),
        DummyStock('000660', 'SK하이닉스', 91.2),
        DummyStock('035720', '카카오', 88.0),
        DummyStock('051910', 'LG화학', 85.5),
        DummyStock('999999', '위험종목', 75.0, critical_risk=True),
    ]
    
    print("\n" + "="*60)
    print("AI Pipeline 배치 분석 테스트")
    print("="*60)
    
    # 배치 분석
    pipeline = AIPipeline()
    results = pipeline.analyze_batch(test_stocks)
    
    print("\n📊 분석 결과:")
    print("-"*60)
    
    for i, result in enumerate(results):
        rec_emoji = {'매수': '🟢', '관망': '🟡', '매도': '🔴'}.get(result.recommendation, '⚪')
        risk_emoji = {'낮음': '✅', '보통': '⚠️', '높음': '🚫'}.get(result.risk_level, '❓')
        
        print(f"\n[{i+1}] {result.stock_name} ({result.stock_code})")
        print(f"    추천: {rec_emoji} {result.recommendation}")
        print(f"    위험도: {risk_emoji} {result.risk_level}")
        print(f"    요약: {result.summary}")
        print(f"    투자포인트: {result.investment_point}")
        print(f"    리스크: {result.risk_factor}")
        print(f"    신뢰도: {result.confidence:.0%}")
        
        if result.error:
            print(f"    ⚠️ 에러: {result.error}")
    
    print("\n" + "="*60)
