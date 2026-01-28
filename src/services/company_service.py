"""
기업 정보 수집 서비스 v6.5
===========================

v6.5: DART API 기반으로 변경 (네이버 크롤링은 fallback)

## 수집 항목 (DART)
- 기업개황: 회사명, 대표자, 업종코드, 설립일
- 재무요약: 매출액, 영업이익, 순이익, 자본총계
- 위험공시: 정리매매, 유상증자 등 자동 탐지

## 기존 네이버 수집 항목 (fallback용)

| 항목 | 소스 | 패턴 |
|------|------|------|
| 시가총액 | coinfo | id="_market_sum" |
| 시가총액순위 | coinfo | 코스피 <em>13</em>위 |
| PER | coinfo | id="_per" |
| EPS | coinfo | id="_eps" |
| PBR | coinfo | id="_pbr" |
| BPS | coinfo | PBR 다음 <em> |
| 외국인보유율 | coinfo | 외국인소진율 |
| 투자의견 | coinfo | <em>4.00</em>매수 |
| 목표주가 | coinfo | 목표주가</th>...<em> |
| 52주최고/최저 | coinfo | 52주최고...<em> |
| 기업개요 | coinfo | <p>동사는... |
| 업종 | main | 업종...<a> |
| 시장 | main | kospi_link |

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
from pathlib import Path
from typing import Dict, Optional, Any
from html import unescape
from dataclasses import dataclass, field, asdict
from datetime import datetime
import pandas as pd

from src.infrastructure.repository import get_nomad_candidates_repository

logger = logging.getLogger(__name__)

# 상수
API_DELAY = 0.3  # 크롤링 간격 (초)
BASE_URL = "https://finance.naver.com"
STOCK_MAPPING_PATH = Path(r"C:\Coding\data\stock_mapping.csv")

# 종목 매핑 캐시
_stock_mapping_cache: Optional[Dict[str, str]] = None

def get_sector_from_mapping(stock_code: str) -> Optional[str]:
    """stock_mapping.csv에서 업종 조회"""
    global _stock_mapping_cache
    
    if _stock_mapping_cache is None:
        try:
            if STOCK_MAPPING_PATH.exists():
                df = pd.read_csv(STOCK_MAPPING_PATH, encoding='utf-8-sig')
                df['code'] = df['code'].astype(str).str.zfill(6)
                _stock_mapping_cache = dict(zip(df['code'], df['sector']))
                logger.info(f"stock_mapping.csv 로드: {len(_stock_mapping_cache)}개 종목")
            else:
                _stock_mapping_cache = {}
                logger.warning(f"stock_mapping.csv 없음: {STOCK_MAPPING_PATH}")
        except Exception as e:
            logger.error(f"stock_mapping.csv 로드 실패: {e}")
            _stock_mapping_cache = {}
    
    return _stock_mapping_cache.get(stock_code.zfill(6))

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
}


@dataclass
class CompanyInfo:
    """기업 정보 데이터 클래스"""
    # 기본
    market: Optional[str] = None  # KOSPI/KOSDAQ
    sector: Optional[str] = None  # 업종
    
    # 시가총액
    market_cap: Optional[float] = None  # 억원
    market_cap_rank: Optional[int] = None  # 순위
    
    # 밸류에이션
    per: Optional[float] = None
    eps: Optional[float] = None
    pbr: Optional[float] = None
    bps: Optional[float] = None
    roe: Optional[float] = None
    
    # 컨센서스
    consensus_per: Optional[float] = None
    consensus_eps: Optional[float] = None
    
    # 외국인
    foreign_rate: Optional[float] = None  # 보유율 %
    foreign_shares: Optional[int] = None  # 보유주수
    
    # 투자의견
    analyst_opinion: Optional[float] = None  # 1~5
    analyst_recommend: Optional[str] = None  # 매수/매도/중립
    target_price: Optional[int] = None  # 목표주가
    
    # 52주
    high_52w: Optional[int] = None
    low_52w: Optional[int] = None
    
    # 배당
    dividend_yield: Optional[float] = None
    
    # 기업 상세
    business_summary: Optional[str] = None
    establishment_date: Optional[str] = None
    ceo_name: Optional[str] = None
    revenue: Optional[float] = None
    operating_profit: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환 (None 제외)"""
        return {k: v for k, v in asdict(self).items() if v is not None}


def clean_text(text: str) -> str:
    """텍스트 정리"""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = unescape(text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def parse_number(text: str) -> Optional[float]:
    """숫자 파싱 (쉼표, 공백 제거)"""
    if not text:
        return None
    try:
        clean = text.replace(',', '').replace(' ', '').replace('\t', '').replace('\n', '').replace('\r', '').strip()
        return float(clean)
    except:
        return None


def parse_int(text: str) -> Optional[int]:
    """정수 파싱"""
    num = parse_number(text)
    return int(num) if num is not None else None


def parse_market_cap(text: str) -> Optional[float]:
    """시가총액 파싱 (조/억 단위 처리)
    
    예: "50조 3,131" → 503131 (억원)
    """
    if not text:
        return None
    
    text = text.strip()
    
    if '조' in text:
        parts = text.split('조')
        trillion = parse_number(parts[0]) or 0
        billion = parse_number(parts[1]) if len(parts) > 1 else 0
        return trillion * 10000 + (billion or 0)
    else:
        return parse_number(text)


def fetch_html(url: str, encoding: str = 'euc-kr') -> Optional[str]:
    """HTML 가져오기"""
    try:
        request = urllib.request.Request(url, headers=HEADERS)
        response = urllib.request.urlopen(request, timeout=15)
        return response.read().decode(encoding, errors='ignore')
    except Exception as e:
        logger.warning(f"Fetch 실패: {url} - {e}")
        return None


def parse_coinfo_page(html: str) -> CompanyInfo:
    """
    coinfo.naver 페이지 파싱 (메인 데이터 소스)
    
    검증된 패턴 (2026.01.20):
    - 시가총액: id="_market_sum" → "50조 3,131"
    - PER: id="_per" → "24.21"
    - EPS: id="_eps" → "12,227"
    - PBR: id="_pbr" → "1.17"
    - 외국인소진율: "29.61%"
    - 투자의견: <em>4.00</em>매수
    - 목표주가: "298,929"
    - 52주최고/최저: "307,500" / "108,100"
    """
    info = CompanyInfo()
    
    # ===== 시가총액 =====
    cap_match = re.search(r'id="_market_sum">([^<]+)</em>억원', html, re.DOTALL)
    if cap_match:
        info.market_cap = parse_market_cap(cap_match.group(1))
    
    # 시가총액 순위
    rank_match = re.search(r'코스피\s*<em>(\d+)</em>위', html)
    if not rank_match:
        rank_match = re.search(r'코스닥\s*<em>(\d+)</em>위', html)
    if rank_match:
        info.market_cap_rank = int(rank_match.group(1))
    
    # ===== 밸류에이션 (ID 기반) =====
    # PER
    per_match = re.search(r'id="_per">([0-9,.]+)</em>', html)
    if per_match:
        val = parse_number(per_match.group(1))
        if val and 0 < val < 500:
            info.per = val
    
    # EPS
    eps_match = re.search(r'id="_eps">([0-9,.-]+)</em>', html)
    if eps_match:
        info.eps = parse_number(eps_match.group(1))
    
    # 추정 PER (컨센서스)
    cns_per_match = re.search(r'id="_cns_per">([0-9,.]+)</em>', html)
    if cns_per_match:
        val = parse_number(cns_per_match.group(1))
        if val and 0 < val < 500:
            info.consensus_per = val
    
    # 추정 EPS (컨센서스)
    cns_eps_match = re.search(r'id="_cns_eps">([0-9,.-]+)</em>', html)
    if cns_eps_match:
        info.consensus_eps = parse_number(cns_eps_match.group(1))
    
    # PBR
    pbr_match = re.search(r'id="_pbr">([0-9,.]+)</em>', html)
    if pbr_match:
        val = parse_number(pbr_match.group(1))
        if val and 0 < val < 50:
            info.pbr = val
    
    # BPS (PBR 행의 두 번째 값)
    bps_match = re.search(r'PBR</a></th>.*?<em[^>]*>[^<]+</em>.*?<em>([0-9,]+)</em>원', html, re.DOTALL)
    if bps_match:
        info.bps = parse_number(bps_match.group(1))
    
    # ===== 외국인 =====
    foreign_match = re.search(r'외국인소진율.*?<em>([0-9,.]+)%</em>', html, re.DOTALL)
    if foreign_match:
        info.foreign_rate = parse_number(foreign_match.group(1))
    
    # 외국인 보유주수
    foreign_shares_match = re.search(r'외국인보유주식수.*?<em>([0-9,]+)</em>', html, re.DOTALL)
    if foreign_shares_match:
        info.foreign_shares = parse_int(foreign_shares_match.group(1))
    
    # ===== 투자의견 =====
    opinion_match = re.search(r'투자의견.*?<em>([0-9,.]+)</em>\s*(매수|매도|중립|Buy|Sell|Hold)', html, re.DOTALL)
    if opinion_match:
        info.analyst_opinion = parse_number(opinion_match.group(1))
        recommend = opinion_match.group(2)
        if recommend in ['Buy', '매수']:
            info.analyst_recommend = '매수'
        elif recommend in ['Sell', '매도']:
            info.analyst_recommend = '매도'
        else:
            info.analyst_recommend = '중립'
    
    # 목표주가
    target_match = re.search(r'목표주가</th>.*?<em>([0-9,]+)</em>', html, re.DOTALL)
    if target_match:
        info.target_price = parse_int(target_match.group(1))
    
    # ===== 52주 최고/최저 =====
    high_low_match = re.search(r'52주최고.*?<em>([0-9,]+)</em>.*?52주최저.*?<em>([0-9,]+)</em>', html, re.DOTALL)
    if high_low_match:
        info.high_52w = parse_int(high_low_match.group(1))
        info.low_52w = parse_int(high_low_match.group(2))
    else:
        # 대안 패턴
        high_match = re.search(r'최고\s*<em>([0-9,]+)</em>', html)
        low_match = re.search(r'최저\s*<em>([0-9,]+)</em>', html)
        if high_match:
            info.high_52w = parse_int(high_match.group(1))
        if low_match:
            info.low_52w = parse_int(low_match.group(1))
    
    # ===== 배당수익률 =====
    div_match = re.search(r'배당수익률.*?<em>([0-9,.]+)%</em>', html, re.DOTALL)
    if div_match:
        info.dividend_yield = parse_number(div_match.group(1))
    
    # ===== 기업개요 =====
    summary_match = re.search(r'<p>(동사[^<]{10,500})</p>', html)
    if summary_match:
        info.business_summary = clean_text(summary_match.group(1))[:500]
    
    # ===== 대표자/설립일 =====
    ceo_match = re.search(r'대표자명.*?<td[^>]*>([^<]+)</td>', html, re.DOTALL)
    if ceo_match:
        info.ceo_name = clean_text(ceo_match.group(1))
    
    est_match = re.search(r'설립일.*?<td[^>]*>([^<]+)</td>', html, re.DOTALL)
    if est_match:
        info.establishment_date = clean_text(est_match.group(1))
    
    return info


def parse_main_page(html: str, info: CompanyInfo) -> CompanyInfo:
    """
    main.naver 페이지에서 추가 정보 파싱
    
    - 시장 구분 (KOSPI/KOSDAQ)
    - 업종
    - ROE
    """
    # 시장 구분
    if 'kospi_link' in html or 'class="kospi"' in html.lower():
        info.market = 'KOSPI'
    elif 'kosdaq_link' in html or 'class="kosdaq"' in html.lower():
        info.market = 'KOSDAQ'
    
    # 업종
    sector_match = re.search(r'업종[^<]*<a[^>]*>([^<]+)</a>', html)
    if not sector_match:
        sector_match = re.search(r'<em class="t_nm">([^<]+)</em>', html)
    if sector_match:
        sector_value = clean_text(sector_match.group(1))
        if sector_value and not sector_value.replace(',', '').replace('.', '').isdigit():
            info.sector = sector_value
    
    # ROE (main 페이지에서)
    roe_match = re.search(r'ROE.*?<em>([0-9,.-]+)</em>', html, re.DOTALL)
    if roe_match:
        val = parse_number(roe_match.group(1))
        if val and abs(val) < 200:
            info.roe = val
    
    # 매출액
    revenue_match = re.search(r'매출액.*?([0-9,]+)억', html, re.DOTALL)
    if revenue_match:
        info.revenue = parse_number(revenue_match.group(1))
    
    # 영업이익
    profit_match = re.search(r'영업이익.*?([0-9,.-]+)억', html, re.DOTALL)
    if profit_match:
        info.operating_profit = parse_number(profit_match.group(1))
    
    return info


def fetch_naver_finance(stock_code: str) -> Dict[str, Any]:
    """
    네이버 금융에서 기업 정보 수집 (통합)
    
    Args:
        stock_code: 종목코드 (6자리)
        
    Returns:
        기업 정보 딕셔너리
    """
    info = CompanyInfo()
    
    try:
        # 1. coinfo 페이지 (메인 데이터 소스)
        coinfo_url = f"{BASE_URL}/item/coinfo.naver?code={stock_code}"
        coinfo_html = fetch_html(coinfo_url)
        
        if coinfo_html:
            info = parse_coinfo_page(coinfo_html)
            logger.info(f"[{stock_code}] coinfo 파싱: 시총={info.market_cap}, PER={info.per}, 외국인={info.foreign_rate}%")
        
        time.sleep(API_DELAY)
        
        # 2. main 페이지 (추가 정보)
        main_url = f"{BASE_URL}/item/main.naver?code={stock_code}"
        main_html = fetch_html(main_url)
        
        if main_html:
            info = parse_main_page(main_html, info)
        
        # 3. 업종: stock_mapping.csv 우선 사용 (더 신뢰성 있음)
        mapping_sector = get_sector_from_mapping(stock_code)
        if mapping_sector:
            info.sector = mapping_sector
            logger.debug(f"[{stock_code}] 업종 from stock_mapping: {mapping_sector}")
        
        logger.info(f"[{stock_code}] 최종: 시장={info.market}, 업종={info.sector}")
        
        return info.to_dict()
        
    except Exception as e:
        logger.error(f"네이버 금융 크롤링 실패 [{stock_code}]: {e}")
        return info.to_dict()


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


def run_company_info_collection(limit: int = 100) -> Dict:
    """
    기업 정보 수집 실행 (스케줄러용)
    
    v6.5: DART 기반으로 변경 (네이버 크롤링 대체)
    """
    return collect_company_info_with_dart(limit=limit)


def collect_company_info_with_dart(limit: int = 100) -> Dict:
    """
    v6.5: DART API 기반 기업정보 수집
    
    Args:
        limit: 최대 종목 수
        
    Returns:
        수집 결과 통계
    """
    logger.info("=" * 60)
    logger.info("🏢 기업 정보 수집 시작 (DART)")
    logger.info("=" * 60)
    
    try:
        from src.services.dart_service import get_dart_service
        from src.infrastructure.repository import get_company_profile_repository
        
        dart = get_dart_service()
        profile_repo = get_company_profile_repository()
        
    except ImportError as e:
        logger.warning(f"DART 서비스 미설치: {e}")
        # Fallback: 기존 네이버 방식
        return collect_company_info_for_candidates(limit=limit)
    
    repo = get_nomad_candidates_repository()
    
    # 기업정보 미수집 후보 조회
    candidates = repo.get_uncollected_company_info(limit=limit)
    
    if not candidates:
        logger.info("📭 기업정보 수집할 후보 없음")
        return {'total': 0, 'success': 0, 'source': 'DART'}
    
    logger.info(f"📋 DART 기업정보 수집 대상: {len(candidates)}개 종목")
    
    stats = {'total': len(candidates), 'success': 0, 'source': 'DART'}
    
    for i, candidate in enumerate(candidates[:limit]):
        stock_code = candidate['stock_code']
        stock_name = candidate['stock_name']
        
        try:
            # DART 전체 프로필 조회 (캐시 저장 포함)
            profile = dart.get_full_company_profile(
                stock_code, 
                stock_name,
                include_risk=True,
                cache_to_db=True,
            )
            
            if profile.get('success'):
                # nomad_candidates 테이블에 기업정보 플래그 업데이트
                basic = profile.get('basic') or {}
                financial = profile.get('financial') or {}
                
                # v6.5.1: 네이버에서 PER/PBR/ROE 보충 수집
                per, pbr, roe = None, None, None
                try:
                    naver_info = fetch_naver_finance(stock_code)
                    per = naver_info.per
                    pbr = naver_info.pbr
                    roe = naver_info.roe
                except Exception as e:
                    logger.debug(f"네이버 PER/PBR/ROE 수집 실패 ({stock_code}): {e}")
                
                repo.update_company_info_by_id(
                    candidate_id=candidate.get('id'),
                    info={
                        'market': basic.get('corp_cls', ''),
                        'sector': basic.get('induty_code', ''),
                        'ceo_name': basic.get('ceo_nm', ''),  # ceo → ceo_name
                        'revenue': financial.get('revenue'),
                        'operating_profit': financial.get('operating_profit'),
                        'net_income': financial.get('net_income'),
                        # v6.5.1: PER/PBR/ROE 추가
                        'per': per,
                        'pbr': pbr,
                        'roe': roe,
                        'data_source': 'DART+NAVER',
                    }
                )
                stats['success'] += 1
                logger.debug(f"✅ {stock_name} DART 수집 완료")
            else:
                logger.debug(f"⚠️ {stock_name} DART 정보 없음")
                
        except Exception as e:
            logger.warning(f"❌ {stock_name} DART 수집 실패: {e}")
        
        # API 호출 간격 (DART는 빠르지만 예의상)
        time.sleep(0.2)
    
    logger.info("=" * 60)
    logger.info(f"🏢 DART 기업정보 수집 완료: {stats['success']}/{stats['total']}")
    logger.info("=" * 60)
    
    return stats


def run_company_info_collection_legacy() -> Dict:
    """
    기존 네이버 크롤링 방식 (fallback용)
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
    test_codes = ["005930", "028260", "035720"]
    
    for code in test_codes:
        print(f"\n--- {code} ---")
        info = fetch_naver_finance(code)
        for k, v in sorted(info.items()):
            if v is not None:
                print(f"  {k}: {v}")
        time.sleep(1)