"""
기업 정보 수집 서비스 v6.0
===========================

네이버 금융에서 기업 정보를 수집합니다.

수집 항목:
- market (KOSPI/KOSDAQ)
- sector (업종)
- market_cap (시가총액)
- per, pbr, eps, roe
- business_summary (사업내용)
- ceo_name, establishment_date
- revenue, operating_profit

사용:
    python main.py --run-company-info
    
    또는 코드에서:
    from src.services.company_service import run_company_info_collection
    run_company_info_collection()
"""

import re
import time
import logging
import urllib.request
from typing import Dict, Optional
from html import unescape

from src.infrastructure.repository import get_nomad_candidates_repository

logger = logging.getLogger(__name__)

# 상수
API_DELAY = 0.3  # 크롤링 간격 (초)


def clean_text(text: str) -> str:
    """텍스트 정리"""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = unescape(text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def parse_number(text: str) -> Optional[float]:
    """숫자 파싱 (억, 조 단위 처리)"""
    if not text:
        return None
    
    text = text.replace(',', '').replace(' ', '')
    
    multiplier = 1
    if '조' in text:
        multiplier = 10000  # 억 단위로 변환
        text = text.replace('조', '')
    elif '억' in text:
        multiplier = 1
        text = text.replace('억', '')
    
    try:
        return float(text) * multiplier
    except:
        return None


def fetch_naver_finance(stock_code: str) -> Dict:
    """
    네이버 금융에서 기업 정보 수집
    
    Args:
        stock_code: 종목코드 (6자리)
        
    Returns:
        기업 정보 딕셔너리
    """
    info = {
        'market': None,
        'sector': None,
        'market_cap': None,
        'per': None,
        'pbr': None,
        'eps': None,
        'roe': None,
        'business_summary': None,
        'establishment_date': None,
        'ceo_name': None,
        'revenue': None,
        'operating_profit': None,
    }
    
    try:
        # 1. 기본 정보 페이지
        url = f"https://finance.naver.com/item/main.naver?code={stock_code}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        request = urllib.request.Request(url, headers=headers)
        response = urllib.request.urlopen(request, timeout=10)
        html = response.read().decode('euc-kr', errors='ignore')
        
        # 시장 구분 (KOSPI/KOSDAQ)
        if 'kospi_link' in html or 'class="kospi"' in html.lower():
            info['market'] = 'KOSPI'
        elif 'kosdaq_link' in html or 'class="kosdaq"' in html.lower():
            info['market'] = 'KOSDAQ'
        
        # 업종
        sector_match = re.search(r'<em class="t_nm">([^<]+)</em>', html)
        if sector_match:
            info['sector'] = clean_text(sector_match.group(1))
        
        # 시가총액 (억원)
        cap_match = re.search(r'시가총액.*?<em>([0-9,]+)</em>.*?억원', html, re.DOTALL)
        if cap_match:
            info['market_cap'] = parse_number(cap_match.group(1))
        
        # PER
        per_match = re.search(r'PER.*?<em>([0-9,.]+)</em>', html, re.DOTALL)
        if per_match:
            try:
                info['per'] = float(per_match.group(1).replace(',', ''))
            except:
                pass
        
        # PBR
        pbr_match = re.search(r'PBR.*?<em>([0-9,.]+)</em>', html, re.DOTALL)
        if pbr_match:
            try:
                info['pbr'] = float(pbr_match.group(1).replace(',', ''))
            except:
                pass
        
        # EPS
        eps_match = re.search(r'EPS.*?<em>([0-9,.-]+)</em>', html, re.DOTALL)
        if eps_match:
            try:
                info['eps'] = float(eps_match.group(1).replace(',', ''))
            except:
                pass
        
        # ROE
        roe_match = re.search(r'ROE.*?<em>([0-9,.-]+)</em>', html, re.DOTALL)
        if roe_match:
            try:
                info['roe'] = float(roe_match.group(1).replace(',', ''))
            except:
                pass
        
        time.sleep(API_DELAY)
        
        # 2. 기업 개요 페이지
        url_company = f"https://finance.naver.com/item/coinfo.naver?code={stock_code}"
        request2 = urllib.request.Request(url_company, headers=headers)
        response2 = urllib.request.urlopen(request2, timeout=10)
        html2 = response2.read().decode('euc-kr', errors='ignore')
        
        # 대표자명
        ceo_match = re.search(r'대표자명.*?<td[^>]*>([^<]+)</td>', html2, re.DOTALL)
        if ceo_match:
            info['ceo_name'] = clean_text(ceo_match.group(1))
        
        # 설립일
        est_match = re.search(r'설립일.*?<td[^>]*>([^<]+)</td>', html2, re.DOTALL)
        if est_match:
            info['establishment_date'] = clean_text(est_match.group(1))
        
        # 업종 (백업)
        if not info['sector']:
            sector_match2 = re.search(r'업종.*?<td[^>]*>([^<]+)</td>', html2, re.DOTALL)
            if sector_match2:
                info['sector'] = clean_text(sector_match2.group(1))
        
        # 매출액
        revenue_match = re.search(r'매출액.*?([0-9,]+)억', html2, re.DOTALL)
        if revenue_match:
            info['revenue'] = parse_number(revenue_match.group(1))
        
        # 영업이익
        profit_match = re.search(r'영업이익.*?([0-9,.-]+)억', html2, re.DOTALL)
        if profit_match:
            info['operating_profit'] = parse_number(profit_match.group(1))
        
        # 사업내용 (간략)
        biz_match = re.search(r'기업개요.*?<p[^>]*>([^<]+)</p>', html2, re.DOTALL)
        if biz_match:
            summary = clean_text(biz_match.group(1))
            info['business_summary'] = summary[:500] if summary else None
        
        return info
        
    except Exception as e:
        logger.error(f"네이버 금융 크롤링 실패 [{stock_code}]: {e}")
        return info


def collect_company_info_for_candidate(candidate: Dict) -> bool:
    """
    단일 종목의 기업 정보 수집
    
    Args:
        candidate: nomad_candidates 레코드
        
    Returns:
        성공 여부
    """
    stock_code = candidate['stock_code']
    stock_name = candidate['stock_name']
    candidate_id = candidate['id']
    
    logger.info(f"  🏢 {stock_name} ({stock_code}) 기업정보 수집...")
    
    # 네이버 금융에서 정보 수집
    info = fetch_naver_finance(stock_code)
    
    if not any(info.values()):
        logger.warning(f"  ⚠️ {stock_name}: 기업정보 없음")
        return False
    
    # DB 업데이트
    try:
        repo = get_nomad_candidates_repository()
        repo.update_company_info_by_id(candidate_id, info)
        
        # 수집된 항목 카운트
        collected = sum(1 for v in info.values() if v is not None)
        logger.info(f"  ✅ {stock_name}: {collected}개 항목 저장")
        
        return True
        
    except Exception as e:
        logger.error(f"  기업정보 저장 실패: {e}")
        return False


def collect_company_info_for_candidates(limit: int = 600) -> Dict:
    """
    유목민 후보들의 기업 정보 수집
    
    Args:
        limit: 최대 종목 수
        
    Returns:
        수집 결과 통계
    """
    logger.info("=" * 60)
    logger.info("🏢 기업 정보 수집 시작")
    logger.info("=" * 60)
    
    repo = get_nomad_candidates_repository()
    
    # 기업정보 미수집 후보 조회
    candidates = repo.get_uncollected_company_info(limit=limit)
    
    if not candidates:
        logger.info("📭 기업정보 수집할 후보 없음")
        print("\n📭 기업정보 수집할 후보가 없습니다.")
        return {'total': 0, 'success': 0}
    
    logger.info(f"📋 기업정보 수집 대상: {len(candidates)}개 종목")
    print(f"\n📋 기업정보 수집 대상: {len(candidates)}개 종목\n")
    
    stats = {'total': len(candidates), 'success': 0}
    
    for i, candidate in enumerate(candidates[:limit]):
        print(f"[{i+1}/{min(len(candidates), limit)}] {candidate['stock_name']} ({candidate['stock_code']})")
        
        if collect_company_info_for_candidate(candidate):
            stats['success'] += 1
        
        time.sleep(API_DELAY)
    
    logger.info("=" * 60)
    logger.info(f"🏢 기업정보 수집 완료: {stats['success']}/{stats['total']}")
    logger.info("=" * 60)
    
    return stats


def run_company_info_collection() -> Dict:
    """
    기업 정보 수집 실행 (스케줄러용)
    """
    return collect_company_info_for_candidates(limit=600)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    )
    
    print("=" * 60)
    print("🏢 기업 정보 수집 테스트")
    print("=" * 60)
    
    # 테스트: 삼성전자
    info = fetch_naver_finance("005930")
    print("\n삼성전자 기업정보:")
    for k, v in info.items():
        if v:
            print(f"  {k}: {v}")
