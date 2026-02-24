"""
ClosingBell v2 — 스크리닝 + 점수 계산
"""
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from config import (
    CCI_PERIOD, CCI_OPTIMAL, CCI_ZERO_LOW, CCI_ZERO_HIGH,
    MA20_GAP_OPTIMAL, MA20_GAP_ZERO,
    CHANGE_OPTIMAL, CHANGE_ZERO,
    SCORE_CCI, SCORE_MA20_GAP, SCORE_CHANGE, SCORE_CCI_SLOPE, SCORE_MA20_SLOPE,
    TOP_N, TOP_N_CONSERVATIVE, MIN_PRICE, MAX_PRICE,
    NASDAQ_DROP_THRESHOLD, OHLCV_DIR, GLOBAL_CSV, MAPPING_CSV,
    TV200_CONDITION_NAME, API_DELAY,
)
from kis_api import KisAPI

logger = logging.getLogger("closingbell")


class Screener:
    """종가매매 스크리닝 엔진"""

    def __init__(self, api: KisAPI):
        self.api = api
        self.stock_map = self._load_stock_map()

    def _load_stock_map(self) -> dict:
        """stock_mapping.csv → {code: {name, market, sector}}"""
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
    def run(self) -> dict:
        """
        전체 스크리닝 실행
        반환: {"date", "market", "universe_count", "top5", "all_scored", "skipped"?}
        """
        today = datetime.now().strftime("%Y-%m-%d")
        market = self.get_market_status()

        # 나스닥 필터
        nasdaq_chg = market.get("nasdaq_change", 0)
        if nasdaq_chg <= NASDAQ_DROP_THRESHOLD:
            logger.warning("나스닥 급락 (%.1f%%) → 스크리닝 스킵", nasdaq_chg)
            return {
                "date": today,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "market": market,
                "skipped": True,
                "reason": f"나스닥 전일 {nasdaq_chg:+.1f}% (기준: {NASDAQ_DROP_THRESHOLD}%)",
                "universe_count": 0,
                "top5": [],
                "all_scored": [],
            }

        # 유니버스 확보
        universe = self.get_universe()
        if not universe:
            logger.warning("유니버스 0건 → 거래량순위 fallback")
            universe = self.get_universe_fallback()

        logger.info("유니버스: %d종목", len(universe))

        # 가격 필터 (가격=0이면 현재가 API로 보완)
        filtered = []
        price_zero = 0
        for s in universe:
            if s["price"] == 0:
                try:
                    cur = self.api.get_current_price(s["code"])
                    s["price"] = cur["price"]
                    s["change_rate"] = cur["change_rate"]
                except Exception:
                    pass

            if s["price"] == 0:
                price_zero += 1
                continue
            if s["price"] < MIN_PRICE or s["price"] > MAX_PRICE:
                continue
            filtered.append(s)

        if price_zero > 0:
            logger.warning("가격 0원 종목: %d개 (API 필드명 불일치 가능)", price_zero)
        logger.info("가격 필터 후: %d종목 (원본 %d, 범위 %d~%d원)",
                     len(filtered), len(universe), MIN_PRICE, MAX_PRICE)
        universe = filtered

        # 각 종목 지표 계산
        scored = []
        calc_fail = 0
        for stock in universe:
            try:
                self._calc_indicators(stock)
                stock["score"] = self._calc_score(stock)
                scored.append(stock)
            except Exception as e:
                calc_fail += 1
                if calc_fail <= 3:  # 처음 3건만 상세 로그
                    logger.warning("지표 계산 실패 [%s %s]: %s",
                                   stock.get("code"), stock.get("name"), e)

        if calc_fail > 0:
            logger.warning("지표 계산 실패: %d/%d종목", calc_fail, len(universe))

        # 정렬
        scored.sort(key=lambda x: x["score"], reverse=True)

        # TOP_N 결정 (시장 보수 모드)
        top_n = TOP_N
        kospi_ma20 = market.get("kospi_ma20")
        if kospi_ma20 and market.get("kospi", 0) < kospi_ma20:
            top_n = TOP_N_CONSERVATIVE
            logger.info("코스피 < MA20 → 보수 모드 (TOP%d)", top_n)

        top5 = scored[:top_n]

        return {
            "date": today,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "market": market,
            "universe_count": len(universe),
            "top5": [self._stock_summary(s, i + 1) for i, s in enumerate(top5)],
            "all_scored": [self._stock_summary(s, i + 1) for i, s in enumerate(scored)],
        }

    # ──────────────────────────────────────────────
    # 유니버스
    # ──────────────────────────────────────────────
    def get_universe(self) -> list[dict]:
        """TV200 조건검색으로 유니버스 확보"""
        seq = self.api.find_tv200_seq(TV200_CONDITION_NAME)
        if not seq:
            return []
        stocks = self.api.get_condition_stocks(seq)
        logger.info("TV200 조건검색: %d종목", len(stocks))
        return stocks

    def get_universe_fallback(self) -> list[dict]:
        """거래량순위 API fallback (30건 한계)"""
        stocks = self.api.get_volume_rank()
        # 등락률 1~29% 필터
        stocks = [s for s in stocks if 1.0 <= s.get("change_rate", 0) <= 29.0]
        logger.info("거래량순위 fallback: %d종목", len(stocks))
        return stocks

    # ──────────────────────────────────────────────
    # 지표 계산
    # ──────────────────────────────────────────────
    def _calc_indicators(self, stock: dict):
        """종목에 CCI, MA20, 이격도, 기울기 추가"""
        code = stock["code"]

        # OHLCV: 로컬 CSV 우선 → 없으면 API
        df = self._load_ohlcv(code)
        if df is None or len(df) < 20:
            df = self._fetch_ohlcv_api(code)

        if df is None or len(df) < 20:
            raise ValueError(f"{code}: OHLCV 부족 ({len(df) if df is not None else 0}일)")

        # 최근 데이터 사용
        df = df.tail(50).copy()

        # MA20
        df["ma20"] = df["close"].rolling(20).mean()

        # CCI(14)
        tp = (df["high"] + df["low"] + df["close"]) / 3
        sma_tp = tp.rolling(CCI_PERIOD).mean()
        mad = tp.rolling(CCI_PERIOD).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
        df["cci"] = (tp - sma_tp) / (0.015 * mad)

        latest = df.iloc[-1]
        prev_3 = df.tail(4)  # 최근 4일 (현재 + 3일전)

        stock["cci"] = round(float(latest["cci"]), 1) if pd.notna(latest["cci"]) else 0
        stock["ma20"] = round(float(latest["ma20"]), 0) if pd.notna(latest["ma20"]) else 0
        stock["ma20_gap"] = round(
            (float(latest["close"]) / float(latest["ma20"]) - 1) * 100, 1
        ) if latest["ma20"] > 0 else 0

        # CCI 기울기: 최근 3일간 연속 상승일 수
        cci_vals = prev_3["cci"].dropna().tolist()
        stock["cci_slope"] = _count_rising(cci_vals)

        # MA20 기울기: 최근 3일간 연속 상승일 수
        ma20_vals = prev_3["ma20"].dropna().tolist()
        stock["ma20_slope"] = _count_rising(ma20_vals)

    def _load_ohlcv(self, code: str) -> pd.DataFrame | None:
        """로컬 CSV에서 OHLCV 로드"""
        code = code.strip().zfill(6)
        path = OHLCV_DIR / f"{code}.csv"
        if not path.exists():
            return None
        try:
            df = pd.read_csv(path)
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            return df
        except Exception:
            return None

    def _fetch_ohlcv_api(self, code: str) -> pd.DataFrame | None:
        """API에서 최근 30일 OHLCV 가져오기"""
        try:
            end = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")
            rows = self.api.get_daily_prices(code, start, end)
            if not rows:
                return None
            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            return df.sort_values("date").reset_index(drop=True)
        except Exception as e:
            logger.debug("API OHLCV 실패 [%s]: %s", code, e)
            return None

    # ──────────────────────────────────────────────
    # 점수 계산 (100점, 종형분포)
    # ──────────────────────────────────────────────
    def _calc_score(self, stock: dict) -> float:
        """5개 지표 종형분포 점수"""
        score = 0.0

        # CCI (30점): 160~180 만점
        score += bell_score(
            stock.get("cci", 0),
            CCI_OPTIMAL[0], CCI_OPTIMAL[1],
            CCI_ZERO_LOW, CCI_ZERO_HIGH,
            SCORE_CCI,
        )

        # MA20 이격도 (25점): 2~8% 만점
        gap = stock.get("ma20_gap", 0)
        score += bell_score(
            gap,
            MA20_GAP_OPTIMAL[0], MA20_GAP_OPTIMAL[1],
            0, MA20_GAP_ZERO,
            SCORE_MA20_GAP,
        )

        # 등락률 (20점): 2~8% 만점
        chg = stock.get("change_rate", 0)
        score += bell_score(
            chg,
            CHANGE_OPTIMAL[0], CHANGE_OPTIMAL[1],
            0, CHANGE_ZERO,
            SCORE_CHANGE,
        )

        # CCI 기울기 (15점): 연속 상승일 × 5
        score += min(SCORE_CCI_SLOPE, max(0, stock.get("cci_slope", 0)) * 5)

        # MA20 기울기 (10점): 연속 상승일 × 3.33
        score += min(SCORE_MA20_SLOPE, max(0, stock.get("ma20_slope", 0)) * 3.33)

        return round(score, 1)

    # ──────────────────────────────────────────────
    # 시장 현황
    # ──────────────────────────────────────────────
    def get_market_status(self) -> dict:
        """코스피/코스닥/나스닥(전일) 상태"""
        result = {}

        # API로 코스피/코스닥
        try:
            kospi = self.api.get_index_price("0001")
            result["kospi"] = kospi["price"]
            result["kospi_change"] = kospi["change_rate"]
        except Exception:
            result["kospi"] = 0
            result["kospi_change"] = 0

        try:
            kosdaq = self.api.get_index_price("1001")
            result["kosdaq"] = kosdaq["price"]
            result["kosdaq_change"] = kosdaq["change_rate"]
        except Exception:
            result["kosdaq"] = 0
            result["kosdaq_change"] = 0

        # 나스닥(전일) - global_merged.csv에서
        result["nasdaq"] = 0
        result["nasdaq_change"] = 0
        result["kospi_ma20"] = None
        try:
            df = pd.read_csv(GLOBAL_CSV)
            df = df.dropna(subset=["nasdaq_close"])
            if len(df) > 0:
                latest = df.iloc[-1]
                result["nasdaq"] = round(float(latest["nasdaq_close"]), 2)
                result["nasdaq_change"] = round(float(latest["nasdaq_change_pct"]), 2)

            # 코스피 MA20
            kospi_col = df.dropna(subset=["kospi_close"])
            if len(kospi_col) >= 20:
                result["kospi_ma20"] = round(kospi_col["kospi_close"].tail(20).mean(), 2)
        except Exception as e:
            logger.debug("global_merged 로드 실패: %s", e)

        return result

    # ──────────────────────────────────────────────
    # 백테스트 (심플)
    # ──────────────────────────────────────────────
    def run_backtest(self, days: int = 30) -> dict:
        """로컬 data/ohlcv 기반 간단 백테스트 (시가 매도 기준)"""
        from config import LOG_DIR
        import json

        log_files = sorted(LOG_DIR.glob("*.json"))
        if not log_files:
            logger.warning("로그 파일 없음 → 백테스트 불가")
            return {"error": "로그 파일 없음"}

        results = []
        for lf in log_files[-days:]:
            try:
                data = json.loads(lf.read_text(encoding="utf-8"))
                if data.get("skipped"):
                    continue
                rec_date = data["date"]
                for stock in data.get("top5", []):
                    code = stock["code"]
                    buy_price = stock["price"]
                    # 다음날 시가 조회
                    next_open = self._get_next_open(code, rec_date)
                    if next_open and buy_price > 0:
                        ret = (next_open / buy_price - 1) * 100
                        results.append({
                            "date": rec_date,
                            "code": code,
                            "name": stock.get("name", ""),
                            "rank": stock.get("rank", 0),
                            "score": stock.get("score", 0),
                            "buy_price": buy_price,
                            "next_open": next_open,
                            "return_pct": round(ret, 2),
                        })
            except Exception as e:
                logger.debug("백테스트 로그 처리 실패 [%s]: %s", lf.name, e)

        if not results:
            return {"total": 0, "message": "결과 없음"}

        df = pd.DataFrame(results)
        win_rate = (df["return_pct"] > 0).mean() * 100
        avg_ret = df["return_pct"].mean()

        return {
            "total": len(results),
            "win_rate": round(win_rate, 1),
            "avg_return": round(avg_ret, 2),
            "details": results,
        }

    def _get_next_open(self, code: str, date_str: str) -> int | None:
        """다음 거래일 시가 조회 (로컬 CSV)"""
        df = self._load_ohlcv(code)
        if df is None:
            return None
        df["date_str"] = df["date"].dt.strftime("%Y-%m-%d")
        mask = df["date_str"] > date_str
        next_rows = df[mask]
        if len(next_rows) == 0:
            return None
        return int(next_rows.iloc[0]["open"])

    # ──────────────────────────────────────────────
    # 유틸
    # ──────────────────────────────────────────────
    def _stock_summary(self, stock: dict, rank: int) -> dict:
        """종목 요약 (JSON 저장/디스코드용)"""
        name = stock.get("name", "")
        if not name:
            info = self.stock_map.get(stock.get("code", ""), {})
            name = info.get("name", stock.get("code", "?"))

        return {
            "rank": rank,
            "code": stock.get("code", ""),
            "name": name,
            "price": stock.get("price", 0),
            "change_rate": stock.get("change_rate", 0),
            "score": stock.get("score", 0),
            "cci": stock.get("cci", 0),
            "ma20_gap": stock.get("ma20_gap", 0),
            "cci_slope": stock.get("cci_slope", 0),
            "ma20_slope": stock.get("ma20_slope", 0),
        }


# ──────────────────────────────────────────────
# 유틸 함수
# ──────────────────────────────────────────────
def bell_score(
    value: float,
    opt_low: float,
    opt_high: float,
    zero_low: float,
    zero_high: float,
    max_points: float,
) -> float:
    """
    종형분포 점수 계산

    opt_low~opt_high: 만점 구간
    zero_low 이하 또는 zero_high 이상: 0점
    그 사이: 선형 보간
    """
    if value < zero_low or value > zero_high:
        return 0.0
    if opt_low <= value <= opt_high:
        return max_points

    if value < opt_low:
        # zero_low ~ opt_low 사이 선형
        span = opt_low - zero_low
        if span <= 0:
            return 0.0
        return max_points * (value - zero_low) / span
    else:
        # opt_high ~ zero_high 사이 선형
        span = zero_high - opt_high
        if span <= 0:
            return 0.0
        return max_points * (zero_high - value) / span


def _count_rising(values: list) -> int:
    """리스트 끝에서부터 연속 상승 일수 (최대 3)"""
    if len(values) < 2:
        return 0
    count = 0
    for i in range(len(values) - 1, 0, -1):
        if values[i] > values[i - 1]:
            count += 1
        else:
            break
    return min(count, 3)
