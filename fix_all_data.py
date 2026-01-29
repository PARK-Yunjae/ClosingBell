"""
ClosingBell 데이터 수정 통합 스크립트
======================================

1. 오늘자 유목민 후보 재수집 (기존 10개 → 40개+)
2. TOP5 업종 데이터 백필 (2026-01-27 이전)
3. news_count 동기화

실행:
    python fix_all_data.py
"""

import sqlite3
import logging
from pathlib import Path
from datetime import date
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
logger = logging.getLogger(__name__)

# 경로 설정
DB_PATH = Path(__file__).parent / 'data' / 'screener.db'
OHLCV_DIR = Path("C:/Coding/data/ohlcv")
STOCK_MAPPING_PATH = Path("C:/Coding/data/stock_mapping.csv")

# 상수
LIMIT_UP_THRESHOLD = 29.5
VOLUME_EXPLOSION_THRESHOLD = 10_000_000

EXCLUDE_PATTERNS = [
    'KODEX', 'TIGER', 'KBSTAR', 'ARIRANG', 'HANARO',
    'SOL', 'KOSEF', 'KINDEX', 'SMART', 'ACE', 'TIMEFOLIO',
    'ETF', 'ETN', '인버스', '레버리지', '선물', '스팩',
]


def load_stock_mapping():
    """종목 매핑 로드"""
    mapping = {}
    sector_mapping = {}
    
    if STOCK_MAPPING_PATH.exists():
        try:
            df = pd.read_csv(STOCK_MAPPING_PATH, dtype={'code': str})
            for _, row in df.iterrows():
                code = str(row['code']).zfill(6)
                mapping[code] = row.get('name', code)
                if 'sector' in df.columns:
                    sector_mapping[code] = row.get('sector', '')
        except Exception as e:
            logger.warning(f"stock_mapping.csv 로드 실패: {e}")
    
    return mapping, sector_mapping


def fix_nomad_candidates_today():
    """오늘자 유목민 후보 재수집 - 이미 있으면 스킵"""
    logger.info("=" * 60)
    logger.info("📚 오늘자 유목민 후보 확인")
    logger.info("=" * 60)
    
    today_str = date.today().isoformat()
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. 기존 데이터 개수 확인
    cursor.execute("SELECT COUNT(*) as cnt FROM nomad_candidates WHERE study_date = ?", (today_str,))
    existing = cursor.fetchone()['cnt']
    
    # 이미 충분한 데이터가 있으면 스킵
    if existing >= 30:
        logger.info(f"오늘({today_str}) 이미 {existing}개 있음 → 스킵")
        logger.info(f"재수집하려면: python main.py --run-nomad --force")
        conn.close()
        return {'old': existing, 'new': existing, 'skipped': True}
    
    # 데이터가 적으면 삭제 후 재수집
    if existing > 0:
        logger.info(f"기존 {today_str} 데이터: {existing}개 (부족) → 삭제 후 재수집")
        cursor.execute("DELETE FROM nomad_candidates WHERE study_date = ?", (today_str,))
        cursor.execute("DELETE FROM nomad_news WHERE study_date = ?", (today_str,))
        conn.commit()
        logger.info(f"기존 데이터 삭제 완료")
    else:
        logger.info(f"오늘({today_str}) 데이터 없음 → 수집")
    
    # 2. 종목 매핑 로드
    stock_mapping, sector_mapping = load_stock_mapping()
    logger.info(f"종목 매핑: {len(stock_mapping)}개")
    
    # 4. OHLCV 폴더 스캔
    if not OHLCV_DIR.exists():
        logger.error(f"OHLCV 폴더 없음: {OHLCV_DIR}")
        conn.close()
        return {'old': existing, 'new': 0}
    
    csv_files = list(OHLCV_DIR.glob("*.csv"))
    logger.info(f"CSV 파일: {len(csv_files)}개 스캔")
    
    candidates = []
    limit_up_count = 0
    volume_count = 0
    
    for csv_file in csv_files:
        try:
            stock_code = csv_file.stem
            stock_name = stock_mapping.get(stock_code, stock_code)
            
            # ETF 제외
            skip = False
            for pattern in EXCLUDE_PATTERNS:
                if pattern.lower() in stock_name.lower():
                    skip = True
                    break
            if skip:
                continue
            
            # CSV 읽기
            df = pd.read_csv(csv_file)
            df.columns = df.columns.str.lower()
            
            if 'date' not in df.columns:
                if 'unnamed: 0' in df.columns:
                    df = df.rename(columns={'unnamed: 0': 'date'})
                else:
                    continue
            
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
            today_df = df[df['date'] == today_str]
            
            if today_df.empty:
                continue
            
            today_row = today_df.iloc[-1]
            volume = int(today_row.get('volume', 0))
            close = int(today_row.get('close', 0))
            
            # 전일 데이터
            prev_df = df[df['date'] < today_str]
            if prev_df.empty:
                continue
            
            prev_row = prev_df.iloc[-1]
            prev_close = int(prev_row.get('close', 0))
            
            if prev_close == 0:
                continue
            
            change_rate = ((close - prev_close) / prev_close) * 100
            trading_value = (close * volume) / 100_000_000
            
            is_limit_up = change_rate >= LIMIT_UP_THRESHOLD
            is_volume_explosion = volume >= VOLUME_EXPLOSION_THRESHOLD
            
            if not (is_limit_up or is_volume_explosion):
                continue
            
            if is_limit_up and is_volume_explosion:
                reason = '상한가+거래량'
            elif is_limit_up:
                reason = '상한가'
            else:
                reason = '거래량천만'
            
            candidates.append({
                'study_date': today_str,
                'stock_code': stock_code,
                'stock_name': stock_name,
                'reason_flag': reason,
                'close_price': close,
                'change_rate': round(change_rate, 2),
                'volume': volume,
                'trading_value': round(trading_value, 2),
                'sector': sector_mapping.get(stock_code, ''),
                'data_source': 'fix_script',
            })
            
            if is_limit_up:
                limit_up_count += 1
            if is_volume_explosion:
                volume_count += 1
                
        except Exception as e:
            continue
    
    # 5. DB 저장
    saved = 0
    for c in candidates:
        try:
            cursor.execute("""
                INSERT INTO nomad_candidates 
                (study_date, stock_code, stock_name, reason_flag, close_price, change_rate, volume, trading_value, sector, data_source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (c['study_date'], c['stock_code'], c['stock_name'], c['reason_flag'], 
                  c['close_price'], c['change_rate'], c['volume'], c['trading_value'], 
                  c['sector'], c['data_source']))
            saved += 1
        except Exception as e:
            pass
    
    conn.commit()
    conn.close()
    
    logger.info(f"✅ 재수집 완료: 상한가 {limit_up_count}, 거래량천만 {volume_count}, 총 {saved}개 저장")
    
    return {'old': existing, 'new': saved, 'limit_up': limit_up_count, 'volume': volume_count}


def fix_top5_sectors():
    """TOP5 업종 데이터 백필"""
    logger.info("=" * 60)
    logger.info("📊 TOP5 업종 데이터 백필")
    logger.info("=" * 60)
    
    _, sector_mapping = load_stock_mapping()
    logger.info(f"업종 매핑: {len(sector_mapping)}개")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 업종이 없는 TOP5 조회
    cursor.execute("""
        SELECT id, stock_code, stock_name, screen_date
        FROM closing_top5_history
        WHERE sector IS NULL OR sector = ''
    """)
    missing_sectors = cursor.fetchall()
    
    logger.info(f"업종 누락: {len(missing_sectors)}개")
    
    updated = 0
    for row in missing_sectors:
        sector = sector_mapping.get(row['stock_code'], '')
        if sector:
            cursor.execute("""
                UPDATE closing_top5_history
                SET sector = ?
                WHERE id = ?
            """, (sector, row['id']))
            updated += 1
    
    conn.commit()
    
    # 결과 확인
    cursor.execute("""
        SELECT COUNT(*) as cnt FROM closing_top5_history WHERE sector IS NULL OR sector = ''
    """)
    still_missing = cursor.fetchone()['cnt']
    
    conn.close()
    
    logger.info(f"✅ 업종 백필 완료: {updated}개 업데이트, {still_missing}개 여전히 누락")
    
    return {'updated': updated, 'still_missing': still_missing}


def fix_news_count():
    """news_count 동기화"""
    logger.info("=" * 60)
    logger.info("📰 news_count 동기화")
    logger.info("=" * 60)
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # nomad_news에서 실제 개수 조회
    cursor.execute("""
        SELECT study_date, stock_code, COUNT(*) as cnt
        FROM nomad_news
        GROUP BY study_date, stock_code
    """)
    news_counts = {(r['study_date'], r['stock_code']): r['cnt'] for r in cursor.fetchall()}
    
    # nomad_candidates 업데이트
    cursor.execute("SELECT id, study_date, stock_code FROM nomad_candidates")
    candidates = cursor.fetchall()
    
    updated = 0
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
    
    conn.commit()
    conn.close()
    
    logger.info(f"✅ news_count 동기화 완료: {updated}개 업데이트")
    
    return {'updated': updated}


def verify_all():
    """전체 데이터 검증"""
    logger.info("=" * 60)
    logger.info("🔍 전체 데이터 검증")
    logger.info("=" * 60)
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 유목민 후보 날짜별 카운트
    cursor.execute("""
        SELECT study_date, COUNT(*) as cnt
        FROM nomad_candidates
        GROUP BY study_date
        ORDER BY study_date DESC
        LIMIT 7
    """)
    nomad_stats = cursor.fetchall()
    
    print("\n📚 유목민 후보 (최근 7일):")
    for r in nomad_stats:
        print(f"  {r['study_date']} | {r['cnt']}개")
    
    # TOP5 업종 상태
    cursor.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN sector IS NOT NULL AND sector != '' THEN 1 ELSE 0 END) as with_sector
        FROM closing_top5_history
    """)
    top5_stats = cursor.fetchone()
    
    print(f"\n📊 TOP5 업종 상태:")
    print(f"  전체: {top5_stats['total']}개")
    print(f"  업종 있음: {top5_stats['with_sector']}개")
    print(f"  업종 없음: {top5_stats['total'] - top5_stats['with_sector']}개")
    
    # news_count 상태
    cursor.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN news_count > 0 THEN 1 ELSE 0 END) as with_news
        FROM nomad_candidates
    """)
    news_stats = cursor.fetchone()
    
    print(f"\n📰 뉴스 상태:")
    print(f"  전체: {news_stats['total']}개")
    print(f"  뉴스 있음: {news_stats['with_news']}개")
    
    conn.close()
    
    return True


def main():
    print("=" * 60)
    print("🔧 ClosingBell 데이터 수정 시작")
    print("=" * 60)
    
    # 1. 오늘자 유목민 재수집
    nomad_result = fix_nomad_candidates_today()
    
    # 2. TOP5 업종 백필
    sector_result = fix_top5_sectors()
    
    # 3. news_count 동기화
    news_result = fix_news_count()
    
    # 4. 검증
    verify_all()
    
    print("\n" + "=" * 60)
    print("✅ 모든 수정 완료!")
    print("=" * 60)
    print(f"유목민 재수집: {nomad_result['old']}개 → {nomad_result['new']}개")
    print(f"TOP5 업종 백필: {sector_result['updated']}개 업데이트")
    print(f"news_count 동기화: {news_result['updated']}개 업데이트")


if __name__ == "__main__":
    main()
