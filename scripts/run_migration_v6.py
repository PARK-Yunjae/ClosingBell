#!/usr/bin/env python3
"""
ClosingBell v6.0 마이그레이션 스크립트

사용법:
    python scripts/run_migration_v6.py
    
수행 작업:
    1. 기존 DB 백업 (screener.db.backup_YYYYMMDD_HHMMSS)
    2. v6.0 테이블 마이그레이션 실행
    3. 테이블 생성 확인
    4. 결과 리포트
"""

import sys
import os
from pathlib import Path
from datetime import datetime
import shutil

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def main():
    print("=" * 60)
    print("🔔 ClosingBell v6.0 마이그레이션")
    print("=" * 60)
    
    # 1. 설정 로드
    try:
        from src.config.settings import settings
        db_path = settings.database.path
        print(f"\n[1/4] DB 경로 확인: {db_path}")
    except Exception as e:
        print(f"❌ 설정 로드 실패: {e}")
        return False
    
    # 2. DB 백업
    if db_path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = db_path.parent / f"screener.db.backup_{timestamp}"
        
        print(f"\n[2/4] DB 백업 중...")
        try:
            shutil.copy2(db_path, backup_path)
            print(f"✅ 백업 완료: {backup_path}")
        except Exception as e:
            print(f"❌ 백업 실패: {e}")
            return False
    else:
        print(f"\n[2/4] 기존 DB 없음 - 신규 생성")
    
    # 3. 마이그레이션 실행
    print(f"\n[3/4] v6.0 마이그레이션 실행 중...")
    try:
        from src.infrastructure.database import get_database
        
        db = get_database()
        db.init_database()  # DDL + 마이그레이션 포함
        
        print("✅ 마이그레이션 완료")
    except Exception as e:
        print(f"❌ 마이그레이션 실패: {e}")
        print(f"\n💡 롤백하려면:")
        print(f"   copy {backup_path} {db_path}")
        return False
    
    # 4. 검증
    print(f"\n[4/4] 테이블 검증 중...")
    try:
        from src.infrastructure.database import get_database
        
        db = get_database()
        
        # v6.0 테이블 확인
        v6_tables = ['closing_top5_history', 'top5_daily_prices', 'nomad_candidates', 'nomad_news']
        
        existing = db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?, ?, ?, ?)",
            tuple(v6_tables)
        )
        existing_names = {row['name'] for row in existing}
        
        print("\nv6.0 테이블:")
        for table in v6_tables:
            if table in existing_names:
                print(f"  ✅ {table}")
            else:
                print(f"  ❌ {table} (없음)")
        
        if len(existing_names) == len(v6_tables):
            print("\n" + "=" * 60)
            print("✅ v6.0 마이그레이션 완료!")
            print("=" * 60)
            print(f"\n다음 단계:")
            print(f"  1. 과거 데이터 백필:")
            print(f"     python main.py --backfill 20")
            print(f"  2. 대시보드 확인:")
            print(f"     streamlit run dashboard/app.py")
            return True
        else:
            print("\n❌ 일부 테이블이 생성되지 않았습니다.")
            return False
            
    except Exception as e:
        print(f"❌ 검증 실패: {e}")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
