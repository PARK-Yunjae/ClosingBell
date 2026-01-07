#!/usr/bin/env python
"""
백테스트 CLI 도구

사용법:
    # 기간 백테스트 (adjusted 파일 기반)
    python tools/run_backtest.py --start 2024-01-01 --end 2024-01-31
    
    # 랭킹 파일 기반 백테스트
    python tools/run_backtest.py --ranking project/data/final_ranking_v6.csv
    
    # TOP N 개수 지정
    python tools/run_backtest.py --start 2024-01-01 --end 2024-01-31 --top 5
    
    # 상세 거래 내역 출력
    python tools/run_backtest.py --ranking project/data/final_ranking_v6.csv --verbose
"""

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

# 프로젝트 루트 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.backtest_service import BacktestService, BacktestSummary


def parse_date(date_str: str) -> date:
    """날짜 문자열 파싱"""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date format: {date_str}. Use YYYY-MM-DD")


def print_summary(result: BacktestSummary, verbose: bool = False):
    """백테스트 결과 출력"""
    print("\n" + "=" * 60)
    print("📊 백테스트 결과 요약")
    print("=" * 60)
    
    print(f"\n📅 기간: {result.start_date} ~ {result.end_date}")
    print(f"📈 총 거래: {result.total_trades}회")
    
    if result.total_trades == 0:
        print("\n❌ 거래 데이터가 없습니다.")
        return
    
    print("\n" + "-" * 40)
    print("💰 수익률 통계")
    print("-" * 40)
    print(f"  갭 수익률 (평균):   {result.avg_gap_return:+.2f}%")
    print(f"  최대 수익률 (평균): {result.avg_max_return:+.2f}%")
    print(f"  종가 수익률 (평균): {result.avg_end_return:+.2f}%")
    
    print("\n" + "-" * 40)
    print("🎯 승률")
    print("-" * 40)
    print(f"  갭 승률:  {result.gap_win_rate:.1f}%")
    print(f"  종가 승률: {result.end_win_rate:.1f}%")
    
    if result.best_trade:
        print("\n" + "-" * 40)
        print("🏆 최고 거래")
        print("-" * 40)
        best = result.best_trade
        print(f"  {best.date} | {best.name} ({best.code})")
        print(f"  점수: {best.score:.1f} | 종가 수익률: {best.end_return:+.2f}%")
    
    if result.worst_trade:
        print("\n" + "-" * 40)
        print("💔 최저 거래")
        print("-" * 40)
        worst = result.worst_trade
        print(f"  {worst.date} | {worst.name} ({worst.code})")
        print(f"  점수: {worst.score:.1f} | 종가 수익률: {worst.end_return:+.2f}%")
    
    if verbose and result.trades:
        print("\n" + "=" * 60)
        print("📋 상세 거래 내역")
        print("=" * 60)
        print(f"{'날짜':<12} {'종목명':<12} {'점수':>6} {'갭':>8} {'최대':>8} {'종가':>8}")
        print("-" * 60)
        
        for trade in result.trades:
            print(
                f"{trade.date} | {trade.name:<10} | "
                f"{trade.score:>5.1f} | "
                f"{trade.gap_return:>+6.2f}% | "
                f"{trade.max_return:>+6.2f}% | "
                f"{trade.end_return:>+6.2f}%"
            )
    
    # 월별 요약
    if len(result.trades) >= 20:
        print("\n" + "=" * 60)
        print("📆 월별 요약")
        print("=" * 60)
        
        monthly_stats = {}
        for trade in result.trades:
            month_key = trade.date.strftime("%Y-%m")
            if month_key not in monthly_stats:
                monthly_stats[month_key] = {"count": 0, "gap_sum": 0, "end_sum": 0, "gap_wins": 0}
            
            monthly_stats[month_key]["count"] += 1
            monthly_stats[month_key]["gap_sum"] += trade.gap_return
            monthly_stats[month_key]["end_sum"] += trade.end_return
            if trade.gap_return > 0:
                monthly_stats[month_key]["gap_wins"] += 1
        
        print(f"{'월':<10} {'거래수':>6} {'평균갭':>10} {'평균종가':>10} {'갭승률':>10}")
        print("-" * 50)
        
        for month, stats in sorted(monthly_stats.items()):
            avg_gap = stats["gap_sum"] / stats["count"]
            avg_end = stats["end_sum"] / stats["count"]
            gap_win_rate = (stats["gap_wins"] / stats["count"]) * 100
            
            print(
                f"{month:<10} {stats['count']:>6} "
                f"{avg_gap:>+9.2f}% {avg_end:>+9.2f}% "
                f"{gap_win_rate:>9.1f}%"
            )
    
    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="ClosingBell 백테스트 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    
    parser.add_argument(
        "--start", "-s",
        type=parse_date,
        help="시작 날짜 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end", "-e",
        type=parse_date,
        help="종료 날짜 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--ranking", "-r",
        type=str,
        help="랭킹 파일 경로 (final_ranking_v6.csv)",
    )
    parser.add_argument(
        "--data-dir", "-d",
        type=str,
        default="project/data/adjusted",
        help="주가 데이터 디렉토리 (기본값: project/data/adjusted)",
    )
    parser.add_argument(
        "--top", "-n",
        type=int,
        default=3,
        help="TOP N 개수 (기본값: 3)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="상세 거래 내역 출력",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="디버그 로그 출력",
    )
    
    args = parser.parse_args()
    
    # 로깅 설정
    log_level = logging.DEBUG if args.debug else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    
    # 서비스 초기화
    service = BacktestService(data_dir=args.data_dir)
    
    # 백테스트 실행
    if args.ranking:
        # 랭킹 파일 기반
        ranking_path = Path(args.ranking)
        if not ranking_path.exists():
            print(f"❌ 랭킹 파일을 찾을 수 없습니다: {args.ranking}")
            sys.exit(1)
        
        print(f"📂 랭킹 파일 기반 백테스트: {args.ranking}")
        result = service.run_from_ranking_file(str(ranking_path), top_n=args.top)
    
    elif args.start and args.end:
        # 기간 백테스트
        print(f"📂 기간 백테스트: {args.start} ~ {args.end}")
        print(f"📁 데이터 디렉토리: {args.data_dir}")
        
        result = service.run_backtest(
            start_date=args.start,
            end_date=args.end,
            top_n=args.top,
        )
    
    else:
        parser.print_help()
        print("\n❌ --ranking 또는 --start/--end 옵션을 지정해주세요.")
        sys.exit(1)
    
    # 결과 출력
    print_summary(result, verbose=args.verbose)
    
    # 종료 코드
    if result.total_trades > 0:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
