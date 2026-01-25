"""
ClosingBell v6.5 - 출현 횟수 및 매수 타이밍 분석

가설 검증:
1. TOP5에 2~3번 등장 → 나중에 오름?
2. TOP5에 4~5번 이상 등장 → 떨어짐?
3. D+0 매수보다 D+4~5일 매수가 더 좋음?

사용법:
    python scripts/analyze_occurrence.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlite3
import pandas as pd
from datetime import datetime, timedelta

# DB 경로
DB_PATH = Path(__file__).parent.parent / "data" / "screener.db"


def load_data():
    """DB에서 TOP5 데이터 로드"""
    conn = sqlite3.connect(DB_PATH)
    
    # TOP5 히스토리
    df_history = pd.read_sql_query("""
        SELECT 
            id,
            screen_date,
            stock_code,
            stock_name,
            rank,
            screen_price,
            screen_score,
            grade,
            change_rate,
            trading_value
        FROM closing_top5_history
        ORDER BY screen_date, rank
    """, conn)
    
    # TOP5 가격 (D+1 ~ D+20)
    df_prices = pd.read_sql_query("""
        SELECT 
            top5_history_id as history_id,
            days_after as day_number,
            trade_date,
            close_price,
            return_from_screen as return_rate
        FROM top5_daily_prices
    """, conn)
    
    conn.close()
    
    return df_history, df_prices


def analyze_occurrence_count(df_history, df_prices):
    """가설 1, 2: 출현 횟수별 수익률 분석"""
    
    print("\n" + "="*60)
    print("📊 가설 1, 2: 출현 횟수별 수익률 분석")
    print("="*60)
    
    # 종목별 출현 횟수 계산
    occurrence_count = df_history.groupby('stock_code').size().reset_index(name='total_count')
    
    # 각 출현에 순번 부여
    df_history = df_history.sort_values(['stock_code', 'screen_date'])
    df_history['occurrence_num'] = df_history.groupby('stock_code').cumcount() + 1
    
    # 가격 데이터 조인
    df_merged = df_history.merge(df_prices, left_on='id', right_on='history_id', how='left')
    
    # 출현 순번별 D+1 수익률
    print("\n📈 N번째 출현 시 D+1 수익률:")
    print("-" * 50)
    
    d1_returns = df_merged[df_merged['day_number'] == 1].copy()
    
    for n in range(1, 8):
        subset = d1_returns[d1_returns['occurrence_num'] == n]
        if len(subset) > 5:
            avg_return = subset['return_rate'].mean()
            win_rate = (subset['return_rate'] > 0).mean() * 100
            print(f"  {n}번째 출현: 평균 {avg_return:+.2f}%, 승률 {win_rate:.1f}% (n={len(subset)})")
    
    # 총 출현 횟수 그룹별 분석
    print("\n📊 총 출현 횟수별 평균 D+1 수익률:")
    print("-" * 50)
    
    d1_with_count = d1_returns.merge(occurrence_count, on='stock_code')
    
    bins = [0, 1, 2, 3, 5, 10, 100]
    labels = ['1회', '2회', '3회', '4~5회', '6~10회', '10회+']
    d1_with_count['count_group'] = pd.cut(d1_with_count['total_count'], bins=bins, labels=labels)
    
    for group in labels:
        subset = d1_with_count[d1_with_count['count_group'] == group]
        if len(subset) > 5:
            avg_return = subset['return_rate'].mean()
            win_rate = (subset['return_rate'] > 0).mean() * 100
            print(f"  {group}: 평균 {avg_return:+.2f}%, 승률 {win_rate:.1f}% (n={len(subset)})")


def analyze_buy_timing(df_history, df_prices):
    """가설 3: 매수 타이밍 분석 (D+0 vs D+N)"""
    
    print("\n" + "="*60)
    print("📊 가설 3: 매수 타이밍별 수익률 분석")
    print("="*60)
    
    # 가격 데이터 pivot
    df_pivot = df_prices.pivot(
        index='history_id',
        columns='day_number',
        values='return_rate'
    ).reset_index()
    
    # 히스토리와 조인
    df_merged = df_history.merge(df_pivot, left_on='id', right_on='history_id', how='left')
    
    print("\n📈 D+N 매수 시 수익률 (D+20 기준 보유):")
    print("-" * 50)
    print("  (D+0 매수 = TOP5 선정일 종가 매수)")
    print()
    
    # D+0 매수 → D+20 수익률 = D+20 수익률 그대로
    if 20 in df_merged.columns:
        d0_to_d20 = df_merged[20].dropna()
        if len(d0_to_d20) > 0:
            print(f"  D+0 매수 → D+20: 평균 {d0_to_d20.mean():+.2f}%, "
                  f"승률 {(d0_to_d20 > 0).mean()*100:.1f}% (n={len(d0_to_d20)})")
    
    # D+N 매수 → D+20 수익률 = (D+20 수익률 - D+N 수익률) 근사
    for buy_day in [1, 3, 5, 7, 10]:
        if buy_day in df_merged.columns and 20 in df_merged.columns:
            # D+N 시점 매수 → D+20 보유 수익률
            # 근사: (1 + D20수익률) / (1 + DN수익률) - 1
            valid = df_merged[[buy_day, 20]].dropna()
            if len(valid) > 10:
                relative_return = ((1 + valid[20]/100) / (1 + valid[buy_day]/100) - 1) * 100
                avg_return = relative_return.mean()
                win_rate = (relative_return > 0).mean() * 100
                print(f"  D+{buy_day} 매수 → D+20: 평균 {avg_return:+.2f}%, "
                      f"승률 {win_rate:.1f}% (n={len(valid)})")
    
    print("\n📈 D+N 시점 누적 수익률 (D+0 대비):")
    print("-" * 50)
    
    for day in [1, 3, 5, 7, 10, 15, 20]:
        if day in df_merged.columns:
            returns = df_merged[day].dropna()
            if len(returns) > 0:
                avg = returns.mean()
                win = (returns > 0).mean() * 100
                print(f"  D+{day:2d}: 평균 {avg:+.2f}%, 승률 {win:.1f}% (n={len(returns)})")


def analyze_grade_timing(df_history, df_prices):
    """등급별 최적 매수 타이밍 분석"""
    
    print("\n" + "="*60)
    print("📊 등급별 최적 매수 타이밍")
    print("="*60)
    
    df_pivot = df_prices.pivot(
        index='history_id',
        columns='day_number',
        values='return_rate'
    ).reset_index()
    
    df_merged = df_history.merge(df_pivot, left_on='id', right_on='history_id', how='left')
    
    for grade in ['S', 'A', 'B', 'C']:
        subset = df_merged[df_merged['grade'] == grade]
        if len(subset) < 10:
            continue
            
        print(f"\n🏆 {grade}등급 (n={len(subset)}):")
        
        best_day = None
        best_return = -999
        
        for day in [1, 3, 5, 7, 10]:
            if day in subset.columns and 20 in subset.columns:
                valid = subset[[day, 20]].dropna()
                if len(valid) > 5:
                    relative = ((1 + valid[20]/100) / (1 + valid[day]/100) - 1) * 100
                    avg = relative.mean()
                    if avg > best_return:
                        best_return = avg
                        best_day = day
                    print(f"    D+{day} 매수 → D+20: {avg:+.2f}%")
        
        if best_day:
            print(f"    ⭐ 최적 매수일: D+{best_day} (평균 {best_return:+.2f}%)")


def analyze_price_range(df_history, df_prices):
    """금액대별 D+N 수익률 분석"""
    
    print("\n" + "="*60)
    print("📊 주가 금액대별 D+N 수익률 분석")
    print("="*60)
    
    # 가격 데이터 pivot
    df_pivot = df_prices.pivot(
        index='history_id',
        columns='day_number',
        values='return_rate'
    ).reset_index()
    
    df_merged = df_history.merge(df_pivot, left_on='id', right_on='history_id', how='left')
    
    # 주가 금액대 구분
    price_bins = [0, 5000, 10000, 30000, 50000, 100000, 1000000]
    price_labels = ['~5천', '5천~1만', '1~3만', '3~5만', '5~10만', '10만+']
    
    df_merged['price_group'] = pd.cut(
        df_merged['screen_price'], 
        bins=price_bins, 
        labels=price_labels
    )
    
    print("\n📈 주가 금액대별 D+N 수익률:")
    print("-" * 70)
    print(f"{'금액대':<12} {'D+1':>10} {'D+3':>10} {'D+5':>10} {'D+7':>10} {'D+10':>10} {'n':>6}")
    print("-" * 70)
    
    for group in price_labels:
        subset = df_merged[df_merged['price_group'] == group]
        if len(subset) < 3:
            continue
        
        row = f"{group:<12}"
        for day in [1, 3, 5, 7, 10]:
            if day in subset.columns:
                returns = subset[day].dropna()
                if len(returns) > 0:
                    avg = returns.mean()
                    row += f" {avg:+8.2f}%"
                else:
                    row += f" {'-':>9}"
            else:
                row += f" {'-':>9}"
        
        row += f" {len(subset):>5}"
        print(row)
    
    print("-" * 70)
    
    # 금액대별 승률
    print("\n📊 주가 금액대별 D+5 승률:")
    print("-" * 50)
    
    for group in price_labels:
        subset = df_merged[df_merged['price_group'] == group]
        if 5 not in subset.columns or len(subset) < 3:
            continue
        
        returns = subset[5].dropna()
        if len(returns) > 0:
            win_rate = (returns > 0).mean() * 100
            avg = returns.mean()
            print(f"  {group:<12}: 평균 {avg:+.2f}%, 승률 {win_rate:.1f}% (n={len(returns)})")


def analyze_trading_value(df_history, df_prices):
    """거래대금별 D+N 수익률 분석"""
    
    print("\n" + "="*60)
    print("📊 거래대금별 D+N 수익률 분석")
    print("="*60)
    
    # 가격 데이터 pivot
    df_pivot = df_prices.pivot(
        index='history_id',
        columns='day_number',
        values='return_rate'
    ).reset_index()
    
    df_merged = df_history.merge(df_pivot, left_on='id', right_on='history_id', how='left')
    
    # 거래대금 구분 (억원)
    value_bins = [0, 200, 500, 1000, 3000, 100000]
    value_labels = ['~200억', '200~500억', '500~1000억', '1000~3000억', '3000억+']
    
    df_merged['value_group'] = pd.cut(
        df_merged['trading_value'], 
        bins=value_bins, 
        labels=value_labels
    )
    
    print("\n📈 거래대금별 D+N 수익률:")
    print("-" * 70)
    print(f"{'거래대금':<15} {'D+1':>10} {'D+3':>10} {'D+5':>10} {'D+7':>10} {'D+10':>10} {'n':>6}")
    print("-" * 70)
    
    for group in value_labels:
        subset = df_merged[df_merged['value_group'] == group]
        if len(subset) < 3:
            continue
        
        row = f"{group:<15}"
        for day in [1, 3, 5, 7, 10]:
            if day in subset.columns:
                returns = subset[day].dropna()
                if len(returns) > 0:
                    avg = returns.mean()
                    row += f" {avg:+8.2f}%"
                else:
                    row += f" {'-':>9}"
            else:
                row += f" {'-':>9}"
        
        row += f" {len(subset):>5}"
        print(row)
    
    print("-" * 70)
    
    # 거래대금별 승률
    print("\n📊 거래대금별 D+5 승률:")
    print("-" * 50)
    
    for group in value_labels:
        subset = df_merged[df_merged['value_group'] == group]
        if 5 not in subset.columns or len(subset) < 3:
            continue
        
        returns = subset[5].dropna()
        if len(returns) > 0:
            win_rate = (returns > 0).mean() * 100
            avg = returns.mean()
            print(f"  {group:<15}: 평균 {avg:+.2f}%, 승률 {win_rate:.1f}% (n={len(returns)})")


def main():
    print("="*60)
    print("🔔 ClosingBell v6.5 - 출현 횟수 & 매수 타이밍 분석")
    print("="*60)
    
    if not DB_PATH.exists():
        print(f"❌ DB 파일 없음: {DB_PATH}")
        return
    
    print(f"\n📁 DB: {DB_PATH}")
    
    # 데이터 로드
    df_history, df_prices = load_data()
    
    print(f"📊 TOP5 히스토리: {len(df_history)}건")
    print(f"📊 TOP5 가격: {len(df_prices)}건")
    
    if df_history.empty:
        print("❌ 데이터가 없습니다. 먼저 백필을 실행하세요.")
        return
    
    # 분석 실행
    analyze_occurrence_count(df_history, df_prices)
    analyze_buy_timing(df_history, df_prices)
    analyze_grade_timing(df_history, df_prices)
    analyze_price_range(df_history, df_prices)
    analyze_trading_value(df_history, df_prices)
    
    print("\n" + "="*60)
    print("✅ 분석 완료")
    print("="*60)


if __name__ == "__main__":
    main()