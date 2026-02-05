"""
Quiet Accumulation 스크리너 v2.0 (백테스트 기반 개편)

🎯 목표: "거래량 폭발 전, 조용히 모이는 종목" 탐지

v2.0 변경사항 (백테스트 120일, N=1,200건 기반):
┌──────────────────────────────────────────────────────────┐
│ 발견                      │ 대응                         │
├──────────────────────────────────────────────────────────┤
│ 점수 역전: 90+점 < 70-80점  │ 조용함↓(25→15), 온기↑(25→30) │
│ 하락장 승률 23%             │ 시장 필터 추가 (코스피 20MA)  │
│ 폭발 O +4.33% vs X -2.72% │ 폭발 확률 보조지표 추가       │
│ 반복 종목 패널티 없음       │ 10일 중복 제외               │
│ TOP 20 과다                │ TOP 10 축소                  │
└──────────────────────────────────────────────────────────┘

핵심 수치 (v1.1 → v2.0 목표):
- 승률 D+5: 43% → 52%+
- 거래량 폭발 예측률: 47% → 55%+

4단계 필터 (변경 없음):
A) 가격 범위: 2,000~10,000원
B) 조용한 상태: 당일 거래량 < 20일 평균 × 1.5, 등락률 < 5%
C) 온기 상승: 5일 평균 거래대금 > 20일 평균 × 1.1
D) 기술적 준비: 60일 고점 75% 이상, 저점 상승 추세

+ 신규 필터:
E) 시장 필터: 코스피 20MA 위 (CONSERVATIVE 모드면 스킵)
F) 중복 제외: 최근 10일 내 시그널 발생 종목 제외

실행 시점: 15:05 (ClosingBell 직후)
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
from dataclasses import dataclass, field
from pathlib import Path
from collections import deque
import pandas as pd
import numpy as np

from src.config.app_config import OHLCV_FULL_DIR, MAPPING_FILE
from src.adapters.discord_notifier import get_discord_notifier
from src.utils.stock_filters import is_eligible_universe_stock

logger = logging.getLogger(__name__)


# ============================================================
# 데이터 모델
# ============================================================
@dataclass
class QuietStock:
    """조용한 축적 종목 정보"""
    code: str
    name: str
    current_price: int
    change_rate: float
    
    # 유동성
    avg_trading_value_20d: float  # 억원
    
    # 조용한 상태
    volume_ratio: float  # 당일 거래량 / 20일 평균
    
    # 온기 상승
    trading_value_ratio: float  # 5일/20일 거래대금 비율
    warm_days: int  # 최근 5일 중 20일 평균 초과 일수
    
    # 기술적 준비
    vs_high_60d: float  # 60일 고점 대비 %
    low_slope: float  # 저점 상승 추세
    
    # v2.0 신규: 거래량 폭발 보조지표
    vol_contraction_days: int = 0  # 연속 거래량 감소 일수 (스프링 압축)
    price_range_squeeze: float = 0.0  # 10일 가격 변동폭 축소율
    
    # 종합 점수
    total_score: float = 0.0
    grade: str = ""
    
    # v2.0: 매매 가이드
    suggested_action: str = ""


# ============================================================
# 설정 상수
# ============================================================
class QuietConfig:
    """Quiet Accumulation v2.0 설정"""
    
    # 가격 범위
    MIN_PRICE = 2000
    MAX_PRICE = 10000
    
    # 유동성 최소치
    MIN_AVG_TRADING_VALUE_20D = 3.0  # 억원
    
    # 조용한 상태 (핵심!)
    MAX_VOLUME_RATIO = 1.5  # 당일 거래량 < 20일 평균 × 1.5
    MAX_CHANGE_RATE = 5.0   # 등락률 5% 이하
    
    # 온기 상승
    MIN_TRADING_VALUE_RATIO = 1.1  # 5일/20일 ≥ 1.1배
    MAX_TRADING_VALUE_RATIO = 2.0  # 너무 높으면 이미 관심
    MIN_WARM_DAYS = 2
    
    # 기술적 준비
    MIN_VS_HIGH_60D = 0.75  # 60일 고점의 75% 이상
    
    # v2.0: 결과 축소 (20 → 10)
    TOP_N = 10
    
    # v2.0: 중복 제외 기간 (거래일)
    DEDUP_LOOKBACK_DAYS = 10
    
    # v2.0: 시장 필터
    USE_MARKET_FILTER = True
    
    # v2.0: 점수 캡 (90+점 역전 현상 방지)
    SCORE_CAP = 90.0


# ============================================================
# 시그널 히스토리 (중복 방지)
# ============================================================
class SignalHistory:
    """최근 시그널 이력 관리 (메모리 기반)"""
    
    def __init__(self, lookback_days: int = 10):
        self.lookback_days = lookback_days
        # {code: last_signal_date}
        self._history: Dict[str, str] = {}
    
    def is_duplicate(self, code: str, current_date: str) -> bool:
        """최근 N일 내 시그널 발생 여부"""
        if code not in self._history:
            return False
        
        last_date = self._history[code]
        try:
            last_dt = datetime.strptime(last_date, "%Y-%m-%d")
            curr_dt = datetime.strptime(current_date, "%Y-%m-%d")
            diff = (curr_dt - last_dt).days
            return diff <= self.lookback_days
        except ValueError:
            return False
    
    def record(self, codes: List[str], date: str):
        """시그널 발생 기록"""
        for code in codes:
            self._history[code] = date
    
    def cleanup(self, current_date: str):
        """오래된 이력 정리"""
        try:
            curr_dt = datetime.strptime(current_date, "%Y-%m-%d")
            cutoff = (curr_dt - timedelta(days=self.lookback_days + 5)).strftime("%Y-%m-%d")
            self._history = {
                k: v for k, v in self._history.items() if v >= cutoff
            }
        except ValueError:
            pass


# 전역 히스토리 인스턴스
_signal_history = SignalHistory()


# ============================================================
# 메인 스캐너
# ============================================================
class QuietAccumulationScanner:
    """조용한 축적 패턴 스캐너 v2.0 (OHLCV 기반)"""
    
    def __init__(self, use_market_filter: bool = True):
        self.config = QuietConfig()
        self.ohlcv_dir = Path(OHLCV_FULL_DIR)
        self.mapping_file = Path(MAPPING_FILE)
        self.stock_names = self._load_stock_names()
        self.use_market_filter = use_market_filter
    
    def _load_stock_names(self) -> Dict[str, str]:
        """종목 코드 → 이름 매핑 로드"""
        if not self.mapping_file.exists():
            logger.warning(f"매핑 파일 없음: {self.mapping_file}")
            return {}
        
        try:
            df = pd.read_csv(self.mapping_file, dtype={'code': str})
            return dict(zip(df['code'], df['name']))
        except Exception as e:
            logger.error(f"매핑 파일 로드 오류: {e}")
            return {}
    
    def _check_market_filter(self) -> bool:
        """시장 필터: 코스피 20MA 위인지 확인
        
        Returns:
            True: 매매 가능 (NORMAL 모드)
            False: 매매 보류 (CONSERVATIVE/HALT 모드)
        """
        if not self.use_market_filter:
            return True
        
        try:
            from src.data.index_monitor import get_index_monitor, MarketMode
            monitor = get_index_monitor()
            status = monitor.get_market_status()
            
            if status.mode == MarketMode.NORMAL:
                logger.info(f"  [시장] ✅ 정상 (코스피 MA20 위)")
                return True
            elif status.mode == MarketMode.HALT:
                logger.warning(f"  [시장] 🛑 급락 - QA 중지: {status.halt_reason}")
                return False
            else:
                logger.info(f"  [시장] ⚠️ 보수적 (코스피 MA20 아래) - QA 스킵")
                return False
                
        except Exception as e:
            logger.warning(f"  [시장] 시장 필터 조회 실패: {e} → 실행 계속")
            return True  # 조회 실패 시 실행 (안전 모드)
    
    def scan(self) -> List[QuietStock]:
        """전체 스캔 실행"""
        logger.info("🔍 Quiet Accumulation v2.0 스캔 시작")
        
        # 0. 시장 필터
        if not self._check_market_filter():
            logger.info("⏸️ 시장 필터에 의해 QA 스캔 스킵")
            return []
        
        # 1. OHLCV 파일 목록
        ohlcv_files = list(self.ohlcv_dir.glob('*.csv'))
        total_files = len(ohlcv_files)
        logger.info(f"  [1단계] OHLCV 파일: {total_files}개")
        
        if not ohlcv_files:
            logger.warning(f"OHLCV 파일 없음: {self.ohlcv_dir}")
            return []
        
        # 2. 각 종목 분석
        candidates = []
        stats = {'total': 0, 'price': 0, 'quiet': 0, 'warm': 0, 'dedup': 0, 'error': 0}
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        for idx, f in enumerate(ohlcv_files):
            if idx % 500 == 0:
                logger.info(f"    진행: {idx}/{total_files} ({idx*100//total_files}%)")
            
            code = f.stem
            name = self.stock_names.get(code, code)
            
            # ETF/스팩 등 제외
            is_ok, _ = is_eligible_universe_stock(code, name)
            if not is_ok:
                continue
            
            stats['total'] += 1
            
            # v2.0: 중복 제외
            if _signal_history.is_duplicate(code, today_str):
                stats['dedup'] += 1
                continue
            
            result = self._analyze_ohlcv(code, name, f)
            
            if result is None:
                stats['error'] += 1
            elif result == 'price':
                stats['price'] += 1
            elif result == 'quiet':
                stats['quiet'] += 1
            elif result == 'warm':
                stats['warm'] += 1
            elif isinstance(result, QuietStock):
                candidates.append(result)
        
        logger.info(f"  [2단계] 필터링 결과:")
        logger.info(f"    - 총 스캔: {stats['total']}개")
        logger.info(f"    - 가격 범위 외: {stats['price']}개")
        logger.info(f"    - 조용하지 않음: {stats['quiet']}개")
        logger.info(f"    - 온기 부족: {stats['warm']}개")
        logger.info(f"    - 중복 제외: {stats['dedup']}개")
        logger.info(f"    - 후보: {len(candidates)}개")
        
        # 3. 점수순 정렬 및 TOP N 선정
        candidates.sort(key=lambda x: x.total_score, reverse=True)
        top_stocks = candidates[:self.config.TOP_N]
        
        # 4. 등급 부여 + 매매 가이드
        for stock in top_stocks:
            stock.grade = self._assign_grade(stock.total_score)
            stock.suggested_action = self._suggest_action(stock)
        
        # 5. 시그널 히스토리 기록
        _signal_history.record([s.code for s in top_stocks], today_str)
        _signal_history.cleanup(today_str)
        
        logger.info(f"✅ Quiet Accumulation v2.0 TOP {len(top_stocks)}개 선정")
        
        return top_stocks
    
    def _analyze_ohlcv(self, code: str, name: str, filepath: Path):
        """OHLCV 파일 분석"""
        try:
            df = pd.read_csv(filepath, usecols=['date', 'open', 'high', 'low', 'close', 'volume'])
            if len(df) < 20:
                return None
            
            # 최신 60일
            df = df.sort_values('date').tail(60).reset_index(drop=True)
            
            current_price = int(df.iloc[-1]['close'])
            
            # 가격 범위 체크
            if not (self.config.MIN_PRICE <= current_price <= self.config.MAX_PRICE):
                return 'price'
            
            # 등락률
            prev_close = df.iloc[-2]['close'] if len(df) >= 2 else current_price
            change_rate = (current_price - prev_close) / prev_close * 100 if prev_close > 0 else 0
            
            # 20일/5일 데이터
            df_20 = df.tail(20).copy()
            df_5 = df.tail(5).copy()
            
            df_20['tv'] = df_20['close'] * df_20['volume'] / 100_000_000
            df_5['tv'] = df_5['close'] * df_5['volume'] / 100_000_000
            
            avg_tv_20d = df_20['tv'].mean()
            avg_tv_5d = df_5['tv'].mean()
            
            # 유동성 최소치
            if avg_tv_20d < self.config.MIN_AVG_TRADING_VALUE_20D:
                return None
            
            # 조용한 상태 체크
            avg_volume_20d = df_20['volume'].mean()
            today_volume = df.iloc[-1]['volume']
            volume_ratio = today_volume / avg_volume_20d if avg_volume_20d > 0 else 999
            
            if volume_ratio > self.config.MAX_VOLUME_RATIO:
                return 'quiet'
            
            if abs(change_rate) > self.config.MAX_CHANGE_RATE:
                return 'quiet'
            
            # 온기 상승 체크
            tv_ratio = avg_tv_5d / avg_tv_20d if avg_tv_20d > 0 else 0
            
            if tv_ratio < self.config.MIN_TRADING_VALUE_RATIO:
                return 'warm'
            if tv_ratio > self.config.MAX_TRADING_VALUE_RATIO:
                return 'quiet'
            
            warm_days = sum(1 for tv in df_5['tv'] if tv >= avg_tv_20d)
            
            # 기술적 준비
            high_60d = df['high'].max()
            vs_high_60d = current_price / high_60d if high_60d > 0 else 0
            
            # 저점 추세
            low_slope = self._calc_slope(df.tail(10)['low'].values)
            
            # ─── v2.0 신규: 거래량 폭발 보조지표 ───
            vol_contraction_days = self._calc_vol_contraction(df_20['volume'].values)
            price_range_squeeze = self._calc_price_squeeze(df.tail(10))
            
            # ─── 점수 계산 (v2.0) ───
            score = self._calc_score_v2(
                volume_ratio, change_rate, tv_ratio, warm_days,
                vs_high_60d, low_slope, avg_tv_20d,
                vol_contraction_days, price_range_squeeze,
            )
            
            return QuietStock(
                code=code,
                name=name,
                current_price=current_price,
                change_rate=change_rate,
                avg_trading_value_20d=avg_tv_20d,
                volume_ratio=volume_ratio,
                trading_value_ratio=tv_ratio,
                warm_days=warm_days,
                vs_high_60d=vs_high_60d,
                low_slope=low_slope,
                vol_contraction_days=vol_contraction_days,
                price_range_squeeze=price_range_squeeze,
                total_score=score,
            )
            
        except Exception as e:
            logger.debug(f"분석 오류 ({code}): {e}")
            return None
    
    # ─── v2.0 신규 지표 계산 ───
    
    def _calc_vol_contraction(self, volumes: np.ndarray) -> int:
        """연속 거래량 감소 일수 (뒤에서부터)
        
        거래량이 연속으로 줄어들면 → 스프링 압축 중 → 폭발 직전 가능성↑
        """
        if len(volumes) < 3:
            return 0
        
        count = 0
        for i in range(len(volumes) - 1, 0, -1):
            if volumes[i] < volumes[i - 1]:
                count += 1
            else:
                break
        return count
    
    def _calc_price_squeeze(self, df_10: pd.DataFrame) -> float:
        """가격 변동폭 축소율
        
        전반 5일 변동폭 vs 후반 5일 변동폭
        후반이 더 좁으면 → 에너지 축적 중
        
        Returns:
            0~1: 후반이 더 좁음 (0.5 = 절반으로 축소)
            >1: 후반이 더 넓음 (변동성 확대)
        """
        if len(df_10) < 10:
            return 1.0
        
        first_half = df_10.iloc[:5]
        second_half = df_10.iloc[5:]
        
        range_first = (first_half['high'].max() - first_half['low'].min())
        range_second = (second_half['high'].max() - second_half['low'].min())
        
        if range_first == 0:
            return 1.0
        
        return range_second / range_first
    
    # ─── 유틸 ───
    
    def _calc_slope(self, values) -> float:
        """선형회귀 기울기"""
        if len(values) < 3:
            return 0.0
        try:
            x = np.arange(len(values))
            coeffs = np.polyfit(x, values, 1)
            return coeffs[0]
        except:
            return 0.0
    
    # ─── v2.0 점수 체계 ───
    
    def _calc_score_v2(
        self,
        volume_ratio: float,
        change_rate: float,
        tv_ratio: float,
        warm_days: int,
        vs_high_60d: float,
        low_slope: float,
        avg_tv_20d: float,
        vol_contraction: int,
        price_squeeze: float,
    ) -> float:
        """v2.0 점수 계산 (100점 만점)
        
        v1.1 → v2.0 변경:
        ┌──────────────┬───────┬───────┐
        │ 항목          │ v1.1  │ v2.0  │
        ├──────────────┼───────┼───────┤
        │ 조용함        │ 25점  │ 15점  │ ← 과도한 조용함 = 죽은 종목
        │ 안정성        │ 20점  │ 15점  │ 
        │ 온기 상승     │ 25점  │ 30점  │ ← 핵심 알파 요인
        │ 기술적 준비   │ 20점  │ 25점  │ ← 상승 가능성
        │ 유동성 보너스 │ 10점  │  5점  │ 
        │ 폭발 준비도   │  -    │ 10점  │ ← v2.0 신규
        └──────────────┴───────┴───────┘
        """
        score = 0.0
        
        # 1. 조용함 (15점) — 적절한 조용함이 최적
        if volume_ratio < 0.3:
            quiet_score = 5  # 너무 조용 = 죽은 종목
        elif volume_ratio < 0.8:
            quiet_score = 15  # 스위트 스팟
        else:
            quiet_score = max(0, min(15, (1.5 - volume_ratio) / 0.7 * 15))
        score += quiet_score
        
        # 2. 안정성 (15점)
        stable_score = max(0, min(15, (5.0 - abs(change_rate)) / 5.0 * 15))
        score += stable_score
        
        # 3. 온기 상승 (30점) — 가장 중요!
        ratio_score = min(20, (tv_ratio - 1.0) / 0.3 * 20)
        warm_score = min(10, warm_days * 3.5)
        score += max(0, ratio_score) + warm_score
        
        # 4. 기술적 준비 (25점)
        high_score = min(15, (vs_high_60d - 0.75) / 0.20 * 15)
        if low_slope > 0:
            slope_score = min(10, 5 + low_slope / 50 * 5)
        else:
            slope_score = 0
        score += max(0, high_score) + slope_score
        
        # 5. 유동성 보너스 (5점)
        if 5 <= avg_tv_20d <= 20:
            score += 5
        elif 3 <= avg_tv_20d < 5 or 20 < avg_tv_20d <= 50:
            score += 2
        
        # 6. v2.0 신규: 폭발 준비도 (10점)
        contraction_score = min(5, vol_contraction * 1.5)
        if price_squeeze < 0.6:
            squeeze_score = 5
        elif price_squeeze < 0.8:
            squeeze_score = 3
        elif price_squeeze < 1.0:
            squeeze_score = 1
        else:
            squeeze_score = 0
        score += contraction_score + squeeze_score
        
        # v2.0: 점수 캡 (역전 방지)
        return min(self.config.SCORE_CAP, score)
    
    def _assign_grade(self, score: float) -> str:
        """등급 부여"""
        if score >= 75:
            return "🔥S"
        elif score >= 60:
            return "🥇A"
        elif score >= 45:
            return "🥈B"
        elif score >= 30:
            return "🥉C"
        else:
            return "📊D"
    
    def _suggest_action(self, stock: QuietStock) -> str:
        """v2.0: 매매 가이드 제안
        
        백테스트 기반:
        - 최적 보유기간: D+10 (최대수익 도달일 평균 D+9)
        - 손절: -5% (D+3 기준)
        - 익절: +10% 이상이면 분할 매도
        """
        parts = []
        
        if stock.vol_contraction_days >= 3 and stock.price_range_squeeze < 0.7:
            parts.append("🎯 폭발 임박 (거래량↓+변동폭↓)")
        elif stock.trading_value_ratio >= 1.3:
            parts.append("📈 온기 강함 (거래대금 1.3배+)")
        else:
            parts.append("👁️ 관찰 (기본 시그널)")
        
        parts.append("⏰ 목표 D+10")
        parts.append("🛑 손절 -5% | 🎯 익절 +10%")
        
        return " | ".join(parts)


# ============================================================
# Discord 알림
# ============================================================
def format_quiet_discord(stocks: List[QuietStock], market_note: str = "") -> str:
    """Discord 알림 포맷 (v2.0)"""
    if not stocks:
        return "🔇 Quiet Accumulation v2.0: 조건 충족 종목 없음"
    
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🔇 **Quiet Accumulation v2.0 TOP 10**",
        "💡 거래량 폭발 전 조용한 축적 패턴",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    
    if market_note:
        lines.append(f"🌡️ {market_note}")
    lines.append("")
    
    for i, s in enumerate(stocks, 1):
        explosion_indicator = ""
        if s.vol_contraction_days >= 3 and s.price_range_squeeze < 0.7:
            explosion_indicator = " 🎯💥"
        elif s.vol_contraction_days >= 2:
            explosion_indicator = " 🔋"
        
        lines.append(
            f"**#{i}** {s.grade} **{s.name}** ({s.code}){explosion_indicator}\n"
            f"   💰 {s.current_price:,}원 ({s.change_rate:+.1f}%)\n"
            f"   📊 점수: {s.total_score:.0f}점\n"
            f"   🔉 거래량: 평균의 {s.volume_ratio:.1f}배 | "
            f"📈 온기: {s.trading_value_ratio:.2f}배\n"
            f"   🔋 폭발준비: 거래량↓{s.vol_contraction_days}일 | "
            f"변동폭 {s.price_range_squeeze:.0%}\n"
            f"   💬 {s.suggested_action}\n"
        )
    
    lines.append("")
    lines.append("📋 매매 규칙: D+1 시가 매수 → D+10 목표 | 손절 -5% | 익절 +10%")
    lines.append(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')} | ClosingBell v7.0")
    
    return "\n".join(lines)


def send_quiet_alert(stocks: List[QuietStock]) -> bool:
    """Discord 알림 발송"""
    notifier = get_discord_notifier()
    message = format_quiet_discord(stocks)
    result = notifier.send_simple_message(message)
    return result.success


# ============================================================
# 메인 실행 함수
# ============================================================
def run_quiet_accumulation(send_alert: bool = True) -> List[QuietStock]:
    """Quiet Accumulation v2.0 스크리너 실행"""
    logger.info("=" * 50)
    logger.info("🔇 Quiet Accumulation v2.0 스크리너 시작")
    logger.info("=" * 50)
    
    scanner = QuietAccumulationScanner(use_market_filter=QuietConfig.USE_MARKET_FILTER)
    stocks = scanner.scan()
    
    if send_alert and stocks:
        success = send_quiet_alert(stocks)
        if success:
            logger.info("✅ Discord 알림 발송 완료")
        else:
            logger.warning("⚠️ Discord 알림 발송 실패")
    elif send_alert and not stocks:
        notifier = get_discord_notifier()
        notifier.send_simple_message(
            "🔇 Quiet Accumulation v2.0: "
            "시장 필터(코스피 MA20 하향) 또는 조건 미충족으로 시그널 없음"
        )
    
    logger.info(f"🔇 Quiet Accumulation v2.0 완료: {len(stocks)}개")
    
    return stocks


# ============================================================
# CLI 테스트
# ============================================================
if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    
    from src.infrastructure.logging_config import init_logging
    init_logging()
    
    # CLI에서는 시장 필터 비활성화 (장 종료 후 테스트용)
    scanner = QuietAccumulationScanner(use_market_filter=False)
    stocks = scanner.scan()
    
    print("\n" + "=" * 60)
    print("🔇 Quiet Accumulation v2.0 결과")
    print("=" * 60)
    
    for i, s in enumerate(stocks[:10], 1):
        exp_tag = "🎯" if s.vol_contraction_days >= 3 and s.price_range_squeeze < 0.7 else "  "
        print(f"\n#{i} {s.grade} {s.name} ({s.code}) {exp_tag}")
        print(f"   가격: {s.current_price:,}원 ({s.change_rate:+.1f}%)")
        print(f"   점수: {s.total_score:.0f}점")
        print(f"   거래량: 평균의 {s.volume_ratio:.1f}배 | 온기: {s.trading_value_ratio:.2f}배")
        print(f"   폭발준비: 거래량↓{s.vol_contraction_days}일 | 변동폭 {s.price_range_squeeze:.0%}")
        print(f"   → {s.suggested_action}")
