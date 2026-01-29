"""
기존 데이터 news_count 수정 스크립트
=====================================

nomad_candidates 테이블의 news_count를 
실제 nomad_news 테이블의 개수와 동기화합니다.

실행:
    python fix_news_count.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / 'data' / 'screener.db'

def fix_news_count():
    """news_count 수정"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("=" * 60)
    print("📰 news_count 수정 시작")
    print("=" * 60)
    
    # 1. 현재 상태 확인
    cursor.execute("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN news_count > 0 THEN 1 ELSE 0 END) as with_count,
               SUM(CASE WHEN news_collected = 1 THEN 1 ELSE 0 END) as collected
        FROM nomad_candidates
    """)
    stats = cursor.fetchone()
    print(f"\n수정 전 상태:")
    print(f"  - 총 후보: {stats['total']}개")
    print(f"  - news_count > 0: {stats['with_count']}개")
    print(f"  - news_collected = 1: {stats['collected']}개")
    
    # 2. nomad_news에서 실제 개수 조회
    cursor.execute("""
        SELECT study_date, stock_code, COUNT(*) as cnt
        FROM nomad_news
        GROUP BY study_date, stock_code
    """)
    news_counts = {(r['study_date'], r['stock_code']): r['cnt'] for r in cursor.fetchall()}
    
    print(f"\n  - nomad_news 그룹: {len(news_counts)}개")
    
    # 3. nomad_candidates 업데이트
    updated = 0
    cursor.execute("SELECT id, study_date, stock_code FROM nomad_candidates")
    candidates = cursor.fetchall()
    
    for c in candidates:
        key = (c['study_date'], c['stock_code'])
        count = news_counts.get(key, 0)
        
        if count > 0:
            cursor.execute("""
                UPDATE nomad_candidates 
                SET news_count = ?, news_status = 'collected'
                WHERE id = ?
            """, (count, c['id']))
            updated += 1
        else:
            # 뉴스가 없는 경우에도 수집된 상태로 표시
            cursor.execute("""
                UPDATE nomad_candidates 
                SET news_count = 0, news_status = 'no_news'
                WHERE id = ? AND news_collected = 1
            """, (c['id'],))
    
    conn.commit()
    
    # 4. 수정 후 상태 확인
    cursor.execute("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN news_count > 0 THEN 1 ELSE 0 END) as with_count,
               SUM(CASE WHEN news_status = 'collected' THEN 1 ELSE 0 END) as collected,
               SUM(news_count) as total_news
        FROM nomad_candidates
    """)
    stats = cursor.fetchone()
    print(f"\n수정 후 상태:")
    print(f"  - 총 후보: {stats['total']}개")
    print(f"  - news_count > 0: {stats['with_count']}개")
    print(f"  - news_status = 'collected': {stats['collected']}개")
    print(f"  - 총 뉴스 개수: {stats['total_news']}개")
    print(f"\n✅ {updated}개 레코드 업데이트 완료")
    
    conn.close()
    print("=" * 60)

if __name__ == "__main__":
    fix_news_count()
