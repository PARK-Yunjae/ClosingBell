"""OHLCV 파일에서 2026-01-20 라인 삭제"""
from pathlib import Path

OHLCV_DIR = Path(r"C:\Coding\data\ohlcv")

def delete_20th():
    count = 0
    for csv_file in OHLCV_DIR.glob("*.csv"):
        try:
            lines = csv_file.read_text(encoding='utf-8').splitlines()
            filtered = [l for l in lines if not l.startswith("2026-01-20")]
            
            if len(filtered) < len(lines):
                csv_file.write_text("\n".join(filtered) + "\n", encoding='utf-8')
                count += 1
                
        except Exception as e:
            print(f"❌ {csv_file.name}: {e}")
    
    print(f"✅ {count}개 파일에서 2026-01-20 삭제 완료!")

if __name__ == "__main__":
    delete_20th()
