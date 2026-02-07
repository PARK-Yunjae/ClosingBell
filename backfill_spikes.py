"""눌림목 감시풀 백필 — 최근 N거래일 거래량 폭발 소급 스캔

사용법:
    python backfill_spikes.py          # 최근 3거래일
    python backfill_spikes.py 5        # 최근 5거래일
"""

import sys
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from datetime import date, timedelta


def get_recent_trading_days(n: int = 3):
    """최근 N거래일 날짜 추출 (OHLCV 파일 기반)"""
    from src.services.pullback_scanner import _get_all_codes, _load_ohlcv

    codes = _get_all_codes()
    if not codes:
        print("❌ OHLCV 파일 없음")
        return []

    # 첫 번째 종목에서 날짜 추출
    for code in codes[:10]:
        df = _load_ohlcv(code)
        if df is not None and len(df) >= n:
            dates = df["date"].dt.date.tolist()
            recent = sorted(set(dates), reverse=True)[:n]
            return sorted(recent)

    return []


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3

    print("=" * 50)
    print(f"눌림목 감시풀 백필 (최근 {n}거래일)")
    print("=" * 50)

    # DB 마이그레이션 확인
    from src.infrastructure.database import get_database
    db = get_database()
    db.run_migration_v91_pullback()
    print("✅ DB 테이블 확인 완료")

    # 최근 거래일 추출
    trading_days = get_recent_trading_days(n)
    if not trading_days:
        print("❌ 거래일 추출 실패")
        return

    print(f"📅 스캔 대상: {[d.strftime('%Y-%m-%d') for d in trading_days]}")
    print()

    # 각 거래일별 거래량 폭발 스캔
    from src.services.pullback_scanner import scan_volume_spikes

    total_spikes = 0
    for td in trading_days:
        print(f"─── {td.strftime('%Y-%m-%d')} ───")
        spikes = scan_volume_spikes(target_date=td)
        total_spikes += len(spikes)
        if spikes:
            for s in spikes[:5]:
                sector_tag = f" [{s.sector}]" if s.sector else ""
                print(f"  🔥 {s.stock_name}({s.stock_code}){sector_tag} | {s.spike_volume:,}주 | {s.spike_ratio:.1f}배 | {s.change_pct:+.1f}%")
            if len(spikes) > 5:
                print(f"  ... 외 {len(spikes) - 5}개")
        else:
            print("  (폭발 종목 없음)")
        print()

    # 감시풀 현황
    from src.infrastructure.repository import get_pullback_repository
    repo = get_pullback_repository()
    active = repo.get_active_spikes(date.today(), watch_days=n + 2)

    print("=" * 50)
    print(f"✅ 총 {total_spikes}개 거래량 폭발 저장 완료")
    print(f"📋 현재 감시풀: {len(active)}개 종목")
    print()

    if active:
        print("감시풀 종목:")
        for a in active:
            r = dict(a) if not isinstance(a, dict) else a
            sector = r.get("sector", "") or "-"
            print(f"  {r.get('stock_name')} ({r.get('stock_code')}) | "
                  f"{r.get('spike_date')} | "
                  f"{int(r.get('spike_volume', 0)):,}주 | "
                  f"{float(r.get('spike_ratio', 0)):.1f}배 | "
                  f"섹터: {sector}")

    print()
    print("→ 월요일 15:10 스케줄러가 이 감시풀 기반으로 눌림목 시그널을 체크합니다.")
    print("→ 수동 테스트: python test_pullback.py --pull")


if __name__ == "__main__":
    main()
