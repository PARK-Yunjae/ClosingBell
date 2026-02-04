"""
키움증권 REST API 클라이언트

책임:
- OAuth 토큰 발급 및 갱신 (au10001)
- 일봉 데이터 조회 (ka10081)
- 현재가/기본정보 조회 (ka10001)
- 거래대금 상위 조회 (ka10032)
- 거래량 상위 조회 (ka10030)
- Rate Limit 핸들링
- Circuit Breaker (연속 실패 시 폴백)
"""

import json
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
import requests
from requests.exceptions import RequestException, Timeout

from src.config.settings import settings, BASE_DIR
from src.domain.models import DailyPrice, StockInfo, CurrentPrice, ScreenerError

logger = logging.getLogger(__name__)


# ============================================================
# 에러 코드 상수
# ============================================================
class KiwoomErrorCode:
    """키움 API 에러 코드"""
    TOKEN_ISSUE_FAILED = "KIWOOM_001"
    TOKEN_EXPIRED = "KIWOOM_002"
    RATE_LIMIT = "KIWOOM_003"
    API_ERROR = "KIWOOM_004"
    NETWORK_ERROR = "KIWOOM_005"
    TIMEOUT_ERROR = "KIWOOM_006"
    CIRCUIT_OPEN = "KIWOOM_007"


# ============================================================
# 토큰 캐시 관리
# ============================================================
@dataclass
class TokenCache:
    """토큰 캐시 데이터"""
    token: str
    expires_at: datetime
    
    def is_valid(self, buffer_seconds: int = 300) -> bool:
        """토큰 유효성 확인 (만료 5분 전부터 무효 처리)"""
        return datetime.now() < self.expires_at - timedelta(seconds=buffer_seconds)


class TokenManager:
    """토큰 관리자 - 메모리 + 파일 캐시"""
    
    CACHE_PATH = BASE_DIR / ".cache" / "kiwoom_token.json"
    
    def __init__(self):
        self._memory_cache: Optional[TokenCache] = None
        self._ensure_cache_dir()
    
    def _ensure_cache_dir(self):
        """캐시 디렉토리 생성"""
        self.CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    def get_cached_token(self) -> Optional[TokenCache]:
        """캐시된 토큰 조회 (메모리 -> 파일 순서)"""
        # 1. 메모리 캐시 확인
        if self._memory_cache and self._memory_cache.is_valid():
            return self._memory_cache
        
        # 2. 파일 캐시 확인
        if self.CACHE_PATH.exists():
            try:
                with open(self.CACHE_PATH, 'r') as f:
                    data = json.load(f)
                    expires_at = datetime.fromisoformat(data['expires_at'])
                    cache = TokenCache(token=data['token'], expires_at=expires_at)
                    if cache.is_valid():
                        self._memory_cache = cache
                        return cache
            except Exception as e:
                logger.warning(f"토큰 캐시 파일 읽기 실패: {e}")
        
        return None
    
    def save_token(self, token: str, expires_dt: str):
        """토큰 저장 (메모리 + 파일)
        
        Args:
            token: 접근 토큰
            expires_dt: 만료일시 (YYYYMMDDHHmmss 형식)
        """
        # expires_dt 파싱: "20241107083713" -> datetime
        try:
            expires_at = datetime.strptime(expires_dt, "%Y%m%d%H%M%S")
        except ValueError:
            # 파싱 실패 시 24시간 후로 설정
            expires_at = datetime.now() + timedelta(hours=24)
        
        cache = TokenCache(token=token, expires_at=expires_at)
        
        # 메모리 캐시
        self._memory_cache = cache
        
        # 파일 캐시
        try:
            with open(self.CACHE_PATH, 'w') as f:
                json.dump({
                    'token': token,
                    'expires_at': expires_at.isoformat()
                }, f)
        except Exception as e:
            logger.warning(f"토큰 캐시 파일 저장 실패: {e}")
    
    def clear(self):
        """캐시 초기화"""
        self._memory_cache = None
        if self.CACHE_PATH.exists():
            self.CACHE_PATH.unlink()


# ============================================================
# Circuit Breaker
# ============================================================
class CircuitBreaker:
    """연속 실패 시 일시 차단"""
    
    def __init__(self, failure_threshold: int = 3, reset_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.is_open = False
    
    def record_failure(self):
        """실패 기록"""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.failure_count >= self.failure_threshold:
            self.is_open = True
            logger.warning(
                f"🔴 Circuit Breaker OPEN - 연속 {self.failure_count}회 실패, "
                f"{self.reset_timeout}초 동안 키움 API 호출 스킵"
            )
    
    def record_success(self):
        """성공 기록"""
        if self.failure_count > 0:
            logger.info(f"✅ Circuit Breaker 복구 - 이전 실패 횟수: {self.failure_count}")
        self.failure_count = 0
        self.is_open = False
    
    def can_request(self) -> bool:
        """요청 가능 여부"""
        if not self.is_open:
            return True
        
        # 타임아웃 경과 시 half-open 상태로 전환
        if self.last_failure_time:
            elapsed = (datetime.now() - self.last_failure_time).total_seconds()
            if elapsed >= self.reset_timeout:
                logger.info("🟡 Circuit Breaker HALF-OPEN - 재시도 허용")
                return True
        
        return False


# ============================================================
# 메인 클라이언트
# ============================================================
class KiwoomRestClient:
    """키움증권 REST API 클라이언트"""
    
    # API 엔드포인트 (키움 REST API 문서 기준)
    ENDPOINTS = {
        'token': '/oauth2/token',              # au10001 토큰발급
        'stock_info': '/api/dostk/stkinfo',    # ka10001 주식기본정보
        'daily_chart': '/api/dostk/chart',     # ka10081 일봉차트
        'rank_info': '/api/dostk/rkinfo',      # ka10030/ka10032 거래량/거래대금 상위
    }
    
    # Rate Limit: 초당 10회 (안전하게 0.12초 간격)
    API_CALL_INTERVAL = 0.12
    REQUEST_TIMEOUT = 10
    MAX_RETRIES = 2
    
    def __init__(self):
        self.base_url = settings.kiwoom.base_url
        self.app_key = settings.kiwoom.app_key
        self.secret_key = settings.kiwoom.secret_key
        
        self._token_manager = TokenManager()
        self._circuit_breaker = CircuitBreaker()
        self._last_call_time: float = 0
    
    # ========================================
    # Rate Limit
    # ========================================
    def _wait_for_rate_limit(self):
        """Rate Limit 대기"""
        elapsed = time.time() - self._last_call_time
        if elapsed < self.API_CALL_INTERVAL:
            time.sleep(self.API_CALL_INTERVAL - elapsed)
        self._last_call_time = time.time()
    
    # ========================================
    # 토큰 관리
    # ========================================
    def _get_token(self) -> str:
        """OAuth 토큰 발급/갱신"""
        # 1. 캐시 확인
        cached = self._token_manager.get_cached_token()
        if cached:
            return cached.token
        
        # 2. 신규 발급
        url = f"{self.base_url}{self.ENDPOINTS['token']}"
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "api-id": "au10001",
        }
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "secretkey": self.secret_key,
        }
        
        try:
            self._wait_for_rate_limit()
            response = requests.post(
                url, headers=headers, json=body, 
                timeout=self.REQUEST_TIMEOUT
            )
            response.raise_for_status()
            
            data = response.json()
            
            # 응답 검증
            if data.get('return_code', -1) != 0:
                raise ScreenerError(
                    KiwoomErrorCode.TOKEN_ISSUE_FAILED,
                    f"토큰 발급 실패: {data.get('return_msg', 'Unknown error')}",
                    recoverable=True
                )
            
            token = data['token']
            expires_dt = data.get('expires_dt', '')
            
            self._token_manager.save_token(token, expires_dt)
            logger.info(f"✅ 키움 토큰 발급 성공, 만료: {expires_dt}")
            
            return token
            
        except requests.exceptions.RequestException as e:
            logger.error(f"토큰 발급 네트워크 오류: {e}")
            raise ScreenerError(
                KiwoomErrorCode.NETWORK_ERROR,
                f"토큰 발급 실패: {e}",
                recoverable=True
            )
    
    # ========================================
    # 공통 요청 래퍼
    # ========================================
    def _get_headers(self, tr_id: str) -> Dict[str, str]:
        """API 호출용 헤더 생성"""
        token = self._get_token()
        return {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {token}",
            "api-id": tr_id,
        }
    
    def _request(
        self,
        method: str,
        endpoint: str,
        tr_id: str,
        body: Optional[Dict] = None,
        retry_count: int = 0,
    ) -> Dict[str, Any]:
        """API 요청 공통 처리"""
        
        # Circuit Breaker 확인
        if not self._circuit_breaker.can_request():
            raise ScreenerError(
                KiwoomErrorCode.CIRCUIT_OPEN,
                "Circuit Breaker OPEN - 키움 API 일시 차단 중",
                recoverable=True
            )
        
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers(tr_id)
        
        try:
            self._wait_for_rate_limit()
            
            if method.upper() == "POST":
                response = requests.post(
                    url, headers=headers, json=body,
                    timeout=self.REQUEST_TIMEOUT
                )
            else:
                response = requests.get(
                    url, headers=headers, params=body,
                    timeout=self.REQUEST_TIMEOUT
                )
            
            # 429 Rate Limit
            if response.status_code == 429:
                if retry_count < self.MAX_RETRIES:
                    wait_time = 2 ** retry_count
                    logger.warning(f"Rate Limit 429 - {wait_time}초 후 재시도")
                    time.sleep(wait_time)
                    return self._request(method, endpoint, tr_id, body, retry_count + 1)
                else:
                    self._circuit_breaker.record_failure()
                    raise ScreenerError(
                        KiwoomErrorCode.RATE_LIMIT,
                        "Rate Limit 초과 - 재시도 실패",
                        recoverable=True
                    )
            
            # 5xx 서버 오류
            if response.status_code >= 500:
                if retry_count < self.MAX_RETRIES:
                    wait_time = 2 ** retry_count
                    logger.warning(f"서버 오류 {response.status_code} - {wait_time}초 후 재시도")
                    time.sleep(wait_time)
                    return self._request(method, endpoint, tr_id, body, retry_count + 1)
                else:
                    self._circuit_breaker.record_failure()
                    raise ScreenerError(
                        KiwoomErrorCode.API_ERROR,
                        f"서버 오류: {response.status_code}",
                        recoverable=True
                    )
            
            response.raise_for_status()
            data = response.json()
            
            # 응답 코드 검증
            if data.get('return_code', 0) != 0:
                logger.warning(f"API 응답 오류: {data.get('return_msg', 'Unknown')}")
            
            self._circuit_breaker.record_success()
            return data
            
        except Timeout:
            self._circuit_breaker.record_failure()
            raise ScreenerError(
                KiwoomErrorCode.TIMEOUT_ERROR,
                f"요청 타임아웃: {endpoint}",
                recoverable=True
            )
        except RequestException as e:
            self._circuit_breaker.record_failure()
            raise ScreenerError(
                KiwoomErrorCode.NETWORK_ERROR,
                f"네트워크 오류: {e}",
                recoverable=True
            )
    
    # ========================================
    # 일봉 데이터 조회 (ka10081)
    # ========================================
    def get_daily_prices(
        self, 
        stock_code: str, 
        count: int = 200
    ) -> List[DailyPrice]:
        """일봉 데이터 조회
        
        Args:
            stock_code: 종목코드 (6자리)
            count: 조회할 일수 (기본 200)
            
        Returns:
            DailyPrice 리스트 (최신순)
        """
        today = datetime.now().strftime("%Y%m%d")
        
        body = {
            "stk_cd": stock_code,
            "base_dt": today,
            "upd_stkpc_tp": "1",  # 수정주가 적용
        }
        
        data = self._request(
            "POST",
            self.ENDPOINTS['daily_chart'],
            "ka10081",
            body
        )
        
        prices = []
        chart_list = data.get('stk_dt_pole_chart_qry', [])
        
        for item in chart_list[:count]:
            try:
                # 키움 API 필드명: open_pric, high_pric, low_pric, cur_prc
                prices.append(DailyPrice(
                    date=item.get('dt', ''),
                    open=self._parse_int(item.get('open_pric', '0')),
                    high=self._parse_int(item.get('high_pric', '0')),
                    low=self._parse_int(item.get('low_pric', '0')),
                    close=self._parse_int(item.get('cur_prc', '0')),
                    volume=self._parse_int(item.get('trde_qty', '0')),
                ))
            except (ValueError, TypeError) as e:
                logger.warning(f"일봉 파싱 오류 ({stock_code}): {e}")
                continue
        
        return prices
    
    # ========================================
    # 현재가/기본정보 조회 (ka10001)
    # ========================================
    def get_current_price(self, stock_code: str) -> CurrentPrice:
        """현재가 및 기본정보 조회
        
        Args:
            stock_code: 종목코드 (6자리)
            
        Returns:
            CurrentPrice 객체
        """
        body = {"stk_cd": stock_code}
        
        data = self._request(
            "POST",
            self.ENDPOINTS['stock_info'],
            "ka10001",
            body
        )
        
        # 필드 파싱 (키움 API 필드명 기준)
        try:
            current_price = self._parse_int(data.get('cur_prc', '0'))
            change_rate = self._parse_float(data.get('flu_rt', '0'))
            volume = self._parse_int(data.get('trde_qty', '0'))
            
            # 시가총액: ka10001에는 직접 제공되지 않음
            market_cap = 0
            
            return CurrentPrice(
                code=stock_code,
                price=current_price,
                change=0,  # 키움 API에서 별도 제공 안 함
                change_rate=change_rate,
                trading_value=0.0,  # 별도 조회 필요
                volume=volume,
                market_cap=market_cap,
            )
        except Exception as e:
            logger.error(f"현재가 파싱 오류 ({stock_code}): {e}")
            raise
    
    # ========================================
    # 거래대금 상위 조회 (ka10032) - v7.0 연속조회 지원
    # ========================================
    def get_trading_value_rank(
        self, 
        market_type: str = "0",  # 0:전체, 1:코스피, 2:코스닥
        count: int = 300
    ) -> List[Dict[str, Any]]:
        """거래대금 상위 종목 조회 (연속조회로 최대 300개)
        
        Args:
            market_type: 시장구분 (0:전체, 1:코스피, 2:코스닥)
            count: 조회 개수 (최대 300, 100개 단위 페이지네이션)
            
        Returns:
            종목 정보 리스트 (trde_prica는 백만원 단위)
        """
        results = []
        next_key = ""
        cont_yn = "N"
        
        while len(results) < count:
            # 헤더 설정 (연속조회 시 cont-yn, next-key 추가)
            headers = self._get_headers("ka10032")
            if cont_yn == "Y" and next_key:
                headers["cont-yn"] = "Y"
                headers["next-key"] = next_key
            
            body = {
                "mrkt_tp": market_type,
                "mang_stk_incls": "N",
                "stex_tp": "K",
                "sort_tp": "1",
            }
            
            # 직접 요청 (연속조회 헤더 처리)
            try:
                self._wait_for_rate_limit()
                url = f"{self.base_url}{self.ENDPOINTS['rank_info']}"
                response = requests.post(url, headers=headers, json=body, timeout=self.REQUEST_TIMEOUT)
                response.raise_for_status()
                data = response.json()
                
                # 연속조회 정보 추출
                cont_yn = response.headers.get("cont-yn", "N")
                next_key = response.headers.get("next-key", "")
                
            except Exception as e:
                logger.warning(f"거래대금 상위 조회 오류: {e}")
                break
            
            rank_list = data.get('trde_prica_upper', [])
            if not rank_list:
                break
            
            for item in rank_list:
                if len(results) >= count:
                    break
                code = item.get('stk_cd', '').replace('A', '')
                results.append({
                    'code': code,
                    'name': item.get('stk_nm', ''),
                    'current_price': self._parse_int(item.get('cur_prc', '0')),
                    'change_rate': self._parse_float(item.get('flu_rt', '0')),
                    'volume': self._parse_int(item.get('now_trde_qty', '0')),
                    'trading_value': self._parse_int(item.get('trde_prica', '0')),
                    'rank': len(results) + 1,
                })
            
            # 연속조회 불가능하면 종료
            if cont_yn != "Y":
                break
        
        return results
    
    # ========================================
    # 거래량 상위 조회 (ka10030) - v7.0 연속조회 지원
    # ========================================
    def get_volume_rank(
        self, 
        market_type: str = "0",
        count: int = 150
    ) -> List[Dict[str, Any]]:
        """거래량 상위 종목 조회 (연속조회로 최대 150개)
        
        Args:
            market_type: 시장구분 (0:전체, 1:코스피, 2:코스닥)
            count: 조회 개수 (최대 150, 100개 단위 페이지네이션)
            
        Returns:
            종목 정보 리스트
        """
        results = []
        next_key = ""
        cont_yn = "N"
        
        while len(results) < count:
            # 헤더 설정 (연속조회 시 cont-yn, next-key 추가)
            headers = self._get_headers("ka10030")
            if cont_yn == "Y" and next_key:
                headers["cont-yn"] = "Y"
                headers["next-key"] = next_key
            
            body = {
                "mrkt_tp": market_type,
                "mang_stk_incls": "N",
                "stex_tp": "K",
                "sort_tp": "1",
                "trde_qty_tp": "1",
                "trde_prica_tp": "1",
                "crd_tp": "0",
                "pric_tp": "0",
                "mrkt_open_tp": "0",
            }
            
            # 직접 요청 (연속조회 헤더 처리)
            try:
                self._wait_for_rate_limit()
                url = f"{self.base_url}{self.ENDPOINTS['rank_info']}"
                response = requests.post(url, headers=headers, json=body, timeout=self.REQUEST_TIMEOUT)
                response.raise_for_status()
                data = response.json()
                
                # 연속조회 정보 추출
                cont_yn = response.headers.get("cont-yn", "N")
                next_key = response.headers.get("next-key", "")
                
            except Exception as e:
                logger.warning(f"거래량 상위 조회 오류: {e}")
                break
            
            rank_list = data.get('tdy_trde_qty_upper', [])
            if not rank_list:
                break
            
            for item in rank_list:
                if len(results) >= count:
                    break
                code = item.get('stk_cd', '').replace('A', '')
                results.append({
                    'code': code,
                    'name': item.get('stk_nm', ''),
                    'rank': len(results) + 1,
                    'volume': self._parse_int(item.get('trde_qty', '0')),
                })
            
            # 연속조회 불가능하면 종료
            if cont_yn != "Y":
                break
        
        return results
    
    # ========================================
    # 유니버스 조회 (거래대금 + 거래량 조합)
    # ========================================
    def get_rank_universe(
        self,
        min_trading_value: int = 15000,   # 백만원 단위 (150억 = 15000)
        min_change_rate: float = 1.0,
        max_change_rate: float = 30.0,
        min_price: int = 2000,
        max_price: int = 99999999,
        volume_rank_limit: int = 150,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
        """유니버스 조회 (TV200 대체)
        
        명세서 알고리즘:
        1) ka10032에서 300개 조회
        2) ka10030에서 150개 조회 → {code: rank} 딕셔너리
        3) 필터링:
           - volume_rank_dict에 존재 (거래량 150위 이내)
           - trde_prica >= 15000 (백만원 단위 = 150억)
           - 1.0 <= flu_rt <= 30.0
           - 2000 <= cur_prc <= 10000
        4) trde_prica desc 정렬 (이미 정렬되어 있음)
        
        Returns:
            (종목 정보 리스트, 코드→이름 딕셔너리)
        """
        logger.info("📊 키움 유니버스 조회 시작")
        
        # Step 1: 거래대금 상위 300개 조회
        trading_value_stocks = self.get_trading_value_rank(market_type="0", count=300)
        logger.info(f"  [Step1] ka10032 거래대금 상위: {len(trading_value_stocks)}개")
        
        # Step 2: 거래량 상위 150개 조회 → 딕셔너리
        volume_stocks = self.get_volume_rank(market_type="0", count=volume_rank_limit)
        volume_rank_dict = {item['code']: item['rank'] for item in volume_stocks}
        logger.info(f"  [Step2] ka10030 거래량 상위: {len(volume_stocks)}개")
        
        # Step 3: 필터링
        filtered = []
        names_dict = {}
        
        # 필터링 통계
        stats = {
            'volume_rank_fail': 0,
            'trading_value_fail': 0,
            'change_rate_fail': 0,
            'price_fail': 0,
            'passed': 0,
        }
        
        for stock in trading_value_stocks:
            code = stock['code']
            name = stock['name']
            
            # 조건 1: 거래량 150위 이내
            if code not in volume_rank_dict:
                stats['volume_rank_fail'] += 1
                continue
            
            # 조건 2: 거래대금 >= 150억 (백만원 단위로 15000)
            if stock['trading_value'] < min_trading_value:
                stats['trading_value_fail'] += 1
                continue
            
            # 조건 3: 등락률 1% ~ 30%
            change_rate = stock['change_rate']
            if not (min_change_rate <= change_rate <= max_change_rate):
                stats['change_rate_fail'] += 1
                continue
            
            # 조건 4: 가격 2,000 ~ 10,000원
            price = stock['current_price']
            if not (min_price <= price <= max_price):
                stats['price_fail'] += 1
                continue
            
            # 모든 조건 통과
            stats['passed'] += 1
            stock['volume_rank'] = volume_rank_dict[code]
            filtered.append(stock)
            names_dict[code] = name
        
        # 로그 (운영자가 수치만 봐도 이상 감지 가능)
        logger.info(
            f"  [Step3] 조건 필터링 결과:\n"
            f"    - 거래량순위 탈락: {stats['volume_rank_fail']}개\n"
            f"    - 거래대금 미달: {stats['trading_value_fail']}개\n"
            f"    - 등락률 범위외: {stats['change_rate_fail']}개\n"
            f"    - 가격 범위외: {stats['price_fail']}개\n"
            f"    - 최종 통과: {stats['passed']}개"
        )
        
        return filtered, names_dict
    
    # ========================================
    # 유틸리티
    # ========================================
    def _parse_int(self, value: str) -> int:
        """문자열을 정수로 변환"""
        try:
            return int(str(value).replace(',', '').replace('+', '').replace('-', '').strip())
        except (ValueError, TypeError):
            return 0
    
    def _parse_float(self, value: str) -> float:
        """문자열을 실수로 변환"""
        try:
            return float(str(value).replace('%', '').replace('+', '').strip())
        except (ValueError, TypeError):
            return 0.0
    
    def get_stock_name(self, stock_code: str) -> str:
        """종목명 조회"""
        try:
            price = self.get_current_price(stock_code)
            return ""  # CurrentPrice에 name 필드 없음
        except Exception:
            return ""


# ============================================================
# 팩토리 함수
# ============================================================
_client_instance: Optional[KiwoomRestClient] = None


def get_kiwoom_client() -> KiwoomRestClient:
    """키움 클라이언트 싱글톤 인스턴스"""
    global _client_instance
    if _client_instance is None:
        _client_instance = KiwoomRestClient()
    return _client_instance


# KIS 호환 별칭 (기존 코드 호환성)
def get_broker_client() -> KiwoomRestClient:
    """브로커 클라이언트 (키움)"""
    return get_kiwoom_client()