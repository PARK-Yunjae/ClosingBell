import sqlite3
conn = sqlite3.connect('data/screener.db')
cursor = conn.cursor()

print('=== 26일 이후 데이터 삭제 ===')

# top5_daily_prices - 고아 레코드 삭제
cursor.execute('''
    DELETE FROM top5_daily_prices 
    WHERE top5_history_id NOT IN (SELECT id FROM closing_top5_history)
''')
print(f'top5_daily_prices: {cursor.rowcount}건')

# 유목민 삭제
cursor.execute('DELETE FROM nomad_candidates WHERE study_date >= "2026-01-26"')
print(f'nomad_candidates: {cursor.rowcount}건')

cursor.execute('DELETE FROM nomad_news WHERE study_date >= "2026-01-26"')
print(f'nomad_news: {cursor.rowcount}건')

conn.commit()
conn.close()
print('\n삭제 완료!')