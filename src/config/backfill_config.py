"""
ClosingBell v6.0 백필 설정

백테스트 코드의 데이터 경로 및 설정 통합
"""

from pathlib import Path
from dataclasses import dataclass
from typing import Optional
import os


@dataclass
class BackfillConfig:
    """백필 설정"""
    
    # 데이터 경로 (Windows 환경)
    ohlcv_dir: Path = Path(r"C:\Coding\data\ohlcv")
    stock_mapping_path: Path = Path(r"C:\Coding\data\stock_mapping.csv")
    global_data_dir: Path = Path(r"C:\Coding\data\global")
    
    # 필터 설정
    min_price: int = 1000           # 최소 가격
    min_trading_value: float = 30   # 최소 거래대금 (억원)
    exclude_patterns: list = None   # 제외 패턴 (ETF 등)
    
    # TOP5 설정
    top5_count: int = 5             # TOP N
    tracking_days: int = 20         # 추적 일수
    
    # 유목민 설정
    limit_up_threshold: float = 29.5    # 상한가 기준 (%)
    volume_explosion_shares: int = 10_000_000  # 거래량천만 기준 (주)
    
    # 성능 설정
    num_workers: int = 10           # 멀티프로세싱 워커 수
    chunk_size: int = 100           # 청크 크기
    
    def __post_init__(self):
        if self.exclude_patterns is None:
            self.exclude_patterns = [
                'KODEX', 'TIGER', 'KBSTAR', 'ARIRANG', 'HANARO',
                'SOL', 'KOSEF', 'KINDEX', 'SMART', 'ACE', 'TIMEFOLIO',
                'ETF', 'ETN', '인버스', '레버리지', '선물', '스팩',
            ]
    
    def get_ohlcv_files(self) -> list:
        """OHLCV 파일 목록"""
        if not self.ohlcv_dir.exists():
            return []
        return list(self.ohlcv_dir.glob("*.csv"))
    
    def validate(self) -> tuple:
        """설정 검증
        
        Returns:
            (is_valid, errors)
        """
        errors = []
        
        if not self.ohlcv_dir.exists():
            errors.append(f"OHLCV 디렉토리 없음: {self.ohlcv_dir}")
        
        if not self.stock_mapping_path.exists():
            errors.append(f"종목 매핑 파일 없음: {self.stock_mapping_path}")
        
        if not self.global_data_dir.exists():
            errors.append(f"글로벌 데이터 디렉토리 없음: {self.global_data_dir}")
        
        return len(errors) == 0, errors


# 기본 설정 인스턴스
backfill_config = BackfillConfig()


def get_backfill_config() -> BackfillConfig:
    """백필 설정 반환"""
    return backfill_config
