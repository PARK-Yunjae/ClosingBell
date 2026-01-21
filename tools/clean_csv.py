"""
CSV 데이터 정리 스크립트
========================

사용법:
    python tools/clean_csv.py

기능:
    1. 지수 파일 정리 (kospi, kosdaq, nasdaq, sp500, dow)
    2. 환율 파일 정리 (usdkrw)
    3. 종목 OHLCV 파일 정리 (개별 종목)

출력 형식:
    - 지수/환율: date,open,high,low,close,volume
    - 종목: date,open,high,low,close,volume,trading_value
"""

import pandas as pd
from pathlib import Path
import logging
import sys

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


# ============================================================
# 설정
# ============================================================
GLOBAL_DIR = Path(r"C:\Coding\data\global")
OHLCV_DIR = Path(r"C:\Coding\data\ohlcv")

# 지수 파일 목록
INDEX_FILES = ['kospi.csv', 'kosdaq.csv', 'nasdaq.csv', 'sp500.csv', 'dow.csv']
CURRENCY_FILES = ['usdkrw.csv']


# ============================================================
# 지수/환율 파일 정리
# ============================================================
def clean_index_file(file_path: Path) -> bool:
    """
    지수/환율 파일 정리
    
    입력 형식 (현재):
        ,open,high,low,close,volume,prev_close,change_pct,ma5,...
        2016-06-01,1976.87,1986.76,1975.82,1982.72,502290353.0,...
    
    출력 형식:
        date,open,high,low,close,volume
        2016-06-01,1976.87,1986.76,1975.82,1982.72,502290353
    """
    try:
        # 읽기
        df = pd.read_csv(file_path, encoding='utf-8-sig')
        
        # 첫 번째 컬럼이 날짜 (Unnamed: 0 또는 빈 문자열)
        first_col = df.columns[0]
        if first_col in ['', 'Unnamed: 0']:
            df = df.rename(columns={first_col: 'date'})
        
        # 컬럼명 소문자 통일
        df.columns = df.columns.str.lower()
        
        # 중복 컬럼 제거 (첫 번째만 유지)
        df = df.loc[:, ~df.columns.duplicated()]
        
        # 필요한 컬럼만 선택
        cols = ['date', 'open', 'high', 'low', 'close', 'volume']
        available = [c for c in cols if c in df.columns]
        df = df[available]
        
        # 날짜 정렬
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')
        
        # volume이 없으면 0으로
        if 'volume' not in df.columns:
            df['volume'] = 0
        
        # 정수 변환 (가능한 경우)
        if 'volume' in df.columns:
            df['volume'] = df['volume'].fillna(0).astype(int)
        
        # 저장
        df.to_csv(file_path, index=False, encoding='utf-8-sig')
        logger.info(f"✅ {file_path.name}: {len(df)}행")
        return True
        
    except Exception as e:
        logger.error(f"❌ {file_path.name}: {e}")
        return False


# ============================================================
# 종목 OHLCV 파일 정리
# ============================================================
def clean_stock_file(file_path: Path) -> bool:
    """
    종목 OHLCV 파일 정리
    
    입력 형식 (현재):
        Date,Open,High,Low,Close,Volume,Change,TradingValue,Marcap,Shares
        2020-08-06,201600,262000,201600,262000,75906,,19689441200.0,...
    
    출력 형식:
        date,open,high,low,close,volume,trading_value
        2020-08-06,201600,262000,201600,262000,75906,19689441200
    """
    try:
        # 읽기
        df = pd.read_csv(file_path, encoding='utf-8-sig')
        
        # 컬럼명 소문자 통일
        df.columns = df.columns.str.lower()
        
        # 컬럼명 매핑
        column_map = {
            'tradingvalue': 'trading_value',
            'trading_value': 'trading_value',
            '거래대금': 'trading_value',
        }
        df = df.rename(columns=column_map)
        
        # 첫 번째 컬럼이 날짜인 경우
        first_col = df.columns[0]
        if first_col in ['', 'Unnamed: 0']:
            df = df.rename(columns={first_col: 'date'})
        
        # 필요한 컬럼만 선택 (A안: OHLCV만)
        cols = ['date', 'open', 'high', 'low', 'close', 'volume']
        available = [c for c in cols if c in df.columns]
        df = df[available]
        
        # 날짜 정렬
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')
        
        # 정수 변환
        int_cols = ['open', 'high', 'low', 'close', 'volume']
        for col in int_cols:
            if col in df.columns:
                df[col] = df[col].fillna(0).astype(int)
        
        # 저장
        df.to_csv(file_path, index=False, encoding='utf-8-sig')
        return True
        
    except Exception as e:
        logger.error(f"❌ {file_path.name}: {e}")
        return False


# ============================================================
# 메인
# ============================================================
def clean_global_data():
    """글로벌 데이터 (지수/환율) 정리"""
    logger.info("\n📊 글로벌 데이터 정리")
    logger.info("=" * 40)
    
    if not GLOBAL_DIR.exists():
        logger.error(f"디렉토리 없음: {GLOBAL_DIR}")
        return
    
    # 지수 파일
    for filename in INDEX_FILES:
        file_path = GLOBAL_DIR / filename
        if file_path.exists():
            clean_index_file(file_path)
        else:
            logger.warning(f"⏭️ {filename} 없음")
    
    # 환율 파일
    for filename in CURRENCY_FILES:
        file_path = GLOBAL_DIR / filename
        if file_path.exists():
            clean_index_file(file_path)
        else:
            logger.warning(f"⏭️ {filename} 없음")


def clean_ohlcv_data():
    """종목 OHLCV 데이터 정리"""
    logger.info("\n📈 종목 OHLCV 정리")
    logger.info("=" * 40)
    
    if not OHLCV_DIR.exists():
        logger.error(f"디렉토리 없음: {OHLCV_DIR}")
        return
    
    files = list(OHLCV_DIR.glob("*.csv"))
    logger.info(f"총 {len(files)}개 파일")
    
    success = 0
    for i, file_path in enumerate(files, 1):
        if clean_stock_file(file_path):
            success += 1
        
        # 진행률 (100개마다)
        if i % 100 == 0:
            logger.info(f"  진행: {i}/{len(files)}")
    
    logger.info(f"\n✅ 완료: {success}/{len(files)}")


def main():
    """메인 함수"""
    logger.info("🧹 CSV 데이터 정리 시작")
    logger.info("=" * 50)
    
    # 명령행 인자 처리
    if len(sys.argv) > 1:
        if sys.argv[1] == '--global':
            clean_global_data()
        elif sys.argv[1] == '--ohlcv':
            clean_ohlcv_data()
        else:
            logger.info("사용법: python clean_csv.py [--global|--ohlcv]")
            logger.info("  --global: 지수/환율 파일만")
            logger.info("  --ohlcv:  종목 파일만")
            logger.info("  (인자 없음): 전체")
    else:
        # 전체 정리
        clean_global_data()
        clean_ohlcv_data()
    
    logger.info("\n🎉 정리 완료!")


if __name__ == "__main__":
    main()
