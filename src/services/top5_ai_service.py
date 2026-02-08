"""
종가매매 TOP5 AI 분석 서비스 v7.0

뉴스는 메모리에서만 사용하고 DB 저장 안 함
AI 분석 결과(summary, risk_level, recommendation)만 DB 저장

v6.5.1 변경사항:
- PER/PBR 없을 때 테마·수급 중심 종목으로 분류
- 밸류에이션 컨텍스트 개선
"""

import os
import json
import logging
import requests
from typing import Dict, List, Optional, Tuple
from datetime import date
from bs4 import BeautifulSoup

from src.config.settings import settings
from src.services.http_utils import request_with_retry, redact_url, mask_text

from src.utils.news_utils import fetch_news_headlines

logger = logging.getLogger(__name__)


def format_market_cap(market_cap: float) -> str:
    """시가총액 포맷"""
    if not market_cap:
        return "-"
    if market_cap >= 10000:
        return f"{market_cap/10000:.1f}조"
    return f"{market_cap:,.0f}억"


def format_volume(volume: int) -> str:
    """거래량 포맷 (만주 단위)"""
    if not volume:
        return "-"
    if volume >= 100_000_000:  # 1억주 이상
        return f"{volume/100_000_000:.1f}억주"
    elif volume >= 10_000:  # 1만주 이상
        return f"{volume/10_000:.0f}만주"
    else:
        return f"{volume:,}주"


def format_valuation_for_top5(per, pbr) -> str:
    """TOP5용 밸류에이션 컨텍스트 (v6.5.1)"""
    has_per = per is not None and per > 0
    has_pbr = pbr is not None and pbr > 0
    
    if not has_per and not has_pbr:
        return "PER/PBR: 미제공 (적자 또는 신규상장) → 테마·수급 중심 종목"
    
    parts = []
    if has_per:
        parts.append(f"PER: {per:.1f}")
    else:
        parts.append("PER: 적자")
    
    if has_pbr:
        parts.append(f"PBR: {pbr:.1f}")
    else:
        parts.append("PBR: 미제공")
    
    return " | ".join(parts)


def fetch_naver_company_info(stock_code: str) -> Dict:
    """네이버 금융에서 기업정보 수집 (메모리)"""
    try:
        url = f"https://finance.naver.com/item/main.naver?code={stock_code}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = request_with_retry(
            "GET",
            url,
            headers=headers,
            timeout=10,
            max_retries=2,
            backoff=1.0,
            logger=logger,
            context=f"Naver Finance {redact_url(url)}",
        )
        if resp is None:
            return {}
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        info = {}
        
        # 시가총액
        market_cap_elem = soup.select_one('#_market_sum')
        if market_cap_elem:
            text = market_cap_elem.get_text(strip=True).replace(',', '').replace('억원', '')
            try:
                info['market_cap'] = float(text)
            except:
                pass
        
        # PER, PBR 등
        table = soup.select_one('table.per_table')
        if table:
            for row in table.select('tr'):
                cells = row.select('td, th')
                for i, cell in enumerate(cells):
                    text = cell.get_text(strip=True)
                    if 'PER' in text and i + 1 < len(cells):
                        try:
                            info['per'] = float(cells[i+1].get_text(strip=True).replace(',', ''))
                        except:
                            pass
                    if 'PBR' in text and i + 1 < len(cells):
                        try:
                            info['pbr'] = float(cells[i+1].get_text(strip=True).replace(',', ''))
                        except:
                            pass
        
        # 업종
        sector_elem = soup.select_one('div.sub_section h4 a')
        if sector_elem:
            info['sector'] = sector_elem.get_text(strip=True)
        
        return info
    except Exception as e:
        logger.warning(f"기업정보 수집 실패 ({stock_code}): {mask_text(str(e))}")
        return {}


def fetch_news_headlines(stock_name: str, limit: int = 5) -> List[Dict]:
    """네이버 검색 API로 뉴스 수집 (메모리만, DB 저장 X)"""
    try:
        from src.services.news_service import search_naver_news
        
        query = f"{stock_name} 주식"
        news_list = search_naver_news(query, display=limit, sort='date')
        
        if not news_list:
            return []
        
        # 형식 맞추기
        result = []
        for news in news_list[:limit]:
            result.append({
                'title': news.get('title', '').replace('<b>', '').replace('</b>', ''),
                'url': news.get('link', '')
            })
        
        return result
    except Exception as e:
        logger.warning(f"뉴스 수집 실패 ({stock_name}): {e}")
        return []


def generate_top5_ai_analysis(stock_data: Dict, company_info: Dict, news_list: List[Dict]) -> Tuple[Optional[Dict], Optional[str]]:
    """
    Gemini로 TOP5 종목 AI 분석
    
    Returns:
        (result_dict, error_message)
    """
    try:
        from google import genai
        from dotenv import load_dotenv
        
        load_dotenv()
        api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
        
        if not api_key:
            return None, "Gemini API 키가 설정되지 않았습니다."
        
        client = genai.Client(api_key=api_key)
        
        # 프롬프트 구성
        per = company_info.get('per')
        pbr = company_info.get('pbr')
        valuation_text = format_valuation_for_top5(per, pbr)
        
        stock_info = f"""
종목: {stock_data['stock_name']} ({stock_data['stock_code']})
점수: {stock_data.get('screen_score', 0):.1f}점 ({stock_data.get('grade', '-')}등급)
등락률: {stock_data.get('change_rate', 0):+.1f}%

업종: {stock_data.get('sector') or company_info.get('sector', '-')}
시가총액: {format_market_cap(company_info.get('market_cap') or stock_data.get('market_cap'))}
{valuation_text}

CCI: {stock_data.get('cci', 0):.0f}
RSI: {stock_data.get('rsi', '-')}
이격도(20): {stock_data.get('disparity_20', 0):.1f}%
연속양봉: {stock_data.get('consecutive_up', 0)}일
거래대금: {format_market_cap(stock_data.get('trading_value', 0))}
거래량: {format_volume(stock_data.get('volume', 0))}
"""
        
        news_text = ""
        if news_list:
            news_text = "\n최근 뉴스:\n"
            for news in news_list[:5]:
                news_text += f"- {news.get('title', '')}\n"
        
        prompt = f"""
다음 종목에 대해 종가매매 관점에서 분석해주세요.
특히 정리매매, 상장폐지, 횡령, 분식회계 등 위험 요소가 있는지 확인해주세요.

⚠️ PER/PBR이 없는 종목은:
- 적자 기업이거나 신규상장 종목입니다
- 실적 기반 밸류에이션이 어려우므로 테마·수급·모멘텀 관점에서 분석해주세요
- "PER이 제공되지 않아 판단 어렵다"가 아니라, 테마·수급 종목으로 다른 관점의 분석을 해주세요

{stock_info}
{news_text}

다음 형식으로 JSON으로 응답하세요:
{{
    "summary": "핵심 요약 (1-2문장)",
    "price_reason": "오늘 주가 급등 원인 추정 (1문장)",
    "investment_points": ["투자 포인트 1", "투자 포인트 2"],
    "risk_factors": ["리스크 1", "리스크 2"],
    "valuation_comment": "밸류에이션 의견 (PER/PBR 없으면 테마·수급 관점 코멘트)",
    "risk_level": "낮음/보통/높음 중 하나",
    "recommendation": "매수/관망/매도 중 하나"
}}

중요: 정리매매, 관리종목, 상장폐지 위험이 있으면 반드시 risk_level을 "높음"으로, recommendation을 "매도"로 설정하세요.
"""
        
        # settings에서 AI 설정 로드
        response = client.models.generate_content(
            model=settings.ai.model,
            contents=prompt,
            config={
                'max_output_tokens': settings.ai.max_output_tokens,
                'temperature': settings.ai.temperature,
            },
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
        return None, "google-genai 패키지가 설치되지 않았습니다."
    except json.JSONDecodeError as e:
        return None, f"AI 응답 파싱 실패: {e}"
    except Exception as e:
        return None, f"AI 분석 실패: {e}"


def analyze_top5_stocks(target_date: str = None, limit: int = 5) -> Dict:
    """
    종가매매 TOP5 AI 분석 실행
    
    Args:
        target_date: 분석 대상 날짜 (None이면 최신)
        limit: 분석할 종목 수
    
    Returns:
        {'analyzed': n, 'failed': m, 'errors': [...]}
    """
    from src.infrastructure.database import get_database
    
    db = get_database()
    stats = {'analyzed': 0, 'failed': 0, 'skipped': 0, 'errors': []}
    
    try:
        # 대상 날짜 결정
        if not target_date:
            cursor = db.execute("SELECT MAX(screen_date) FROM closing_top5_history")
            row = cursor.fetchone()
            target_date = row[0] if row else None
        
        if not target_date:
            logger.warning("분석할 TOP5 데이터가 없습니다.")
            return stats
        
        logger.info(f"=" * 60)
        logger.info(f"🤖 종가매매 TOP5 AI 분석 시작: {target_date}")
        logger.info(f"=" * 60)
        
        # TOP5 조회 (AI 분석 없는 것만)
        cursor = db.execute("""
            SELECT id, stock_code, stock_name, screen_score, grade,
                   cci, rsi, change_rate, disparity_20, consecutive_up,
                   volume_ratio_5, sector, trading_value, volume,
                   ai_summary, ai_recommendation
            FROM closing_top5_history
            WHERE screen_date = ?
            ORDER BY rank
            LIMIT ?
        """, (target_date, limit))
        
        stocks = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        
        for row in stocks:
            stock = dict(zip(columns, row))
            
            # 이미 분석된 종목 스킵 (JSON 형식의 ai_summary가 있으면 스킵)
            ai_summary_raw = stock.get('ai_summary', '')
            
            # JSON 형식인지 확인 (웹훅용 짧은 텍스트는 재분석)
            is_valid_json = False
            if ai_summary_raw and ai_summary_raw.strip():
                try:
                    parsed = json.loads(ai_summary_raw)
                    # JSON이고 필수 필드가 있으면 유효
                    if isinstance(parsed, dict) and parsed.get('summary'):
                        is_valid_json = True
                except json.JSONDecodeError:
                    pass  # JSON 아님 → 재분석 필요
            
            if is_valid_json:
                logger.info(f"  ⏭️ {stock['stock_name']} - 이미 분석됨 (스킵)")
                stats['skipped'] += 1
                continue
            
            logger.info(f"  🔍 {stock['stock_name']} ({stock['stock_code']}) 분석 중...")
            
            # 1. 네이버 기업정보 수집 (메모리)
            company_info = fetch_naver_company_info(stock['stock_code'])
            
            # 2. 네이버 뉴스 수집 (메모리만, API 사용)
            news_list = fetch_news_headlines(stock['stock_name'], limit=5)
            logger.info(f"     뉴스 {len(news_list)}개 수집 (메모리)")
            
            # 3. AI 분석
            result, error = generate_top5_ai_analysis(stock, company_info, news_list)
            
            if error:
                logger.error(f"     ❌ AI 분석 실패: {error}")
                stats['failed'] += 1
                stats['errors'].append(f"{stock['stock_name']}: {error}")
                continue
            
            # 4. DB에 AI 결과만 저장
            ai_summary = json.dumps(result, ensure_ascii=False)
            ai_risk_level = result.get('risk_level', '보통')
            ai_recommendation = result.get('recommendation', '관망')
            
            db.execute("""
                UPDATE closing_top5_history
                SET ai_summary = ?, ai_risk_level = ?, ai_recommendation = ?
                WHERE id = ?
            """, (ai_summary, ai_risk_level, ai_recommendation, stock['id']))
            
            risk_emoji = {'낮음': '✅', '보통': '⚠️', '높음': '🚫'}.get(ai_risk_level, '❓')
            logger.info(f"     ✅ 분석 완료: {ai_risk_level} {risk_emoji} / {ai_recommendation}")
            stats['analyzed'] += 1
        
        logger.info(f"=" * 60)
        logger.info(f"🤖 TOP5 AI 분석 완료: {stats['analyzed']}개 성공, {stats['failed']}개 실패, {stats['skipped']}개 스킵")
        logger.info(f"=" * 60)
        
        return stats
        
    except Exception as e:
        logger.error(f"TOP5 AI 분석 중 오류: {e}")
        stats['errors'].append(str(e))
        return stats


def run_top5_ai_analysis() -> Dict:
    """스케줄러/CLI용 실행 함수 (최신 1일)"""
    return analyze_top5_stocks()


def run_top5_ai_analysis_all(limit_per_day: int = 5) -> Dict:
    """백필용 - 전체 미분석 TOP5 AI 분석"""
    from src.infrastructure.database import get_database
    
    db = get_database()
    total_stats = {'analyzed': 0, 'failed': 0, 'skipped': 0, 'errors': []}
    
    # 미분석 날짜 조회 (ai_summary가 NULL이거나 JSON 아닌 짧은 텍스트)
    # JSON은 '{'로 시작하므로, '{'로 시작하지 않으면 재분석 대상
    rows = db.fetch_all("""
        SELECT DISTINCT screen_date 
        FROM closing_top5_history 
        WHERE ai_summary IS NULL 
           OR (ai_summary NOT LIKE '{%' AND ai_summary != '')
        ORDER BY screen_date
    """)
    
    dates = [row['screen_date'] for row in rows]
    
    if not dates:
        logger.info("✅ 모든 TOP5가 이미 AI 분석 완료됨")
        return total_stats
    
    logger.info(f"📅 미분석 날짜: {len(dates)}일")
    
    for i, target_date in enumerate(dates):
        logger.info(f"[{i+1}/{len(dates)}] {target_date} 분석 중...")
        
        result = analyze_top5_stocks(target_date=target_date, limit=limit_per_day)
        
        total_stats['analyzed'] += result.get('analyzed', 0)
        total_stats['failed'] += result.get('failed', 0)
        total_stats['skipped'] += result.get('skipped', 0)
        total_stats['errors'].extend(result.get('errors', []))
    
    logger.info(f"🤖 전체 TOP5 AI 분석 완료: {total_stats['analyzed']}개 성공")
    return total_stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    result = run_top5_ai_analysis()
    print(f"결과: {result}")
