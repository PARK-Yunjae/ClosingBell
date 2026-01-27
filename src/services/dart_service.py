"""
DART OpenAPI 연동 서비스 v1.0

종가매매 AI 분석용 공시 정보 수집
- 최근 공시 목록 조회
- 위험 공시 자동 탐지 (정리매매, 관리종목, 유상증자 등)
- AI 프롬프트용 요약 생성

API 문서: https://opendart.fss.or.kr/guide/main.do
일일 한도: 40,000건
"""

import os
import logging
import requests
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# ============================================================
# 위험 공시 키워드 (AI가 "매도" 판단해야 할 공시들)
# ============================================================
RISK_KEYWORDS = {
    'critical': [  # 🚫 즉시 매도
        '정리매매', '상장폐지', '관리종목', '거래정지',
        '횡령', '배임', '분식회계', '감사의견거절',
        '자본잠식', '파산', '회생절차', '부도',
    ],
    'high': [  # ⚠️ 높은 위험
        '유상증자', '전환사채', '신주인수권', 'CB발행', 'BW발행',
        '최대주주변경', '경영권분쟁', '대표이사사임',
        '감사의견한정', '계속기업불확실',
    ],
    'medium': [  # 주의
        '무상증자', '주식분할', '합병', '분할',
        '자기주식취득', '자기주식처분',
    ],
}

# ============================================================
# DART 업종코드 → 한글명 매핑 (KSIC 기반)
# ============================================================
INDUSTRY_CODE_MAP = {
    # 제조업 - 전자/반도체
    '261': '반도체',
    '262': '전자부품',
    '263': '컴퓨터/주변장치',
    '264': '통신장비',
    '265': '영상/음향기기',
    '266': '의료/측정기기',
    '267': '광학기기',
    '268': '전기장비',
    
    # 제조업 - 자동차/기계
    '291': '자동차',
    '292': '자동차부품',
    '293': '트레일러',
    '301': '선박/보트',
    '302': '철도장비',
    '303': '항공기/우주선',
    '311': '가구',
    
    # 제조업 - 화학/소재
    '201': '기초화학',
    '202': '비료/질소화합물',
    '203': '합성수지/플라스틱',
    '204': '합성고무',
    '205': '기타화학제품',
    '206': '화학섬유',
    '210': '의약품',
    '211': '의료용품',
    '221': '고무제품',
    '222': '플라스틱제품',
    '231': '유리',
    '232': '도자기',
    '233': '시멘트/콘크리트',
    '241': '철강',
    '242': '비철금속',
    '243': '금속가공',
    '251': '구조용금속',
    '252': '무기/탱크',
    '259': '금속가공제품',
    
    # 제조업 - 식품/섬유
    '101': '도축/육가공',
    '102': '수산물가공',
    '103': '과일/채소가공',
    '104': '식용유지',
    '105': '낙농/아이스크림',
    '106': '곡물가공',
    '107': '기타식품',
    '108': '동물사료',
    '110': '음료',
    '120': '담배',
    '131': '방적',
    '132': '직물',
    '133': '섬유제품',
    '134': '편조원단',
    '139': '기타섬유',
    '141': '봉제의복',
    '142': '모피제품',
    '143': '편조의복',
    '151': '가죽/신발',
    '152': '가방/핸드백',
    '161': '제재/목재',
    '162': '나무제품',
    '171': '펄프/종이',
    '172': '종이제품',
    '181': '인쇄',
    '182': '기록매체',
    
    # 2차전지/에너지
    '269': '2차전지/축전지',
    '351': '전력/가스',
    '352': '가스공급',
    '360': '수도',
    '370': '하수/폐기물',
    
    # 건설/부동산
    '411': '건물건설',
    '412': '토목건설',
    '421': '기반조성',
    '422': '건물설비',
    '423': '전기/통신공사',
    '429': '기타건설',
    '681': '부동산',
    '682': '부동산개발',
    
    # 도소매
    '451': '자동차판매',
    '452': '자동차부품판매',
    '461': '산업용품도매',
    '462': '생활용품도매',
    '463': '기계/장비도매',
    '471': '종합소매',
    '472': '식품/음료소매',
    '473': '연료소매',
    '474': 'IT/통신기기소매',
    '475': '섬유/의류소매',
    
    # 운수/물류
    '491': '철도운송',
    '492': '육상운송',
    '493': '파이프라인',
    '501': '해상운송',
    '502': '내륙수상운송',
    '511': '항공운송',
    '521': '창고/보관',
    '529': '운수지원',
    
    # IT/통신/미디어
    '581': '소프트웨어',
    '582': '게임소프트웨어',
    '591': '영화/비디오',
    '592': '오디오/음반',
    '601': '라디오방송',
    '602': 'TV방송',
    '611': '유선통신',
    '612': '무선통신',
    '619': '기타통신',
    '620': 'IT서비스',
    '631': '정보서비스',
    '639': '기타정보서비스',
    
    # 금융/보험
    '641': '은행',
    '642': '지주회사',
    '649': '기타금융',
    '651': '보험',
    '652': '재보험',
    '653': '연금/공제',
    '661': '금융지원서비스',
    '662': '보험지원서비스',
    '663': '펀드운용',
    
    # 기타 서비스
    '701': '연구개발',
    '711': '광고',
    '712': '시장조사',
    '713': '경영컨설팅',
    '721': '건축/엔지니어링',
    '722': '기술시험분석',
    '731': '디자인',
    '732': '사진촬영',
    '741': '번역/통역',
    '751': '사업지원',
    '801': '교육',
    '851': '의료',
    '861': '스포츠/오락',
    
    # 기타
    '990': '기타',
}


def get_industry_name(code: str) -> str:
    """업종코드 → 한글명 변환
    
    Args:
        code: 업종코드 (예: '264', '26')
    
    Returns:
        업종명 (예: '통신장비')
    """
    if not code:
        return '-'
    
    code = str(code).strip()
    
    # 정확히 매칭
    if code in INDUSTRY_CODE_MAP:
        return INDUSTRY_CODE_MAP[code]
    
    # 앞 2자리로 대분류 매칭 시도
    if len(code) >= 2:
        prefix = code[:2]
        # 대분류 찾기
        for k, v in INDUSTRY_CODE_MAP.items():
            if k.startswith(prefix):
                return v
    
    return f"기타({code})"


class DartService:
    """DART OpenAPI 서비스"""
    
    BASE_URL = "https://opendart.fss.or.kr/api"
    
    def __init__(self, api_key: str = None):
        load_dotenv()
        self.api_key = api_key or os.getenv('DART_API_KEY')
        
        if not self.api_key:
            logger.warning("DART API 키가 설정되지 않았습니다.")
        
        # 종목코드 → DART 고유번호 매핑 캐시
        self._corp_code_cache: Dict[str, str] = {}
    
    def _request(self, endpoint: str, params: Dict) -> Optional[Dict]:
        """API 요청"""
        if not self.api_key:
            return None
        
        params['crtfc_key'] = self.api_key
        url = f"{self.BASE_URL}/{endpoint}"
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # DART API 상태 확인
            status = data.get('status', '000')
            if status != '000':
                message = data.get('message', 'Unknown error')
                logger.warning(f"DART API 에러: {status} - {message}")
                return None
            
            return data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"DART API 요청 실패: {e}")
            return None
        except Exception as e:
            logger.error(f"DART API 처리 실패: {e}")
            return None
    
    def get_corp_code(self, stock_code: str) -> Optional[str]:
        """종목코드(6자리) → DART 고유번호(8자리) 변환
        
        Args:
            stock_code: 종목코드 (예: '005930')
        
        Returns:
            DART 고유번호 (예: '00126380') 또는 None
        """
        # 캐시 확인
        if stock_code in self._corp_code_cache:
            return self._corp_code_cache[stock_code]
        
        # 전체 기업 목록에서 검색 (첫 호출 시 한 번만)
        if not self._corp_code_cache:
            self._load_corp_codes()
        
        return self._corp_code_cache.get(stock_code)
    
    def _load_corp_codes(self):
        """기업 고유번호 목록 로드 (ZIP 파일)"""
        import zipfile
        import io
        import xml.etree.ElementTree as ET
        
        try:
            url = f"{self.BASE_URL}/corpCode.xml"
            params = {'crtfc_key': self.api_key}
            
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            # ZIP 파일 해제
            with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
                with zf.open('CORPCODE.xml') as f:
                    tree = ET.parse(f)
                    root = tree.getroot()
                    
                    for corp in root.findall('.//list'):
                        stock_code = corp.findtext('stock_code', '').strip()
                        corp_code = corp.findtext('corp_code', '').strip()
                        
                        if stock_code:  # 상장사만 (stock_code가 있는 경우)
                            self._corp_code_cache[stock_code] = corp_code
            
            logger.info(f"DART 기업코드 로드: {len(self._corp_code_cache)}개")
            
        except Exception as e:
            logger.error(f"기업코드 로드 실패: {e}")
    
    def get_recent_disclosures(
        self, 
        stock_code: str, 
        days: int = 30,
        limit: int = 10
    ) -> List[Dict]:
        """최근 공시 목록 조회
        
        Args:
            stock_code: 종목코드
            days: 조회 기간 (일)
            limit: 최대 건수
        
        Returns:
            공시 목록 [{rcept_no, rcept_dt, report_nm, ...}, ...]
        """
        corp_code = self.get_corp_code(stock_code)
        if not corp_code:
            logger.warning(f"DART 고유번호 없음: {stock_code}")
            return []
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        params = {
            'corp_code': corp_code,
            'bgn_de': start_date.strftime('%Y%m%d'),
            'end_de': end_date.strftime('%Y%m%d'),
            'page_count': limit,
        }
        
        data = self._request('list.json', params)
        if not data:
            return []
        
        return data.get('list', [])
    
    def check_risk_disclosures(
        self, 
        stock_code: str,
        stock_name: str = "",
        days: int = 30
    ) -> Dict:
        """위험 공시 확인
        
        Args:
            stock_code: 종목코드
            stock_name: 종목명 (로깅용)
            days: 조회 기간
        
        Returns:
            {
                'has_critical_risk': bool,  # 즉시 매도 필요
                'has_high_risk': bool,      # 높은 위험
                'risk_level': '높음/보통/낮음',
                'risk_disclosures': [{'date': ..., 'title': ..., 'risk_type': ...}],
                'summary': '요약 문자열'
            }
        """
        result = {
            'has_critical_risk': False,
            'has_high_risk': False,
            'risk_level': '낮음',
            'risk_disclosures': [],
            'summary': '',
        }
        
        disclosures = self.get_recent_disclosures(stock_code, days=days)
        if not disclosures:
            result['summary'] = f"최근 {days}일 공시 없음"
            return result
        
        risk_items = []
        
        for disc in disclosures:
            title = disc.get('report_nm', '')
            date = disc.get('rcept_dt', '')
            
            # 위험 키워드 체크
            for keyword in RISK_KEYWORDS['critical']:
                if keyword in title:
                    result['has_critical_risk'] = True
                    risk_items.append({
                        'date': date,
                        'title': title,
                        'risk_type': 'critical',
                        'keyword': keyword,
                    })
                    break
            else:
                for keyword in RISK_KEYWORDS['high']:
                    if keyword in title:
                        result['has_high_risk'] = True
                        risk_items.append({
                            'date': date,
                            'title': title,
                            'risk_type': 'high',
                            'keyword': keyword,
                        })
                        break
        
        result['risk_disclosures'] = risk_items
        
        # 위험도 결정
        if result['has_critical_risk']:
            result['risk_level'] = '높음'
            result['summary'] = f"🚫 위험 공시 발견: {risk_items[0]['keyword']}"
        elif result['has_high_risk']:
            result['risk_level'] = '보통'  # AI가 추가 판단
            result['summary'] = f"⚠️ 주의 공시: {risk_items[0]['keyword']}"
        else:
            result['risk_level'] = '낮음'
            result['summary'] = f"✅ 최근 {days}일 위험 공시 없음 (총 {len(disclosures)}건)"
        
        logger.info(f"DART 위험 체크: {stock_name}({stock_code}) → {result['risk_level']}")
        
        return result
    
    def get_company_info(self, stock_code: str) -> Optional[Dict]:
        """기업 개황 조회
        
        Returns:
            {corp_name, ceo_nm, corp_cls, jurir_no, bizr_no, ...}
        """
        corp_code = self.get_corp_code(stock_code)
        if not corp_code:
            return None
        
        params = {'corp_code': corp_code}
        return self._request('company.json', params)
    
    def get_financial_info(
        self, 
        stock_code: str, 
        year: str = None,
        report_code: str = '11011'  # 사업보고서
    ) -> Optional[Dict]:
        """재무정보 조회
        
        Args:
            stock_code: 종목코드
            year: 사업연도 (기본: 전년도)
            report_code: 11011(사업), 11012(반기), 11013(1분기), 11014(3분기)
        
        Returns:
            재무제표 데이터
        """
        corp_code = self.get_corp_code(stock_code)
        if not corp_code:
            return None
        
        if not year:
            year = str(datetime.now().year - 1)
        
        params = {
            'corp_code': corp_code,
            'bsns_year': year,
            'reprt_code': report_code,
        }
        
        return self._request('fnlttSinglAcnt.json', params)
    
    def format_for_ai_prompt(
        self, 
        stock_code: str,
        stock_name: str = ""
    ) -> str:
        """AI 프롬프트용 DART 정보 포맷
        
        Returns:
            AI 프롬프트에 추가할 문자열
        """
        lines = []
        
        # 1. 위험 공시 체크
        risk_info = self.check_risk_disclosures(stock_code, stock_name)
        
        if risk_info['has_critical_risk']:
            lines.append(f"⚠️ [DART 공식] 위험 공시 발견!")
            for item in risk_info['risk_disclosures'][:3]:
                lines.append(f"  - {item['date']}: {item['title']}")
            lines.append("→ 정리매매/관리종목/상장폐지 위험 있음. 매도 권장.")
            
        elif risk_info['has_high_risk']:
            lines.append(f"⚠️ [DART 공식] 주의 공시:")
            for item in risk_info['risk_disclosures'][:3]:
                lines.append(f"  - {item['date']}: {item['title']}")
            lines.append("→ 유상증자/희석 위험 확인 필요")
            
        else:
            lines.append(f"✅ [DART] 최근 30일 위험 공시 없음")
        
        return "\n".join(lines)

    # ============================================================
    # Phase 1: 기업개황 조회 (v6.5)
    # ============================================================
    def get_company_info(self, stock_code: str) -> Optional[Dict]:
        """DART 기업개황 조회
        
        Args:
            stock_code: 종목코드 (6자리)
        
        Returns:
            {
                'corp_code': '00126380',
                'corp_name': '삼성전자',
                'corp_name_eng': 'SAMSUNG ELECTRONICS CO,.LTD',
                'stock_code': '005930',
                'ceo_nm': '한종희, 경계현',
                'corp_cls': 'Y',  # Y:유가, K:코스닥, N:코넥스
                'jurir_no': '1301110006246',
                'bizr_no': '1248100998',
                'adres': '경기도 수원시...',
                'hm_url': 'www.samsung.com',
                'ir_url': '',
                'phn_no': '031-200-1114',
                'fax_no': '031-200-7538',
                'induty_code': '264',
                'est_dt': '19690113',
                'acc_mt': '12',  # 결산월
            }
        """
        corp_code = self.get_corp_code(stock_code)
        if not corp_code:
            logger.warning(f"DART 고유번호 없음: {stock_code}")
            return None
        
        params = {'corp_code': corp_code}
        data = self._request('company.json', params)
        
        if not data:
            return None
        
        # 필요한 필드만 추출
        return {
            'corp_code': data.get('corp_code', ''),
            'corp_name': data.get('corp_name', ''),
            'corp_name_eng': data.get('corp_name_eng', ''),
            'stock_code': data.get('stock_code', stock_code),
            'ceo_nm': data.get('ceo_nm', ''),
            'corp_cls': data.get('corp_cls', ''),  # Y:유가, K:코스닥, N:코넥스
            'jurir_no': data.get('jurir_no', ''),
            'bizr_no': data.get('bizr_no', ''),
            'adres': data.get('adres', ''),
            'hm_url': data.get('hm_url', ''),
            'ir_url': data.get('ir_url', ''),
            'phn_no': data.get('phn_no', ''),
            'induty_code': data.get('induty_code', ''),
            'est_dt': data.get('est_dt', ''),
            'acc_mt': data.get('acc_mt', ''),
        }

    # ============================================================
    # Phase 1: 재무제표 요약 조회 (v6.5)
    # ============================================================
    def get_financial_summary(
        self, 
        stock_code: str, 
        year: str = None,
        report_code: str = '11011'  # 사업보고서
    ) -> Optional[Dict]:
        """DART 재무제표 요약 조회
        
        Args:
            stock_code: 종목코드
            year: 사업연도 (기본: 전년도)
            report_code: 
                - 11011: 사업보고서
                - 11012: 반기보고서
                - 11013: 1분기보고서
                - 11014: 3분기보고서
        
        Returns:
            {
                'fiscal_year': '2024',
                'revenue': 2796048,          # 매출액 (억원)
                'operating_profit': 65670,   # 영업이익 (억원)
                'net_income': 154873,        # 당기순이익 (억원)
                'total_equity': 3547133,     # 자본총계 (억원)
                'total_assets': 4555000,     # 자산총계 (억원)
                'report_code': '11011',
            }
        """
        corp_code = self.get_corp_code(stock_code)
        if not corp_code:
            return None
        
        if not year:
            year = str(datetime.now().year - 1)
        
        params = {
            'corp_code': corp_code,
            'bsns_year': year,
            'reprt_code': report_code,
        }
        
        data = self._request('fnlttSinglAcnt.json', params)
        if not data:
            # 사업보고서가 없으면 반기보고서 시도
            if report_code == '11011':
                return self.get_financial_summary(stock_code, year, '11012')
            return None
        
        items = data.get('list', [])
        if not items:
            return None
        
        result = {
            'fiscal_year': year,
            'report_code': report_code,
            'revenue': None,
            'operating_profit': None,
            'net_income': None,
            'total_equity': None,
            'total_assets': None,
        }
        
        # 연결재무제표 우선, 없으면 개별재무제표
        for item in items:
            account_nm = item.get('account_nm', '')
            fs_div = item.get('fs_div', '')  # CFS:연결, OFS:개별
            
            # 당기 금액 (억원 단위로 변환)
            try:
                amount_str = item.get('thstrm_amount', '0')
                if amount_str:
                    amount_str = amount_str.replace(',', '')
                    amount = int(amount_str) / 100000000  # 원 → 억원
                else:
                    amount = 0
            except (ValueError, TypeError):
                amount = 0
            
            # 연결재무제표 우선
            if fs_div == 'OFS' and result.get(self._get_field_name(account_nm)):
                continue
            
            field_name = self._get_field_name(account_nm)
            if field_name and amount:
                result[field_name] = round(amount, 0)
        
        return result
    
    def _get_field_name(self, account_nm: str) -> Optional[str]:
        """계정과목명 → 필드명 매핑"""
        mappings = {
            '매출액': 'revenue',
            '수익(매출액)': 'revenue',
            '영업수익': 'revenue',
            '영업이익': 'operating_profit',
            '영업이익(손실)': 'operating_profit',
            '당기순이익': 'net_income',
            '당기순이익(손실)': 'net_income',
            '자본총계': 'total_equity',
            '자산총계': 'total_assets',
        }
        return mappings.get(account_nm)

    # ============================================================
    # Phase 1: 통합 기업 프로필 (v6.5)
    # ============================================================
    def get_full_company_profile(
        self, 
        stock_code: str,
        stock_name: str = "",
        include_risk: bool = True,
        cache_to_db: bool = True
    ) -> Dict:
        """DART 기반 전체 기업 프로필 조회
        
        Args:
            stock_code: 종목코드
            stock_name: 종목명 (로깅용)
            include_risk: 위험공시 포함 여부
            cache_to_db: DB 캐시 저장 여부
        
        Returns:
            {
                'basic': {...},      # 기업개황
                'financial': {...},  # 재무요약
                'risk': {...},       # 위험공시 (옵션)
                'cached_at': '2026-01-27 15:30:00',
                'success': True/False,
            }
        """
        result = {
            'basic': None,
            'financial': None,
            'risk': None,
            'cached_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'success': False,
        }
        
        # 1. 기업개황
        try:
            result['basic'] = self.get_company_info(stock_code)
        except Exception as e:
            logger.warning(f"기업개황 조회 실패 ({stock_code}): {e}")
        
        # 2. 재무요약
        try:
            result['financial'] = self.get_financial_summary(stock_code)
        except Exception as e:
            logger.warning(f"재무요약 조회 실패 ({stock_code}): {e}")
        
        # 3. 위험공시
        if include_risk:
            try:
                result['risk'] = self.check_risk_disclosures(stock_code, stock_name)
            except Exception as e:
                logger.warning(f"위험공시 조회 실패 ({stock_code}): {e}")
        
        # 성공 여부
        result['success'] = result['basic'] is not None
        
        # 4. DB 캐시 저장
        if cache_to_db and result['success']:
            try:
                self._save_profile_to_db(stock_code, result)
            except Exception as e:
                logger.warning(f"프로필 DB 저장 실패 ({stock_code}): {e}")
        
        return result
    
    def _save_profile_to_db(self, stock_code: str, profile: Dict):
        """기업 프로필을 DB에 캐시 저장"""
        try:
            from src.infrastructure.repository import get_company_profile_repository
            repo = get_company_profile_repository()
            repo.upsert(stock_code, profile)
        except ImportError:
            logger.debug("company_profile_repository 미구현")
        except Exception as e:
            logger.warning(f"프로필 저장 실패: {e}")

    # ============================================================
    # Phase 1: AI 프롬프트용 전체 정보 (v6.5)
    # ============================================================
    def format_full_profile_for_ai(
        self, 
        stock_code: str,
        stock_name: str = ""
    ) -> str:
        """AI 프롬프트용 전체 DART 정보 포맷
        
        Returns:
            기업개황 + 재무 + 위험공시 문자열
        """
        profile = self.get_full_company_profile(stock_code, stock_name, cache_to_db=False)
        
        lines = []
        
        # 1. 기업개황
        basic = profile.get('basic')
        if basic:
            corp_cls_map = {'Y': '유가증권', 'K': '코스닥', 'N': '코넥스'}
            market = corp_cls_map.get(basic.get('corp_cls', ''), '-')
            
            # 업종코드 → 업종명 변환
            induty_code = basic.get('induty_code', '')
            induty_name = get_industry_name(induty_code)
            
            lines.append(f"[기업개황]")
            lines.append(f"• 회사명: {basic.get('corp_name', stock_name)}")
            lines.append(f"• 시장: {market}")
            lines.append(f"• 대표자: {basic.get('ceo_nm', '-')}")
            lines.append(f"• 업종: {induty_name}")
            lines.append(f"• 설립일: {basic.get('est_dt', '-')}")
            lines.append(f"• 결산월: {basic.get('acc_mt', '-')}월")
        
        # 2. 재무요약
        fin = profile.get('financial')
        if fin:
            lines.append(f"\n[재무요약 - {fin.get('fiscal_year', '-')}년]")
            
            revenue = fin.get('revenue')
            op = fin.get('operating_profit')
            net = fin.get('net_income')
            equity = fin.get('total_equity')
            
            if revenue:
                lines.append(f"• 매출액: {revenue:,.0f}억원")
            if op:
                lines.append(f"• 영업이익: {op:,.0f}억원")
            if net:
                lines.append(f"• 순이익: {net:,.0f}억원")
            if equity:
                lines.append(f"• 자본총계: {equity:,.0f}억원")
        
        # 3. 위험공시
        risk = profile.get('risk')
        if risk:
            lines.append(f"\n[DART 공시]")
            if risk.get('has_critical_risk'):
                lines.append(f"⚠️ 위험 공시 발견!")
                for item in risk.get('risk_disclosures', [])[:3]:
                    lines.append(f"  - {item['date']}: {item['title']}")
            elif risk.get('has_high_risk'):
                lines.append(f"⚠️ 주의 공시:")
                for item in risk.get('risk_disclosures', [])[:3]:
                    lines.append(f"  - {item['date']}: {item['title']}")
            else:
                lines.append(f"✅ 최근 30일 위험 공시 없음")
        
        return "\n".join(lines) if lines else "DART 정보 없음"


# 싱글톤 인스턴스
_dart_service: Optional[DartService] = None


def get_dart_service() -> DartService:
    """DART 서비스 인스턴스 반환"""
    global _dart_service
    if _dart_service is None:
        _dart_service = DartService()
    return _dart_service


# ============================================================
# 테스트
# ============================================================
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    
    # .env에서 DART_API_KEY 로드
    dart = get_dart_service()
    
    # 테스트: 삼성전자
    print("\n" + "="*50)
    print("삼성전자 (005930) DART 정보 테스트")
    print("="*50)
    
    # 1. 고유번호 조회
    corp_code = dart.get_corp_code('005930')
    print(f"\n[1] DART 고유번호: {corp_code}")
    
    # 2. 기업개황
    print("\n[2] 기업개황:")
    company = dart.get_company_info('005930')
    if company:
        print(f"  • 회사명: {company.get('corp_name')}")
        print(f"  • 대표자: {company.get('ceo_nm')}")
        print(f"  • 시장: {company.get('corp_cls')} (Y:유가, K:코스닥)")
        induty_code = company.get('induty_code', '')
        print(f"  • 업종: {get_industry_name(induty_code)} ({induty_code})")
        print(f"  • 설립일: {company.get('est_dt')}")
    
    # 3. 재무요약
    print("\n[3] 재무요약:")
    financial = dart.get_financial_summary('005930')
    if financial:
        print(f"  • 연도: {financial.get('fiscal_year')}")
        print(f"  • 매출액: {financial.get('revenue'):,.0f}억원" if financial.get('revenue') else "  • 매출액: -")
        print(f"  • 영업이익: {financial.get('operating_profit'):,.0f}억원" if financial.get('operating_profit') else "  • 영업이익: -")
        print(f"  • 순이익: {financial.get('net_income'):,.0f}억원" if financial.get('net_income') else "  • 순이익: -")
    
    # 4. 위험 공시 체크
    print("\n[4] 위험 공시:")
    risk = dart.check_risk_disclosures('005930', '삼성전자')
    print(f"  • 위험도: {risk['risk_level']}")
    print(f"  • 요약: {risk['summary']}")
    
    # 5. 최근 공시
    print("\n[5] 최근 공시 (3건):")
    disclosures = dart.get_recent_disclosures('005930', days=30, limit=5)
    for d in disclosures[:3]:
        print(f"  • {d.get('rcept_dt')}: {d.get('report_nm')}")
    
    # 6. 전체 프로필 (AI용)
    print("\n[6] AI 프롬프트용 전체 정보:")
    print("-" * 40)
    prompt_text = dart.format_full_profile_for_ai('005930', '삼성전자')
    print(prompt_text)
    print("-" * 40)
