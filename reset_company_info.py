"""기업정보 재수집을 위한 DB 리셋 스크립트"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "screener.db"

def reset_company_info():
    """company_info_collected 플래그 리셋"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 기존 기업정보 초기화
    cursor.execute("""
        UPDATE nomad_candidates 
        SET company_info_collected = 0,
            market = NULL,
            sector = NULL,
            market_cap = NULL,
            per = NULL,
            pbr = NULL,
            eps = NULL,
            roe = NULL,
            business_summary = NULL,
            establishment_date = NULL,
            ceo_name = NULL
        WHERE company_info_collected = 1
    """)
    
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    
    print(f"✅ {affected}개 종목 기업정보 리셋 완료!")
    print("재수집: python main.py --run-company-info")

if __name__ == "__main__":
    reset_company_info()
