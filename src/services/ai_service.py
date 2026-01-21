"""
AI 분석 서비스 v6.2
====================

유목민 공부법 종목에 대해 Gemini 2.0 Flash로 AI 분석 생성

스케줄:
- 17:50 기업정보 수집 후 자동 실행

사용:
    python main.py --run-ai-analysis
    
    또는 코드에서:
    from src.services.ai_service import run_ai_analysis
    run_ai_analysis()
"""

import os
import json
import logging
import time
from datetime import date
from typing import Dict, Optional, List

from src.infrastructure.repository import (
    get_nomad_candidates_repository,
    get_nomad_news_repository,
)

logger = logging.getLogger(__name__)

# API 호출 간격 (초)
API_DELAY = 1.0


def format_market_cap(cap) -> str:
    """시가총액 포맷"""
    if cap is None or cap <= 0:
        return "-"
    if cap >= 10000:
        return f"{cap/10000:.1f}조"
    return f"{cap:,.0f}억"


def generate_ai_analysis(candidate: dict, news_list: list) -> tuple:
    """
    Gemini 2.0 Flash로 AI 분석 생성
    
    Returns:
        (result_dict, error_message)
    """
    try:
        from google import genai
        from dotenv import load_dotenv
        
        # .env 로드
        load_dotenv()
        api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
        
        if not api_key:
            return None, "Gemini API 키가 설정되지 않았습니다."
        
        # 새 API 클라이언트
        client = genai.Client(api_key=api_key)
        
        # 프롬프트 구성
        company_info = f"""
종목: {candidate['stock_name']} ({candidate['stock_code']})
등락률: {candidate['change_rate']:+.1f}%
사유: {candidate['reason_flag']}
시장: {candidate.get('market', '-')}
업종: {candidate.get('sector', '-')}
시가총액: {format_market_cap(candidate.get('market_cap'))}
PER: {candidate.get('per', '-')}
PBR: {candidate.get('pbr', '-')}
ROE: {candidate.get('roe', '-')}%
외국인보유율: {candidate.get('foreign_rate', '-')}%
사업내용: {str(candidate.get('business_summary', '-'))[:300]}
"""
        
        news_text = ""
        if news_list:
            news_text = "\n관련 뉴스:\n"
            for news in news_list[:5]:
                sentiment = news.get('sentiment', '중립')
                title = news.get('news_title', '')
                news_text += f"- [{sentiment}] {title}\n"
        
        prompt = f"""
다음 종목에 대해 간결하게 분석해주세요. 각 항목은 1-2문장으로 작성하세요.

{company_info}
{news_text}

다음 형식으로 JSON으로 응답하세요:
{{
    "summary": "핵심 요약 (1문장)",
    "price_reason": "오늘 주가 움직임 원인 추정",
    "investment_points": ["투자 포인트 1", "투자 포인트 2"],
    "risk_factors": ["리스크 1", "리스크 2"],
    "valuation_comment": "밸류에이션 의견",
    "short_term_outlook": "단기 전망 (1-2주)",
    "recommendation": "매수/관망/매도 중 하나"
}}
"""
        
        # 새 API 호출
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        result_text = response.text
        
        # JSON 파싱
        if '```json' in result_text:
            result_text = result_text.split('```json')[1].split('```')[0]
        elif '```' in result_text:
            result_text = result_text.split('```')[1].split('```')[0]
        
        result = json.loads(result_text.strip())
        return result, None
        
    except ImportError:
        return None, "google-genai 패키지가 설치되지 않았습니다. pip install google-genai"
    except json.JSONDecodeError as e:
        return None, f"AI 응답 파싱 실패: {e}"
    except Exception as e:
        return None, f"AI 분석 실패: {e}"


def analyze_candidates_with_ai(study_date: str = None, limit: int = 50) -> Dict:
    """
    유목민 종목에 대해 AI 분석 실행
    
    Args:
        study_date: 분석할 날짜 (기본: 오늘)
        limit: 최대 분석 개수
    
    Returns:
        분석 결과 통계
    """
    if study_date is None:
        study_date = date.today().isoformat()
    
    logger.info("=" * 60)
    logger.info(f"🤖 AI 분석 시작: {study_date}")
    logger.info("=" * 60)
    
    stats = {
        'date': study_date,
        'total': 0,
        'analyzed': 0,
        'skipped': 0,
        'failed': 0,
        'errors': [],
    }
    
    try:
        candidate_repo = get_nomad_candidates_repository()
        news_repo = get_nomad_news_repository()
        
        # 오늘 종목 중 AI 분석 없는 것
        candidates = candidate_repo.get_by_date(study_date)
        candidates_to_analyze = [
            c for c in candidates 
            if not c.get('ai_summary')
        ]
        
        stats['total'] = len(candidates_to_analyze)
        logger.info(f"분석 대상: {stats['total']}개 (전체 {len(candidates)}개 중 AI 분석 없는 것)")
        
        if stats['total'] == 0:
            logger.info("✅ 모든 종목이 이미 AI 분석 완료됨")
            return stats
        
        # API 키 확인
        api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
        if not api_key:
            logger.error("❌ Gemini API 키가 없습니다. .env에 GEMINI_API_KEY 추가하세요.")
            stats['errors'].append("API 키 없음")
            return stats
        
        # 분석 실행
        for i, candidate in enumerate(candidates_to_analyze[:limit]):
            stock_name = candidate['stock_name']
            stock_code = candidate['stock_code']
            
            logger.info(f"  [{i+1}/{min(stats['total'], limit)}] {stock_name} ({stock_code})")
            
            try:
                # 뉴스 조회
                news_list = news_repo.get_by_candidate(study_date, stock_code)
                
                # AI 분석
                result, error = generate_ai_analysis(candidate, news_list)
                
                if result:
                    # DB 저장
                    candidate_repo.update_ai_summary(
                        candidate['id'], 
                        json.dumps(result, ensure_ascii=False)
                    )
                    stats['analyzed'] += 1
                    
                    rec = result.get('recommendation', '-')
                    logger.info(f"    ✅ 완료 → {rec}")
                else:
                    stats['failed'] += 1
                    stats['errors'].append(f"{stock_name}: {error}")
                    logger.warning(f"    ❌ 실패: {error}")
                
                # API 호출 간격
                time.sleep(API_DELAY)
                
            except Exception as e:
                stats['failed'] += 1
                stats['errors'].append(f"{stock_name}: {str(e)}")
                logger.error(f"    ❌ 에러: {e}")
        
    except Exception as e:
        logger.error(f"AI 분석 중 오류: {e}")
        stats['errors'].append(str(e))
    
    logger.info("=" * 60)
    logger.info(f"🤖 AI 분석 완료: {stats['analyzed']}/{stats['total']} 성공")
    if stats['failed'] > 0:
        logger.warning(f"   실패: {stats['failed']}개")
    logger.info("=" * 60)
    
    return stats


def run_ai_analysis() -> Dict:
    """
    AI 분석 실행 (스케줄러용 - 오늘 날짜만)
    """
    return analyze_candidates_with_ai(limit=50)


def analyze_all_pending(limit: int = 500) -> Dict:
    """
    AI 분석 없는 모든 종목 분석 (백필 데이터 포함)
    
    Args:
        limit: 최대 분석 개수
    
    Returns:
        분석 결과 통계
    """
    logger.info("=" * 60)
    logger.info("🤖 전체 AI 분석 시작 (백필 데이터 포함)")
    logger.info("=" * 60)
    
    stats = {
        'total': 0,
        'analyzed': 0,
        'skipped': 0,
        'failed': 0,
        'errors': [],
    }
    
    try:
        candidate_repo = get_nomad_candidates_repository()
        news_repo = get_nomad_news_repository()
        
        # AI 분석 없는 모든 종목 조회
        with candidate_repo.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM nomad_candidates 
                WHERE ai_summary IS NULL OR ai_summary = ''
                ORDER BY study_date DESC
                LIMIT ?
            """, (limit,))
            columns = [desc[0] for desc in cursor.description]
            candidates = [dict(zip(columns, row)) for row in cursor.fetchall()]
        
        stats['total'] = len(candidates)
        logger.info(f"분석 대상: {stats['total']}개 (AI 분석 없는 전체 종목)")
        
        if stats['total'] == 0:
            logger.info("✅ 모든 종목이 이미 AI 분석 완료됨")
            return stats
        
        # API 키 확인
        api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
        if not api_key:
            logger.error("❌ Gemini API 키가 없습니다. .env에 GEMINI_API_KEY 추가하세요.")
            stats['errors'].append("API 키 없음")
            return stats
        
        # 분석 실행
        for i, candidate in enumerate(candidates):
            stock_name = candidate['stock_name']
            stock_code = candidate['stock_code']
            study_date = candidate['study_date']
            
            logger.info(f"  [{i+1}/{stats['total']}] {study_date} {stock_name} ({stock_code})")
            
            try:
                # 뉴스 조회
                news_list = news_repo.get_by_candidate(study_date, stock_code)
                
                # AI 분석
                result, error = generate_ai_analysis(candidate, news_list)
                
                if result:
                    candidate_repo.update_ai_summary(
                        candidate['id'], 
                        json.dumps(result, ensure_ascii=False)
                    )
                    stats['analyzed'] += 1
                    time.sleep(0.5)  # API 속도 제한
                else:
                    stats['failed'] += 1
                    if error:
                        stats['errors'].append(f"{stock_name}: {error}")
                        
            except Exception as e:
                logger.error(f"    ❌ 에러: {e}")
                stats['failed'] += 1
                stats['errors'].append(f"{stock_name}: {str(e)}")
    
    except Exception as e:
        logger.error(f"AI 분석 실패: {e}")
        stats['errors'].append(str(e))
    
    logger.info("=" * 60)
    logger.info(f"🤖 전체 AI 분석 완료: {stats['analyzed']}/{stats['total']} 성공")
    if stats['failed'] > 0:
        logger.warning(f"   실패: {stats['failed']}개")
    logger.info("=" * 60)
    
    return stats


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    )
    
    from dotenv import load_dotenv
    load_dotenv()
    
    print("=" * 60)
    print("🤖 AI 분석 테스트")
    print("=" * 60)
    
    result = run_ai_analysis()
    print(f"\n결과: {result}")
