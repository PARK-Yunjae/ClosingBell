"""
KIS API OHLCV 수집 스크립트

정규장 기준 OHLCV 데이터 수집
- FDR(프리장 포함)과 달리 정규장 09:00~15:30 기준
- 실시간 스크리닝과 동일한 데이터 소스

사용법:
    python scripts/collect_kis_ohlcv.py              # 전체 종목 수집
    python scripts/collect_kis_ohlcv.py --days 30   # 최근 30일만
    python scripts/collect_kis_ohlcv.py --code 005930  # 특정 종목만
"""

import os
import sys
import time
import logging
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional, Dict

import pandas as pd

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.adapters.kis_client import KISClient
from src.config.backfill_config import get_backfill_config

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class KISOHLCVCollector:
    """KIS API OHLCV 수집기"""
    
    # API 제한: 초당 20회
    API_RATE_LIMIT = 20
    API_DELAY = 1.0 / API_RATE_LIMIT + 0.01  # 0.06초
    
    # 한 번에 조회 가능한 최대 일수
    MAX_DAYS_PER_REQUEST = 100
    
    def __init__(self, output_dir: Optional[Path] = None):
        """
        Args:
            output_dir: OHLCV 저장 경로 (기본: C:\Coding\data\ohlcv_kis)
        """
        self.client = KISClient()
        self.config = get_backfill_config()
        
        # 출력 디렉토리 설정
        if output_dir:
            self.output_dir = output_dir
        else:
            # 기본 경로: ohlcv와 같은 레벨에 ohlcv_kis 생성
            self.output_dir = self.config.ohlcv_dir.parent / "ohlcv_kis"
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"출력 디렉토리: {self.output_dir}")
        
        # 통계
        self.stats = {
            'total': 0,
            'success': 0,
            'failed': 0,
            'skipped': 0,
        }
    
    def load_stock_list(self) -> pd.DataFrame:
        """종목 목록 로드"""
        mapping_path = self.config.stock_mapping_path
        
        if not mapping_path.exists():
            raise FileNotFoundError(f"종목 매핑 파일 없음: {mapping_path}")
        
        df = pd.read_csv(mapping_path, encoding='utf-8-sig')
        
        # 컬럼명 정규화
        if 'stock_code' in df.columns:
            df = df.rename(columns={'stock_code': 'code', 'stock_name': 'name'})
        
        # 종목코드 문자열 변환
        df['code'] = df['code'].astype(str).str.zfill(6)
        
        logger.info(f"종목 목록 로드: {len(df)}개")
        return df
    
    def fetch_ohlcv(
        self, 
        stock_code: str, 
        days: int = 100,
        end_date: Optional[datetime] = None
    ) -> Optional[pd.DataFrame]:
        """
        종목의 OHLCV 데이터 조회
        
        Args:
            stock_code: 종목코드 (6자리)
            days: 조회 일수 (최대 100)
            end_date: 종료일 (기본: 오늘)
            
        Returns:
            DataFrame with columns: date, open, high, low, close, volume, trading_value
        """
        if end_date is None:
            end_date = datetime.now()
        
        start_date = end_date - timedelta(days=days + 30)  # 여유 있게
        
        endpoint = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
        tr_id = "FHKST03010100"
        
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
            "FID_INPUT_DATE_1": start_date.strftime("%Y%m%d"),
            "FID_INPUT_DATE_2": end_date.strftime("%Y%m%d"),
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "0",  # 수정주가
        }
        
        try:
            data = self.client._request("GET", endpoint, tr_id, params=params)
            output = data.get("output2", [])
            
            if not output:
                return None
            
            # DataFrame 변환
            records = []
            for item in output:
                try:
                    records.append({
                        'date': datetime.strptime(item['stck_bsop_date'], '%Y%m%d'),
                        'open': int(item.get('stck_oprc', 0)),
                        'high': int(item.get('stck_hgpr', 0)),
                        'low': int(item.get('stck_lwpr', 0)),
                        'close': int(item.get('stck_clpr', 0)),
                        'volume': int(item.get('acml_vol', 0)),
                        'trading_value': int(item.get('acml_tr_pbmn', 0)),
                    })
                except (ValueError, KeyError) as e:
                    continue
            
            if not records:
                return None
            
            df = pd.DataFrame(records)
            df = df.sort_values('date')
            
            # 최근 N일만
            df = df.tail(days)
            
            return df
            
        except Exception as e:
            logger.warning(f"[{stock_code}] 조회 실패: {e}")
            return None
    
    def save_ohlcv(self, stock_code: str, df: pd.DataFrame) -> bool:
        """
        OHLCV 데이터 저장
        
        Args:
            stock_code: 종목코드
            df: OHLCV DataFrame
            
        Returns:
            저장 성공 여부
        """
        try:
            file_path = self.output_dir / f"{stock_code}.csv"
            
            # 날짜 형식 변환
            df_save = df.copy()
            df_save['date'] = df_save['date'].dt.strftime('%Y-%m-%d')
            
            # CSV 저장
            df_save.to_csv(file_path, index=False, encoding='utf-8-sig')
            return True
            
        except Exception as e:
            logger.error(f"[{stock_code}] 저장 실패: {e}")
            return False
    
    def collect_single(self, stock_code: str, days: int = 100) -> bool:
        """단일 종목 수집"""
        df = self.fetch_ohlcv(stock_code, days=days)
        
        if df is None or df.empty:
            return False
        
        return self.save_ohlcv(stock_code, df)
    
    def collect_all(
        self, 
        days: int = 100,
        codes: Optional[List[str]] = None,
        skip_existing: bool = False
    ) -> Dict[str, int]:
        """
        전체 종목 수집
        
        Args:
            days: 조회 일수
            codes: 수집할 종목코드 목록 (None이면 전체)
            skip_existing: 기존 파일 스킵 여부
            
        Returns:
            수집 통계
        """
        # 종목 목록
        if codes:
            stock_list = pd.DataFrame({'code': codes})
        else:
            stock_list = self.load_stock_list()
        
        total = len(stock_list)
        self.stats = {'total': total, 'success': 0, 'failed': 0, 'skipped': 0}
        
        logger.info(f"수집 시작: {total}개 종목, {days}일치")
        logger.info(f"예상 소요 시간: {total * self.API_DELAY / 60:.1f}분")
        
        start_time = time.time()
        
        for idx, row in stock_list.iterrows():
            code = row['code']
            
            # 기존 파일 스킵
            if skip_existing:
                file_path = self.output_dir / f"{code}.csv"
                if file_path.exists():
                    self.stats['skipped'] += 1
                    continue
            
            # 수집
            success = self.collect_single(code, days=days)
            
            if success:
                self.stats['success'] += 1
            else:
                self.stats['failed'] += 1
            
            # 진행률 표시 (100개마다)
            processed = self.stats['success'] + self.stats['failed'] + self.stats['skipped']
            if processed % 100 == 0:
                elapsed = time.time() - start_time
                eta = (total - processed) * elapsed / max(processed, 1)
                logger.info(
                    f"진행: {processed}/{total} "
                    f"(성공: {self.stats['success']}, 실패: {self.stats['failed']}) "
                    f"예상 남은시간: {eta/60:.1f}분"
                )
            
            # Rate limiting
            time.sleep(self.API_DELAY)
        
        elapsed = time.time() - start_time
        logger.info(f"수집 완료: {elapsed/60:.1f}분 소요")
        logger.info(f"결과: 성공 {self.stats['success']}, 실패 {self.stats['failed']}, 스킵 {self.stats['skipped']}")
        
        return self.stats
    
    def update_recent(self, days: int = 5) -> Dict[str, int]:
        """
        최근 데이터만 업데이트 (기존 파일에 추가)
        
        Args:
            days: 최근 며칠치 업데이트
            
        Returns:
            업데이트 통계
        """
        stock_list = self.load_stock_list()
        total = len(stock_list)
        
        stats = {'total': total, 'updated': 0, 'failed': 0, 'no_change': 0}
        
        logger.info(f"업데이트 시작: {total}개 종목, 최근 {days}일")
        
        for idx, row in stock_list.iterrows():
            code = row['code']
            file_path = self.output_dir / f"{code}.csv"
            
            # 새 데이터 조회
            new_df = self.fetch_ohlcv(code, days=days)
            
            if new_df is None or new_df.empty:
                stats['failed'] += 1
                time.sleep(self.API_DELAY)
                continue
            
            # 기존 파일 있으면 병합
            if file_path.exists():
                try:
                    old_df = pd.read_csv(file_path, encoding='utf-8-sig')
                    old_df['date'] = pd.to_datetime(old_df['date'])
                    
                    # 병합 (중복 제거)
                    merged = pd.concat([old_df, new_df])
                    merged = merged.drop_duplicates(subset=['date'], keep='last')
                    merged = merged.sort_values('date')
                    
                    # 100일 유지
                    merged = merged.tail(100)
                    
                    new_df = merged
                except Exception as e:
                    logger.warning(f"[{code}] 기존 파일 병합 실패: {e}")
            
            # 저장
            if self.save_ohlcv(code, new_df):
                stats['updated'] += 1
            else:
                stats['failed'] += 1
            
            # 진행률 (500개마다)
            processed = stats['updated'] + stats['failed']
            if processed % 500 == 0:
                logger.info(f"진행: {processed}/{total}")
            
            time.sleep(self.API_DELAY)
        
        logger.info(f"업데이트 완료: 성공 {stats['updated']}, 실패 {stats['failed']}")
        return stats


def main():
    parser = argparse.ArgumentParser(description='KIS API OHLCV 수집')
    parser.add_argument('--days', type=int, default=100, help='수집 일수 (기본: 100)')
    parser.add_argument('--code', type=str, help='특정 종목코드만 수집')
    parser.add_argument('--update', action='store_true', help='최근 데이터만 업데이트')
    parser.add_argument('--skip-existing', action='store_true', help='기존 파일 스킵')
    parser.add_argument('--output', type=str, help='출력 디렉토리')
    
    args = parser.parse_args()
    
    # 출력 디렉토리
    output_dir = Path(args.output) if args.output else None
    
    # 수집기 생성
    collector = KISOHLCVCollector(output_dir=output_dir)
    
    if args.code:
        # 단일 종목
        logger.info(f"단일 종목 수집: {args.code}")
        success = collector.collect_single(args.code, days=args.days)
        print(f"결과: {'성공' if success else '실패'}")
        
    elif args.update:
        # 업데이트 모드
        collector.update_recent(days=args.days)
        
    else:
        # 전체 수집
        collector.collect_all(
            days=args.days,
            skip_existing=args.skip_existing
        )


if __name__ == "__main__":
    main()