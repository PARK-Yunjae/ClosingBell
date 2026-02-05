"""
기술적 분석기 (v9.0)

CCI/RSI + MACD + 볼린저밴드 + MA 배열을 요약합니다.
"""

from dataclasses import dataclass
from typing import Optional, List

import pandas as pd

from src.domain.models import DailyPrice
from src.domain.indicators import calculate_cci, calculate_rsi


@dataclass
class TechnicalSummary:
    last_close: float
    change_pct: float
    cci: Optional[float]
    rsi: Optional[float]
    macd: Optional[float]
    macd_signal: Optional[float]
    macd_hist: Optional[float]
    ma5: Optional[float]
    ma20: Optional[float]
    ma60: Optional[float]
    ma120: Optional[float]
    bb_mid: Optional[float]
    bb_upper: Optional[float]
    bb_lower: Optional[float]
    note: str = ""


def _to_daily_prices(df: pd.DataFrame) -> List[DailyPrice]:
    prices: List[DailyPrice] = []
    for _, row in df.iterrows():
        prices.append(
            DailyPrice(
                date=row["date"].date(),
                open=int(row["open"]),
                high=int(row["high"]),
                low=int(row["low"]),
                close=int(row["close"]),
                volume=int(row["volume"]),
                trading_value=float(row.get("trading_value", 0.0)),
            )
        )
    return prices


def analyze_technical(df: pd.DataFrame) -> TechnicalSummary:
    if df is None or df.empty or len(df) < 20:
        return TechnicalSummary(
            last_close=0.0,
            change_pct=0.0,
            cci=None,
            rsi=None,
            macd=None,
            macd_signal=None,
            macd_hist=None,
            ma5=None,
            ma20=None,
            ma60=None,
            ma120=None,
            bb_mid=None,
            bb_upper=None,
            bb_lower=None,
            note="데이터 부족",
        )

    df = df.sort_values("date").reset_index(drop=True)
    close = df["close"].astype(float)
    last_close = float(close.iloc[-1])
    prev_close = float(close.iloc[-2]) if len(close) > 1 else 0.0
    change_pct = ((last_close - prev_close) / prev_close * 100.0) if prev_close > 0 else 0.0

    prices = _to_daily_prices(df)
    cci_values = calculate_cci(prices, period=14)
    rsi_values = calculate_rsi(prices, period=14)
    cci = cci_values[-1] if cci_values else None
    rsi = rsi_values[-1] if rsi_values else None

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - signal_line

    ma5 = close.rolling(window=5).mean()
    ma20 = close.rolling(window=20).mean()
    ma60 = close.rolling(window=60).mean()
    ma120 = close.rolling(window=120).mean()

    bb_mid = ma20
    bb_std = close.rolling(window=20).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std

    return TechnicalSummary(
        last_close=last_close,
        change_pct=change_pct,
        cci=round(cci, 2) if cci is not None else None,
        rsi=round(rsi, 2) if rsi is not None else None,
        macd=round(macd_line.iloc[-1], 4) if len(macd_line) > 0 else None,
        macd_signal=round(signal_line.iloc[-1], 4) if len(signal_line) > 0 else None,
        macd_hist=round(macd_hist.iloc[-1], 4) if len(macd_hist) > 0 else None,
        ma5=round(ma5.iloc[-1], 2) if len(ma5.dropna()) > 0 else None,
        ma20=round(ma20.iloc[-1], 2) if len(ma20.dropna()) > 0 else None,
        ma60=round(ma60.iloc[-1], 2) if len(ma60.dropna()) > 0 else None,
        ma120=round(ma120.iloc[-1], 2) if len(ma120.dropna()) > 0 else None,
        bb_mid=round(bb_mid.iloc[-1], 2) if len(bb_mid.dropna()) > 0 else None,
        bb_upper=round(bb_upper.iloc[-1], 2) if len(bb_upper.dropna()) > 0 else None,
        bb_lower=round(bb_lower.iloc[-1], 2) if len(bb_lower.dropna()) > 0 else None,
    )

