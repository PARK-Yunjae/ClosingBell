"""눌림목(거감음봉) 스캐너 v9.1

유목민 거래량 단타법 기반:
1) 거래량 1000만주+ 폭발 감지 → 감시풀 등록
2) D+1~D+3 모니터링: 거감 80%↑ + 음봉 + MA 지지 → 시그널
3) 재료/섹터 필터: 주도섹터 유지, 뉴스 존재

스케줄:
  15:10 → run_pullback_scan()        눌림목 시그널 (실시간 API) + 디스코드
  16:05 → run_volume_spike_scan()    거래량 폭발 감지 (OHLCV CSV)
"""

import logging
import os
import csv
import json
import time
from pathlib import Path
from datetime import date, datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ============================================================
# 설정
# ============================================================

VOLUME_SPIKE_MIN = 10_000_000       # 최소 거래량 (1000만주)
VOLUME_SPIKE_MA_RATIO = 3.0         # 20일 평균 대비 배수
PULLBACK_WATCH_DAYS = 3             # 감시 기간 (D+1 ~ D+3)
PULLBACK_VOL_RATIO = 0.20           # 거래량 급감 기준 (폭발일 대비 20% 이하)
PULLBACK_MA_TOLERANCE = 0.02        # MA 지지 허용 오차 (±2%)
PULLBACK_MAX_DROP = 0.15            # 고점 대비 최대 낙폭 15%


# ============================================================
# 모델
# ============================================================

@dataclass
class VolumeSpike:
    """거래량 폭발 감지 결과"""
    stock_code: str
    stock_name: str
    spike_date: str           # YYYY-MM-DD
    spike_volume: int
    volume_ma20: int
    spike_ratio: float        # volume / ma20
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    change_pct: float         # 등락률
    sector: str = ""
    theme: str = ""
    is_leading_sector: bool = False


@dataclass
class PullbackSignal:
    """눌림목 시그널"""
    stock_code: str
    stock_name: str
    spike_date: str           # 폭발일
    signal_date: str          # 시그널 발생일
    days_after: int           # D+N
    # 가격
    close_price: float
    open_price: float
    spike_high: float
    drop_from_high_pct: float  # 고점 대비 낙폭 %
    # 거래량
    today_volume: int
    spike_volume: int
    vol_decrease_pct: float    # 거래량 감소율 (0.15 = 폭발일의 15%)
    # MA 지지
    ma5: float
    ma20: float
    ma_support: str            # "5일선" / "20일선" / "없음"
    ma_distance_pct: float     # MA와의 거리 %
    # 필터
    is_negative_candle: bool
    sector: str = ""
    is_leading_sector: bool = False
    has_recent_news: bool = False
    # 종합
    signal_strength: str = ""  # "강", "중", "약"
    reason: str = ""


# ============================================================
# OHLCV 로딩 (CSV 기반 - 16:05 폭발감지용)
# ============================================================

def _load_ohlcv(code: str) -> Optional[pd.DataFrame]:
    """종목 OHLCV 로드 (로컬 CSV)"""
    try:
        from src.config.app_config import OHLCV_DIR, OHLCV_FULL_DIR
    except ImportError:
        return None

    bases = []
    for d in [OHLCV_DIR, OHLCV_FULL_DIR]:
        if d and d not in bases:
            bases.append(d)
    try:
        from src.config.backfill_config import get_backfill_config
        cfg = get_backfill_config()
        bd = cfg.get_active_ohlcv_dir()
        if bd and bd not in bases:
            bases.append(bd)
    except Exception:
        pass

    for base in bases:
        for name in [f"{code}.csv", f"A{code}.csv"]:
            p = Path(base) / name
            if p.exists():
                try:
                    from src.services.backfill.data_loader import load_single_ohlcv
                    return load_single_ohlcv(p)
                except Exception:
                    pass
    return None


# ============================================================
# 실시간 OHLCV 로딩 (키움 API - 15:10 눌림목용)
# ============================================================

def _load_ohlcv_live(code: str, days: int = 30) -> Optional[pd.DataFrame]:
    """실시간 OHLCV 로드 (키움 API → FDR → CSV 순 폴백)

    15:10 시점에는 OHLCV CSV가 아직 갱신 안 됐으므로
    키움 API로 당일 포함 실시간 데이터를 가져옴.
    """
    # 1) 키움 API (실시간, 당일 포함)
    try:
        from src.adapters.kiwoom_rest_client import KiwoomRestClient
        client = KiwoomRestClient()
        prices = client.get_daily_prices(code, count=days)
        if prices and len(prices) >= 5:
            rows = []
            for p in prices:
                rows.append({
                    "date": pd.Timestamp(p.date),
                    "open": float(p.open),
                    "high": float(p.high),
                    "low": float(p.low),
                    "close": float(p.close),
                    "volume": int(p.volume),
                })
            df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
            logger.debug(f"[pullback] {code} 키움 API 로드: {len(df)}일")
            return df
    except Exception as e:
        logger.debug(f"[pullback] {code} 키움 API 실패: {e}")

    # 2) FDR (장 마감 후에만 당일 반영)
    try:
        import FinanceDataReader as fdr
        end = datetime.now().date()
        start = end - timedelta(days=days * 2)
        df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if df is not None and not df.empty:
            df = df.reset_index()
            df.columns = [c.lower() for c in df.columns]
            if "date" not in df.columns and "index" in df.columns:
                df = df.rename(columns={"index": "date"})
            df["date"] = pd.to_datetime(df["date"])
            logger.debug(f"[pullback] {code} FDR 로드: {len(df)}일")
            return df
    except Exception as e:
        logger.debug(f"[pullback] {code} FDR 실패: {e}")

    # 3) CSV 폴백
    return _load_ohlcv(code)


def _load_stock_names() -> Dict[str, str]:
    """종목 매핑 로드 (stock_mapping.csv → FDR 폴백)"""
    names = {}
    try:
        from src.config.app_config import MAPPING_FILE
        if MAPPING_FILE and MAPPING_FILE.exists():
            with open(MAPPING_FILE, "r", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    names[str(row.get("code", "")).zfill(6)] = row.get("name", "")
    except Exception:
        pass

    # FDR 폴백 (로컬 매핑이 부족할 때)
    if len(names) < 100:
        try:
            import FinanceDataReader as fdr
            for market in ["KOSPI", "KOSDAQ"]:
                listing = fdr.StockListing(market)
                if listing is not None and not listing.empty:
                    for _, row in listing.iterrows():
                        code = str(row.get("Code", "")).strip().zfill(6)
                        name = str(row.get("Name", "")).strip()
                        if code and name and code not in names:
                            names[code] = name
        except Exception:
            pass

    return names


def _get_all_codes() -> List[str]:
    """전체 종목코드 리스트 (OHLCV 파일 기반)"""
    codes = []
    try:
        from src.config.app_config import OHLCV_DIR, OHLCV_FULL_DIR
        dirs = []
        for d in [OHLCV_DIR, OHLCV_FULL_DIR]:
            if d and d.exists():
                dirs.append(d)
        try:
            from src.config.backfill_config import get_backfill_config
            cfg = get_backfill_config()
            bd = cfg.get_active_ohlcv_dir()
            if bd and bd.exists():
                dirs.append(bd)
        except Exception:
            pass

        seen = set()
        for d in dirs:
            for f in d.glob("*.csv"):
                code = f.stem.replace("A", "")
                if code.isdigit() and len(code) == 6 and code not in seen:
                    seen.add(code)
                    codes.append(code)
    except Exception as e:
        logger.error(f"[pullback] 종목코드 로딩 실패: {e}")
    return codes


# ============================================================
# 재료/섹터/뉴스 Enrichment (3단계 필터)
# ============================================================

def _enrich_sector(code: str) -> Tuple[str, bool]:
    """종목의 섹터 + 주도섹터 여부 조회

    Returns:
        (섹터명, 주도섹터여부)
    """
    sector = ""
    is_leading = False

    # 1) stock_mapping.csv에서 업종 조회
    try:
        from src.services.company_service import get_sector_from_mapping
        sector = get_sector_from_mapping(code) or ""
    except Exception as e:
        logger.debug(f"[pullback] 섹터 조회 실패 ({code}): {e}")

    # 2) 주도섹터 판별 (캐시된 결과 사용)
    if sector:
        try:
            from src.services.sector_service import SectorService
            svc = SectorService()
            leading = svc.get_leading_sectors()
            is_leading = sector in leading
        except Exception:
            pass

    return sector, is_leading


def _check_recent_news(stock_name: str, days: int = 3) -> Tuple[bool, str]:
    """최근 N일 뉴스 존재 여부 + 첫번째 헤드라인

    Returns:
        (뉴스존재여부, 대표헤드라인)
    """
    try:
        from src.services.news_service import search_naver_news
        query = f"{stock_name} 주식"
        news_list = search_naver_news(query, display=5, sort='date')

        if not news_list:
            return False, ""

        # 최근 N일 이내 뉴스 필터
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        recent = []
        for n in news_list:
            pub = n.get("pub_date", "")
            # pub_date가 RFC 822 형식일 수 있음
            news_date = n.get("news_date", "")
            if not news_date and pub:
                try:
                    from src.services.news_service import parse_pub_date
                    news_date = parse_pub_date(pub) or ""
                except Exception:
                    pass
            if news_date and news_date >= cutoff:
                recent.append(n)

        if recent:
            headline = recent[0].get("title", "")[:60]
            return True, headline
        # 날짜 파싱 실패 시 뉴스 존재 자체로 판단
        if news_list:
            return True, news_list[0].get("title", "")[:60]
        return False, ""
    except Exception as e:
        logger.debug(f"[pullback] 뉴스 조회 실패 ({stock_name}): {e}")
        return False, ""


def _get_company_summary(code: str) -> str:
    """기업 프로필 한줄 요약 (DART 캐시)

    Returns:
        "반도체장비 | 매출 1,234억 | 위험: 낮음" 형태
    """
    try:
        from src.infrastructure.repository import get_company_profile_repository
        repo = get_company_profile_repository()
        profile = repo.get_by_code(code)
        if not profile:
            return ""

        parts = []
        # 업종
        induty = profile.get("induty_code", "")
        if induty:
            parts.append(induty)
        # 매출
        revenue = profile.get("revenue")
        if revenue and revenue > 0:
            if revenue >= 10000:
                parts.append(f"매출 {revenue/10000:.1f}조")
            elif revenue >= 1:
                parts.append(f"매출 {revenue:.0f}억")
        # 위험도
        risk = profile.get("risk_level", "")
        if risk and risk != "낮음":
            parts.append(f"⚠️위험:{risk}")
        # 리스크 요약
        risk_summary = profile.get("risk_summary", "")
        if risk_summary:
            parts.append(risk_summary[:30])

        return " | ".join(parts)
    except Exception:
        return ""


def _enrich_spike(spike: VolumeSpike) -> VolumeSpike:
    """거래량 폭발 종목에 섹터 정보 보강"""
    sector, is_leading = _enrich_sector(spike.stock_code)
    spike.sector = sector
    spike.is_leading_sector = is_leading
    return spike


def _enrich_signal(signal: PullbackSignal) -> PullbackSignal:
    """눌림목 시그널에 섹터/뉴스/기업 정보 보강"""
    # 섹터
    sector, is_leading = _enrich_sector(signal.stock_code)
    signal.sector = sector
    signal.is_leading_sector = is_leading

    # 뉴스 (최근 3일)
    has_news, headline = _check_recent_news(signal.stock_name, days=3)
    signal.has_recent_news = has_news

    # reason에 섹터/뉴스 정보 추가
    extras = []
    if sector:
        label = f"{'🔥' if is_leading else '📂'}{sector}"
        extras.append(label)
    if has_news and headline:
        extras.append(f"📰{headline}")
    elif not has_news:
        extras.append("📰재료없음")

    if extras:
        signal.reason = signal.reason + " | " + " | ".join(extras)

    return signal


# ============================================================
# 1단계: 거래량 폭발 감지
# ============================================================

def scan_volume_spikes(target_date: Optional[date] = None) -> List[VolumeSpike]:
    """전체 종목에서 거래량 폭발 감지

    Args:
        target_date: 검사 날짜 (기본: 오늘)

    Returns:
        거래량 폭발 종목 리스트
    """
    if target_date is None:
        target_date = date.today()

    date_str = target_date.strftime("%Y-%m-%d")
    logger.info(f"[pullback] 거래량 폭발 스캔 시작: {date_str}")

    codes = _get_all_codes()
    if not codes:
        logger.warning("[pullback] OHLCV 파일 없음")
        return []

    names = _load_stock_names()
    spikes = []

    for code in codes:
        df = _load_ohlcv(code)
        if df is None or len(df) < 25:
            continue

        # 날짜 필터
        df["date_str"] = df["date"].dt.strftime("%Y-%m-%d")
        today_row = df[df["date_str"] == date_str]
        if today_row.empty:
            continue

        row = today_row.iloc[-1]
        vol = int(row["volume"])

        # 거래량 최소 기준
        if vol < VOLUME_SPIKE_MIN:
            continue

        # 20일 이동평균 계산
        idx = today_row.index[0]
        pos = df.index.get_loc(idx)
        if pos < 20:
            continue

        vol_ma20 = int(df.iloc[pos - 20:pos]["volume"].mean())
        if vol_ma20 <= 0:
            continue

        ratio = vol / vol_ma20
        if ratio < VOLUME_SPIKE_MA_RATIO:
            continue

        # 등락률
        prev_close = float(df.iloc[pos - 1]["close"]) if pos > 0 else float(row["open"])
        change_pct = ((float(row["close"]) - prev_close) / prev_close * 100) if prev_close > 0 else 0

        spike = VolumeSpike(
            stock_code=code,
            stock_name=names.get(code, code),
            spike_date=date_str,
            spike_volume=vol,
            volume_ma20=vol_ma20,
            spike_ratio=round(ratio, 1),
            open_price=float(row["open"]),
            high_price=float(row["high"]),
            low_price=float(row["low"]),
            close_price=float(row["close"]),
            change_pct=round(change_pct, 2),
        )
        spike = _enrich_spike(spike)
        spikes.append(spike)

    # 거래량 배수 높은 순 정렬
    spikes.sort(key=lambda s: s.spike_ratio, reverse=True)
    logger.info(f"[pullback] 거래량 폭발 감지: {len(spikes)}개 종목")

    # DB 저장
    _save_spikes(spikes)

    return spikes


def _save_spikes(spikes: List[VolumeSpike]):
    """거래량 폭발 DB 저장"""
    if not spikes:
        return
    try:
        from src.infrastructure.repository import get_pullback_repository
        repo = get_pullback_repository()
        for s in spikes:
            repo.save_spike(s)
        logger.info(f"[pullback] {len(spikes)}개 폭발 저장 완료")
    except Exception as e:
        logger.error(f"[pullback] 폭발 저장 실패: {e}")


# ============================================================
# 2단계: 눌림목 시그널 감지
# ============================================================

def scan_pullback_signals(target_date: Optional[date] = None) -> List[PullbackSignal]:
    """감시풀 종목에서 눌림목 시그널 감지

    Args:
        target_date: 검사 날짜 (기본: 오늘)

    Returns:
        눌림목 시그널 리스트
    """
    if target_date is None:
        target_date = date.today()

    date_str = target_date.strftime("%Y-%m-%d")
    logger.info(f"[pullback] 눌림목 시그널 스캔: {date_str}")

    # 감시풀 조회 (최근 PULLBACK_WATCH_DAYS일 이내 폭발 종목)
    try:
        from src.infrastructure.repository import get_pullback_repository
        repo = get_pullback_repository()
        watch_list = repo.get_active_spikes(target_date, PULLBACK_WATCH_DAYS)
    except Exception as e:
        logger.error(f"[pullback] 감시풀 조회 실패: {e}")
        return []

    if not watch_list:
        logger.info("[pullback] 감시풀 비어있음")
        return []

    logger.info(f"[pullback] 감시풀: {len(watch_list)}개 종목")

    signals = []
    names = _load_stock_names()

    for spike_row in watch_list:
        spike = dict(spike_row) if not isinstance(spike_row, dict) else spike_row
        code = spike["stock_code"]
        spike_date_str = spike["spike_date"]
        spike_vol = int(spike["spike_volume"])
        spike_high = float(spike["high_price"])

        df = _load_ohlcv_live(code, days=30)  # 실시간 API (15:10)
        if df is None or len(df) < 20:
            continue

        # 오늘 데이터
        df["date_str"] = df["date"].dt.strftime("%Y-%m-%d")
        today_data = df[df["date_str"] == date_str]
        if today_data.empty:
            continue

        row = today_data.iloc[-1]
        idx = today_data.index[0]
        pos = df.index.get_loc(idx)

        close = float(row["close"])
        open_p = float(row["open"])
        vol = int(row["volume"])

        # D+N 계산
        spike_dt = datetime.strptime(spike_date_str, "%Y-%m-%d").date()
        days_after = (target_date - spike_dt).days
        if days_after < 1 or days_after > PULLBACK_WATCH_DAYS:
            continue

        # ── 조건 체크 ──

        # 1. 거래량 급감 (폭발일 대비 20% 이하)
        vol_ratio = vol / spike_vol if spike_vol > 0 else 1.0
        if vol_ratio > PULLBACK_VOL_RATIO:
            continue

        # 2. 음봉
        is_negative = close < open_p
        if not is_negative:
            continue

        # 3. MA 지지 (5일선 or 20일선 ±2%)
        ma5 = float(df.iloc[max(0, pos - 4):pos + 1]["close"].mean()) if pos >= 4 else 0
        ma20 = float(df.iloc[max(0, pos - 19):pos + 1]["close"].mean()) if pos >= 19 else 0

        ma_support = "없음"
        ma_dist = 999.0

        if ma5 > 0:
            dist5 = abs(close - ma5) / ma5
            if dist5 <= PULLBACK_MA_TOLERANCE:
                ma_support = "5일선"
                ma_dist = dist5
        if ma20 > 0:
            dist20 = abs(close - ma20) / ma20
            if dist20 <= PULLBACK_MA_TOLERANCE:
                if ma_support == "없음" or dist20 < ma_dist:
                    ma_support = "20일선"
                    ma_dist = dist20

        if ma_support == "없음":
            continue

        # 4. 고점 대비 낙폭 제한
        drop_pct = (spike_high - close) / spike_high if spike_high > 0 else 0
        if drop_pct > PULLBACK_MAX_DROP:
            continue

        # ── 시그널 강도 판정 ──
        strength = "중"
        reasons = []
        if vol_ratio <= 0.10:
            reasons.append("거래량 90%↑ 급감")
            strength = "강"
        elif vol_ratio <= 0.15:
            reasons.append(f"거래량 {(1 - vol_ratio) * 100:.0f}% 급감")
            strength = "강"
        else:
            reasons.append(f"거래량 {(1 - vol_ratio) * 100:.0f}% 감소")

        reasons.append(f"{ma_support} 지지 ({ma_dist * 100:.1f}%)")
        if drop_pct <= 0.05:
            reasons.append("고점 근접")
            if strength != "강":
                strength = "강"

        signal = PullbackSignal(
            stock_code=code,
            stock_name=names.get(code, spike.get("stock_name", code)),
            spike_date=spike_date_str,
            signal_date=date_str,
            days_after=days_after,
            close_price=close,
            open_price=open_p,
            spike_high=spike_high,
            drop_from_high_pct=round(drop_pct * 100, 1),
            today_volume=vol,
            spike_volume=spike_vol,
            vol_decrease_pct=round(vol_ratio, 3),
            ma5=round(ma5, 0),
            ma20=round(ma20, 0),
            ma_support=ma_support,
            ma_distance_pct=round(ma_dist * 100, 2),
            is_negative_candle=True,
            signal_strength=strength,
            reason=" | ".join(reasons),
        )
        signal = _enrich_signal(signal)
        signals.append(signal)

    # 강도순 정렬
    order = {"강": 0, "중": 1, "약": 2}
    signals.sort(key=lambda s: (order.get(s.signal_strength, 9), s.vol_decrease_pct))

    logger.info(f"[pullback] 눌림목 시그널: {len(signals)}개")

    # DB 저장
    _save_signals(signals)

    # 디스코드 알림
    if signals:
        _notify_discord(signals)

    return signals


def _save_signals(signals: List[PullbackSignal]):
    """눌림목 시그널 DB 저장"""
    if not signals:
        return
    try:
        from src.infrastructure.repository import get_pullback_repository
        repo = get_pullback_repository()
        for s in signals:
            repo.save_signal(s)
        logger.info(f"[pullback] {len(signals)}개 시그널 저장 완료")
    except Exception as e:
        logger.error(f"[pullback] 시그널 저장 실패: {e}")


# ============================================================
# 디스코드 알림
# ============================================================

def _notify_discord(signals: List[PullbackSignal]):
    """눌림목 시그널 디스코드 알림 (섹터/뉴스 포함)"""
    try:
        from src.adapters.discord_notifier import DiscordNotifier
        notifier = DiscordNotifier()

        # 시그널 강도별 카운트
        strong = sum(1 for s in signals if s.signal_strength == "강")
        medium = sum(1 for s in signals if s.signal_strength == "중")
        desc_parts = ["거래량 폭발 후 거감음봉 + MA 지지 종목"]
        if strong:
            desc_parts.append(f"🔴강 {strong}개")
        if medium:
            desc_parts.append(f"🟠중 {medium}개")

        embed = {
            "title": f"📉 눌림목 시그널 {len(signals)}개 감지",
            "color": 0xFF6B35,
            "description": " | ".join(desc_parts),
            "fields": [],
            "footer": {"text": f"ClosingBell 눌림목 스캐너 | {date.today().strftime('%Y-%m-%d')}"},
        }

        for sig in signals[:10]:
            strength_emoji = {"강": "🔴", "중": "🟠", "약": "🟡"}.get(sig.signal_strength, "⚪")
            vol_pct = f"{sig.vol_decrease_pct * 100:.0f}%"

            value_lines = [
                f"종가 {sig.close_price:,.0f}원 | 고점대비 -{sig.drop_from_high_pct:.1f}%",
                f"거래량 폭발일의 {vol_pct} | {sig.ma_support} 지지",
                f"D+{sig.days_after} | 폭발일: {sig.spike_date}",
            ]

            # 섹터/재료 정보
            info_parts = []
            if sig.sector:
                sector_icon = "🔥" if sig.is_leading_sector else "📂"
                info_parts.append(f"{sector_icon}{sig.sector}")
            if sig.has_recent_news:
                info_parts.append("📰재료살아있음")
            else:
                info_parts.append("📰재료없음")

            # 기업 프로필
            company_info = _get_company_summary(sig.stock_code)
            if company_info:
                info_parts.append(company_info)

            if info_parts:
                value_lines.append(" | ".join(info_parts))

            embed["fields"].append({
                "name": f"{strength_emoji} {sig.stock_name} ({sig.stock_code})",
                "value": "\n".join(value_lines),
                "inline": False,
            })

        notifier.send_embed(embed)
        logger.info(f"[pullback] 디스코드 알림 발송: {len(signals)}개")
    except Exception as e:
        logger.warning(f"[pullback] 디스코드 알림 실패: {e}")


# ============================================================
# 스케줄러 엔트리포인트
# ============================================================

def run_volume_spike_scan():
    """스케줄러용: 거래량 폭발 스캔"""
    return scan_volume_spikes()


def run_pullback_scan():
    """스케줄러용: 눌림목 시그널 스캔"""
    return scan_pullback_signals()