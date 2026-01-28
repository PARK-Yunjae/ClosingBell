import sqlite3
conn = sqlite3.connect('data/screener.db')
cursor = conn.cursor()

print('=== TOP5 현황 ===')
cursor.execute('SELECT screen_date, COUNT(*) FROM closing_top5_history WHERE screen_date >= \"2026-01-26\" GROUP BY screen_date ORDER BY screen_date DESC')
for row in cursor.fetchall():
    print(f'{row[0]}: {row[1]}건')

print('\n=== 유목민 현황 ===')
cursor.execute('SELECT study_date, COUNT(*) FROM nomad_candidates WHERE study_date >= \"2026-01-26\" GROUP BY study_date ORDER BY study_date DESC')
for row in cursor.fetchall():
    print(f'{row[0]}: {row[1]}건')

conn.close()
