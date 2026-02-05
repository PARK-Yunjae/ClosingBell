"""
매물대(Volume Profile) 분석 모듈 - ClosingBell v9.0
====================================================

OHLCV 일봉 데이터로 HTS 매물대와 동일한 가격대별 거래량 분포를 근사 계산.
점수 체계에 편입하여 상승 여력(위 매물 적음) vs 저항벽(위 매물 두꺼움) 판단.

사용법:
    from src.domain.volume_profile import calc_volume_profile_score
    
    # CSV에서 직접
    score, tag, detail = calc_volume_profile_score("090710", n_days=100)
    
    # DataFrame 전달
    result = calc_volume_profile(df, current_price=13360, n_days=100)
    print(result.score, result.tag, result.above_pct, result.below_pct)

설치 위치: src/domain/volume_profile.py
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ============================================================
# 데이터 모델
# ============================================================

@dataclass
class VolumeProfileBand:
    """하나의 가격대 밴드"""
    price_low: float
    price_high: float
    volume: float
    pct: float            # 전체 대비 % (0~100)
    is_current: bool      # 현재가 포함 밴드 여부


@dataclass
class VolumeProfileResult:
    """매물대 분석 결과"""
    bands: List[VolumeProfileBand] = field(default_factory=list)
    current_price: float = 0.0
    period_days: int = 0
    
    # 핵심 지표
    above_pct: float = 0.0     # 현재가 위 매물 비율 (0~100)
    below_pct: float = 0.0     # 현재가 아래 매물 비율 (0~100)
    current_pct: float = 0.0   # 현재가 밴드 매물 비율
    poc_price: float = 0.0     # Point of Control (최다 거래량 가격)
    poc_pct: float = 0.0       # POC 비율
    
    # 점수
    score: float = 6.0         # 0~13 (기본: 중립 6)
    tag: str = "데이터부족"     # "상승여력" / "중립" / "저항벽" / "데이터부족"
    
    # 디버깅용
    above_score: float = 0.0
    below_score: float = 0.0
    poc_bonus: float = 0.0


# 중립 기본값 (데이터 부족 시)
VP_SCORE_NEUTRAL = 6.0


# ============================================================
# 핵심 계산 함수
# ============================================================

def calc_volume_profile(
    df: pd.DataFrame,
    current_price: float,
    n_days: int = 100,
    n_bands: int = 10,
) -> VolumeProfileResult:
    """
    OHLCV DataFrame에서 Volume Profile 계산.
    
    HTS 매물대와 동일한 방식:
    1) 최근 n_days일의 전체 가격 범위를 n_bands개 밴드로 분할
    2) 각 일봉의 거래량을 High~Low에 걸쳐 가중 분배
    3) 밴드별 누적 → 현재가 대비 위/아래 비율 계산
    
    Args:
        df: OHLCV DataFrame (columns: date/open/high/low/close/volume 필수)
        current_price: 현재가 (또는 최근 종가)
        n_days: 분석 기간 (기본 100일, HTS는 50/100/150/200/250/300 지원)
        n_bands: 매물대 수 (기본 10, HTS 기본값)
    
    Returns:
        VolumeProfileResult
    """
    if df is None or len(df) < 10:
        return _empty_result(current_price, n_days)
    
    # 최근 n_days만 사용
    recent = df.tail(n_days).copy()
    if len(recent) < 10:
        return _empty_result(current_price, n_days)
    
    # 필수 컬럼 검증
    required = {'high', 'low', 'close', 'open', 'volume'}
    if not required.issubset(set(recent.columns)):
        logger.warning(f"Volume Profile: 필수 컬럼 부족 {required - set(recent.columns)}")
        return _empty_result(current_price, n_days)
    
    # 전체 가격 범위
    period_low = float(recent['low'].min())
    period_high = float(recent['high'].max())
    
    if period_high <= period_low or period_low <= 0:
        return _empty_result(current_price, n_days)
    
    # 밴드 경계
    band_size = (period_high - period_low) / n_bands
    band_edges = [period_low + i * band_size for i in range(n_bands + 1)]
    band_volumes = np.zeros(n_bands, dtype=np.float64)
    
    # 각 일봉의 거래량을 가격대에 분배
    for _, row in recent.iterrows():
        try:
            h = float(row['high'])
            l = float(row['low'])
            c = float(row['close'])
            o = float(row['open'])
            vol = float(row['volume'])
        except (ValueError, TypeError):
            continue
        
        if vol <= 0:
            continue
        
        if h <= l or l <= 0:
            # 보합/오류 → 종가 밴드에 전량
            idx = _find_band(c, band_edges, n_bands)
            band_volumes[idx] += vol
            continue
        
        # Typical Price 가중 분배
        # HTS도 단순 균등이 아닌 거래 밀집 가격대 추정 사용
        typical_price = (h + l + c) / 3.0
        
        low_band = _find_band(l, band_edges, n_bands)
        high_band = _find_band(h, band_edges, n_bands)
        
        if low_band == high_band:
            band_volumes[low_band] += vol
        else:
            # 여러 밴드에 걸침 → 가중 분배
            weights = np.zeros(n_bands)
            half_range = max((h - l) / 2.0, 1.0)
            
            for bi in range(low_band, high_band + 1):
                band_mid = (band_edges[bi] + band_edges[bi + 1]) / 2.0
                dist = abs(band_mid - typical_price)
                # Typical Price에 가까울수록 가중치 높음 (최소 0.1)
                weights[bi] = max(0.1, 1.0 - dist / half_range)
            
            w_sum = weights.sum()
            if w_sum > 0:
                for bi in range(low_band, high_band + 1):
                    band_volumes[bi] += vol * (weights[bi] / w_sum)
    
    # 결과 조립
    total_vol = band_volumes.sum()
    if total_vol <= 0:
        return _empty_result(current_price, n_days)
    
    bands = []
    above_vol = 0.0
    below_vol = 0.0
    current_vol = 0.0
    current_band_idx = _find_band(current_price, band_edges, n_bands)
    
    for i in range(n_bands):
        pct = (band_volumes[i] / total_vol) * 100.0
        is_current = (i == current_band_idx)
        
        bands.append(VolumeProfileBand(
            price_low=round(band_edges[i], 0),
            price_high=round(band_edges[i + 1], 0),
            volume=round(band_volumes[i], 0),
            pct=round(pct, 2),
            is_current=is_current,
        ))
        
        if i > current_band_idx:
            above_vol += band_volumes[i]
        elif i < current_band_idx:
            below_vol += band_volumes[i]
        else:
            current_vol += band_volumes[i]
    
    above_pct = round((above_vol / total_vol) * 100, 2)
    below_pct = round((below_vol / total_vol) * 100, 2)
    current_pct = round((current_vol / total_vol) * 100, 2)
    
    # POC (Point of Control)
    poc_idx = int(np.argmax(band_volumes))
    poc_price = (band_edges[poc_idx] + band_edges[poc_idx + 1]) / 2.0
    poc_pct = round((band_volumes[poc_idx] / total_vol) * 100, 2)
    
    # 점수 계산
    score, tag, a_s, b_s, p_b = _calc_supply_score(
        above_pct, below_pct, current_pct,
        poc_idx, current_band_idx, n_bands
    )
    
    return VolumeProfileResult(
        bands=bands,
        current_price=current_price,
        period_days=len(recent),
        above_pct=above_pct,
        below_pct=below_pct,
        current_pct=current_pct,
        poc_price=round(poc_price, 0),
        poc_pct=poc_pct,
        score=score,
        tag=tag,
        above_score=a_s,
        below_score=b_s,
        poc_bonus=p_b,
    )


# ============================================================
# 파일 기반 편의 함수 (screener_service에서 호출)
# ============================================================

def calc_volume_profile_from_csv(
    stock_code: str,
    current_price: float,
    ohlcv_dir: Path,
    n_days: int = 100,
    n_bands: int = 10,
) -> VolumeProfileResult:
    """
    CSV 파일에서 직접 Volume Profile 계산.
    
    Args:
        stock_code: 종목코드 (e.g., "090710")
        current_price: 현재가
        ohlcv_dir: OHLCV CSV 디렉토리 경로
        n_days: 분석 기간
        n_bands: 밴드 수
    """
    csv_path = ohlcv_dir / f"{stock_code}.csv"
    
    if not csv_path.exists():
        logger.debug(f"VP: {stock_code} CSV 없음")
        return _empty_result(current_price, n_days)


def calc_volume_profile_from_kiwoom(
    data: dict,
    current_price: float,
    n_days: int,
    cur_entry: int = 0,
) -> VolumeProfileResult:
    """키움 매물대 응답을 VolumeProfileResult로 변환."""
    if not data:
        return _empty_result(current_price, n_days)

    # list 형태 응답 추출 (키 이름은 문서/버전에 따라 다름)
    list_candidates = []
    for key, value in data.items():
        if isinstance(value, list) and value:
            list_candidates.append((key, value))

    def _find_float(item: dict, keys: list) -> Optional[float]:
        for k in keys:
            if k in item:
                try:
                    return float(str(item.get(k, "0")).replace(",", ""))
                except (ValueError, TypeError):
                    return None
        return None

    bands: List[VolumeProfileBand] = []
    for _, items in list_candidates:
        # 매물대 리스트 후보 탐색
        if not isinstance(items[0], dict):
            continue
        if not any(
            k in items[0] for k in ["prps_pric", "prps_pric_strt", "prps_pric_end", "price", "pric"]
        ):
            continue

        for item in items:
            low = _find_float(item, ["prps_pric_strt", "pric_strt", "price_low", "low", "prps_low"])
            high = _find_float(item, ["prps_pric_end", "pric_end", "price_high", "high", "prps_high"])
            if low is None and high is None:
                price = _find_float(item, ["prps_pric", "price", "pric"])
                if price is not None:
                    low = price
                    high = price
            if low is None or high is None:
                continue

            pct = _find_float(item, ["prps_rt", "prps_ratio", "ratio", "pct"])
            vol = _find_float(item, ["prps_qty", "volume", "qty", "trde_qty"])
            if pct is None:
                pct = 0.0
            if vol is None:
                vol = 0.0

            bands.append(
                VolumeProfileBand(
                    price_low=low,
                    price_high=high,
                    volume=vol,
                    pct=pct,
                    is_current=(low <= current_price <= high),
                )
            )
        break

    if not bands:
        return _empty_result(current_price, n_days)

    # above/below 계산
    above_pct = sum(b.pct for b in bands if b.price_low > current_price)
    below_pct = sum(b.pct for b in bands if b.price_high < current_price)
    current_pct = sum(b.pct for b in bands if b.is_current)

    if cur_entry == 1:
        below_pct += current_pct

    # POC
    poc_idx = max(range(len(bands)), key=lambda i: bands[i].pct)
    poc_price = (bands[poc_idx].price_low + bands[poc_idx].price_high) / 2.0
    current_idx = next((i for i, b in enumerate(bands) if b.is_current), poc_idx)

    score, tag, a_s, b_s, p_b = _calc_supply_score(
        above_pct, below_pct, current_pct, poc_idx, current_idx, len(bands)
    )

    return VolumeProfileResult(
        bands=bands,
        current_price=current_price,
        period_days=n_days,
        above_pct=round(above_pct, 2),
        below_pct=round(below_pct, 2),
        current_pct=round(current_pct, 2),
        poc_price=round(poc_price, 0),
        poc_pct=round(bands[poc_idx].pct, 2),
        score=score,
        tag=tag,
        above_score=a_s,
        below_score=b_s,
        poc_bonus=p_b,
    )
    
    try:
        df = pd.read_csv(csv_path, parse_dates=['date'])
        df = df.sort_values('date').reset_index(drop=True)
        return calc_volume_profile(df, current_price, n_days, n_bands)
    except Exception as e:
        logger.warning(f"VP: {stock_code} CSV 파싱 오류: {e}")
        return _empty_result(current_price, n_days)


def calc_volume_profile_score(
    stock_code: str,
    current_price: float,
    ohlcv_dir: Path,
    n_days: int = 100,
) -> Tuple[float, str, VolumeProfileResult]:
    """
    점수 체계 편입용 간편 함수.
    
    Returns:
        (score, tag, full_result)
        score: 0~13 float
        tag: "상승여력" / "중립" / "저항벽" / "데이터부족"
    """
    result = calc_volume_profile_from_csv(stock_code, current_price, ohlcv_dir, n_days)
    return result.score, result.tag, result


# ============================================================
# 내부 함수
# ============================================================

def _find_band(price: float, edges: list, n_bands: int) -> int:
    """가격이 속하는 밴드 인덱스 (0-indexed)"""
    for i in range(n_bands):
        if price <= edges[i + 1]:
            return i
    return n_bands - 1


def _calc_supply_score(
    above_pct: float,
    below_pct: float,
    current_pct: float,
    poc_idx: int,
    current_idx: int,
    n_bands: int,
) -> Tuple[float, str, float, float, float]:
    """
    매물대 점수 계산 (0~13점)
    
    점수 구성:
      (1) 위 매물 점수: 0~7점 (위가 가벼울수록 높음 = 상승 저항 없음)
      (2) 아래 지지 점수: 0~4점 (아래가 두꺼울수록 높음 = 하방 안전)
      (3) POC 위치 보너스: 0~2점 (POC가 아래 = 바닥 매집 신호)
    
    직관:
      - 유목민 관점: "위에 물린 사람 없으면 올라간다"
      - 아래 지지 = 손절 안 나옴 = 바닥 다짐 완료
      - POC 아래 = 대부분 싸게 산 사람들 = 매도 압력 낮음
    """
    # (1) 위 매물 비율 → 0~7점
    above_thresholds = [
        (5, 7.0), (15, 6.0), (25, 5.0), (35, 4.0),
        (50, 3.0), (65, 2.0), (80, 1.0), (100, 0.0),
    ]
    above_score = 0.0
    for threshold, pts in above_thresholds:
        if above_pct <= threshold:
            above_score = pts
            break
    
    # (2) 아래 지지 비율 → 0~4점
    below_thresholds = [
        (70, 4.0), (50, 3.0), (30, 2.0), (15, 1.0), (0, 0.0),
    ]
    below_score = 0.0
    for threshold, pts in below_thresholds:
        if below_pct >= threshold:
            below_score = pts
            break
    
    # (3) POC 위치 → 0~2점
    if poc_idx < current_idx:
        poc_bonus = 2.0   # POC가 현재가 아래 = 지지 강함
    elif poc_idx == current_idx:
        poc_bonus = 1.0   # POC = 현재가 = 중립
    else:
        poc_bonus = 0.0   # POC가 위 = 매물 저항
    
    total = min(13.0, above_score + below_score + poc_bonus)
    
    # 태그
    if total >= 10:
        tag = "상승여력"
    elif total >= 6:
        tag = "중립"
    else:
        tag = "저항벽"
    
    return total, tag, above_score, below_score, poc_bonus


def _empty_result(current_price: float, n_days: int) -> VolumeProfileResult:
    """데이터 부족 시 중립 결과"""
    return VolumeProfileResult(
        current_price=current_price,
        period_days=n_days,
        score=VP_SCORE_NEUTRAL,
        tag="데이터부족",
    )


# ============================================================
# Discord 표시용 헬퍼
# ============================================================

def format_vp_for_discord(result: VolumeProfileResult) -> str:
    """Discord embed용 한줄 요약"""
    if result.tag == "데이터부족":
        return "매물대: 데이터부족"
    
    return (
        f"매물대 {result.score:.0f}/13 [{result.tag}] "
        f"위:{result.above_pct:.0f}% 아래:{result.below_pct:.0f}% "
        f"POC:{result.poc_price:,.0f}"
    )


def format_vp_detail(result: VolumeProfileResult) -> str:
    """콘솔/로그용 상세 출력"""
    if result.tag == "데이터부족":
        return "  매물대: 데이터부족 (CSV 없음 또는 기간 부족)"
    
    lines = [
        f"  매물대 분석 ({result.period_days}일, {len(result.bands)}밴드)",
        f"    위 매물: {result.above_pct:.1f}% → {result.above_score:.0f}점",
        f"    현재 밴드: {result.current_pct:.1f}%",
        f"    아래 지지: {result.below_pct:.1f}% → {result.below_score:.0f}점",
        f"    POC: {result.poc_price:,.0f}원 ({result.poc_pct:.1f}%) → +{result.poc_bonus:.0f}점",
        f"    총점: {result.score:.1f}/13 [{result.tag}]",
    ]
    return "\n".join(lines)
