import FinanceDataReader as fdr
import pandas as pd

# 전체 종목 리스트 (KOSPI + KOSDAQ)
kospi = fdr.StockListing('KOSPI')
kosdaq = fdr.StockListing('KOSDAQ')

# 합치기
df = pd.concat([kospi, kosdaq])
df = df[['Code', 'Name']].drop_duplicates()
df.columns = ['code', 'name']

# 저장
df.to_csv("C:/Coding/data/stock_mapping.csv", index=False, encoding="utf-8-sig")
print(f"완료! {len(df)}개 종목 저장")