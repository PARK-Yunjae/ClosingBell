"""
종목 심층 분석 리포트 생성 (v9.0)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import os
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

from src.config.app_config import OHLCV_FULL_DIR, OHLCV_DIR
from src.config.backfill_config import get_backfill_config
from src.domain.models import DailyPrice, StockData
from src.domain.score_calculator import ScoreCalculatorV5
from src.services.backfill.data_loader import load_single_ohlcv
from src.services.account_service import get_holdings_watchlist
from src.services.dart_service import get_dart_service
from src.analyzers.volume_profile import analyze_volume_profile, VolumeProfileSummary
from src.analyzers.technical_analyzer import analyze_technical
from src.analyzers.broker_tracker import analyze_broker_flow
from src.analyzers.news_timeline import analyze_news_timeline
from src.analyzers.entry_exit_calculator import calculate_entry_exit


@dataclass
class StockReportResult:
    lines: List[str]
    summary: str


def _resolve_ohlcv_path(code: str) -> Optional[Path]:
    candidates: List[Path] = []
    bases: List[Path] = []

    for base in [OHLCV_FULL_DIR, OHLCV_DIR]:
        if base and base not in bases:
            bases.append(base)

    try:
        cfg = get_backfill_config()
        base = cfg.get_active_ohlcv_dir()
        if base and base not in bases:
            bases.append(base)
    except Exception:
        pass

    for base in bases:
        candidates.append(Path(base) / f"{code}.csv")
        candidates.append(Path(base) / f"A{code}.csv")

    for path in candidates:
        if path.exists():
            return path
    return None


def _load_ohlcv_df(code: str) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    path = _resolve_ohlcv_path(code)
    if path:
        df = load_single_ohlcv(path)
        if df is not None and not df.empty:
            return df, str(path)

    # FDR fallback (온라인)
    try:
        import FinanceDataReader as fdr
        end = datetime.now().date()
        start = end - pd.Timedelta(days=365 * 2)
        df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if df is not None and not df.empty:
            df = df.reset_index()
            df.columns = [c.lower() for c in df.columns]
            if "date" not in df.columns and "index" in df.columns:
                df = df.rename(columns={"index": "date"})
            return df, "FDR"
    except Exception:
        pass

    return None, None


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


def _generate_ai_summary(text: str) -> Optional[str]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        prompt = f"""
당신은 투자 리서치 요약가입니다.
아래 리포트를 일반인이 이해하기 쉬운 한국어로 요약하세요.
- 전문 용어는 괄호로 짧게 설명
- 과장/확정 표현 금지
- 길이는 12줄 이내

형식:
1) 한 줄 요약
2) 좋은 점 3개 (불릿)
3) 위험 3개 (불릿)
4) 관찰 포인트 3개 (불릿)
5) 한계 1개 (데이터/기간/모형)

리포트:
{text[:6000]}
"""
        resp = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=prompt,
            config={"max_output_tokens": 512, "temperature": 0.2},
        )
        return getattr(resp, "text", None)
    except Exception:
        return None


def _calc_trading_value(last_row: pd.Series) -> float:
    tv = float(last_row.get("trading_value", 0.0))
    if tv > 0:
        return tv
    return (float(last_row["close"]) * float(last_row["volume"])) / 100_000_000


def _get_holding_row(code: str) -> Optional[dict]:
    try:
        rows = get_holdings_watchlist()
        for row in rows:
            if row.get("stock_code") == code:
                return row
    except Exception:
        return None
    return None


def _format_ohlcv_source(data_path: Optional[str]) -> str:
    if not data_path:
        return "not found"
    if data_path.upper() == "FDR":
        return "FDR"
    try:
        p = Path(data_path)
        return f"local ({p.name})"
    except Exception:
        return str(data_path)


def _interpret_cci(value: Optional[float]) -> str:
    if value is None:
        return "-"
    if value >= 100:
        return "과열 경향"
    if value <= -100:
        return "과매도 경향"
    return "중립 구간"


def _interpret_rsi(value: Optional[float]) -> str:
    if value is None:
        return "-"
    if value >= 70:
        return "과열 경향"
    if value <= 30:
        return "과매도 경향"
    return "중립 구간"


def _summarize_change(change_pct: Optional[float]) -> str:
    if change_pct is None:
        return "변동 정보 없음"
    if change_pct >= 5:
        return "강한 상승"
    if change_pct >= 1:
        return "상승"
    if change_pct <= -5:
        return "강한 하락"
    if change_pct <= -1:
        return "하락"
    return "보합"


def _build_easy_summary(
    change_pct: Optional[float],
    last_close: Optional[float],
    vp_summary: Optional[VolumeProfileSummary],
    tech,
    broker,
    news_summary,
) -> List[str]:
    lines: List[str] = []
    if change_pct is not None:
        lines.append(f"- 오늘 흐름: {_summarize_change(change_pct)} ({change_pct:+.2f}%)")
    else:
        lines.append("- 오늘 흐름: 데이터 부족")

    if last_close is not None:
        lines.append(f"- 종가: {int(last_close):,}원")

    if vp_summary is not None:
        lines.append(
            f"- 매물대: {vp_summary.tag} (위 {vp_summary.above_pct:.1f}%, 아래 {vp_summary.below_pct:.1f}%)"
        )

    if tech and tech.cci is not None:
        lines.append(f"- CCI(14): {tech.cci:.0f} → {_interpret_cci(tech.cci)}")
    if tech and tech.rsi is not None:
        lines.append(f"- RSI(14): {tech.rsi:.0f} → {_interpret_rsi(tech.rsi)}")

    if broker and broker.status == "ok":
        lines.append(f"- 거래원 흐름: {broker.tag} (평균 이상점수 {broker.avg_anomaly:.1f})")
    else:
        lines.append("- 거래원 흐름: 데이터 부족")

    if news_summary:
        lines.append(
            f"- 최근 뉴스 {len(news_summary.news)}건, 공시 {len(news_summary.disclosures)}건"
        )

    return lines


def generate_stock_report(stock_code: str, full: bool = False) -> StockReportResult:
    code = str(stock_code).zfill(6)
    today = date.today()
    now = datetime.now()

    df, data_path = _load_ohlcv_df(code)

    lines: List[str] = []
    lines.append("# ClosingBell v9.0 Analysis Report")
    lines.append("")
    lines.append(f"- Code: {code}")
    lines.append(f"- Generated: {now.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"- OHLCV Source: {_format_ohlcv_source(data_path)}")
    lines.append("")

    # Holdings Snapshot (if available)
    holding = _get_holding_row(code)
    if holding:
        lines.append("## Holdings Snapshot")
        lines.append(f"- Status: {holding.get('status', '-')}")
        qty = holding.get("last_qty", 0) or 0
        price = holding.get("last_price", 0.0) or 0.0
        lines.append(f"- Qty: {int(qty):,} | Avg Price: {float(price):,.2f}")
        lines.append(f"- First Seen: {holding.get('first_seen', '-')}")
        lines.append(f"- Last Seen: {holding.get('last_seen', '-')}")
        lines.append("")

    # OHLCV Summary
    lines.append("## OHLCV Summary")
    last_close: Optional[float] = None
    change_pct: Optional[float] = None
    if df is None:
        lines.append("- OHLCV data not found.")
    else:
        df = df.sort_values("date").reset_index(drop=True)
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else None
        last_close = float(last["close"])
        change_pct = 0.0
        if prev is not None and float(prev["close"]) > 0:
            change_pct = (float(last["close"]) - float(prev["close"])) / float(prev["close"]) * 100.0

        period_start = df["date"].iloc[0].date()
        period_end = last["date"].date()
        tv = _calc_trading_value(last)
        lines.append(f"- Period: {period_start} to {period_end} ({len(df)} days)")
        lines.append(
            f"- Latest ({period_end}): "
            f"O {int(last['open']):,} / H {int(last['high']):,} / "
            f"L {int(last['low']):,} / C {int(last['close']):,}"
        )
        lines.append(f"- Change vs prev close: {change_pct:+.2f}%")
        lines.append(f"- Volume: {int(last['volume']):,} | Trading value (100M KRW): {tv:.2f}")

        tail = df.tail(20) if len(df) >= 20 else df
        high_20 = float(tail["high"].max())
        low_20 = float(tail["low"].min())
        lines.append(f"- 20d High/Low: {high_20:,.0f} / {low_20:,.0f}")

    # Volume Profile
    lines.append("")
    lines.append("## Volume Profile")
    vp_tag = "N/A"
    vp_summary = None
    if df is None or last_close is None:
        lines.append("- VP: N/A (no OHLCV data).")
    else:
        vp_summary = analyze_volume_profile(df, current_price=last_close, n_days=60)
        vp_tag = vp_summary.tag
        lines.append(f"- Score: {vp_summary.score:.1f}/13 | Tag: {vp_summary.tag}")
        lines.append(
            f"- Above/Below: {vp_summary.above_pct:.1f}% / {vp_summary.below_pct:.1f}% | "
            f"POC: {vp_summary.poc_price:,.0f} ({vp_summary.poc_pct:.1f}%)"
        )
        if vp_summary.support or vp_summary.resistance:
            support_str = f"{vp_summary.support:,.0f}" if vp_summary.support else "-"
            resist_str = f"{vp_summary.resistance:,.0f}" if vp_summary.resistance else "-"
            lines.append(f"- Support/Resistance: {support_str} / {resist_str}")
        if vp_summary.reason:
            lines.append(f"- Note: {vp_summary.reason}")

    # Technical Analysis
    lines.append("")
    lines.append("## Technical Analysis")
    tech = analyze_technical(df) if df is not None else analyze_technical(None)
    if tech.note:
        lines.append(f"- Technicals: {tech.note}")
    else:
        lines.append(f"- CCI(14): {tech.cci:.1f}" if tech.cci is not None else "- CCI(14): N/A")
        lines.append(f"- RSI(14): {tech.rsi:.1f}" if tech.rsi is not None else "- RSI(14): N/A")
        lines.append(
            f"- MACD: {tech.macd:.4f} | Signal: {tech.macd_signal:.4f} | Hist: {tech.macd_hist:.4f}"
            if tech.macd is not None and tech.macd_signal is not None and tech.macd_hist is not None
            else "- MACD: N/A"
        )
        lines.append(
            f"- MA: 5={tech.ma5:.2f}, 20={tech.ma20:.2f}, 60={tech.ma60:.2f}, 120={tech.ma120:.2f}"
            if tech.ma20 is not None
            else "- MA: N/A"
        )
        lines.append(
            f"- Bollinger(20): mid {tech.bb_mid:.2f}, upper {tech.bb_upper:.2f}, lower {tech.bb_lower:.2f}"
            if tech.bb_mid is not None
            else "- Bollinger: N/A"
        )

    # Broker Flow
    lines.append("")
    lines.append("## Broker Flow")
    broker = analyze_broker_flow(code, limit=5 if full else 1)
    if broker.status != "ok":
        lines.append(f"- Broker: {broker.note or 'N/A'}")
    else:
        lines.append(f"- Tag: {broker.tag} | Max anomaly: {broker.max_anomaly} | Avg: {broker.avg_anomaly:.1f}")
        if broker.note:
            lines.append(f"- Note: {broker.note}")
        if full and broker.recent_rows:
            lines.append("| Date | Anomaly | Score | Tag |")
            lines.append("| --- | --- | --- | --- |")
            for row in broker.recent_rows:
                lines.append(
                    f"| {row.get('screen_date', '')} | {row.get('anomaly_score', '')} | "
                    f"{float(row.get('broker_score', 0.0)):.1f} | {row.get('tag', '')} |"
                )

    # News & Disclosures
    lines.append("")
    lines.append("## News & Disclosures")
    news_summary = analyze_news_timeline(code, stock_name=code)
    if news_summary.note:
        lines.append(f"- Note: {news_summary.note}")
    if news_summary.news:
        lines.append("- News:")
        for item in news_summary.news[:5]:
            title = item.get("title", "")
            pub = item.get("pub_date", "")
            source = item.get("source", "")
            lines.append(f"  - {pub} {source} {title}".strip())
    else:
        lines.append("- News: N/A")
    if news_summary.disclosures:
        lines.append("- Disclosures:")
        for item in news_summary.disclosures[:5]:
            date_str = item.get("rcept_dt", "")
            title = item.get("report_nm", "")
            lines.append(f"  - {date_str} {title}".strip())
    else:
        lines.append("- Disclosures: N/A")

    # Easy Summary
    lines.append("")
    lines.append("## Easy Summary")
    easy_lines = _build_easy_summary(change_pct, last_close, vp_summary, tech, broker, news_summary)
    lines.extend(easy_lines if easy_lines else ["- 요약 데이터 부족"])

    # DART Company Profile (Full)
    lines.append("")
    lines.append("## DART Company Profile")
    try:
        dart = get_dart_service()
        profile_text = dart.format_full_profile_for_ai(code, stock_name=code)
        if profile_text:
            for line in profile_text.splitlines():
                lines.append(line)
        else:
            lines.append("- DART: N/A")
    except Exception:
        lines.append("- DART: N/A")

    # AI Summary
    lines.append("")
    lines.append("## AI Summary")
    ai_summary = _generate_ai_summary("\n".join(lines))
    if ai_summary:
        for line in ai_summary.splitlines():
            if line.strip():
                lines.append(line.rstrip())
    else:
        lines.append("- AI 요약: N/A (API 키 필요)")

    # Entry/Exit Plan
    lines.append("")
    lines.append("## Entry/Exit Plan")
    if vp_summary is None:
        vp_summary = VolumeProfileSummary(
            score=0.0,
            tag="데이터부족",
            above_pct=0.0,
            below_pct=0.0,
            poc_price=0.0,
            poc_pct=0.0,
            support=None,
            resistance=None,
            reason="데이터 부족",
        )
    plan = (
        calculate_entry_exit(df, last_close or 0.0, vp_summary, tech)
        if df is not None
        else calculate_entry_exit(None, 0.0, vp_summary, tech)
    )
    if plan.entry is None:
        lines.append(f"- Plan: {plan.note or 'N/A'}")
    else:
        lines.append(f"- Entry: {plan.entry:,.0f} | Target1: {plan.target1:,.0f} | Target2: {plan.target2:,.0f}")
        lines.append(f"- Stop-loss: {plan.stop_loss:,.0f} | Holding: {plan.holding_days}")
        if plan.note:
            lines.append(f"- Note: {plan.note}")

    # Composite Summary
    lines.append("")
    lines.append("## Summary")
    cb_score = None
    if df is not None:
        try:
            prices = _to_daily_prices(df)
            last = df.iloc[-1]
            tv = _calc_trading_value(last)
            stock = StockData(
                code=code,
                name=code,
                daily_prices=prices,
                current_price=int(last["close"]),
                trading_value=tv,
            )
            calc = ScoreCalculatorV5()
            score_list = calc.calculate_scores([stock])
            if score_list:
                cb_score = score_list[0].score_total
        except Exception:
            cb_score = None
    if cb_score is not None:
        lines.append(f"- ClosingBell Score: {cb_score:.1f} / 100")
    else:
        lines.append("- ClosingBell Score: N/A")
    lines.append(f"- VP Tag: {vp_tag}")
    if ai_summary:
        lines.append("- AI 요약: 보고서의 AI Summary 참고")
    else:
        lines.append("- AI 요약: N/A (AI 설정 필요)")

    summary_parts = []
    if tech.cci is not None:
        summary_parts.append(f"CCI {tech.cci:.0f}")
    if tech.rsi is not None:
        summary_parts.append(f"RSI {tech.rsi:.0f}")
    if vp_tag:
        summary_parts.append(f"VP {vp_tag}")
    summary = f"{code} | " + ", ".join(summary_parts) if summary_parts else f"{code} | report generated"

    return StockReportResult(lines=lines, summary=summary)
