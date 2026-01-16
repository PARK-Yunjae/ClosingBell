#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K값 스크리닝 서비스
====================
K값 변동성 돌파 전략 실시간 스크리닝

사용법:
    from src.services.k_screener import run_k_screening
    
    result = run_k_screening(send_alert=True)
"""

import logging
import time
from datetime import datetime, date
from typing import List, Dict, Optional

from src.config.settings import settings
from src.domain.k_breakout import (
    KBreakoutStrategy,
    KBreakoutConfig,
    KBreakoutSignal,
    format_k_signal_embed,
)
from src.adapters.discord_notifier import get_discord_notifier
from src.adapters.kis_client import get_kis_client
from src.config.constants import MIN_DAILY_DATA_COUNT

logger = logging.getLogger(__name__)


def run_k_screening(
    send_alert: bool = True,
    max_stocks: int = 200,
    save_to_db: bool = True,
) -> Dict:
    """
    K값 변동성 돌파 스크리닝 실행
    
    Args:
        send_alert: Discord 알림 발송 여부
        max_stocks: 스캔할 최대 종목 수
        save_to_db: DB 저장 여부
    
    Returns:
        스크리닝 결과
    """
    start_time = time.time()
    logger.info("K값 스크리닝 시작")
    
    result = {
        'screen_date': str(date.today()),
        'screen_time': datetime.now().strftime("%H:%M"),
        'status': 'SUCCESS',
        'total_scanned': 0,
        'signals': [],
        'execution_time_sec': 0,
        'error': None,
    }
    
    try:
        # 1. KIS 클라이언트
        kis_client = get_kis_client()
        
        # 2. 전략 초기화
        config = KBreakoutConfig(
            k=0.3,
            stop_loss_pct=-2.0,
            take_profit_pct=5.0,
            min_trading_value=200.0,
            min_volume_ratio=2.0,
            prev_change_min=0.0,
            prev_change_max=10.0,
            require_index_above_ma5=True,
            max_signals=10,
        )
        strategy = KBreakoutStrategy(config)
        
        # 3. 지수 데이터 조회 (선택사항 - 실패해도 계속 진행)
        logger.info("코스피 지수 조회 시도...")
        try:
            # 지수 조회는 선택사항 - 실패 시 필터 비활성화
            strategy.config.require_index_above_ma5 = False
            logger.info("지수 필터 비활성화 (API 미지원)")
        except Exception as e:
            logger.warning(f"지수 조회 실패, 필터 비활성화: {e}")
            strategy.config.require_index_above_ma5 = False
        
        # 4. 유니버스 구성 (거래대금 상위)
        logger.info(f"유니버스 조회 (거래대금 상위 {max_stocks}개)...")
        
        try:
            # 거래대금 상위 종목 (기존 메서드 사용)
            universe = kis_client.get_top_trading_value_stocks(
                min_trading_value=50.0,  # K값용: 50억 이상으로 느슨하게
                limit=max_stocks
            )
            logger.info(f"유니버스: {len(universe)}개 종목")
        except Exception as e:
            logger.error(f"유니버스 조회 실패: {e}")
            result['status'] = 'FAILED'
            result['error'] = str(e)
            return result
        
        # 5. 종목별 스캔
        logger.info("종목 스캔 중...")
        signals = []
        
        for i, stock in enumerate(universe):
            try:
                # StockInfo 객체에서 속성 추출
                stock_code = stock.code
                stock_name = stock.name
                
                # 일봉 데이터 조회
                daily_prices = kis_client.get_daily_prices(
                    stock_code,
                    count=MIN_DAILY_DATA_COUNT + 5
                )
                
                if len(daily_prices) < 2:
                    continue
                
                # 현재가 조회
                current_data = kis_client.get_current_price(stock_code)
                current_price = current_data.price if current_data else daily_prices[-1].close
                
                # 시그널 체크
                signal = strategy.scan_from_daily_prices(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    daily_prices=daily_prices,
                    current_price=current_price,
                )
                
                if signal:
                    signals.append(signal)
                    logger.info(f"  ✅ {stock_name} ({stock_code}): {signal.score:.0f}점")
                
                # 진행률 (50개마다)
                if (i + 1) % 50 == 0:
                    logger.info(f"  진행: {i+1}/{len(universe)}")
                
            except Exception as e:
                logger.debug(f"종목 스캔 에러 {stock_code}: {e}")
                continue
        
        result['total_scanned'] = len(universe)
        result['signals'] = signals
        
        # 6. 결과 정렬
        signals.sort(key=lambda x: x.score, reverse=True)
        
        logger.info(f"스캔 완료: {len(signals)}개 시그널 발견")
        
        # 7. Discord 알림
        if send_alert and signals:
            logger.info("Discord 알림 발송...")
            notifier = get_discord_notifier()
            
            embed = format_k_signal_embed(
                signals[:5],
                title=f"🚀 K값 돌파 시그널 ({result['screen_time']})"
            )
            
            success = notifier.send_embed(embed)
            
            if success:
                logger.info("Discord 알림 발송 성공")
            else:
                logger.warning("Discord 알림 발송 실패")
        
        # 8. DB 저장 (옵션)
        if save_to_db and signals:
            try:
                from src.infrastructure.repository import get_k_signal_repository
                k_repo = get_k_signal_repository()
                
                signal_dicts = []
                for i, sig in enumerate(signals):
                    sig_dict = {
                        'stock_code': sig.stock_code,
                        'stock_name': sig.stock_name,
                        'signal_date': sig.signal_date,
                        'signal_time': sig.signal_time,
                        'current_price': sig.current_price,
                        'open_price': sig.open_price,
                        'breakout_price': sig.breakout_price,
                        'prev_high': sig.prev_high,
                        'prev_low': sig.prev_low,
                        'prev_close': sig.prev_close,
                        'k_value': sig.k_value,
                        'range_value': sig.range_value,
                        'prev_change_pct': sig.prev_change_pct,
                        'volume_ratio': sig.volume_ratio,
                        'trading_value': sig.trading_value,
                        'stop_loss_pct': sig.stop_loss_pct,
                        'take_profit_pct': sig.take_profit_pct,
                        'stop_loss_price': sig.stop_loss_price,
                        'take_profit_price': sig.take_profit_price,
                        'score': sig.score,
                        'rank': i + 1,
                    }
                    signal_dicts.append(sig_dict)
                
                k_repo.save_signals(signal_dicts)
                logger.info(f"DB 저장 완료: {len(signals)}개")
            except Exception as e:
                logger.warning(f"DB 저장 실패: {e}")
        
    except Exception as e:
        logger.error(f"K값 스크리닝 에러: {e}")
        result['status'] = 'FAILED'
        result['error'] = str(e)
    
    # 실행 시간
    result['execution_time_sec'] = time.time() - start_time
    
    logger.info(f"K값 스크리닝 완료 ({result['execution_time_sec']:.1f}초)")
    
    return result


def print_k_result(result: Dict):
    """결과 출력"""
    print(f"\n{'='*60}")
    print(f"🚀 K값 변동성 돌파 스크리닝 결과")
    print(f"{'='*60}")
    print(f"📅 날짜: {result['screen_date']}")
    print(f"⏰ 시간: {result['screen_time']}")
    print(f"📊 스캔 종목: {result['total_scanned']}개")
    print(f"✅ 시그널: {len(result.get('signals', []))}개")
    print(f"⏱️ 실행 시간: {result['execution_time_sec']:.1f}초")
    
    signals = result.get('signals', [])
    if signals:
        print(f"\n{'─'*60}")
        print("🏆 TOP 5 시그널")
        print(f"{'─'*60}")
        
        for i, sig in enumerate(signals[:5], 1):
            emoji = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i-1]
            print(f"\n{emoji} {sig.stock_name} ({sig.stock_code})")
            print(f"   💰 현재가: {sig.current_price:,}원")
            print(f"   📈 돌파가: {sig.breakout_price:,.0f}원 (k={sig.k_value})")
            print(f"   📊 거래대금: {sig.trading_value:,.0f}억 | 볼륨: {sig.volume_ratio:.1f}x")
            print(f"   🎯 익절: +{sig.take_profit_pct}% → {sig.take_profit_price:,.0f}원")
            print(f"   🛡️ 손절: {sig.stop_loss_pct}% → {sig.stop_loss_price:,.0f}원")
            print(f"   ⭐ 점수: {sig.score:.0f}점")
    else:
        print("\n❌ 조건을 충족하는 종목이 없습니다.")
    
    print(f"\n{'='*60}")
    print("📌 K값 전략 (백테스트 최적)")
    print(f"{'='*60}")
    print("• 승률: 76.3% ~ 84.5%")
    print("• 평균 수익: +6.32%")
    print("• 매수: 시가 + 전일레인지 × 0.3 돌파 시")
    print("• 매도: 익일 시가 (오버나이트)")


# 테스트
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s - %(message)s'
    )
    
    print("K값 스크리닝 테스트 (알림 없음)")
    result = run_k_screening(send_alert=False, save_to_db=False)
    print_k_result(result)
