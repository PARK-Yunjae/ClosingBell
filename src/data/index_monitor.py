"""
지수 모니터링 모듈 v1.0

책임:
- 코스피/코스닥 지수 실시간 조회
- 지수 MA20 계산 및 위치 판단
- 시장 상태(정상/보수적/중지) 결정
- 급락 감지

의존성:
- KIS API (지수 시세 조회)
- FinanceDataReader (백업)
"""

import logging
from dataclasses import dataclass
from datetime import datetime, date
from enum import Enum
from typing import Optional, List, Tuple
import requests

logger = logging.getLogger(__name__)


class MarketMode(Enum):
    """시장 모드"""
    NORMAL = "normal"           # 정상: 지수 MA20 위
    CONSERVATIVE = "conservative"  # 보수적: 지수 MA20 아래
    HALT = "halt"               # 중지: 급락 또는 비상


@dataclass
class IndexData:
    """지수 데이터"""
    code: str               # 지수 코드 (0001: 코스피, 1001: 코스닥)
    name: str               # 지수명
    current: float          # 현재가
    change: float           # 전일대비
    change_rate: float      # 등락률 (%)
    open: float             # 시가
    high: float             # 고가
    low: float              # 저가
    volume: int             # 거래량
    timestamp: datetime     # 조회 시각


@dataclass 
class IndexMA:
    """지수 이동평균 데이터"""
    code: str
    name: str
    current: float
    ma20: float
    ma5: float
    is_above_ma20: bool
    distance_from_ma20: float  # MA20 대비 이격도 (%)
    trend_5day: str            # 5일 추세 (상승/하락/횡보)


@dataclass
class MarketStatus:
    """시장 상태"""
    mode: MarketMode
    kospi: Optional[IndexMA]
    kosdaq: Optional[IndexMA]
    
    # 판단 기준
    halt_reason: Optional[str] = None  # 중지 사유
    
    # 매매 기준 (모드에 따라 달라짐)
    min_score: int = 65                # 최소 점수
    min_confidence: float = 0.70       # 최소 AI 신뢰도
    
    # 익절 목표 조정 비율
    profit_target_ratio: float = 1.0   # 1.0 = 100%, 0.625 = 62.5%
    
    def __post_init__(self):
        """모드에 따른 기준 설정"""
        if self.mode == MarketMode.NORMAL:
            self.min_score = 65
            self.min_confidence = 0.70
            self.profit_target_ratio = 1.0
        elif self.mode == MarketMode.CONSERVATIVE:
            self.min_score = 75
            self.min_confidence = 0.85
            self.profit_target_ratio = 0.625  # 목표가 62.5%로 축소
        elif self.mode == MarketMode.HALT:
            self.min_score = 999  # 사실상 매수 불가
            self.min_confidence = 1.0
            self.profit_target_ratio = 0.0


class IndexMonitor:
    """지수 모니터링"""
    
    # 지수 코드
    KOSPI_CODE = "0001"
    KOSDAQ_CODE = "1001"
    
    # 급락 기준
    HALT_THRESHOLD = -2.0      # -2% 이상 급락 시 매매 중지
    WARNING_THRESHOLD = -1.5   # -1.5% 이상 시 경고
    
    def __init__(self, kis_client=None):
        """
        Args:
            kis_client: KIS API 클라이언트 (None이면 FDR 사용)
        """
        self.kis_client = kis_client
        self._cache: dict = {}
        self._cache_time: Optional[datetime] = None
        self._cache_ttl = 60  # 캐시 유효시간 (초)
    
    def get_index_current(self, index_code: str) -> Optional[IndexData]:
        """지수 현재가 조회
        
        Args:
            index_code: 지수 코드 (0001: 코스피, 1001: 코스닥)
        """
        try:
            if self.kis_client:
                return self._get_from_kis(index_code)
            else:
                return self._get_from_fdr(index_code)
        except Exception as e:
            logger.error(f"지수 조회 실패 ({index_code}): {e}")
            return None
    
    def _get_from_kis(self, index_code: str) -> Optional[IndexData]:
        """KIS API에서 지수 조회"""
        try:
            # KIS API 지수현재가 조회
            data = self.kis_client.get_index_price(index_code)
            if not data:
                return None
            
            name = "코스피" if index_code == self.KOSPI_CODE else "코스닥"
            
            return IndexData(
                code=index_code,
                name=name,
                current=float(data.get("bstp_nmix_prpr", 0)),
                change=float(data.get("bstp_nmix_prdy_vrss", 0)),
                change_rate=float(data.get("bstp_nmix_prdy_ctrt", 0)),
                open=float(data.get("bstp_nmix_oprc", 0)),
                high=float(data.get("bstp_nmix_hgpr", 0)),
                low=float(data.get("bstp_nmix_lwpr", 0)),
                volume=int(data.get("acml_vol", 0)),
                timestamp=datetime.now(),
            )
        except Exception as e:
            logger.error(f"KIS 지수 조회 실패: {e}")
            return None
    
    def _get_from_fdr(self, index_code: str) -> Optional[IndexData]:
        """FinanceDataReader에서 지수 조회 (백업)"""
        try:
            import FinanceDataReader as fdr
            from datetime import timedelta
            
            # FDR 지수 심볼
            symbol = "KS11" if index_code == self.KOSPI_CODE else "KQ11"
            name = "코스피" if index_code == self.KOSPI_CODE else "코스닥"
            
            # 최근 2일 데이터
            end_date = date.today()
            start_date = end_date - timedelta(days=7)
            
            df = fdr.DataReader(symbol, start_date, end_date)
            if df.empty:
                return None
            
            today = df.iloc[-1]
            yesterday = df.iloc[-2] if len(df) > 1 else today
            
            change = today["Close"] - yesterday["Close"]
            change_rate = (change / yesterday["Close"]) * 100
            
            return IndexData(
                code=index_code,
                name=name,
                current=float(today["Close"]),
                change=float(change),
                change_rate=float(change_rate),
                open=float(today["Open"]),
                high=float(today["High"]),
                low=float(today["Low"]),
                volume=int(today["Volume"]),
                timestamp=datetime.now(),
            )
        except Exception as e:
            logger.error(f"FDR 지수 조회 실패: {e}")
            return None
    
    def get_index_daily(self, index_code: str, count: int = 30) -> List[dict]:
        """지수 일봉 데이터 조회
        
        Args:
            index_code: 지수 코드
            count: 조회 일수
        """
        try:
            if self.kis_client:
                return self._get_daily_from_kis(index_code, count)
            else:
                return self._get_daily_from_fdr(index_code, count)
        except Exception as e:
            logger.error(f"지수 일봉 조회 실패: {e}")
            return []
    
    def _get_daily_from_kis(self, index_code: str, count: int) -> List[dict]:
        """KIS API에서 지수 일봉 조회"""
        try:
            data = self.kis_client.get_index_daily_price(index_code, count)
            return data if data else []
        except Exception as e:
            logger.error(f"KIS 지수 일봉 조회 실패: {e}")
            return []
    
    def _get_daily_from_fdr(self, index_code: str, count: int) -> List[dict]:
        """FDR에서 지수 일봉 조회"""
        try:
            import FinanceDataReader as fdr
            from datetime import timedelta
            
            symbol = "KS11" if index_code == self.KOSPI_CODE else "KQ11"
            
            end_date = date.today()
            start_date = end_date - timedelta(days=count + 10)
            
            df = fdr.DataReader(symbol, start_date, end_date)
            if df.empty:
                return []
            
            result = []
            for idx, row in df.tail(count).iterrows():
                result.append({
                    "date": idx.strftime("%Y%m%d"),
                    "close": float(row["Close"]),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "volume": int(row["Volume"]),
                })
            
            return result
        except Exception as e:
            logger.error(f"FDR 지수 일봉 조회 실패: {e}")
            return []
    
    def calculate_index_ma(self, index_code: str) -> Optional[IndexMA]:
        """지수 MA 계산
        
        Args:
            index_code: 지수 코드
            
        Returns:
            IndexMA 또는 None
        """
        try:
            # 현재가 조회
            current_data = self.get_index_current(index_code)
            if not current_data:
                return None
            
            # 일봉 데이터 조회 (MA20 계산용)
            daily_data = self.get_index_daily(index_code, count=25)
            if len(daily_data) < 20:
                logger.warning(f"지수 일봉 데이터 부족: {len(daily_data)}개")
                return None
            
            # MA 계산
            closes = [d["close"] for d in daily_data]
            
            ma20 = sum(closes[-20:]) / 20
            ma5 = sum(closes[-5:]) / 5
            
            # 현재가 사용 (장중이면 현재가, 장마감이면 최근 종가)
            current = current_data.current if current_data.current > 0 else closes[-1]
            
            # MA20 대비 위치
            is_above_ma20 = current > ma20
            distance_from_ma20 = ((current - ma20) / ma20) * 100
            
            # 5일 추세 판단
            if len(closes) >= 5:
                recent_5 = closes[-5:]
                if all(recent_5[i] < recent_5[i+1] for i in range(4)):
                    trend_5day = "상승"
                elif all(recent_5[i] > recent_5[i+1] for i in range(4)):
                    trend_5day = "하락"
                else:
                    # 시작점과 끝점 비교
                    if recent_5[-1] > recent_5[0] * 1.01:
                        trend_5day = "상승"
                    elif recent_5[-1] < recent_5[0] * 0.99:
                        trend_5day = "하락"
                    else:
                        trend_5day = "횡보"
            else:
                trend_5day = "알수없음"
            
            return IndexMA(
                code=index_code,
                name=current_data.name,
                current=current,
                ma20=ma20,
                ma5=ma5,
                is_above_ma20=is_above_ma20,
                distance_from_ma20=distance_from_ma20,
                trend_5day=trend_5day,
            )
            
        except Exception as e:
            logger.error(f"지수 MA 계산 실패: {e}")
            return None
    
    def get_market_status(self) -> MarketStatus:
        """시장 상태 조회
        
        Returns:
            MarketStatus: 현재 시장 상태
        """
        try:
            # 코스피 MA 계산
            kospi_ma = self.calculate_index_ma(self.KOSPI_CODE)
            kosdaq_ma = self.calculate_index_ma(self.KOSDAQ_CODE)
            
            # 현재가 조회 (급락 체크용)
            kospi_current = self.get_index_current(self.KOSPI_CODE)
            
            # 1. 급락 체크 (매매 중지)
            if kospi_current and kospi_current.change_rate <= self.HALT_THRESHOLD:
                return MarketStatus(
                    mode=MarketMode.HALT,
                    kospi=kospi_ma,
                    kosdaq=kosdaq_ma,
                    halt_reason=f"코스피 급락 ({kospi_current.change_rate:+.2f}%)",
                )
            
            # 2. MA20 하향 돌파 체크
            if kospi_ma and not kospi_ma.is_above_ma20:
                # MA20 아래면 보수적 모드
                return MarketStatus(
                    mode=MarketMode.CONSERVATIVE,
                    kospi=kospi_ma,
                    kosdaq=kosdaq_ma,
                    halt_reason=None,
                )
            
            # 3. 정상 모드
            return MarketStatus(
                mode=MarketMode.NORMAL,
                kospi=kospi_ma,
                kosdaq=kosdaq_ma,
                halt_reason=None,
            )
            
        except Exception as e:
            logger.error(f"시장 상태 조회 실패: {e}")
            # 에러 시 보수적으로 처리
            return MarketStatus(
                mode=MarketMode.CONSERVATIVE,
                kospi=None,
                kosdaq=None,
                halt_reason=f"시장 상태 조회 실패: {e}",
            )
    
    def format_market_status(self, status: MarketStatus) -> str:
        """시장 상태 포맷팅 (Discord용)"""
        lines = []
        
        # 모드 표시
        mode_emoji = {
            MarketMode.NORMAL: "🟢",
            MarketMode.CONSERVATIVE: "🟡", 
            MarketMode.HALT: "🔴",
        }
        mode_text = {
            MarketMode.NORMAL: "정상",
            MarketMode.CONSERVATIVE: "보수적",
            MarketMode.HALT: "매매중지",
        }
        
        lines.append(f"{mode_emoji[status.mode]} 시장모드: **{mode_text[status.mode]}**")
        
        if status.halt_reason:
            lines.append(f"⚠️ 사유: {status.halt_reason}")
        
        # 코스피 정보
        if status.kospi:
            k = status.kospi
            ma_status = "MA20↑" if k.is_above_ma20 else "MA20↓"
            lines.append(
                f"📈 코스피: {k.current:,.2f} ({k.distance_from_ma20:+.2f}% {ma_status}) | 추세: {k.trend_5day}"
            )
        
        # 코스닥 정보  
        if status.kosdaq:
            q = status.kosdaq
            ma_status = "MA20↑" if q.is_above_ma20 else "MA20↓"
            lines.append(
                f"📉 코스닥: {q.current:,.2f} ({q.distance_from_ma20:+.2f}% {ma_status}) | 추세: {q.trend_5day}"
            )
        
        # 매매 기준
        if status.mode != MarketMode.HALT:
            lines.append(f"📋 매매기준: 점수≥{status.min_score}, 신뢰도≥{status.min_confidence:.0%}")
        
        return "\n".join(lines)
    
    def format_market_status_short(self, status: MarketStatus) -> str:
        """시장 상태 짧은 포맷 (한 줄)"""
        mode_emoji = {
            MarketMode.NORMAL: "🟢",
            MarketMode.CONSERVATIVE: "🟡",
            MarketMode.HALT: "🔴",
        }
        
        if status.kospi:
            k = status.kospi
            ma_arrow = "↑" if k.is_above_ma20 else "↓"
            return f"{mode_emoji[status.mode]} 코스피 {k.current:,.0f} ({k.distance_from_ma20:+.1f}% MA20{ma_arrow})"
        
        return f"{mode_emoji[status.mode]} 시장정보 없음"


# 싱글톤 인스턴스
_index_monitor: Optional[IndexMonitor] = None


def get_index_monitor(kis_client=None) -> IndexMonitor:
    """IndexMonitor 싱글톤"""
    global _index_monitor
    if _index_monitor is None:
        _index_monitor = IndexMonitor(kis_client)
    return _index_monitor


# 테스트
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    monitor = IndexMonitor()
    
    print("=" * 50)
    print("지수 모니터링 테스트")
    print("=" * 50)
    
    # 시장 상태 조회
    status = monitor.get_market_status()
    print(monitor.format_market_status(status))
    
    print("\n" + "=" * 50)
    print("짧은 형식:")
    print(monitor.format_market_status_short(status))
