import sqlite3
conn = sqlite3.connect('data/screener.db')
cursor = conn.cursor()

print('=== 26일 이후 전체 삭제 ===')

# TOP5 완전 삭제
cursor.execute('DELETE FROM closing_top5_history WHERE screen_date >= "2026-01-26"')
print(f'closing_top5_history: {cursor.rowcount}건')

# 유목민 (이미 삭제됨 - 확인용)
cursor.execute('SELECT COUNT(*) FROM nomad_candidates WHERE study_date >= "2026-01-26"')
print(f'nomad_candidates 남은것: {cursor.fetchone()[0]}건')

conn.commit()
conn.close()
print('\n삭제 완료!')
