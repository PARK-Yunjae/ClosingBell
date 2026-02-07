"""DB에 코드로 저장된 종목명을 일괄 업데이트

사용법:
    python fix_names.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.services.pullback_scanner import _load_stock_names
from src.infrastructure.database import get_database

db = get_database()
names = _load_stock_names()
print(f"매핑 로드: {len(names)}개")

# volume_spikes 업데이트
rows = db.fetch_all("SELECT id, stock_code, stock_name FROM volume_spikes")
updated = 0
for r in rows:
    code = r["stock_code"]
    old_name = r["stock_name"]
    new_name = names.get(code, "")
    if new_name and (old_name == code or old_name.isdigit() or not old_name):
        db.execute("UPDATE volume_spikes SET stock_name = ? WHERE id = ?", (new_name, r["id"]))
        print(f"  spike: {code} → {new_name}")
        updated += 1
print(f"volume_spikes: {updated}개 업데이트")

# pullback_signals 업데이트
rows2 = db.fetch_all("SELECT id, stock_code, stock_name FROM pullback_signals")
updated2 = 0
for r in rows2:
    code = r["stock_code"]
    old_name = r["stock_name"]
    new_name = names.get(code, "")
    if new_name and (old_name == code or old_name.isdigit() or not old_name):
        db.execute("UPDATE pullback_signals SET stock_name = ? WHERE id = ?", (new_name, r["id"]))
        print(f"  signal: {code} → {new_name}")
        updated2 += 1
print(f"pullback_signals: {updated2}개 업데이트")
print("✅ 완료")
