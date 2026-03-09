"""
ClosingBell v3 — 스크리닝 + 8지표 점수 계산
=============================================
키움 REST API 기반 / 유니버스 전체 분석 / 매물대+거래원+AI 통합
"""
import logging
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from config import (
    CCI_PERIOD, RSI_PERIOD,
    CCI_OPTIMAL, CCI_ZERO_LOW, CCI_ZERO_HIGH,
    MA20_GAP_OPTIMAL, MA20_GAP_ZERO,
    CHANGE_OPTIMAL, CHANGE_ZERO,
    RSI_OPTIMAL, RSI_ZERO_LOW, RSI_ZERO_HIGH,
    SCORE_CCI, SCORE_MA20_GAP, SCORE_CHANGE,
    SCORE_CCI_SLOPE, SCORE_MA20_SLOPE, SCORE_RSI,
    SCORE_VOLUME_PROFILE, SCORE_BROKER_FLOW,
    SCORE_VOLUME_BURST, VOL_BURST_OPTIMAL, VOL_BURST_ZERO_HIGH,
    OVERHEAT_PENALTY, OVERHEAT_CCI_THRESH, OVERHEAT_RSI_THRESH, OVERHEAT_GAP_THRESH,
    TOP_N, TOP_N_CONSERVATIVE,
    MIN_PRICE, MAX_PRICE,
    MIN_CHANGE_RATE, MAX_CHANGE_RATE,
    NASDAQ_DROP_THRESHOLD, NASDAQ_PENALTY,
    OHLCV_DIR, GLOBAL_CSV, MAPPING_CSV, LOG_DIR,
    MIN_TRADING_VALUE,
    EXCLUDE_NAMES, ETF_KEYWORDS, EXCLUDE_PREF_STOCK, EXCLUDE_ETF,
    API_DELAY,
)
from kiwoom_api import KiwoomAPI

logger = logging.getLogger("closingbell")


class Screener:
    """종가매매 스크리닝 엔진 v3"""

    def __init__(self, api: KiwoomAPI):
        self.api = api
        self.stock_map = self._load_stock_map()
        # 종목별 OHLCV DataFrame 캐시 (enricher에서도 사용)
        self._ohlcv_cache: dict[str, pd.DataFrame] = {}

    def _load_stock_map(self) -> dict:
        try:
            df = pd.read_csv(MAPPING_CSV, dtype={"code": str}, encoding="utf-8-sig")
            df["code"] = df["code"].str.zfill(6)
            return df.set_index("code").to_dict("index")
        except Exception as e:
            logger.warning("stock_mapping 로드 실패: %s", e)
            return {}

    # ──────────────────────────────────────────────
    # 메인 스크리닝
    # ──────────────────────────────────────────────
    def run(self, enricher=None) -> dict:
        """
        전체 스크리닝 + 유니버스 전체 enrich + TOP3 선정
        enricher: Enricher 인스턴스 (매물대+거래원+DART+AI)
        """
        today = datetime.now().strftime("%Y-%m-%d")
        market = self.get_market_status()

        # 나스닥 경고 (스킵하지 않고 진행, 웹훅에서 경고 표시)
        nasdaq_chg = market.get("nasdaq_change", 0)
        market["nasdaq_warning"] = nasdaq_chg <= NASDAQ_DROP_THRESHOLD

        # ── 1) 유니버스 확보 (ka10030 + ka10032 합집합) ──
        universe = self._get_universe()
        logger.info("유니버스 (필터 전): %d종목", len(universe))

        # 종목유형 필터
        universe = [s for s in universe if not self._is_excluded(s)]
        # 등락률 필터
        universe = [s for s in universe
                    if MIN_CHANGE_RATE <= s.get("change_rate", 0) <= MAX_CHANGE_RATE]
        # 가격 필터
        universe = [s for s in universe
                    if s.get("price", 0) > 0
                    and MIN_PRICE <= s["price"] <= MAX_PRICE]
        # ETF 키워드 필터
        universe = [s for s in universe
                    if not any(kw in s.get("name", "") for kw in ETF_KEYWORDS)]

        logger.info("유니버스 (필터 후): %d종목", len(universe))

        if not universe:
            return {
                "date": today, "timestamp": datetime.now().isoformat(timespec="seconds"),
                "market": market, "skipped": True,
                "reason": "유니버스 0건", "universe_count": 0,
                "top": [], "all_scored": [],
            }

        # ── 2) 기본 지표 계산 (CCI, RSI, MA20, 기울기, 매물대) ──
        scored = []
        for stock in universe:
            try:
                self._calc_indicators(stock)
                stock["score"] = self._calc_score(stock)
                scored.append(stock)
            except Exception as e:
                logger.debug("지표 계산 실패 [%s]: %s", stock.get("code"), e)

        logger.info("점수 계산 완료: %d종목", len(scored))

        # ── 3) 유니버스 전체 enricher 실행 ──
        if enricher:
            logger.info("유니버스 전체 enrich 시작 (%d종목)...", len(scored))
            scored = enricher.enrich_all(scored, self.api)
            # enrich 결과로 점수 재계산 (매물대+거래원 점수 반영)
            for s in scored:
                s["score"] = self._calc_score(s)
            logger.info("enrich 완료, 점수 재계산 완료")

        # ── 4) 나스닥 급락 감점 (전종목 -5점) ──
        if market.get("nasdaq_warning"):
            logger.info("나스닥 급락 → 전종목 %.1f점 감점", NASDAQ_PENALTY)
            for s in scored:
                s["score"] = round(max(0, s["score"] - NASDAQ_PENALTY), 1)

        # ── 5) 과열 복합 감점 (CCI>200 & RSI>80 & MA20이격>15% 동시 충족) ──
        overheat_count = 0
        for s in scored:
            cci_hot = s.get("cci", 0) > OVERHEAT_CCI_THRESH
            rsi_hot = s.get("rsi", 0) > OVERHEAT_RSI_THRESH
            gap_hot = s.get("ma20_gap", 0) > OVERHEAT_GAP_THRESH
            if cci_hot and rsi_hot and gap_hot:
                s["score"] = round(max(0, s["score"] - OVERHEAT_PENALTY), 1)
                s["overheat"] = True
                overheat_count += 1
            else:
                s["overheat"] = False
        if overheat_count > 0:
            logger.info("과열 감점: %d종목 (CCI>%d & RSI>%d & 이격>%.0f%%)",
                        overheat_count, OVERHEAT_CCI_THRESH,
                        OVERHEAT_RSI_THRESH, OVERHEAT_GAP_THRESH)

        # 정렬
        scored.sort(key=lambda x: x["score"], reverse=True)

        # TOP_N 결정 (시장 상황별 차등)
        top_n = TOP_N
        kospi_ma20 = market.get("kospi_ma20")
        if market.get("nasdaq_warning"):
            top_n = max(1, TOP_N_CONSERVATIVE - 1)  # 나스닥 급락: 1개
            logger.info("나스닥 급락 → 보수 모드 (TOP%d)", top_n)
        elif kospi_ma20 and kospi_ma20 > 0:
            kospi_gap = (market.get("kospi", 0) / kospi_ma20 - 1) * 100
            market["kospi_ma20_gap"] = round(kospi_gap, 1)
            if kospi_gap < -10:
                top_n = 1        # 폭락장
                logger.info("코스피 MA20 이격 %.1f%% (폭락) → TOP%d", kospi_gap, top_n)
            elif kospi_gap < -3:
                top_n = TOP_N_CONSERVATIVE  # 약세장
                logger.info("코스피 MA20 이격 %.1f%% (약세) → TOP%d", kospi_gap, top_n)
            elif kospi_gap < 0:
                top_n = TOP_N    # MA20 근접: 반등 가능
                logger.info("코스피 MA20 이격 %.1f%% (반등기대) → TOP%d", kospi_gap, top_n)
            # kospi_gap >= 0: 기본 TOP_N 유지

        top = scored[:top_n]

        # 섹터 분석
        sector_stats = self._analyze_sectors(scored)

        # 주도테마 조회
        theme_stats = self._get_themes()

        # 전일 추천 수익률
        prev_returns = self._calc_prev_returns()

        return {
            "date": today,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "market": market,
            "universe_count": len(scored),
            "top": [self._stock_summary(s, i + 1) for i, s in enumerate(top)],
            "all_scored": [self._stock_summary(s, i + 1) for i, s in enumerate(scored)],
            "sector_summary": sector_stats,
            "theme_summary": theme_stats,
            "prev_returns": prev_returns,
        }

    # ──────────────────────────────────────────────
    # 유니버스 확보 (ka10030 + ka10032 합집합)
    # ──────────────────────────────────────────────
    def _get_universe(self) -> list[dict]:
        """거래량상위 + 거래대금상위 합집합"""
        seen = {}

        # ka10030: 거래량상위
        try:
            vol_rank = self.api.get_volume_rank(min_trading_value=MIN_TRADING_VALUE)
            for s in vol_rank:
                code = s["code"]
                if code not in seen:
                    seen[code] = s
        except Exception as e:
            logger.warning("ka10030 실패: %s", e)

        vol_count = len(seen)

        # ka10032: 거래대금상위
        try:
            val_rank = self.api.get_trading_value_rank()
            for s in val_rank:
                code = s["code"]
                if code not in seen:
                    seen[code] = s
        except Exception as e:
            logger.warning("ka10032 실패: %s", e)

        result = list(seen.values())

        # stock_map에서 이름/섹터 보완
        for s in result:
            info = self.stock_map.get(s["code"], {})
            if not s.get("name"):
                s["name"] = info.get("name", s["code"])
            s["sector"] = info.get("sector", "")

        logger.info("유니버스 합집합: %d종목 (거래량 %d + 거래대금 %d 추가)",
                     len(result), vol_count, len(result) - vol_count)
        return result

    # ──────────────────────────────────────────────
    # 지표 계산 (CCI, RSI, MA20, 기울기, 매물대)
    # ──────────────────────────────────────────────
    def _calc_indicators(self, stock: dict):
        """종목에 CCI, RSI, MA20, 이격도, 기울기, 매물대 추가"""
        code = stock["code"]

        df = self._load_ohlcv(code)
        if df is None or len(df) < 20:
            df = self._fetch_ohlcv_api(code)
        if df is None or len(df) < 20:
            raise ValueError(f"{code}: OHLCV 부족")

        # 당일 임시 캔들 주입
        today = pd.Timestamp(datetime.now().date())
        if df["date"].max() < today:
            try:
                cur = self.api.get_current_price(code)
                if cur["price"] > 0:
                    today_candle = pd.DataFrame([{
                        "date": today,
                        "open": cur["open"] or cur["price"],
                        "high": cur["high"] or cur["price"],
                        "low": cur["low"] or cur["price"],
                        "close": cur["price"],
                        "volume": cur["volume"],
                    }])
                    df = pd.concat([df, today_candle], ignore_index=True)
            except Exception:
                pass

        df = df.tail(60).copy()
        self._ohlcv_cache[code] = df  # enricher용 캐시

        # MA20
        df["ma20"] = df["close"].rolling(20).mean()

        # CCI(14)
        tp = (df["high"] + df["low"] + df["close"]) / 3
        sma_tp = tp.rolling(CCI_PERIOD).mean()
        mad = tp.rolling(CCI_PERIOD).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
        df["cci"] = (tp - sma_tp) / (0.015 * mad)

        # RSI(14)
        delta = df["close"].diff()
        gain = delta.clip(lower=0).rolling(RSI_PERIOD).mean()
        loss = (-delta.clip(upper=0)).rolling(RSI_PERIOD).mean()
        rs = gain / loss.replace(0, np.nan)
        df["rsi"] = 100 - (100 / (1 + rs))

        latest = df.iloc[-1]
        prev_4 = df.tail(4)

        stock["cci"] = round(float(latest["cci"]), 1) if pd.notna(latest["cci"]) else 0
        stock["rsi"] = round(float(latest["rsi"]), 1) if pd.notna(latest["rsi"]) else 50
        stock["ma20"] = round(float(latest["ma20"]), 0) if pd.notna(latest["ma20"]) else 0
        stock["ma20_gap"] = round(
            (float(latest["close"]) / float(latest["ma20"]) - 1) * 100, 1
        ) if latest["ma20"] > 0 else 0

        # CCI/MA20 기울기
        stock["cci_slope"] = _count_rising(prev_4["cci"].dropna().tolist())
        stock["ma20_slope"] = _count_rising(prev_4["ma20"].dropna().tolist())

        # MA5 (눌림목 감지용)
        df["ma5"] = df["close"].rolling(5).mean()
        stock["ma5"] = round(float(latest["close"]), 0)
        if pd.notna(df["ma5"].iloc[-1]) and df["ma5"].iloc[-1] > 0:
            stock["ma5"] = round(float(df["ma5"].iloc[-1]), 0)
            stock["ma5_gap"] = round(
                (float(latest["close"]) / float(df["ma5"].iloc[-1]) - 1) * 100, 1
            )
        else:
            stock["ma5_gap"] = 0

        # 거래량 폭발 (당일 거래량 / 20일 평균)
        df["vol_ma20"] = df["volume"].rolling(20).mean()
        if pd.notna(df["vol_ma20"].iloc[-1]) and df["vol_ma20"].iloc[-1] > 0:
            stock["vol_ratio"] = round(
                float(latest["volume"]) / float(df["vol_ma20"].iloc[-1]), 1
            )
        else:
            stock["vol_ratio"] = 1.0

        # 매물대 자체 계산 (OHLCV 기반 가격대별 거래량)
        vp = self._calc_volume_profile(df, float(latest["close"]))
        stock["vp_above_pct"] = vp["above_pct"]
        stock["vp_below_pct"] = vp["below_pct"]
        stock["vp_tag"] = vp["tag"]

    def _calc_volume_profile(self, df: pd.DataFrame, current_price: float,
                              lookback: int = 50, bands: int = 10) -> dict:
        """
        OHLCV 기반 매물대 계산
        가격대를 bands개로 나누고, 각 구간의 거래량 집계
        현재가 위/아래 매물 비율 계산
        """
        recent = df.tail(lookback)
        if len(recent) < 10 or current_price <= 0:
            return {"above_pct": 50.0, "below_pct": 50.0, "tag": "데이터부족"}

        price_min = recent["low"].min()
        price_max = recent["high"].max()
        if price_max <= price_min:
            return {"above_pct": 50.0, "below_pct": 50.0, "tag": "횡보"}

        band_size = (price_max - price_min) / bands
        band_volumes = [0.0] * bands

        for _, row in recent.iterrows():
            # 각 캔들의 거래량을 고가~저가 전체 범위에 분배 (꼬리 포함)
            candle_low = row["low"]
            candle_high = row["high"]
            vol = row["volume"]

            for b in range(bands):
                band_low = price_min + b * band_size
                band_high = band_low + band_size
                # 캔들이 이 밴드와 겹치는 비율
                overlap = max(0, min(candle_high, band_high) - max(candle_low, band_low))
                candle_range = candle_high - candle_low
                if candle_range > 0 and overlap > 0:
                    ratio = overlap / candle_range
                    band_volumes[b] += vol * ratio

        total = sum(band_volumes)
        if total == 0:
            return {"above_pct": 50.0, "below_pct": 50.0, "tag": "거래없음"}

        # 현재가 기준 위/아래 매물 비율
        above_vol = 0.0
        below_vol = 0.0
        for b in range(bands):
            band_mid = price_min + (b + 0.5) * band_size
            if band_mid > current_price:
                above_vol += band_volumes[b]
            else:
                below_vol += band_volumes[b]

        above_pct = round(above_vol / total * 100, 1)
        below_pct = round(below_vol / total * 100, 1)

        # 태그 결정
        if above_pct <= 30:
            tag = "위 매물 적음"   # 돌파 여유
        elif above_pct >= 60:
            tag = "위 저항 강함"   # 돌파 어려움
        else:
            tag = "매물대 중립"

        return {"above_pct": above_pct, "below_pct": below_pct, "tag": tag}

    # ──────────────────────────────────────────────
    # 점수 계산 (100점, 9지표 종형분포)
    # ──────────────────────────────────────────────
    def _calc_score(self, stock: dict) -> float:
        """9개 지표 종형분포 점수"""
        score = 0.0

        # 1. CCI (25점)
        score += bell_score(stock.get("cci", 0),
                            CCI_OPTIMAL[0], CCI_OPTIMAL[1],
                            CCI_ZERO_LOW, CCI_ZERO_HIGH, SCORE_CCI)

        # 2. MA20 이격도 (20점)
        score += bell_score(stock.get("ma20_gap", 0),
                            MA20_GAP_OPTIMAL[0], MA20_GAP_OPTIMAL[1],
                            0, MA20_GAP_ZERO, SCORE_MA20_GAP)

        # 3. 등락률 (15점)
        score += bell_score(stock.get("change_rate", 0),
                            CHANGE_OPTIMAL[0], CHANGE_OPTIMAL[1],
                            0, CHANGE_ZERO, SCORE_CHANGE)

        # 4. CCI 기울기 (10점)
        score += min(SCORE_CCI_SLOPE, max(0, stock.get("cci_slope", 0)) * 3.33)

        # 5. MA20 기울기 (10점)
        score += min(SCORE_MA20_SLOPE, max(0, stock.get("ma20_slope", 0)) * 3.33)

        # 6. RSI (5점)
        score += bell_score(stock.get("rsi", 50),
                            RSI_OPTIMAL[0], RSI_OPTIMAL[1],
                            RSI_ZERO_LOW, RSI_ZERO_HIGH, SCORE_RSI)

        # 7. 매물대 저항도 (10점): 위 매물이 적을수록 고점
        above = stock.get("vp_above_pct", 50)
        if above <= 20:
            score += SCORE_VOLUME_PROFILE
        elif above <= 35:
            score += SCORE_VOLUME_PROFILE * 0.7
        elif above <= 50:
            score += SCORE_VOLUME_PROFILE * 0.4
        elif above <= 65:
            score += SCORE_VOLUME_PROFILE * 0.2
        # 65% 이상: 0점

        # 8. 거래원 이상도 (5점): enricher에서 설정
        broker_score = stock.get("broker_score", 0)
        score += min(SCORE_BROKER_FLOW, broker_score)

        # 9. 거래량 폭발 (5점): 당일거래량/20일평균 비율
        vol_ratio = stock.get("vol_ratio", 1.0)
        if vol_ratio >= VOL_BURST_OPTIMAL[0]:
            score += bell_score(vol_ratio,
                                VOL_BURST_OPTIMAL[0], VOL_BURST_OPTIMAL[1],
                                1.0, VOL_BURST_ZERO_HIGH, SCORE_VOLUME_BURST)

        return round(score, 1)

    # ──────────────────────────────────────────────
    # 시장 현황 + 테마 + 전일수익률
    # ──────────────────────────────────────────────
    def get_market_status(self) -> dict:
        result = {}
        try:
            kospi = self.api.get_index_price("001")
            result["kospi"] = kospi["price"]
            result["kospi_change"] = kospi["change_rate"]
        except Exception:
            result["kospi"] = 0
            result["kospi_change"] = 0
        try:
            kosdaq = self.api.get_index_price("101")
            result["kosdaq"] = kosdaq["price"]
            result["kosdaq_change"] = kosdaq["change_rate"]
        except Exception:
            result["kosdaq"] = 0
            result["kosdaq_change"] = 0

        # 나스닥(전일) — global_merged.csv
        result["nasdaq"] = 0
        result["nasdaq_change"] = 0
        result["kospi_ma20"] = None
        try:
            df = pd.read_csv(GLOBAL_CSV)
            df.columns = [c.strip().lower() for c in df.columns]
            df = df.dropna(subset=["kospi_close"])
            if len(df) > 0:
                # 나스닥: 비어있을 수 있으므로 마지막 유효값 사용
                nasdaq_valid = df.dropna(subset=["nasdaq_close"])
                if len(nasdaq_valid) > 0:
                    result["nasdaq"] = round(float(nasdaq_valid.iloc[-1]["nasdaq_close"]), 2)
                    result["nasdaq_change"] = round(float(nasdaq_valid.iloc[-1]["nasdaq_change_pct"]), 2)
            # 코스피 MA20
            if len(df) >= 20:
                result["kospi_ma20"] = round(df["kospi_close"].tail(20).mean(), 2)
        except Exception:
            pass

        return result

    def _get_themes(self) -> list[dict]:
        """주도테마 TOP5"""
        try:
            themes = self.api.get_theme_groups(sort="3", period="1")
            return themes[:5]
        except Exception as e:
            logger.debug("테마 조회 실패: %s", e)
            return []

    def _analyze_sectors(self, scored: list) -> list[dict]:
        sector_data = defaultdict(lambda: {"count": 0, "total_change": 0.0, "stocks": []})
        for s in scored:
            sector = s.get("sector") or self.stock_map.get(s.get("code", ""), {}).get("sector", "기타")
            sector_data[sector]["count"] += 1
            sector_data[sector]["total_change"] += s.get("change_rate", 0)
            sector_data[sector]["stocks"].append(s.get("name", ""))

        result = []
        for sector, data in sector_data.items():
            avg_chg = data["total_change"] / data["count"] if data["count"] > 0 else 0
            result.append({"sector": sector, "count": data["count"],
                           "avg_change": round(avg_chg, 2), "stocks": data["stocks"][:5]})
        result.sort(key=lambda x: x["avg_change"], reverse=True)
        return result

    def _calc_prev_returns(self) -> list[dict]:
        today = datetime.now().strftime("%Y-%m-%d")
        log_files = sorted(LOG_DIR.glob("*.json"))
        prev_log = None
        for lf in reversed(log_files):
            if lf.stem != today:
                prev_log = lf
                break
        if not prev_log:
            return []
        try:
            prev_data = json.loads(prev_log.read_text(encoding="utf-8"))
            if prev_data.get("skipped"):
                return []
            results = []
            for stock in prev_data.get("top", []):
                try:
                    cur = self.api.get_current_price(stock["code"])
                    buy_price = stock["price"]
                    if buy_price > 0 and cur["price"] > 0:
                        ret = (cur["price"] / buy_price - 1) * 100
                        results.append({
                            "date": prev_log.stem, "code": stock["code"],
                            "name": stock.get("name", ""), "rank": stock.get("rank", 0),
                            "buy_price": buy_price, "today_price": cur["price"],
                            "return_pct": round(ret, 2),
                        })
                except Exception:
                    pass
            return results
        except Exception:
            return []

    # ──────────────────────────────────────────────
    # OHLCV 로드
    # ──────────────────────────────────────────────
    def _load_ohlcv(self, code: str) -> pd.DataFrame | None:
        code = code.strip().zfill(6)
        path = OHLCV_DIR / f"{code}.csv"
        if not path.exists():
            return None
        try:
            df = pd.read_csv(path)
            df.columns = [c.lower() for c in df.columns]  # 대문자→소문자 통일
            df["date"] = pd.to_datetime(df["date"])
            return df.sort_values("date").reset_index(drop=True)
        except Exception:
            return None

    def _fetch_ohlcv_api(self, code: str) -> pd.DataFrame | None:
        try:
            rows = self.api.get_daily_ohlcv(code)
            if not rows:
                return None
            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            return df.sort_values("date").reset_index(drop=True)
        except Exception:
            return None

    def _is_excluded(self, stock: dict) -> bool:
        name = stock.get("name", "")
        code = stock.get("code", "").strip().zfill(6)
        for keyword in EXCLUDE_NAMES:
            if keyword in name:
                return True
        if EXCLUDE_PREF_STOCK and code[-1] in ("5", "7", "8", "9"):
            return True
        if EXCLUDE_PREF_STOCK and (name.endswith("우") or name.endswith("우B")):
            return True
        if EXCLUDE_ETF:
            info = self.stock_map.get(code, {})
            if "ETF" in info.get("market", "").upper() or "ETF" in name.upper():
                return True
        return False

    def _stock_summary(self, stock: dict, rank: int) -> dict:
        code = stock.get("code", "").strip().zfill(6)
        name = stock.get("name", "")
        info = self.stock_map.get(code, {})
        return {
            "rank": rank,
            "code": code,
            "name": name or info.get("name", code),
            "sector": stock.get("sector") or info.get("sector", ""),
            "price": stock.get("price", 0),
            "change_rate": stock.get("change_rate", 0),
            "score": stock.get("score", 0),
            # 9지표
            "cci": stock.get("cci", 0),
            "rsi": stock.get("rsi", 0),
            "ma20_gap": stock.get("ma20_gap", 0),
            "cci_slope": stock.get("cci_slope", 0),
            "ma20_slope": stock.get("ma20_slope", 0),
            "vp_above_pct": stock.get("vp_above_pct", 50),
            "vp_tag": stock.get("vp_tag", ""),
            "broker_score": stock.get("broker_score", 0),
            "broker_signal": stock.get("broker_signal", ""),
            "vol_ratio": stock.get("vol_ratio", 1.0),
            # 추가 지표
            "ma5_gap": stock.get("ma5_gap", 0),
            "overheat": stock.get("overheat", False),
            # enricher 결과
            "broker_top_buy": stock.get("broker_top_buy", ""),
            "foreign_net": stock.get("foreign_net", 0),
            "dart_risk": stock.get("dart_risk", ""),
            "dart_note": stock.get("dart_note", ""),
            "profit_loss": stock.get("profit_loss", ""),
            "ai_action": stock.get("ai_action", ""),
            "ai_risk": stock.get("ai_risk", ""),
            "ai_summary": stock.get("ai_summary", ""),
        }


# ──────────────────────────────────────────────
# 유틸 함수
# ──────────────────────────────────────────────
def bell_score(value, opt_low, opt_high, zero_low, zero_high, max_points):
    """종형분포 점수 계산"""
    if value < zero_low or value > zero_high:
        return 0.0
    if opt_low <= value <= opt_high:
        return max_points
    if value < opt_low:
        span = opt_low - zero_low
        return max_points * (value - zero_low) / span if span > 0 else 0.0
    else:
        span = zero_high - opt_high
        return max_points * (zero_high - value) / span if span > 0 else 0.0


def _count_rising(values: list) -> int:
    if len(values) < 2:
        return 0
    count = 0
    for i in range(len(values) - 1, 0, -1):
        if values[i] > values[i - 1]:
            count += 1
        else:
            break
    return min(count, 3)