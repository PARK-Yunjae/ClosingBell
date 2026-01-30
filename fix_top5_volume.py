"""
TOP5 volume NULL 데이터 수정 스크립트

사용: python fix_top5_volume.py
"""

import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime

# 경로 설정
DB_PATH = Path("data/screener.db")
OHLCV_DIR = Path(r"C:\Coding\data\ohlcv")

def main():
    print("=" * 60)
    print("📊 TOP5 volume 데이터 수정")
    print("=" * 60)
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. volume이 NULL인 레코드 조회
    cursor.execute("""
        SELECT id, screen_date, stock_code, stock_name
        FROM closing_top5_history
        WHERE volume IS NULL
        ORDER BY screen_date DESC
    """)
    
    null_records = cursor.fetchall()
    print(f"volume NULL 레코드: {len(null_records)}개")
    
    if not null_records:
        print("✅ 수정할 데이터 없음")
        conn.close()
        return
    
    # 2. 각 레코드의 volume 채우기
    updated = 0
    for record in null_records:
        record_id = record['id']
        screen_date = record['screen_date']
        stock_code = record['stock_code']
        stock_name = record['stock_name']
        
        # OHLCV CSV 파일에서 volume 조회
        csv_path = OHLCV_DIR / f"{stock_code}.csv"
        
        if not csv_path.exists():
            print(f"  ⚠️ CSV 없음: {stock_code} ({stock_name})")
            continue
        
        try:
            df = pd.read_csv(csv_path)
            df.columns = df.columns.str.lower()
            
            if 'date' not in df.columns:
                if 'unnamed: 0' in df.columns:
                    df = df.rename(columns={'unnamed: 0': 'date'})
                else:
                    print(f"  ⚠️ date 컬럼 없음: {stock_code}")
                    continue
            
            # 날짜 포맷 맞추기
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
            
            # 해당 날짜 데이터 찾기
            day_data = df[df['date'] == screen_date]
            
            if day_data.empty:
                print(f"  ⚠️ {screen_date} 데이터 없음: {stock_code}")
                continue
            
            volume = int(day_data.iloc[-1]['volume'])
            
            # DB 업데이트
            cursor.execute(
                "UPDATE closing_top5_history SET volume = ? WHERE id = ?",
                (volume, record_id)
            )
            
            print(f"  ✅ {screen_date} {stock_name}: volume = {volume:,}")
            updated += 1
            
        except Exception as e:
            print(f"  ❌ 오류 {stock_code}: {e}")
            continue
    
    conn.commit()
    conn.close()
    
    print()
    print("=" * 60)
    print(f"✅ 완료: {updated}/{len(null_records)}개 업데이트")
    print("=" * 60)


if __name__ == "__main__":
    main()
