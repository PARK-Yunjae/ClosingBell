"""
웹훅용 실시간 AI 분석 헬퍼

screener_service.py의 _send_alert에서 사용
종목 5개 기준 약 30초~2분 소요
"""

import os
import json
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def format_market_cap(market_cap: float) -> str:
    """시가총액 포맷"""
    if not market_cap:
        return "-"
    if market_cap >= 10000:
        return f"{market_cap/10000:.1f}조"
    return f"{market_cap:,.0f}억"


def analyze_single_stock_for_webhook(stock_data: Dict) -> Optional[Dict]:
    """단일 종목 AI 분석 (웹훅용 경량 버전) - DART 연동
    
    Args:
        stock_data: 종목 정보 딕셔너리
            - stock_code, stock_name, screen_score, grade
            - cci, rsi, change_rate, disparity_20, consecutive_up
            - trading_value, volume, sector
    
    Returns:
        AI 분석 결과 또는 None
        {
            'recommendation': '매수/관망/매도',
            'risk_level': '낮음/보통/높음',
            'summary': '핵심 요약'
        }
    """
    try:
        from google import genai
        from dotenv import load_dotenv
        
        load_dotenv()
        api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
        
        if not api_key:
            logger.warning("Gemini API 키 없음")
            return None
        
        client = genai.Client(api_key=api_key)
        
        # ============================================================
        # DART 공시 정보 수집 (v6.4)
        # ============================================================
        dart_info = ""
        dart_risk_level = None
        try:
            from src.services.dart_service import get_dart_service
            dart = get_dart_service()
            
            stock_code = stock_data.get('stock_code', '')
            stock_name = stock_data.get('stock_name', '')
            
            # 위험 공시 체크
            risk_result = dart.check_risk_disclosures(stock_code, stock_name, days=30)
            
            if risk_result['has_critical_risk']:
                # 🚫 즉시 매도 필요한 공시 발견
                dart_info = "\n[DART 공식 공시 - 위험!]\n"
                for item in risk_result['risk_disclosures'][:3]:
                    dart_info += f"⚠️ {item['date']}: {item['title']}\n"
                dart_info += "→ 정리매매/관리종목/상장폐지 위험. 반드시 '매도' 권장.\n"
                dart_risk_level = '높음'
                
            elif risk_result['has_high_risk']:
                # ⚠️ 주의 필요
                dart_info = "\n[DART 공식 공시 - 주의]\n"
                for item in risk_result['risk_disclosures'][:3]:
                    dart_info += f"⚠️ {item['date']}: {item['title']}\n"
                dart_info += "→ 유상증자/희석 위험 확인 필요.\n"
                dart_risk_level = '보통'
                
            else:
                dart_info = f"\n[DART] 최근 30일 위험 공시 없음 ✅\n"
                
        except ImportError:
            logger.debug("DART 서비스 미설치 - 스킵")
        except Exception as e:
            logger.warning(f"DART 조회 실패: {e}")
        
        # 프롬프트 구성 (DART 정보 포함)
        prompt = f"""
다음 종목의 종가매매 관점에서 빠르게 분석해주세요.

종목: {stock_data.get('stock_name', '')} ({stock_data.get('stock_code', '')})
점수: {stock_data.get('screen_score', 0):.1f}점 ({stock_data.get('grade', '-')}등급)
등락률: {stock_data.get('change_rate', 0):+.1f}%
섹터: {stock_data.get('sector', '-')}
시가총액: {format_market_cap(stock_data.get('market_cap'))}
CCI: {stock_data.get('cci', 0):.0f}
이격도(20): {stock_data.get('disparity_20', 0):.1f}%
연속양봉: {stock_data.get('consecutive_up', 0)}일
거래대금: {format_market_cap(stock_data.get('trading_value', 0))}
{dart_info}
**중요**: 
- DART에서 위험 공시가 발견되면 반드시 "매도"로 설정하세요.
- 유상증자, 전환사채 공시가 있으면 희석 위험으로 "관망" 또는 "매도"로 설정하세요.
- 정리매매, 관리종목, 상장폐지 위험이 있으면 반드시 "매도"로 설정하세요.

다음 형식으로 JSON만 응답하세요:
{{"recommendation": "매수/관망/매도 중 하나", "risk_level": "낮음/보통/높음 중 하나", "summary": "핵심 요약 1문장 (30자 이내)"}}
"""
        
        # max_output_tokens 설정으로 JSON 잘림 방지
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config={
                'max_output_tokens': 2048,  # 단일 종목용 (여유있게)
                'temperature': 0.3,
            },
        )
        result_text = response.text
        
        # JSON 파싱
        if '```json' in result_text:
            result_text = result_text.split('```json')[1].split('```')[0]
        elif '```' in result_text:
            result_text = result_text.split('```')[1].split('```')[0]
        
        result = json.loads(result_text.strip())
        return result
        
    except ImportError:
        logger.warning("google-genai 패키지 미설치")
        return None
    except json.JSONDecodeError as e:
        logger.warning(f"AI 응답 파싱 실패: {e}")
        return None
    except Exception as e:
        logger.warning(f"AI 분석 실패: {e}")
        return None


def analyze_top5_for_webhook(scores: List) -> Dict[str, Dict]:
    """TOP5 종목 웹훅용 AI 분석
    
    Args:
        scores: StockScoreV5 리스트 (최대 5개)
    
    Returns:
        {stock_code: {recommendation, risk_level, summary}}
    """
    results = {}
    
    for i, score in enumerate(scores[:5], 1):
        logger.info(f"  [{i}/5] {score.stock_name} AI 분석 중...")
        
        # 점수 객체에서 데이터 추출
        stock_data = {
            'stock_code': score.stock_code,
            'stock_name': score.stock_name,
            'screen_score': score.score_total,
            'grade': score.grade.value if hasattr(score.grade, 'value') else score.grade,
            'change_rate': score.change_rate,
            'cci': score.score_detail.raw_cci,
            'disparity_20': score.score_detail.raw_distance,
            'consecutive_up': score.score_detail.raw_consec_days,
            'trading_value': score.trading_value,
            'sector': getattr(score, '_sector', '-'),
            'market_cap': getattr(score, '_market_cap', 0),
        }
        
        ai_result = analyze_single_stock_for_webhook(stock_data)
        
        if ai_result:
            results[score.stock_code] = ai_result
            rec = ai_result.get('recommendation', '?')
            risk = ai_result.get('risk_level', '?')
            logger.info(f"    → {rec} / 위험도: {risk}")
        else:
            # AI 분석 실패 시 기본값
            results[score.stock_code] = {
                'recommendation': '관망',
                'risk_level': '보통',
                'summary': 'AI 분석 실패'
            }
            logger.warning(f"    → AI 분석 실패, 기본값 사용")
    
    return results


# ========================================
# screener_service.py _send_alert 수정 가이드
# ========================================
"""
screener_service.py의 _send_alert 메서드를 아래와 같이 수정하세요:

def _send_alert(self, result: Dict, is_preview: bool):
    '''알림 발송 (종가매매 TOP5) v6.4 - AI 추천 포함'''
    try:
        top_n = result["top_n"]
        cci_filtered = result.get("cci_filtered_out", 0)
        large_cap_top5 = result.get("large_cap_top5", [])
        leading_sectors_text = result.get("leading_sectors_text", "")
        
        if not top_n:
            self.discord_notifier.send_message("📊 종가매매: 적합한 종목 없음")
            return
        
        # v6.4: AI 분석 실행 (종목당 5~10초, 총 30초~1분)
        ai_results = {}
        try:
            from src.services.webhook_ai_helper import analyze_top5_for_webhook
            logger.info("🤖 웹훅용 AI 분석 시작...")
            ai_results = analyze_top5_for_webhook(top_n)
            logger.info(f"🤖 AI 분석 완료: {len(ai_results)}개")
        except Exception as e:
            logger.warning(f"AI 분석 실패 (웹훅은 계속 발송): {e}")
        
        # v6.4: AI 결과 포함 Embed 생성
        title = "[프리뷰] 종가매매 TOP5" if is_preview else "🔔 종가매매 TOP5"
        if cci_filtered > 0:
            title += f" (CCI과열 {cci_filtered}개 제외)"
        
        from src.domain.score_calculator_patch import format_discord_embed_with_ai
        embed = format_discord_embed_with_ai(
            top_n, 
            title=title,
            leading_sectors_text=leading_sectors_text,
            ai_results=ai_results,  # AI 결과 전달
        )
        
        success = self.discord_notifier.send_embed(embed)
        if success:
            logger.info("종가매매 Discord 발송 완료 (AI 포함)")
        else:
            logger.warning("종가매매 Discord 발송 실패")
        
        # 대기업 TOP5 별도 발송
        if large_cap_top5 and not is_preview:
            self._send_large_cap_alert(large_cap_top5)
            
    except Exception as e:
        logger.error(f"알림 에러: {e}")
"""

if __name__ == "__main__":
    # 테스트
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    
    # 더미 데이터로 테스트
    test_data = {
        'stock_code': '456010',
        'stock_name': '아이씨티케이',
        'screen_score': 92.9,
        'grade': 'S',
        'change_rate': 12.6,
        'cci': 152,
        'disparity_20': 7.1,
        'consecutive_up': 2,
        'trading_value': 432,
        'sector': '양자컴퓨터',
        'market_cap': 0,
    }
    
    print("테스트 AI 분석...")
    result = analyze_single_stock_for_webhook(test_data)
    print(f"결과: {result}")
