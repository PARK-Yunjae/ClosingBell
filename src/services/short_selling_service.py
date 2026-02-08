"""
공매도/대차거래 분석 서비스

1순위: 키움 REST API (ka10014, ka20068)
2순위: KRX 스크래핑 (TODO: Phase 5)

공매도 데이터를 '위험 회피' 관점에서 분석:
- 공매도 비중 높은 종목 → 스코어 감점
- 대차잔고 증가 중 → 경고 태그
- 숏커버링 감지 → 반등 기대 신호
"""

import logging
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional, Tuple

from src.domain.short_selling import (
    ShortSellingDaily, StockLendingDaily, ShortSellingScore
)

logger = logging.getLogger(__name__)

# 공매도 기준값
SHORT_RATIO_HIGH = 10.0      # 공매도 비중 위험 기준 (%)
SHORT_RATIO_WARN = 7.0       # 공매도 비중 경고 기준 (%)
SHORT_RATIO_LOW = 3.0        # 공매도 비중 안전 기준 (%)
SHORT_RATIO_SURGE = 100.0    # 전일비 급증 기준 (% 증가)
SHORT_RATIO_DROP = -30.0     # 전일비 급감 기준 (% 감소)
LENDING_TREND_DAYS = 3       # 대차잔고 추세 판단 일수


def parse_short_selling_data(raw_list: List[Dict]) -> List[ShortSellingDaily]:
    """키움 API 원시 데이터 → ShortSellingDaily 변환"""
    result = []
    for item in raw_list:
        try:
            dt_str = item.get('dt', '').strip()
            if not dt_str:
                continue
            
            result.append(ShortSellingDaily(
                date=datetime.strptime(dt_str, '%Y%m%d').date(),
                close_price=_parse_int(item.get('close_pric', '0')),
                change_rate=_parse_float(item.get('flu_rt', '0')),
                trade_volume=_parse_int(item.get('trde_qty', '0')),
                short_volume=_parse_int(item.get('shrts_qty', '0')),
                short_ratio=_parse_float(item.get('trde_wght', '0')),
                cumulative_short=_parse_int(item.get('ovr_shrts_qty', '0')),
                short_avg_price=_parse_int(item.get('shrts_avg_pric', '0')),
                short_trade_value=_parse_int(item.get('shrts_trde_prica', '0')),
            ))
        except (ValueError, TypeError) as e:
            logger.warning(f"공매도 데이터 파싱 오류: {e}")
            continue
    
    # 날짜순 정렬 (오래된 → 최신)
    result.sort(key=lambda x: x.date)
    return result


def parse_stock_lending_data(raw_list: List[Dict]) -> List[StockLendingDaily]:
    """키움 API 원시 데이터 → StockLendingDaily 변환"""
    result = []
    for item in raw_list:
        try:
            dt_str = item.get('dt', '').strip()
            if not dt_str:
                continue
            
            result.append(StockLendingDaily(
                date=datetime.strptime(dt_str, '%Y%m%d').date(),
                lending_volume=_parse_int(item.get('dbrt_trde_cntrcnt', '0')),
                repayment_volume=_parse_int(item.get('dbrt_trde_rpy', '0')),
                net_change=_parse_signed_int(item.get('dbrt_trde_irds', '0')),
                balance_shares=_parse_int(item.get('rmnd', '0')),
                balance_amount=_parse_int(item.get('remn_amt', '0')),
            ))
        except (ValueError, TypeError) as e:
            logger.warning(f"대차거래 데이터 파싱 오류: {e}")
            continue
    
    result.sort(key=lambda x: x.date)
    return result


def analyze_short_selling(
    stock_code: str,
    short_data: List[ShortSellingDaily],
    lending_data: List[StockLendingDaily],
) -> ShortSellingScore:
    """공매도/대차 종합 분석 → 스코어 산출
    
    점수 체계 (-10 ~ +10):
    위험 신호 (감점):
      - 공매도 비중 > 10%: -3
      - 공매도 비중 > 7%:  -1.5
      - 공매도 비중 급증:   -2
      - 대차잔고 3일 연속 증가: -1.5
    
    호의적 신호 (가점):
      - 공매도 비중 < 3%:  +1
      - 공매도 비중 급감 (숏커버링): +2
      - 대차잔고 3일 연속 감소: +1.5
    """
    score = ShortSellingScore(stock_code=stock_code)
    
    if not short_data and not lending_data:
        score.summary = "데이터없음"
        return score
    
    points = 0.0
    tags = []
    
    # === 공매도 분석 ===
    if short_data:
        latest = short_data[-1]
        score.latest_short_ratio = latest.short_ratio
        
        # 5일 평균
        recent_5 = short_data[-5:] if len(short_data) >= 5 else short_data
        score.avg_short_ratio_5d = round(
            sum(d.short_ratio for d in recent_5) / len(recent_5), 2
        )
        
        # 비중 변화율
        if len(short_data) >= 2:
            prev = short_data[-2]
            if prev.short_ratio > 0:
                pct_change = ((latest.short_ratio - prev.short_ratio) / prev.short_ratio) * 100
                score.short_ratio_change = round(pct_change, 1)
        
        # [위험] 공매도 비중 높음
        if latest.short_ratio >= SHORT_RATIO_HIGH:
            points -= 3.0
            tags.append("🔻숏과열")
        elif latest.short_ratio >= SHORT_RATIO_WARN:
            points -= 1.5
            tags.append("⚠️숏주의")
        
        # [위험] 공매도 비중 급증
        if score.short_ratio_change >= SHORT_RATIO_SURGE:
            points -= 2.0
            tags.append("⚠️숏급증")
        
        # [호의] 공매도 비중 낮음
        if latest.short_ratio <= SHORT_RATIO_LOW and latest.short_ratio > 0:
            points += 1.0
            tags.append("✅숏비중낮음")
        
        # [호의] 숏커버링 (3일 연속 감소)
        if len(short_data) >= 3:
            last_3 = [d.short_ratio for d in short_data[-3:]]
            if last_3[0] > last_3[1] > last_3[2] and last_3[0] > 0:
                points += 2.0
                tags.append("✅숏커버링")
    
    # === 대차거래 분석 ===
    if lending_data:
        latest_lending = lending_data[-1]
        score.latest_lending_balance = latest_lending.balance_shares
        
        # 3일 잔고 변화
        if len(lending_data) >= LENDING_TREND_DAYS:
            recent_n = lending_data[-LENDING_TREND_DAYS:]
            score.lending_trend_3d = recent_n[-1].balance_shares - recent_n[0].balance_shares
            
            # 연속 감소 일수 계산
            consec_decrease = 0
            for i in range(len(lending_data) - 1, 0, -1):
                if lending_data[i].balance_shares < lending_data[i-1].balance_shares:
                    consec_decrease += 1
                else:
                    break
            score.lending_consecutive_decrease = consec_decrease
            
            # [위험] 대차잔고 연속 증가
            if all(
                lending_data[-(j+1)].balance_shares > lending_data[-(j+2)].balance_shares
                for j in range(min(LENDING_TREND_DAYS - 1, len(lending_data) - 1))
            ):
                points -= 1.5
                tags.append("📉대차증가")
            
            # [호의] 대차잔고 연속 감소
            if consec_decrease >= LENDING_TREND_DAYS:
                points += 1.5
                tags.append("✅대차감소")
    
    # === 점수 클램핑 ===
    score.score = round(max(-10, min(10, points)), 1)
    score.tags = tags
    
    # === 요약 텍스트 ===
    parts = []
    if short_data:
        ratio_arrow = "↑" if score.short_ratio_change > 10 else "↓" if score.short_ratio_change < -10 else "→"
        parts.append(f"공매도:{score.latest_short_ratio:.1f}%{ratio_arrow}")
    if lending_data and score.lending_consecutive_decrease > 0:
        parts.append(f"대차:{score.lending_consecutive_decrease}일↓")
    elif lending_data and score.lending_trend_3d > 0:
        parts.append(f"대차:증가중")
    
    if tags:
        parts.append(" ".join(tags[:2]))  # 태그는 2개까지만 표시
    
    score.summary = " │ ".join(parts) if parts else "정상"
    
    return score


def fetch_and_analyze(
    stock_code: str,
    kiwoom_client,
    lookback_days: int = 20,
) -> ShortSellingScore:
    """API에서 데이터 조회 + 분석 (원스텝)
    
    Args:
        stock_code: 종목코드
        kiwoom_client: KiwoomRestClient 인스턴스
        lookback_days: 조회 기간 (영업일 기준)
    
    Returns:
        ShortSellingScore
    """
    today = date.today()
    start = today - timedelta(days=int(lookback_days * 1.6))  # 영업일→달력일 변환
    
    start_str = start.strftime('%Y%m%d')
    end_str = today.strftime('%Y%m%d')
    
    short_data = []
    lending_data = []
    
    # 1순위: 키움 API
    try:
        raw_short = kiwoom_client.get_short_selling_trend(stock_code, start_str, end_str)
        short_data = parse_short_selling_data(raw_short)
        logger.debug(f"[{stock_code}] 공매도 {len(short_data)}일 로드")
    except Exception as e:
        logger.warning(f"[{stock_code}] 공매도 API 오류: {e}")
    
    try:
        raw_lending = kiwoom_client.get_stock_lending_trend(stock_code, start_str, end_str)
        lending_data = parse_stock_lending_data(raw_lending)
        logger.debug(f"[{stock_code}] 대차거래 {len(lending_data)}일 로드")
    except Exception as e:
        logger.warning(f"[{stock_code}] 대차거래 API 오류: {e}")
    
    # TODO Phase 5: API 실패 시 KRX 스크래핑 폴백
    
    return analyze_short_selling(stock_code, short_data, lending_data)


def batch_analyze(
    stock_codes: List[str],
    kiwoom_client,
    lookback_days: int = 20,
) -> Dict[str, ShortSellingScore]:
    """여러 종목 일괄 분석 (TOP5용)
    
    Returns:
        {stock_code: ShortSellingScore} 딕셔너리
    """
    results = {}
    for code in stock_codes:
        try:
            results[code] = fetch_and_analyze(code, kiwoom_client, lookback_days)
        except Exception as e:
            logger.error(f"[{code}] 공매도 분석 실패: {e}")
            results[code] = ShortSellingScore(stock_code=code, summary="분석실패")
    
    return results


# ========================================
# 유틸리티
# ========================================
def _parse_int(value: str) -> int:
    try:
        return int(str(value).replace(',', '').replace('+', '').replace('-', '').strip())
    except (ValueError, TypeError):
        return 0

def _parse_signed_int(value: str) -> int:
    """부호 유지 파싱"""
    try:
        cleaned = str(value).replace(',', '').strip()
        return int(cleaned)
    except (ValueError, TypeError):
        return 0

def _parse_float(value: str) -> float:
    try:
        return float(str(value).replace('%', '').replace('+', '').strip())
    except (ValueError, TypeError):
        return 0.0
