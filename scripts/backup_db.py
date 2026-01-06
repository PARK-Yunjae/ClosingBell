#!/usr/bin/env python
"""DB 백업 스크립트

사용법:
    python scripts/backup_db.py              # 백업 실행
    python scripts/backup_db.py --keep 14    # 최근 14일 백업 유지
    python scripts/backup_db.py --list       # 백업 파일 목록 확인
"""

import sys
import os
import shutil
import argparse
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_backup_dir() -> Path:
    """백업 디렉토리 경로 반환"""
    project_root = Path(__file__).parent.parent
    backup_dir = project_root / "data" / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def get_db_path() -> Path:
    """DB 파일 경로 반환"""
    project_root = Path(__file__).parent.parent
    return project_root / "data" / "screener.db"


def create_backup() -> Path:
    """백업 파일 생성"""
    db_path = get_db_path()
    backup_dir = get_backup_dir()
    
    if not db_path.exists():
        print(f"❌ DB 파일이 없습니다: {db_path}")
        return None
    
    # 백업 파일명: screener_YYYYMMDD_HHMMSS.db
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"screener_{timestamp}.db"
    backup_path = backup_dir / backup_name
    
    # 파일 복사
    shutil.copy2(db_path, backup_path)
    
    # 파일 크기
    size_bytes = backup_path.stat().st_size
    size_kb = size_bytes / 1024
    size_mb = size_kb / 1024
    
    if size_mb >= 1:
        size_str = f"{size_mb:.2f} MB"
    else:
        size_str = f"{size_kb:.2f} KB"
    
    print(f"✅ 백업 완료: {backup_name} ({size_str})")
    return backup_path


def cleanup_old_backups(keep_days: int = 7):
    """오래된 백업 파일 삭제"""
    backup_dir = get_backup_dir()
    cutoff_date = datetime.now() - timedelta(days=keep_days)
    
    deleted_count = 0
    for backup_file in backup_dir.glob("screener_*.db"):
        # 파일명에서 날짜 추출
        try:
            filename = backup_file.stem  # screener_20260106_223000
            date_str = filename.split("_")[1]  # 20260106
            file_date = datetime.strptime(date_str, "%Y%m%d")
            
            if file_date < cutoff_date:
                backup_file.unlink()
                deleted_count += 1
                print(f"🗑️ 삭제: {backup_file.name}")
        except (IndexError, ValueError):
            continue
    
    if deleted_count > 0:
        print(f"✅ {deleted_count}개 오래된 백업 삭제됨 ({keep_days}일 이전)")
    else:
        print(f"ℹ️ 삭제할 오래된 백업이 없습니다.")


def list_backups():
    """백업 파일 목록 출력"""
    backup_dir = get_backup_dir()
    backups = sorted(backup_dir.glob("screener_*.db"), reverse=True)
    
    print()
    print("=" * 60)
    print("📦 백업 파일 목록")
    print("=" * 60)
    print()
    
    if not backups:
        print("백업 파일이 없습니다.")
        return
    
    print(f"{'파일명':<35} {'크기':>10} {'생성일':>15}")
    print("-" * 60)
    
    total_size = 0
    for backup in backups:
        size_bytes = backup.stat().st_size
        total_size += size_bytes
        size_kb = size_bytes / 1024
        
        if size_kb >= 1024:
            size_str = f"{size_kb/1024:.2f} MB"
        else:
            size_str = f"{size_kb:.2f} KB"
        
        # 파일명에서 날짜/시간 추출
        try:
            parts = backup.stem.split("_")
            date_str = parts[1]
            time_str = parts[2]
            created = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]} {time_str[:2]}:{time_str[2:4]}"
        except (IndexError, ValueError):
            created = "알 수 없음"
        
        print(f"{backup.name:<35} {size_str:>10} {created:>15}")
    
    print("-" * 60)
    
    # 총 크기
    total_mb = total_size / 1024 / 1024
    print(f"총 {len(backups)}개 파일, {total_mb:.2f} MB")
    print()


def main():
    parser = argparse.ArgumentParser(description='DB 백업 관리')
    parser.add_argument('--keep', type=int, default=7, help='백업 유지 기간 (일)')
    parser.add_argument('--list', action='store_true', help='백업 파일 목록 출력')
    parser.add_argument('--no-cleanup', action='store_true', help='오래된 백업 삭제 안 함')
    args = parser.parse_args()
    
    print()
    print("=" * 60)
    print("💾 DB 백업 관리")
    print("=" * 60)
    print()
    
    if args.list:
        list_backups()
        return
    
    # 백업 실행
    backup_path = create_backup()
    
    if backup_path and not args.no_cleanup:
        print()
        cleanup_old_backups(args.keep)
    
    print()
    print("=" * 60)
    
    # 백업 목록 출력
    list_backups()


if __name__ == "__main__":
    main()
