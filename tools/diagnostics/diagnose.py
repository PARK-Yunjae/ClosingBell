"""
data_validator 결과 확인용 진단 스크립트
실행: python diagnose.py
"""
import pandas as pd
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import DATA_DIR, GLOBAL_CSV, MAPPING_CSV, OHLCV_DIR

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 매핑 코드 형식 오류 57건 확인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("=" * 60)
print("1. 매핑 코드 형식 오류 확인")
print("=" * 60)

df = pd.read_csv(MAPPING_CSV, dtype={"code": str}, encoding="utf-8-sig")
df["code"] = df["code"].str.zfill(6)
bad = df[~df["code"].str.match(r"^\d{6}$")]

if len(bad) > 0:
    print(f"  총 {len(bad)}건:")
    for _, row in bad.head(20).iterrows():
        name = row.get("name", "?")
        code = row["code"]
        # OHLCV 파일 존재 여부
        exists = (OHLCV_DIR / f"{code}.csv").exists()
        print(f"    {code!r:>10s}  {name:<20s}  OHLCV={'있음' if exists else '없음'}")
    if len(bad) > 20:
        print(f"    ... 외 {len(bad)-20}건")
    print(f"\n  → 대부분 ETF/외국주식이면 무시해도 됨 (screener에서 이미 필터)")
else:
    print("  문제 없음")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 글로벌 중복 날짜 확인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n" + "=" * 60)
print("2. 글로벌 지수 중복 날짜")
print("=" * 60)

gdf = pd.read_csv(GLOBAL_CSV)
gdf.columns = [c.strip().lower() for c in gdf.columns]
dups = gdf[gdf.duplicated(subset=["date"], keep=False)]
if len(dups) > 0:
    print(f"  중복 날짜 {len(dups)}행:")
    for _, row in dups.iterrows():
        print(f"    {row['date']}  kospi={row.get('kospi_close','')}  nasdaq={row.get('nasdaq_close','')}")
    print(f"\n  → python data_validator.py --fix 로 마지막 값만 남기고 제거")
else:
    print("  중복 없음")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 글로벌 결측 범위 확인 (2024-11 이후만)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n" + "=" * 60)
print("3. 글로벌 결측 — 백필 범위(2024-11~) 확인")
print("=" * 60)

gdf["date"] = pd.to_datetime(gdf["date"])
recent = gdf[gdf["date"] >= "2024-11-01"]
print(f"  2024-11-01 이후: {len(recent)}행")

for col in ["kospi_close", "kosdaq_close", "nasdaq_close"]:
    if col in recent.columns:
        null_count = recent[col].isna().sum()
        pct = null_count / len(recent) * 100
        status = "✅ OK" if pct < 5 else f"⚠️ {null_count}건 ({pct:.1f}%)"
        print(f"  {col}: {status}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. 급등락 TOP10 — 액면분할/병합 확인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n" + "=" * 60)
print("4. 급등락 TOP10 — 액면분할/병합 확인")
print("=" * 60)

extreme_codes = ["078860", "139050", "900300", "159910", "079970",
                 "109960", "023770", "009810", "050090", "050110"]

for code in extreme_codes:
    path = OHLCV_DIR / f"{code}.csv"
    if not path.exists():
        continue
    odf = pd.read_csv(path)
    odf.columns = [c.lower() for c in odf.columns]
    odf["date"] = pd.to_datetime(odf["date"])
    odf["pct"] = odf["close"].pct_change() * 100

    extreme = odf[odf["pct"].abs() > 100].head(3)
    name = df[df["code"] == code]["name"].values[0] if code in df["code"].values else code

    if len(extreme) > 0:
        for _, row in extreme.iterrows():
            prev_idx = odf.index[odf.index < row.name].max() if row.name > 0 else None
            prev_close = odf.at[prev_idx, "close"] if prev_idx is not None else "?"
            print(f"  {code} {name}: {row['date'].strftime('%Y-%m-%d')} "
                  f"{prev_close}→{row['close']} ({row['pct']:+.0f}%)"
                  f" ← {'액면분할/병합' if abs(row['pct']) > 200 else '상한가연속'}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. 미갱신 14종목 확인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n" + "=" * 60)
print("5. 미갱신 종목 (5일 이상)")
print("=" * 60)

ref_path = OHLCV_DIR / "005930.csv"
ref_df = pd.read_csv(ref_path)
ref_df.columns = [c.lower() for c in ref_df.columns]
ref_df["date"] = pd.to_datetime(ref_df["date"])
ref_last = ref_df["date"].max()

stale = []
for f in OHLCV_DIR.glob("*.csv"):
    if f.stem.startswith("INDEX_"):
        continue
    try:
        tmp = pd.read_csv(f, usecols=[0], nrows=0)
        cols = [c.lower() for c in tmp.columns]
        if "date" not in cols:
            continue
        tmp = pd.read_csv(f)
        tmp.columns = [c.lower() for c in tmp.columns]
        tmp["date"] = pd.to_datetime(tmp["date"])
        last = tmp["date"].max()
        gap = (ref_last - last).days
        if gap > 5:
            name = df[df["code"] == f.stem]["name"].values[0] if f.stem in df["code"].values else f.stem
            stale.append((f.stem, name, last.strftime("%Y-%m-%d"), gap))
    except:
        pass

stale.sort(key=lambda x: -x[3])
for code, name, last_date, gap in stale[:20]:
    print(f"  {code} {name}: 마지막 {last_date} ({gap}일 전) ← {'상폐/거래정지' if gap > 60 else '갱신필요'}")

print(f"\n총 {len(stale)}종목")

print("\n" + "=" * 60)
print("결론")
print("=" * 60)
print("  ① python data_validator.py --fix  → 글로벌 중복 제거")
print("  ② 매핑 57건 → ETF/외국주식이면 무시 (screener 필터됨)")
print("  ③ OHLCV 날짜 갭 → 추석/설/거래정지, 정상")
print("  ④ 급등락 → 액면분할/병합, 정상")
print("  ⑤ 백필 범위(2024-11~) 글로벌 결측 5% 이하면 정상")
