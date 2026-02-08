"""
repo_signals: BrokerSignalRepository, PullbackRepository
"""

import json
import logging
from datetime import date
from typing import List, Optional, Dict

from src.infrastructure.database import get_database, Database

logger = logging.getLogger(__name__)

class BrokerSignalRepository:
    """거래원 수급 신호 저장/조회"""
    
    def __init__(self):
        from src.infrastructure.database import get_database
        self.db = get_database()
        self._ensure_ai_column()

    def _ensure_ai_column(self):
        """v9.1: ai_summary 컬럼 추가"""
        try:
            cols = self.db.fetch_all("PRAGMA table_info(broker_signals)")
            if not any(c['name'] == 'ai_summary' for c in cols):
                self.db.execute("ALTER TABLE broker_signals ADD COLUMN ai_summary TEXT")
                logger.info("broker_signals: ai_summary 컬럼 추가")
        except Exception:
            pass
    
    def save_signal(
        self,
        screen_date: str,
        stock_code: str,
        stock_name: str,
        anomaly_score: int,
        broker_score: float,
        tag: str = "",
        buyers_json: str = "",
        sellers_json: str = "",
        unusual_score: int = 0,
        asymmetry_score: int = 0,
        distribution_score: int = 0,
        foreign_score: int = 0,
        frgn_buy: int = 0,
        frgn_sell: int = 0,
    ) -> bool:
        """거래원 신호 저장 (UPSERT)"""
        try:
            self.db.execute("""
                INSERT INTO broker_signals 
                    (screen_date, stock_code, stock_name, anomaly_score, broker_score,
                     tag, buyers_json, sellers_json, unusual_score, asymmetry_score,
                     distribution_score, foreign_score, frgn_buy, frgn_sell)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(screen_date, stock_code) DO UPDATE SET
                    stock_name=excluded.stock_name,
                    anomaly_score=excluded.anomaly_score,
                    broker_score=excluded.broker_score,
                    tag=excluded.tag,
                    buyers_json=excluded.buyers_json,
                    sellers_json=excluded.sellers_json,
                    unusual_score=excluded.unusual_score,
                    asymmetry_score=excluded.asymmetry_score,
                    distribution_score=excluded.distribution_score,
                    foreign_score=excluded.foreign_score,
                    frgn_buy=excluded.frgn_buy,
                    frgn_sell=excluded.frgn_sell
            """, (
                screen_date, stock_code, stock_name, anomaly_score, broker_score,
                tag, buyers_json, sellers_json, unusual_score, asymmetry_score,
                distribution_score, foreign_score, frgn_buy, frgn_sell,
            ))
            return True
        except Exception as e:
            logger.error(f"broker_signals 저장 실패: {e}")
            return False
    
    def get_signals_by_date(self, screen_date: str) -> list:
        """특정 날짜의 거래원 신호 조회"""
        return self.db.fetch_all(
            "SELECT * FROM broker_signals WHERE screen_date = ? ORDER BY anomaly_score DESC",
            (screen_date,)
        )
    
    def get_signals_by_code(self, stock_code: str, limit: int = 20) -> list:
        """특정 종목의 거래원 신호 이력 조회"""
        return self.db.fetch_all(
            "SELECT * FROM broker_signals WHERE stock_code = ? ORDER BY screen_date DESC LIMIT ?",
            (stock_code, limit)
        )
    
    def get_heatmap_data(self, days: int = 20) -> list:
        """히트맵용 데이터 (최근 N일, 종목×날짜 anomaly_score)"""
        return self.db.fetch_all("""
            SELECT screen_date, stock_code, stock_name, anomaly_score, broker_score, tag
            FROM broker_signals
            WHERE screen_date >= date('now', ? || ' days')
            ORDER BY screen_date DESC, anomaly_score DESC
        """, (f"-{days}",))

    def save_ai_summary(self, screen_date: str, ai_summary: str) -> bool:
        """날짜별 거래원 AI 분석 결과 저장 (첫 번째 종목 레코드에 저장)"""
        try:
            self.db.execute("""
                UPDATE broker_signals SET ai_summary = ?
                WHERE screen_date = ? AND id = (
                    SELECT id FROM broker_signals
                    WHERE screen_date = ?
                    ORDER BY anomaly_score DESC LIMIT 1
                )
            """, (ai_summary, screen_date, screen_date))
            return True
        except Exception as e:
            logger.error(f"broker AI summary 저장 실패: {e}")
            return False

    def get_ai_summary_by_date(self, screen_date: str) -> str:
        """날짜별 거래원 AI 분석 결과 조회"""
        try:
            row = self.db.fetch_one("""
                SELECT ai_summary FROM broker_signals
                WHERE screen_date = ? AND ai_summary IS NOT NULL AND ai_summary != ''
                LIMIT 1
            """, (screen_date,))
            return row['ai_summary'] if row else ""
        except Exception:
            return ""


def get_broker_signal_repository() -> BrokerSignalRepository:
    return BrokerSignalRepository()


# ============================================================
# 눌림목 스캐너 Repository (v9.1)
# ============================================================

class PullbackRepository:
    """눌림목 스캐너 데이터 저장/조회"""

    def __init__(self):
        from src.infrastructure.database import get_database
        self.db = get_database()

    # ── 거래량 폭발 ──

    def save_spike(self, spike) -> bool:
        """거래량 폭발 저장 (UPSERT)"""
        try:
            from dataclasses import asdict
            d = asdict(spike) if hasattr(spike, '__dataclass_fields__') else spike
            self.db.execute("""
                INSERT INTO volume_spikes
                    (stock_code, stock_name, spike_date, spike_volume, volume_ma20,
                     spike_ratio, open_price, high_price, low_price, close_price,
                     change_pct, sector, theme, is_leading_sector)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(spike_date, stock_code) DO UPDATE SET
                    stock_name=excluded.stock_name,
                    spike_volume=excluded.spike_volume,
                    volume_ma20=excluded.volume_ma20,
                    spike_ratio=excluded.spike_ratio,
                    open_price=excluded.open_price,
                    high_price=excluded.high_price,
                    low_price=excluded.low_price,
                    close_price=excluded.close_price,
                    change_pct=excluded.change_pct
            """, (
                d['stock_code'], d['stock_name'], d['spike_date'],
                d['spike_volume'], d['volume_ma20'], d['spike_ratio'],
                d['open_price'], d['high_price'], d['low_price'], d['close_price'],
                d['change_pct'], d.get('sector', ''), d.get('theme', ''),
                int(d.get('is_leading_sector', False)),
            ))
            return True
        except Exception as e:
            logger.error(f"volume_spikes 저장 실패: {e}")
            return False

    def get_active_spikes(self, target_date, watch_days: int = 3) -> list:
        """감시 중인 폭발 종목 조회 (최근 N일 이내)"""
        from datetime import timedelta
        cutoff = (target_date - timedelta(days=watch_days + 2)).strftime("%Y-%m-%d")
        target_str = target_date.strftime("%Y-%m-%d")
        return self.db.fetch_all("""
            SELECT * FROM volume_spikes
            WHERE spike_date >= ? AND spike_date < ?
              AND status = 'watching'
            ORDER BY spike_ratio DESC
        """, (cutoff, target_str))

    def get_spikes_by_date(self, spike_date: str) -> list:
        """특정 날짜의 거래량 폭발 조회"""
        return self.db.fetch_all(
            "SELECT * FROM volume_spikes WHERE spike_date = ? ORDER BY spike_ratio DESC",
            (spike_date,)
        )

    def get_recent_spikes(self, days: int = 7) -> list:
        """최근 N일간 거래량 폭발 조회"""
        return self.db.fetch_all("""
            SELECT * FROM volume_spikes
            WHERE spike_date >= date('now', ? || ' days')
            ORDER BY spike_date DESC, spike_ratio DESC
        """, (f"-{days}",))

    # ── 눌림목 시그널 ──

    def save_signal(self, signal) -> bool:
        """눌림목 시그널 저장 (UPSERT)"""
        try:
            from dataclasses import asdict
            d = asdict(signal) if hasattr(signal, '__dataclass_fields__') else signal
            self.db.execute("""
                INSERT INTO pullback_signals
                    (stock_code, stock_name, spike_date, signal_date, days_after,
                     close_price, open_price, spike_high, drop_from_high_pct,
                     today_volume, spike_volume, vol_decrease_pct,
                     ma5, ma20, ma_support, ma_distance_pct,
                     is_negative_candle, sector, is_leading_sector, has_recent_news,
                     signal_strength, reason, ai_comment)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(signal_date, stock_code) DO UPDATE SET
                    days_after=excluded.days_after,
                    close_price=excluded.close_price,
                    vol_decrease_pct=excluded.vol_decrease_pct,
                    ma_support=excluded.ma_support,
                    signal_strength=excluded.signal_strength,
                    reason=excluded.reason,
                    ai_comment=excluded.ai_comment
            """, (
                d['stock_code'], d['stock_name'], d['spike_date'], d['signal_date'],
                d['days_after'], d['close_price'], d['open_price'], d['spike_high'],
                d['drop_from_high_pct'], d['today_volume'], d['spike_volume'],
                d['vol_decrease_pct'], d['ma5'], d['ma20'], d['ma_support'],
                d['ma_distance_pct'], int(d['is_negative_candle']),
                d.get('sector', ''), int(d.get('is_leading_sector', False)),
                int(d.get('has_recent_news', False)),
                d['signal_strength'], d['reason'], d.get('ai_comment', ''),
            ))
            return True
        except Exception as e:
            logger.error(f"pullback_signals 저장 실패: {e}")
            return False

    def get_signals_by_date(self, signal_date: str) -> list:
        """특정 날짜의 눌림목 시그널 조회"""
        return self.db.fetch_all(
            "SELECT * FROM pullback_signals WHERE signal_date = ? ORDER BY signal_strength, vol_decrease_pct",
            (signal_date,)
        )

    def get_recent_signals(self, days: int = 7) -> list:
        """최근 N일간 눌림목 시그널 조회"""
        return self.db.fetch_all("""
            SELECT * FROM pullback_signals
            WHERE signal_date >= date('now', ? || ' days')
            ORDER BY signal_date DESC, signal_strength, vol_decrease_pct
        """, (f"-{days}",))

    def get_signals_with_spikes(self, days: int = 7) -> list:
        """시그널 + 폭발 데이터 JOIN 조회"""
        return self.db.fetch_all("""
            SELECT p.*, v.spike_ratio, v.volume_ma20, v.change_pct as spike_change_pct
            FROM pullback_signals p
            LEFT JOIN volume_spikes v ON p.stock_code = v.stock_code AND p.spike_date = v.spike_date
            WHERE p.signal_date >= date('now', ? || ' days')
            ORDER BY p.signal_date DESC, p.signal_strength, p.vol_decrease_pct
        """, (f"-{days}",))


def get_pullback_repository() -> PullbackRepository:
    return PullbackRepository()


if __name__ == "__main__":
    # 테스트
    from src.infrastructure.database import init_database
    
    logging.basicConfig(level=logging.INFO)
    
    # DB 초기화
    init_database()
    
    # 가중치 테스트
    weight_repo = get_weight_repository()
    weights = weight_repo.get_weights()
    print(f"\n현재 가중치: {weights.to_dict()}")
    
    # 가중치 업데이트 테스트
    weight_repo.update_weight('cci_value', 1.2, reason='테스트')
    weights = weight_repo.get_weights()
    print(f"업데이트 후 가중치: {weights.to_dict()}")
    
    # 이력 확인
    history = weight_repo.get_weight_history()
    print(f"\n가중치 변경 이력: {len(history)}건")
    for h in history[:3]:
        print(f"  - {h['indicator']}: {h['old_weight']} -> {h['new_weight']}")




