"""
한국투자증권 API 클라이언트

책임:
- OAuth 토큰 발급 및 갱신
- 일봉 데이터 조회
- 현재가 조회
- 거래대금 상위 종목 조회
- 조건검색(psearch) API
- Rate Limit 핸들링
- API 에러 변환
- 네트워크 타임아웃 구분 처리
"""

import json
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import requests
from requests.exceptions import (
    RequestException,
    ConnectionError,
    Timeout,
    HTTPError,
)

from src.config.settings import settings
from src.config.constants import (
    API_CALL_INTERVAL,
    API_MAX_RETRIES,
    API_RETRY_DELAY,
    TOKEN_REFRESH_BUFFER,
    MIN_TRADING_VALUE,
    EXCLUDED_STOCK_PATTERNS,
)
from src.domain.models import (
    DailyPrice,
    StockInfo,
    CurrentPrice,
    ScreenerError,
)

logger = logging.getLogger(__name__)


# 에러 코드 상수
class KISErrorCode:
    """KIS API 에러 코드"""
    TOKEN_ISSUE_FAILED = "KIS_001"
    TOKEN_EXPIRED = "KIS_002"
    RATE_LIMIT = "KIS_003"
    API_ERROR = "KIS_004"
    NETWORK_ERROR = "KIS_005"
    TIMEOUT_ERROR = "KIS_006"
    CONNECTION_ERROR = "KIS_007"


class KISClient:
    """한국투자증권 API 클라이언트"""
    
    def __init__(self):
        self.base_url = settings.kis.base_url
        self.app_key = settings.kis.app_key
        self.app_secret = settings.kis.app_secret
        self.account_no = settings.kis.account_no
        
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        self._last_call_time: float = 0
        
    def _wait_for_rate_limit(self):
        """Rate Limit 대기 (초당 4회)"""
        elapsed = time.time() - self._last_call_time
        if elapsed < API_CALL_INTERVAL:
            time.sleep(API_CALL_INTERVAL - elapsed)
        self._last_call_time = time.time()
    
    def _get_token(self) -> str:
        """OAuth 토큰 발급/갱신"""
        # 토큰이 유효하면 재사용
        if self._access_token and self._token_expires_at:
            if datetime.now() < self._token_expires_at - timedelta(seconds=TOKEN_REFRESH_BUFFER):
                return self._access_token
        
        url = f"{self.base_url}/oauth2/tokenP"
        headers = {"Content-Type": "application/json"}
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        
        try:
            self._wait_for_rate_limit()
            response = requests.post(url, headers=headers, json=body, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            self._access_token = data["access_token"]
            expires_in = int(data.get("expires_in", 86400))
            self._token_expires_at = datetime.now() + timedelta(seconds=expires_in)
            
            logger.info(f"토큰 발급 성공, 만료: {self._token_expires_at}")
            return self._access_token
            
        except requests.exceptions.RequestException as e:
            logger.error(f"토큰 발급 실패: {e}")
            raise ScreenerError("KIS_001", f"토큰 발급 실패: {e}", recoverable=True)
    
    def _get_headers(self, tr_id: str) -> Dict[str, str]:
        """API 호출용 헤더 생성"""
        token = self._get_token()
        return {
            "Content-Type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
        }
    
    def _request(
        self,
        method: str,
        endpoint: str,
        tr_id: str,
        params: Optional[Dict] = None,
        body: Optional[Dict] = None,
        retry_count: int = 0,
    ) -> Dict[str, Any]:
        """API 요청 공통 처리
        
        네트워크 에러 타입별 구분 처리:
        - Timeout: 응답 지연 (재시도)
        - ConnectionError: 네트워크 연결 실패 (재시도)
        - HTTPError: HTTP 상태 코드 에러
        """
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers(tr_id)
        
        # 요청 시작 시간 기록
        start_time = time.time()
        
        try:
            self._wait_for_rate_limit()
            
            if method.upper() == "GET":
                response = requests.get(url, headers=headers, params=params, timeout=15)
            else:
                response = requests.post(url, headers=headers, json=body, timeout=15)
            
            # 요청 소요 시간 로깅
            elapsed = time.time() - start_time
            logger.debug(f"API 요청 완료 [{endpoint}] (소요: {elapsed:.3f}초)")
            
            # Rate Limit 처리
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", API_RETRY_DELAY))
                logger.warning(f"Rate Limit 도달, {retry_after}초 대기 (재시도: {retry_count + 1}/{API_MAX_RETRIES})")
                time.sleep(retry_after)
                if retry_count < API_MAX_RETRIES:
                    return self._request(method, endpoint, tr_id, params, body, retry_count + 1)
                raise ScreenerError(
                    KISErrorCode.RATE_LIMIT,
                    "요청 한도 초과 (Rate Limit)",
                    recoverable=True,
                )
            
            # 토큰 만료 처리
            if response.status_code == 401:
                logger.warning(f"토큰 만료, 재발급 시도 (재시도: {retry_count + 1}/{API_MAX_RETRIES})")
                self._access_token = None
                self._token_expires_at = None
                if retry_count < API_MAX_RETRIES:
                    return self._request(method, endpoint, tr_id, params, body, retry_count + 1)
                raise ScreenerError(
                    KISErrorCode.TOKEN_EXPIRED,
                    "토큰 만료 - 재발급 실패",
                    recoverable=True,
                )
            
            response.raise_for_status()
            data = response.json()
            
            # API 응답 코드 확인
            rt_cd = data.get("rt_cd", "0")
            if rt_cd != "0":
                msg = data.get("msg1", "알 수 없는 에러")
                msg_cd = data.get("msg_cd", "")
                logger.error(f"API 에러: [{msg_cd}] {msg}")
                raise ScreenerError(
                    KISErrorCode.API_ERROR,
                    f"[{msg_cd}] {msg}",
                    recoverable=False,
                )
            
            return data
        
        # 타임아웃 에러 (별도 처리)
        except Timeout as e:
            elapsed = time.time() - start_time
            logger.warning(
                f"API 타임아웃 [{endpoint}] (소요: {elapsed:.1f}초, 재시도: {retry_count + 1}/{API_MAX_RETRIES})"
            )
            if retry_count < API_MAX_RETRIES:
                time.sleep(API_RETRY_DELAY)
                return self._request(method, endpoint, tr_id, params, body, retry_count + 1)
            raise ScreenerError(
                KISErrorCode.TIMEOUT_ERROR,
                f"API 타임아웃 (15초 초과): {endpoint}",
                recoverable=True,
            )
        
        # 연결 에러 (별도 처리)
        except ConnectionError as e:
            elapsed = time.time() - start_time
            logger.warning(
                f"네트워크 연결 실패 [{endpoint}] (소요: {elapsed:.1f}초, 재시도: {retry_count + 1}/{API_MAX_RETRIES}): {e}"
            )
            if retry_count < API_MAX_RETRIES:
                time.sleep(API_RETRY_DELAY * 2)  # 연결 에러는 더 오래 대기
                return self._request(method, endpoint, tr_id, params, body, retry_count + 1)
            raise ScreenerError(
                KISErrorCode.CONNECTION_ERROR,
                f"네트워크 연결 실패: {e}",
                recoverable=True,
            )
        
        # HTTP 에러
        except HTTPError as e:
            elapsed = time.time() - start_time
            logger.error(f"HTTP 에러 [{endpoint}] (소요: {elapsed:.1f}초): {e}")
            raise ScreenerError(
                KISErrorCode.NETWORK_ERROR,
                f"HTTP 에러: {e}",
                recoverable=False,
            )
        
        # 기타 요청 에러
        except RequestException as e:
            elapsed = time.time() - start_time
            logger.error(
                f"API 요청 실패 [{endpoint}] (소요: {elapsed:.1f}초, 재시도: {retry_count + 1}/{API_MAX_RETRIES}): {e}",
                exc_info=True,
            )
            if retry_count < API_MAX_RETRIES:
                time.sleep(API_RETRY_DELAY)
                return self._request(method, endpoint, tr_id, params, body, retry_count + 1)
            raise ScreenerError(
                KISErrorCode.NETWORK_ERROR,
                f"API 호출 실패: {e}",
                recoverable=True,
            )
    
    def get_daily_prices(
        self,
        stock_code: str,
        count: int = 30,
    ) -> List[DailyPrice]:
        """일봉 데이터 조회
        
        Args:
            stock_code: 종목코드 (6자리)
            count: 조회 일수
            
        Returns:
            일봉 데이터 리스트 (오래된 순)
        """
        endpoint = "/uapi/domestic-stock/v1/quotations/inquire-daily-price"
        tr_id = "FHKST01010400"
        
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code.zfill(6),
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "0",  # 수정주가
        }
        
        data = self._request("GET", endpoint, tr_id, params=params)
        output = data.get("output", [])
        
        prices = []
        for item in output[:count]:
            try:
                dt = datetime.strptime(item["stck_bsop_date"], "%Y%m%d").date()
                price = DailyPrice(
                    date=dt,
                    open=int(item.get("stck_oprc", 0)),
                    high=int(item.get("stck_hgpr", 0)),
                    low=int(item.get("stck_lwpr", 0)),
                    close=int(item.get("stck_clpr", 0)),
                    volume=int(item.get("acml_vol", 0)),
                    trading_value=float(item.get("acml_tr_pbmn", 0)),
                )
                prices.append(price)
            except (ValueError, KeyError) as e:
                logger.warning(f"일봉 데이터 파싱 오류 ({stock_code}): {e}")
                continue
        
        # 오래된 순으로 정렬
        prices.reverse()
        return prices
    
    def get_current_price(self, stock_code: str) -> CurrentPrice:
        """현재가 조회
        
        Args:
            stock_code: 종목코드 (6자리)
            
        Returns:
            현재가 정보
        """
        endpoint = "/uapi/domestic-stock/v1/quotations/inquire-price"
        tr_id = "FHKST01010100"
        
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code.zfill(6),
        }
        
        data = self._request("GET", endpoint, tr_id, params=params)
        output = data.get("output", {})
        
        return CurrentPrice(
            code=stock_code.zfill(6),
            price=int(output.get("stck_prpr", 0)),
            change=int(output.get("prdy_vrss", 0)),
            change_rate=float(output.get("prdy_ctrt", 0)),
            trading_value=float(output.get("acml_tr_pbmn", 0)),
            volume=int(output.get("acml_vol", 0)),
        )
    
    def get_top_trading_value_stocks(
        self,
        min_trading_value: float = MIN_TRADING_VALUE,
        limit: int = 200,
    ) -> List[StockInfo]:
        """거래대금 상위 종목 조회
        
        장중: volume-rank API 사용
        장마감 후: 주요 종목 리스트에서 현재가 조회로 필터링
        
        Args:
            min_trading_value: 최소 거래대금 (억원)
            limit: 조회 개수
            
        Returns:
            종목 정보 리스트
        """
        # 1. volume-rank API 시도
        stocks = self._get_volume_rank_stocks(min_trading_value, limit)
        
        # 2. API 응답이 부족하면 주요 종목 리스트에서 추가 조회
        # (volume-rank API는 최대 30개 정도만 반환하므로 보완 필요)
        if len(stocks) < 50:
            logger.info(f"volume-rank API 응답 ({len(stocks)}개), 주요 종목 리스트로 보완 중...")
            existing_codes = {s.code for s in stocks}
            additional = self._get_stocks_from_major_list(min_trading_value, limit)
            
            # 중복 제거하고 추가
            for stock in additional:
                if stock.code not in existing_codes:
                    stocks.append(stock)
                    existing_codes.add(stock.code)
        
        logger.info(f"거래대금 {min_trading_value}억 이상 종목: {len(stocks)}개")
        return stocks
    
    def _get_volume_rank_stocks(
            self,
            min_trading_value: float,
            limit: int,
        ) -> List[StockInfo]:
            """거래대금 상위 API를 통해 1차 수집 (통합 조회)"""
            all_stocks = []
            existing_codes = set()
            
            # J(전체)로 한 번에 조회 (시장 구분 로직 제거)
            logger.info("거래대금 상위 API 통합 조회 시작 (Code: J)")
            
            try:
                # 여기서 "J"를 넘기지만, 실제 아래 함수에서 J로 고정해서 쓸 겁니다.
                # limit은 API가 주는 최대치(보통 100개)까지 넉넉히 요청
                stocks = self._get_volume_rank_by_market("J", min_trading_value, 100)
                
                for stock in stocks:
                    if stock.code not in existing_codes:
                        all_stocks.append(stock)
                        existing_codes.add(stock.code)
                        
            except Exception as e:
                logger.warning(f"API 조회 중 에러 발생: {e}")

            logger.info(f"API를 통해 발견한 후보 종목: {len(all_stocks)}개")
            
            # 우리가 원하는 limit 개수만큼 자르기
            return all_stocks[:limit]
    
    def _get_volume_rank_by_market(
        self,
        market_code: str,
        min_trading_value: float,
        limit: int,
    ) -> List[StockInfo]:
        """특정 시장의 거래대금 상위 종목 조회"""
        endpoint = "/uapi/domestic-stock/v1/quotations/volume-rank"
        tr_id = "FHPST01710000"
        
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",  # J:전체, Q:코스닥
            "FID_COND_SCR_DIV_CODE": "20171",  # 거래대금
            "FID_INPUT_ISCD": "0000",  # 전체
            "FID_DIV_CLS_CODE": "0",
            "FID_BLNG_CLS_CODE": "3",       # (0:거래량 -> 3:거래대금순)
            "FID_TRGT_CLS_CODE": "111111111",  # 전체
            "FID_TRGT_EXLS_CLS_CODE": "000000",
            "FID_INPUT_PRICE_1": "",
            "FID_INPUT_PRICE_2": "",
            "FID_VOL_CNT": "",
            "FID_INPUT_DATE_1": "",
        }
        
        try:
            data = self._request("GET", endpoint, tr_id, params=params)
            output = data.get("output", [])
        except Exception as e:
            logger.warning(f"volume-rank API 호출 실패 (market={market_code}): {e}")
            return []
        
        stocks = []
        for item in output[:limit]:
            try:
                # 거래대금 필터링 (억원 단위)
                trading_value = float(item.get("acml_tr_pbmn", 0)) / 100_000_000
                if trading_value < min_trading_value:
                    continue
                
                code = item.get("mksc_shrn_iscd", "").zfill(6)
                name = item.get("hts_kor_isnm", "")
                
                # 제외 종목 필터링
                if self._should_exclude(name, code):
                    continue
                
                # 시장 구분
                market = "KOSDAQ" if market_code == "Q" else "KOSPI"
                
                stocks.append(StockInfo(code=code, name=name, market=market))
                
            except (ValueError, KeyError) as e:
                logger.warning(f"종목 정보 파싱 오류: {e}")
                continue
        
        return stocks
    
    def _get_stocks_from_major_list(
        self,
        min_trading_value: float,
        limit: int,
    ) -> List[StockInfo]:
        """주요 종목 리스트에서 거래대금 기준 필터링"""
        # KOSPI200 + KOSDAQ 대표 종목
        MAJOR_STOCKS = [
            # KOSPI 대형주
            ("005930", "삼성전자", "KOSPI"),
            ("000660", "SK하이닉스", "KOSPI"),
            ("373220", "LG에너지솔루션", "KOSPI"),
            ("207940", "삼성바이오로직스", "KOSPI"),
            ("005380", "현대차", "KOSPI"),
            ("006400", "삼성SDI", "KOSPI"),
            ("051910", "LG화학", "KOSPI"),
            ("000270", "기아", "KOSPI"),
            ("035420", "NAVER", "KOSPI"),
            ("068270", "셀트리온", "KOSPI"),
            ("005490", "POSCO홀딩스", "KOSPI"),
            ("012330", "현대모비스", "KOSPI"),
            ("055550", "신한지주", "KOSPI"),
            ("035720", "카카오", "KOSPI"),
            ("105560", "KB금융", "KOSPI"),
            ("003670", "포스코퓨처엠", "KOSPI"),
            ("066570", "LG전자", "KOSPI"),
            ("096770", "SK이노베이션", "KOSPI"),
            ("003550", "LG", "KOSPI"),
            ("034730", "SK", "KOSPI"),
            ("086790", "하나금융지주", "KOSPI"),
            ("032830", "삼성생명", "KOSPI"),
            ("018260", "삼성에스디에스", "KOSPI"),
            ("010130", "고려아연", "KOSPI"),
            ("015760", "한국전력", "KOSPI"),
            ("033780", "KT&G", "KOSPI"),
            ("090430", "아모레퍼시픽", "KOSPI"),
            ("000810", "삼성화재", "KOSPI"),
            ("017670", "SK텔레콤", "KOSPI"),
            ("030200", "KT", "KOSPI"),
            ("024110", "기업은행", "KOSPI"),
            ("009150", "삼성전기", "KOSPI"),
            ("028260", "삼성물산", "KOSPI"),
            ("010950", "S-Oil", "KOSPI"),
            ("316140", "우리금융지주", "KOSPI"),
            ("034020", "두산에너빌리티", "KOSPI"),
            ("011200", "HMM", "KOSPI"),
            ("259960", "크래프톤", "KOSPI"),
            ("010140", "삼성중공업", "KOSPI"),
            ("009830", "한화솔루션", "KOSPI"),
            ("003490", "대한항공", "KOSPI"),
            ("047050", "포스코인터내셔널", "KOSPI"),
            ("006800", "미래에셋증권", "KOSPI"),
            ("016360", "삼성증권", "KOSPI"),
            ("003410", "쌍용씨앤이", "KOSPI"),
            ("035250", "강원랜드", "KOSPI"),
            ("180640", "한진칼", "KOSPI"),
            ("011780", "금호석유", "KOSPI"),
            ("267260", "HD현대일렉트릭", "KOSPI"),
            ("000880", "한화", "KOSPI"),
            # KOSDAQ 대표종목
            ("247540", "에코프로비엠", "KOSDAQ"),
            ("086520", "에코프로", "KOSDAQ"),
            ("028300", "에이치엘비", "KOSDAQ"),
            ("196170", "알테오젠", "KOSDAQ"),
            ("091990", "셀트리온헬스케어", "KOSDAQ"),
            ("403870", "HPSP", "KOSDAQ"),
            ("377300", "카카오페이", "KOSDAQ"),
            ("293490", "카카오게임즈", "KOSDAQ"),
            ("035900", "JYP Ent.", "KOSDAQ"),
            ("352820", "하이브", "KOSDAQ"),
            ("263750", "펄어비스", "KOSDAQ"),
            ("112040", "위메이드", "KOSDAQ"),
            ("095340", "ISC", "KOSDAQ"),
            ("357780", "솔브레인", "KOSDAQ"),
            ("145020", "휴젤", "KOSDAQ"),
            ("365340", "성일하이텍", "KOSDAQ"),
            ("041510", "에스엠", "KOSDAQ"),
            ("251270", "넷마블", "KOSDAQ"),
            ("039200", "오스코텍", "KOSDAQ"),
            ("067160", "아프리카TV", "KOSDAQ"),
            ("078600", "대주전자재료", "KOSDAQ"),
            ("214150", "클래시스", "KOSDAQ"),
            ("141080", "레고켐바이오", "KOSDAQ"),
            ("039030", "이오테크닉스", "KOSDAQ"),
            ("240810", "원익IPS", "KOSDAQ"),
            ("328130", "루닛", "KOSDAQ"),
            ("122870", "와이지엔터테인먼트", "KOSDAQ"),
            ("053800", "안랩", "KOSDAQ"),
            ("389260", "대명에너지", "KOSDAQ"),
            ("900140", "코라오홀딩스", "KOSDAQ"),
        ]
        
        filtered_stocks = []
        logger.info(f"주요 {len(MAJOR_STOCKS)}개 종목에서 거래대금 조회 중...")
        
        for i, (code, name, market) in enumerate(MAJOR_STOCKS):
            try:
                # 현재가 조회
                current = self.get_current_price(code)
                trading_value = current.trading_value / 100_000_000  # 억원
                
                # 거래대금 필터링
                if trading_value >= min_trading_value:
                    # 제외 종목 체크
                    if not self._should_exclude(name, code):
                        filtered_stocks.append(StockInfo(
                            code=code,
                            name=name,
                            market=market,
                        ))
                
                # 진행 상황 로그 (20개마다)
                if (i + 1) % 20 == 0:
                    logger.info(f"  종목 조회 진행: {i + 1}/{len(MAJOR_STOCKS)}")
                    
            except Exception as e:
                logger.warning(f"종목 {name}({code}) 조회 실패: {e}")
                continue
            
            # 충분한 종목 확보시 종료
            if len(filtered_stocks) >= limit:
                break
        
        # 거래대금 순 정렬 (다시 조회 필요하지만 이미 필터링됨)
        return filtered_stocks[:limit]
    
    def _should_exclude(self, name: str, code: str) -> bool:
        """제외 대상 종목 확인"""
        # 이름 기반 제외
        for pattern in EXCLUDED_STOCK_PATTERNS:
            if pattern in name:
                return True
        
        # 코드 기반 제외 (ETF 등)
        # ETF: 코드가 특정 패턴 (추후 필요시 추가)
        
        return False
    
    def get_stock_name(self, stock_code: str) -> str:
        """종목명 조회"""
        try:
            price = self.get_current_price(stock_code)
            # 현재가 API에서 종목명을 제공하지 않으므로
            # 별도 API 호출 또는 캐시 활용 필요
            return ""
        except Exception:
            return ""
    
    # ============================================================
    # 조건검색(psearch) API
    # ============================================================
    
    # src/adapters/kis_client.py

    def get_condition_list(self, user_id: str) -> List[Dict[str, str]]:
        """
        사용자 조건검색식 목록 조회 (psearch-title)

        Returns:
            [{"seq": "0", "name": "TV200"}, ...]
        """
        endpoint = "/uapi/domestic-stock/v1/quotations/psearch-title"
        tr_id = "HHKST03900300"

        params = {"user_id": user_id}

        try:
            data = self._request("GET", endpoint, tr_id, params=params)

            # ✅ Raw 응답을 logs/condition_list_raw.json에 저장
            raw_path = Path("logs/condition_list_raw.json")
            try:
                Path("logs").mkdir(exist_ok=True)
                with open(raw_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                logger.debug(f"조건검색 raw 저장: {raw_path}")
            except Exception as e:
                logger.warning(f"조건검색 raw 저장 실패: {e}")

            # ✅ 조건 목록이 들어있는 리스트 자동 탐색
            output = None
            for key in ["output2", "output", "output1", "list", "data", "items", "result"]:
                candidate = data.get(key)
                if isinstance(candidate, list) and len(candidate) > 0:
                    output = candidate
                    logger.debug(f"조건검색 목록 키: {key} (count={len(output)})")
                    break
            
            if output is None:
                output = []
                logger.warning("조건검색 응답에서 목록을 찾을 수 없습니다")

            def pick_seq(item: dict) -> str:
                """seq 후보 키를 폭넓게 커버"""
                seq_keys = ["seq", "sn", "scts_seq", "screen_no", "cond_seq", 
                            "condition_seq", "no", "idx", "id", "num"]
                for key in seq_keys:
                    val = item.get(key)
                    if val is not None:
                        return str(val).strip()
                return ""

            def pick_name(item: dict) -> str:
                """name 후보 키를 폭넓게 커버"""
                name_keys = ["name", "condition_name", "cond_nm", "condition_nm", 
                             "cond_name", "tr_cond_nm", "title", "cond_title",
                             "screen_name", "screen_nm", "nm", "label"]
                for key in name_keys:
                    val = item.get(key)
                    if isinstance(val, str) and val.strip():
                        return val.strip()
                return ""

            conditions: List[Dict[str, str]] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                seq = pick_seq(item)
                name = pick_name(item)
                if seq != "":
                    conditions.append({"seq": seq, "name": name})

            logger.info(f"조건검색식 목록 조회 완료: {len(conditions)}개")
            
            # ✅ 첫 1~3개 항목 raw를 로깅 (트러블슈팅용)
            if output:
                sample_items = output[:3]
                for i, item in enumerate(sample_items):
                    if isinstance(item, dict):
                        # 민감정보 제외하고 키/값 출력
                        safe_item = {k: v for k, v in item.items() 
                                     if k.lower() not in ["password", "secret", "token"]}
                        logger.info(f"조건검색 raw 샘플[{i}]: keys={list(safe_item.keys())}, values={list(safe_item.values())}")

            return conditions

        except Exception as e:
            logger.error(f"조건검색식 목록 조회 실패: {e}")
            return []

    def get_condition_result(
        self,
        user_id: str,
        seq: str,
        limit: int = 500,
    ) -> List["StockInfo"]:
        """
        조건검색 결과 조회 (psearch-result)
        """
        endpoint = "/uapi/domestic-stock/v1/quotations/psearch-result"
        tr_id = "HHKST03900400"

        params = {"user_id": user_id, "seq": str(seq).strip()}

        try:
            data = self._request("GET", endpoint, tr_id, params=params)

            # raw 저장(필요시)
            try:
                Path("logs").mkdir(exist_ok=True)
                with open("logs/condition_result_raw.json", "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

            output = data.get("output2") or data.get("output") or []
            if not isinstance(output, list):
                output = []

            stocks: List[StockInfo] = []
            for item in output[:limit]:
                if not isinstance(item, dict):
                    continue

                # 코드 파싱 (키 다양)
                code = (
                    item.get("mksc_shrn_iscd")
                    or item.get("stck_shrn_iscd")
                    or item.get("pdno")
                    or item.get("code")
                    or ""
                )
                code = str(code).strip()
                if not code:
                    continue
                code = code.zfill(6)

                # 이름 파싱 (키 다양)
                name = (
                    item.get("name")  # psearch API 응답 키
                    or item.get("hts_kor_isnm")
                    or item.get("prdt_name")
                    or item.get("kor_item_name")
                    or item.get("itmsNm")
                    or item.get("stck_shrn_iscd_name")
                    or ""
                )
                name = str(name).strip()

                # 시장 구분 (가능한 경우)
                market = "KOSPI"
                market_code = item.get("mrkt_div_code") or item.get("mrkt_cls_code") or ""
                if market_code in ("Q", "J2", "KOSDAQ"):
                    market = "KOSDAQ"

                stocks.append(StockInfo(code=code, name=name, market=market))

            logger.info(f"조건검색 결과 조회 완료: {len(stocks)}개")
            return stocks

        except Exception as e:
            logger.error(f"조건검색 결과 조회 실패: {e}")
            return []

    def get_condition_universe(
        self,
        condition_name: str,
        *,
        user_id: Optional[str] = None,
        limit: int = 500,
        fetch_names: bool = True,
    ) -> List["StockInfo"]:
        """
        조건검색 기반 유니버스 조회
        """
        if user_id is None:
            # settings.kis.hts_id / env(hst_id) 등 프로젝트 방식대로
            user_id = getattr(settings.kis, "hts_id", None)

        if not user_id:
            logger.error("HTS 사용자 ID가 설정되지 않았습니다 (KIS_HTS_ID 또는 hts_id)")
            return []

        want = (condition_name or "").strip().lower()

        logger.info(f"조건검색 유니버스 조회 시작: {condition_name} (user={user_id})")

        conditions = self.get_condition_list(user_id)
        if not conditions:
            logger.warning("조건검색식 목록이 비어있습니다 (HTS [0110] 서버저장 여부 확인)")
            return []

        # ✅ 이름이 빈 값으로 내려오거나 공백/대소문자 차이도 대비
        target_seq = None
        for c in conditions:
            c_name = (c.get("name") or "").strip().lower()
            if c_name == want and c.get("seq") is not None:
                target_seq = str(c["seq"]).strip()
                break

        if target_seq is None:
            # 힌트 로그
            available = ", ".join([(c.get("name") or "(blank)") for c in conditions[:20]])
            logger.error(f"조건검색식 '{condition_name}'을 찾을 수 없습니다")
            logger.info(f"사용 가능한 조건검색식(앞 20개): {available}")
            logger.info("HTS [0110]에서 해당 조건을 '서버저장'했는지 확인하세요.")
            return []

        logger.info(f"조건검색식 찾음: {condition_name} -> seq={target_seq}")

        stocks = self.get_condition_result(user_id, target_seq, limit)

        # (선택) 종목명 빈 값 채우기 - 너무 많이 하면 호출 부담이라 상한 둠
        if fetch_names:
            need = [s for s in stocks if not getattr(s, "name", "")]
            if need:
                logger.info(f"종목명 조회 필요: {len(need)}개")
                for s in need[:50]:
                    try:
                        name = self._get_stock_info_name(s.code)  # 기존 구현 사용
                        if name:
                            s.name = name
                    except Exception:
                        pass

        logger.info(f"조건검색 유니버스 최종: {len(stocks)}개")
        return stocks
    
    def _get_stock_info_name(self, stock_code: str) -> str:
        """
        주식기본조회 API를 통해 종목명 조회
        
        Args:
            stock_code: 종목코드
            
        Returns:
            종목명 (실패 시 빈 문자열)
        """
        endpoint = "/uapi/domestic-stock/v1/quotations/search-stock-info"
        tr_id = "CTPF1002R"
        
        params = {
            "PRDT_TYPE_CD": "300",  # 주식
            "PDNO": stock_code.zfill(6),
        }
        
        try:
            data = self._request("GET", endpoint, tr_id, params=params)
            output = data.get("output", {})
            return output.get("prdt_abrv_name", "") or output.get("prdt_name", "") or ""
        except Exception:
            return ""

    def get_account_balance(self) -> Dict[str, Any]:
        """계좌 잔고 조회
        
        Returns:
            {
                'total_eval': 총평가금액,
                'total_profit': 총수익금액,
                'total_profit_rate': 총수익률,
                'cash': 예수금,
                'stocks': [{
                    'code': 종목코드,
                    'name': 종목명,
                    'qty': 보유수량,
                    'avg_price': 평균단가,
                    'current_price': 현재가,
                    'eval_amount': 평가금액,
                    'profit': 손익금액,
                    'profit_rate': 수익률
                }, ...]
            }
        """
        endpoint = "/uapi/domestic-stock/v1/trading/inquire-balance"
        tr_id = "TTTC8434R"  # 실전: TTTC8434R, 모의: VTTC8434R
        
        # 모의투자 여부 확인
        if "virtual" in self.base_url or "-01" in self.account_no:
            tr_id = "VTTC8434R"
        
        account_prefix = self.account_no.split("-")[0]
        account_suffix = self.account_no.split("-")[1] if "-" in self.account_no else "01"
        
        params = {
            "CANO": account_prefix,
            "ACNT_PRDT_CD": account_suffix,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        
        result = {
            'total_eval': 0,
            'total_profit': 0,
            'total_profit_rate': 0.0,
            'cash': 0,
            'stocks': [],
        }
        
        try:
            data = self._request("GET", endpoint, tr_id, params=params)
            
            # 보유종목 리스트
            output1 = data.get("output1", [])
            for item in output1:
                stock = {
                    'code': item.get("pdno", ""),
                    'name': item.get("prdt_name", ""),
                    'qty': int(item.get("hldg_qty", 0)),
                    'avg_price': int(float(item.get("pchs_avg_pric", 0))),
                    'current_price': int(item.get("prpr", 0)),
                    'eval_amount': int(item.get("evlu_amt", 0)),
                    'profit': int(item.get("evlu_pfls_amt", 0)),
                    'profit_rate': float(item.get("evlu_pfls_rt", 0)),
                }
                if stock['qty'] > 0:
                    result['stocks'].append(stock)
            
            # 계좌 요약
            output2 = data.get("output2", [{}])
            if output2:
                summary = output2[0] if isinstance(output2, list) else output2
                result['total_eval'] = int(summary.get("tot_evlu_amt", 0))
                result['total_profit'] = int(summary.get("evlu_pfls_smtl_amt", 0))
                result['cash'] = int(summary.get("dnca_tot_amt", 0))
                
                # 수익률 계산
                purchase_total = int(summary.get("pchs_amt_smtl_amt", 0))
                if purchase_total > 0:
                    result['total_profit_rate'] = (result['total_profit'] / purchase_total) * 100
            
            logger.info(f"잔고 조회 완료: {len(result['stocks'])}종목, 평가금액 {result['total_eval']:,}원")
            return result
            
        except Exception as e:
            logger.error(f"잔고 조회 실패: {e}")
            return result

    def get_daily_profit_loss(self, start_date: str = None, end_date: str = None) -> List[Dict]:
        """일별 손익 조회
        
        Args:
            start_date: 시작일 (YYYYMMDD)
            end_date: 종료일 (YYYYMMDD)
            
        Returns:
            일별 손익 리스트
        """
        from datetime import datetime, timedelta
        
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
        
        endpoint = "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
        tr_id = "TTTC8001R"
        
        account_prefix = self.account_no.split("-")[0]
        account_suffix = self.account_no.split("-")[1] if "-" in self.account_no else "01"
        
        params = {
            "CANO": account_prefix,
            "ACNT_PRDT_CD": account_suffix,
            "INQR_STRT_DT": start_date,
            "INQR_END_DT": end_date,
            "SLL_BUY_DVSN_CD": "00",
            "INQR_DVSN": "00",
            "PDNO": "",
            "CCLD_DVSN": "00",
            "ORD_GNO_BRNO": "",
            "ODNO": "",
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        
        try:
            data = self._request("GET", endpoint, tr_id, params=params)
            
            results = []
            for item in data.get("output1", []):
                results.append({
                    'date': item.get("ord_dt", ""),
                    'code': item.get("pdno", ""),
                    'name': item.get("prdt_name", ""),
                    'side': "매수" if item.get("sll_buy_dvsn_cd") == "02" else "매도",
                    'qty': int(item.get("ord_qty", 0)),
                    'price': int(item.get("avg_prvs", 0)),
                    'amount': int(item.get("tot_ccld_amt", 0)),
                })
            
            return results
            
        except Exception as e:
            logger.error(f"일별 손익 조회 실패: {e}")
            return []
    
    # ========== 지수 조회 API (v5.2 추가) ==========
    
    def get_index_price(self, index_code: str) -> Optional[Dict[str, Any]]:
        """업종 지수 현재가 조회
        
        Args:
            index_code: 지수 코드 (0001: 코스피, 1001: 코스닥)
            
        Returns:
            지수 데이터 dict 또는 None
        """
        try:
            token = self._get_token()
            
            # API 엔드포인트: 업종현재지수
            url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-index-price"
            
            headers = {
                "Content-Type": "application/json; charset=utf-8",
                "authorization": f"Bearer {token}",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
                "tr_id": "FHPUP02100000",  # 업종현재지수
                "custtype": "P",
            }
            
            params = {
                "FID_COND_MRKT_DIV_CODE": "U",  # 업종
                "FID_INPUT_ISCD": index_code,
            }
            
            self._wait_for_rate_limit()
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get("rt_cd") != "0":
                logger.error(f"지수 조회 실패: {data.get('msg1')}")
                return None
            
            output = data.get("output", {})
            return output
            
        except Exception as e:
            logger.error(f"지수 현재가 조회 실패: {e}")
            return None
    
    def get_index_daily_price(self, index_code: str, count: int = 30) -> List[Dict[str, Any]]:
        """업종 지수 일봉 조회
        
        Args:
            index_code: 지수 코드 (0001: 코스피, 1001: 코스닥)
            count: 조회 일수
            
        Returns:
            일봉 데이터 리스트
        """
        try:
            token = self._get_token()
            
            # API 엔드포인트: 업종일별지수
            url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice"
            
            headers = {
                "Content-Type": "application/json; charset=utf-8",
                "authorization": f"Bearer {token}",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
                "tr_id": "FHKUP03500100",  # 업종일별지수
                "custtype": "P",
            }
            
            # 날짜 계산
            from datetime import datetime, timedelta
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=count + 10)).strftime("%Y%m%d")
            
            params = {
                "FID_COND_MRKT_DIV_CODE": "U",
                "FID_INPUT_ISCD": index_code,
                "FID_INPUT_DATE_1": start_date,
                "FID_INPUT_DATE_2": end_date,
                "FID_PERIOD_DIV_CODE": "D",  # 일봉
            }
            
            self._wait_for_rate_limit()
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get("rt_cd") != "0":
                logger.error(f"지수 일봉 조회 실패: {data.get('msg1')}")
                return []
            
            output2 = data.get("output2", [])
            
            result = []
            for item in output2[:count]:
                try:
                    result.append({
                        "date": item.get("stck_bsop_date", ""),
                        "close": float(item.get("bstp_nmix_prpr", 0)),
                        "open": float(item.get("bstp_nmix_oprc", 0)),
                        "high": float(item.get("bstp_nmix_hgpr", 0)),
                        "low": float(item.get("bstp_nmix_lwpr", 0)),
                        "volume": int(item.get("acml_vol", 0)),
                    })
                except (ValueError, TypeError) as e:
                    continue
            
            # 날짜순 정렬 (오래된 것 → 최신)
            result.sort(key=lambda x: x["date"])
            
            return result
            
        except Exception as e:
            logger.error(f"지수 일봉 조회 실패: {e}")
            return []


# 싱글톤 인스턴스
_kis_client: Optional[KISClient] = None


def get_kis_client() -> KISClient:
    """KIS 클라이언트 인스턴스 반환"""
    global _kis_client
    if _kis_client is None:
        _kis_client = KISClient()
    return _kis_client


if __name__ == "__main__":
    # 테스트
    logging.basicConfig(level=logging.INFO)
    
    client = get_kis_client()
    
    # 거래대금 상위 종목 조회
    print("\n=== 거래대금 300억 이상 종목 ===")
    stocks = client.get_top_trading_value_stocks()
    for i, stock in enumerate(stocks[:5], 1):
        print(f"{i}. {stock.name} ({stock.code}) - {stock.market}")
    
    # 첫 번째 종목 일봉 조회
    if stocks:
        print(f"\n=== {stocks[0].name} 일봉 데이터 ===")
        prices = client.get_daily_prices(stocks[0].code, count=5)
        for price in prices:
            print(f"{price.date}: 시가 {price.open:,} / 고가 {price.high:,} / 저가 {price.low:,} / 종가 {price.close:,}")
        
        print(f"\n=== {stocks[0].name} 현재가 ===")
        current = client.get_current_price(stocks[0].code)
        print(f"현재가: {current.price:,}원 ({current.change_rate:+.2f}%)")
