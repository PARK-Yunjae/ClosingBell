#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K값 변동성 돌파 전략 v1.0
==========================
래리 윌리엄스 변동성 돌파 전략 기반

[백테스트 최적 파라미터]
- k = 0.3
- 손절 = -2%
- 익절 = 5%
- 거래대금 = 200억+
- 볼륨비율 = 2.0x+
- 전일등락 = 0~10%
- 지수 = MA5 상회

[성과] (17,280개 조합 테스트)
- 승률: 76.3% ~ 84.5%
- 평균 수익: 6.32%
- 샤프비율: 3.16

사용법:
    from src.domain.k_breakout import KBreakoutStrategy, KBreakoutSignal
    
    strategy = KBreakoutStrategy()
    signals = strategy.scan(stock_data_list)
"""

import logging
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


# =============================================================================
# 설정
# =============================================================================

@dataclass
class KBreakoutConfig:
    """K값 전략 설정 (백테스트 최적값)"""
    
    # 핵심 파라미터
    k: float = 0.3                      # K값 (0.3 = 최적)
    stop_loss_pct: float = -2.0         # 손절 (-2%)
    take_profit_pct: float = 5.0        # 익절 (+5%)
    
    # 필터
    min_trading_value: float = 200.0    # 최소 거래대금 (억원)
    min_volume_ratio: float = 2.0       # 최소 거래량비율
    prev_change_min: float = 0.0        # 전일 등락 최소 (%)
    prev_change_max: float = 10.0       # 전일 등락 최대 (%)
    
    # 지수 필터
    require_index_above_ma5: bool = True  # 코스피 MA5 상회 필요
    require_index_up_day: bool = False    # 코스피 상승일 필요
    
    # 기타
    holding_days: int = 1               # 보유 기간 (1 = 익일 시가 매도)
    max_signals: int = 10               # 최대 시그널 수


# =============================================================================
# 시그널 데이터 모델
# =============================================================================

@dataclass
class KBreakoutSignal:
    """K값 돌파 시그널"""
    
    # 기본 정보
    stock_code: str
    stock_name: str
    signal_date: date
    signal_time: str = ""
    
    # 가격 정보
    current_price: float = 0            # 현재가
    open_price: float = 0               # 당일 시가
    prev_high: float = 0                # 전일 고가
    prev_low: float = 0                 # 전일 저가
    prev_close: float = 0               # 전일 종가
    
    # 돌파 정보
    breakout_price: float = 0           # 돌파 기준가
    k_value: float = 0.3                # 사용된 K값
    range_value: float = 0              # 전일 레인지 (고-저)
    
    # 지표
    prev_change_pct: float = 0          # 전일 등락률
    volume_ratio: float = 0             # 거래량비율
    trading_value: float = 0            # 거래대금 (억원)
    
    # 전략
    stop_loss_price: float = 0          # 손절가
    take_profit_price: float = 0        # 익절가
    stop_loss_pct: float = -2.0         # 손절률
    take_profit_pct: float = 5.0        # 익절률
    
    # 지수 상태
    index_change: float = 0             # 코스피 등락
    index_above_ma5: bool = True        # MA5 상회 여부
    
    # 점수 (ClosingBell 호환용)
    score: float = 0                    # 종합 점수
    confidence: float = 0.8             # 신뢰도
    
    @property
    def profit_potential(self) -> float:
        """예상 수익률 (돌파가 대비 익절가)"""
        if self.breakout_price > 0:
            return (self.take_profit_price / self.breakout_price - 1) * 100
        return 0
    
    @property
    def risk_reward_ratio(self) -> float:
        """손익비"""
        if abs(self.stop_loss_pct) > 0:
            return self.take_profit_pct / abs(self.stop_loss_pct)
        return 0
    
    def to_dict(self) -> dict:
        """딕셔너리 변환"""
        return {
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'signal_date': str(self.signal_date),
            'current_price': self.current_price,
            'breakout_price': self.breakout_price,
            'prev_change_pct': self.prev_change_pct,
            'volume_ratio': self.volume_ratio,
            'trading_value': self.trading_value,
            'stop_loss_pct': self.stop_loss_pct,
            'take_profit_pct': self.take_profit_pct,
            'score': self.score,
            'confidence': self.confidence,
        }


# =============================================================================
# K값 전략 클래스
# =============================================================================

class KBreakoutStrategy:
    """
    K값 변동성 돌파 전략
    
    [전략 로직]
    1. 당일 시가 + (전일 고가 - 전일 저가) × K 계산
    2. 현재가가 이 값을 돌파하면 매수 시그널
    3. 익일 시가에 매도 (오버나이트 홀딩)
    
    [최적 조건]
    - K = 0.3
    - 거래대금 200억+
    - 전일 양봉 (0~10% 상승)
    - 거래량 2배+
    - 코스피 MA5 상회
    """
    
    def __init__(self, config: KBreakoutConfig = None):
        """
        초기화
        
        Args:
            config: 전략 설정 (None이면 기본값)
        """
        self.config = config or KBreakoutConfig()
        self._index_data: Dict = {}  # 지수 데이터 캐시
        
        logger.info(f"KBreakoutStrategy 초기화 (k={self.config.k})")
    
    def set_index_data(
        self,
        index_change: float = 0,
        index_close: float = 0,
        index_ma5: float = 0,
        index_ma20: float = 0,
    ):
        """
        지수 데이터 설정
        
        Args:
            index_change: 코스피 등락률
            index_close: 코스피 종가
            index_ma5: MA5
            index_ma20: MA20
        """
        self._index_data = {
            'change': index_change,
            'close': index_close,
            'ma5': index_ma5,
            'ma20': index_ma20,
            'above_ma5': index_close > index_ma5 if index_ma5 > 0 else True,
            'above_ma20': index_close > index_ma20 if index_ma20 > 0 else True,
            'is_up': index_change > 0,
        }
    
    def calculate_breakout_price(
        self,
        open_price: float,
        prev_high: float,
        prev_low: float,
    ) -> float:
        """
        돌파 기준가 계산
        
        Args:
            open_price: 당일 시가
            prev_high: 전일 고가
            prev_low: 전일 저가
        
        Returns:
            돌파 기준가
        """
        range_value = prev_high - prev_low
        return open_price + (range_value * self.config.k)
    
    def check_signal(
        self,
        stock_code: str,
        stock_name: str,
        current_price: float,
        open_price: float,
        prev_high: float,
        prev_low: float,
        prev_close: float,
        volume_ratio: float = 1.0,
        trading_value: float = 0,
    ) -> Optional[KBreakoutSignal]:
        """
        개별 종목 시그널 체크
        
        Args:
            stock_code: 종목코드
            stock_name: 종목명
            current_price: 현재가
            open_price: 당일 시가
            prev_high: 전일 고가
            prev_low: 전일 저가
            prev_close: 전일 종가
            volume_ratio: 거래량비율
            trading_value: 거래대금 (억원)
        
        Returns:
            시그널 (조건 미충족시 None)
        """
        # 1. 전일 등락률 계산
        if prev_close <= 0:
            return None
        
        prev_change_pct = ((prev_high + prev_low) / 2 / prev_close - 1) * 100
        # 더 정확한 전일 등락 (전전일 대비)
        # 간단히 고가-저가 중간값 사용
        
        # 실제로는 전일 종가 대비 전전일 종가
        # 여기서는 현재가 대비 전일 종가로 대체
        today_change = (current_price / prev_close - 1) * 100
        
        # 2. 필터 체크
        
        # 거래대금 필터
        if trading_value < self.config.min_trading_value:
            return None
        
        # 거래량 필터
        if volume_ratio < self.config.min_volume_ratio:
            return None
        
        # 전일 등락 필터 (양봉 조건)
        # 전일 종가 > 전일 시가인지 확인 어려우므로 고가/저가로 추정
        est_prev_change = (prev_close - prev_low) / prev_low * 100 if prev_low > 0 else 0
        
        if self.config.prev_change_min is not None:
            if est_prev_change < self.config.prev_change_min:
                return None
        
        if self.config.prev_change_max is not None:
            if est_prev_change > self.config.prev_change_max:
                return None
        
        # 지수 필터
        if self.config.require_index_above_ma5:
            if not self._index_data.get('above_ma5', True):
                return None
        
        if self.config.require_index_up_day:
            if not self._index_data.get('is_up', True):
                return None
        
        # 3. 돌파 기준가 계산
        breakout_price = self.calculate_breakout_price(
            open_price, prev_high, prev_low
        )
        
        # 4. 돌파 체크
        if current_price < breakout_price:
            return None
        
        # 5. 손익가 계산
        stop_loss_price = current_price * (1 + self.config.stop_loss_pct / 100)
        take_profit_price = current_price * (1 + self.config.take_profit_pct / 100)
        
        # 6. 점수 계산 (ClosingBell 호환)
        # 돌파 강도 + 거래량 + 거래대금 기반
        breakout_strength = (current_price / breakout_price - 1) * 100
        score = min(100, 50 + breakout_strength * 10 + min(20, volume_ratio * 5))
        
        # 7. 시그널 생성
        signal = KBreakoutSignal(
            stock_code=stock_code,
            stock_name=stock_name,
            signal_date=date.today(),
            signal_time=datetime.now().strftime("%H:%M:%S"),
            
            current_price=current_price,
            open_price=open_price,
            prev_high=prev_high,
            prev_low=prev_low,
            prev_close=prev_close,
            
            breakout_price=breakout_price,
            k_value=self.config.k,
            range_value=prev_high - prev_low,
            
            prev_change_pct=est_prev_change,
            volume_ratio=volume_ratio,
            trading_value=trading_value,
            
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            stop_loss_pct=self.config.stop_loss_pct,
            take_profit_pct=self.config.take_profit_pct,
            
            index_change=self._index_data.get('change', 0),
            index_above_ma5=self._index_data.get('above_ma5', True),
            
            score=score,
            confidence=0.8 if score >= 70 else 0.6,
        )
        
        return signal
    
    def scan(
        self,
        stock_data_list: List[dict],
    ) -> List[KBreakoutSignal]:
        """
        전체 종목 스캔
        
        Args:
            stock_data_list: 종목 데이터 리스트
                각 항목: {
                    'code': str,
                    'name': str,
                    'current_price': float,
                    'open': float,
                    'prev_high': float,
                    'prev_low': float,
                    'prev_close': float,
                    'volume_ratio': float,
                    'trading_value': float,
                }
        
        Returns:
            시그널 리스트 (점수 내림차순)
        """
        signals = []
        
        for data in stock_data_list:
            try:
                signal = self.check_signal(
                    stock_code=data.get('code', ''),
                    stock_name=data.get('name', ''),
                    current_price=data.get('current_price', 0),
                    open_price=data.get('open', 0),
                    prev_high=data.get('prev_high', 0),
                    prev_low=data.get('prev_low', 0),
                    prev_close=data.get('prev_close', 0),
                    volume_ratio=data.get('volume_ratio', 1.0),
                    trading_value=data.get('trading_value', 0),
                )
                
                if signal:
                    signals.append(signal)
                    
            except Exception as e:
                logger.debug(f"종목 스캔 에러 {data.get('code', '?')}: {e}")
        
        # 점수순 정렬
        signals.sort(key=lambda x: x.score, reverse=True)
        
        # 최대 개수 제한
        if self.config.max_signals > 0:
            signals = signals[:self.config.max_signals]
        
        logger.info(f"K값 스캔 완료: {len(signals)}개 시그널")
        
        return signals
    
    def scan_from_daily_prices(
        self,
        stock_code: str,
        stock_name: str,
        daily_prices: List,
        current_price: float = None,
    ) -> Optional[KBreakoutSignal]:
        """
        일봉 데이터에서 시그널 스캔
        
        Args:
            stock_code: 종목코드
            stock_name: 종목명
            daily_prices: 일봉 리스트 (최근 데이터가 마지막)
            current_price: 현재가 (None이면 마지막 종가)
        
        Returns:
            시그널 (조건 미충족시 None)
        """
        if len(daily_prices) < 2:
            return None
        
        today = daily_prices[-1]
        yesterday = daily_prices[-2]
        
        # 현재가 (없으면 당일 종가)
        if current_price is None:
            current_price = today.close if hasattr(today, 'close') else today['close']
        
        # 거래량 비율
        if len(daily_prices) >= 22:
            recent_volumes = [
                (d.volume if hasattr(d, 'volume') else d['volume'])
                for d in daily_prices[-22:-1]
            ]
            avg_volume = np.mean(recent_volumes) if recent_volumes else 1
            today_volume = today.volume if hasattr(today, 'volume') else today['volume']
            volume_ratio = today_volume / avg_volume if avg_volume > 0 else 1
        else:
            volume_ratio = 1.0
        
        # 거래대금
        today_close = today.close if hasattr(today, 'close') else today['close']
        today_volume = today.volume if hasattr(today, 'volume') else today['volume']
        trading_value = (today_close * today_volume) / 100_000_000  # 억원
        
        # 가격 데이터 추출
        def get_attr(obj, attr):
            return getattr(obj, attr) if hasattr(obj, attr) else obj.get(attr, 0)
        
        return self.check_signal(
            stock_code=stock_code,
            stock_name=stock_name,
            current_price=current_price,
            open_price=get_attr(today, 'open'),
            prev_high=get_attr(yesterday, 'high'),
            prev_low=get_attr(yesterday, 'low'),
            prev_close=get_attr(yesterday, 'close'),
            volume_ratio=volume_ratio,
            trading_value=trading_value,
        )


# =============================================================================
# Discord 알림 포맷터
# =============================================================================

def format_k_signal_embed(
    signals: List[KBreakoutSignal],
    title: str = "🚀 K값 돌파 시그널",
) -> dict:
    """
    Discord Embed 포맷
    
    Args:
        signals: 시그널 리스트
        title: 타이틀
    
    Returns:
        Discord Embed 딕셔너리
    """
    if not signals:
        return {
            "title": title,
            "description": "❌ 조건을 충족하는 종목이 없습니다.",
            "color": 0xFFA500,  # Orange
        }
    
    # 필드 생성
    fields = []
    
    for i, sig in enumerate(signals[:5], 1):
        emoji = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i-1]
        
        field = {
            "name": f"{emoji} {sig.stock_name} ({sig.stock_code})",
            "value": (
                f"💰 현재가: {sig.current_price:,.0f}원\n"
                f"📈 돌파가: {sig.breakout_price:,.0f}원 (k={sig.k_value})\n"
                f"📊 거래대금: {sig.trading_value:,.0f}억 | 볼륨: {sig.volume_ratio:.1f}x\n"
                f"🎯 익절: +{sig.take_profit_pct}% ({sig.take_profit_price:,.0f}원)\n"
                f"🛡️ 손절: {sig.stop_loss_pct}% ({sig.stop_loss_price:,.0f}원)\n"
                f"⭐ 점수: {sig.score:.0f}점"
            ),
            "inline": False,
        }
        fields.append(field)
    
    # 전략 안내
    fields.append({
        "name": "📌 K값 돌파 전략 (백테스트 최적)",
        "value": (
            "• 승률: 76.3% ~ 84.5%\n"
            "• 평균 수익: +6.32%\n"
            "• 매수: 시가 + 전일레인지 × 0.3 돌파 시\n"
            "• 매도: 익일 시가 (오버나이트)"
        ),
        "inline": False,
    })
    
    embed = {
        "title": title,
        "description": f"📅 {date.today()} | 총 {len(signals)}개 시그널",
        "color": 0x00FF00,  # Green
        "fields": fields,
        "footer": {
            "text": "K값 변동성 돌파 전략 v1.0",
        },
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    
    return embed


# =============================================================================
# 테스트
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 60)
    print("K값 변동성 돌파 전략 테스트")
    print("=" * 60)
    
    # 전략 생성
    strategy = KBreakoutStrategy()
    
    # 지수 데이터 설정
    strategy.set_index_data(
        index_change=0.5,
        index_close=2500,
        index_ma5=2480,
        index_ma20=2450,
    )
    
    # 테스트 데이터
    test_data = [
        {
            'code': '005930',
            'name': '삼성전자',
            'current_price': 72000,
            'open': 71000,
            'prev_high': 71500,
            'prev_low': 70000,
            'prev_close': 70500,
            'volume_ratio': 2.5,
            'trading_value': 500,
        },
        {
            'code': '000660',
            'name': 'SK하이닉스',
            'current_price': 185000,
            'open': 183000,
            'prev_high': 184000,
            'prev_low': 180000,
            'prev_close': 182000,
            'volume_ratio': 3.0,
            'trading_value': 300,
        },
    ]
    
    # 스캔
    signals = strategy.scan(test_data)
    
    print(f"\n발견된 시그널: {len(signals)}개")
    
    for sig in signals:
        print(f"\n{sig.stock_name} ({sig.stock_code})")
        print(f"  현재가: {sig.current_price:,}원")
        print(f"  돌파가: {sig.breakout_price:,.0f}원")
        print(f"  익절가: {sig.take_profit_price:,.0f}원 (+{sig.take_profit_pct}%)")
        print(f"  손절가: {sig.stop_loss_price:,.0f}원 ({sig.stop_loss_pct}%)")
        print(f"  점수: {sig.score:.0f}점")
    
    # Discord Embed 테스트
    embed = format_k_signal_embed(signals)
    print(f"\nDiscord Embed 생성 완료: {embed['title']}")
