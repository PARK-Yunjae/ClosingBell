"""
ClosingBell v7.0 백필 설정

v6.4 변경사항:
- TV200 조건검색 대신 거래량 TOP 방식 사용
- 거래대금 150억 이상 + 거래량 상위 150위 + 등락률 1~29%
- CCI 필터 제거, ETF/스팩 제외 제거
- 백필 = 실시간 100% 일치 가능
"""

from pathlib import Path
from dataclasses import dataclass
from typing import Optional
import os
from src.config.app_config import DATA_DIR, OHLCV_FULL_DIR, OHLCV_DIR, GLOBAL_DIR, MAPPING_FILE


@dataclass
class BackfillConfig:
    """백필 설정"""
    
    # 데이터 경로 (Windows 환경)
    ohlcv_dir: Path = OHLCV_FULL_DIR  # 3년+ 전체 데이터
    ohlcv_kiwoom_dir: Path = OHLCV_DIR  # 키움 기반 (운영용)
    stock_mapping_path: Path = MAPPING_FILE
    global_data_dir: Path = GLOBAL_DIR
    
    # 데이터 소스 선택: 'ohlcv' 또는 'kiwoom'
    data_source: str = 'ohlcv'  # 기본: C:\Coding\data\ohlcv
    
    # ============================================================
    # v6.4 새 필터 조건 (거래량 TOP 방식)
    # ============================================================
    # HTS에서 동일한 조건으로 재현 가능
    # - 거래대금: 150억 이상
    # - 거래량: 상위 150위
    # - 등락률: 1% ~ 29%
    # - CCI/ETF/스팩 제외: 없음 (점수제에서 자연 반영)
    # ============================================================
    
    min_price: int = 0              # 최소 가격 (제한 없음)
    min_trading_value: float = 150  # 최소 거래대금 (억원) - v6.4
    volume_top_n: int = 150         # 거래량 상위 N위 - v6.4 신규
    min_change_rate: float = 1.0    # 최소 등락률 (%) - v6.4
    max_change_rate: float = 29.0   # 최대 등락률 (%) - v6.4
    
    # CCI 필터 제거 (v6.4)
    use_cci_filter: bool = False    # CCI 필터 사용 여부
    min_cci: float = -9999          # 비활성화
    max_cci: float = 9999           # 비활성화
    
    # ETF/스팩 제외 제거 (v6.4)
    exclude_patterns: list = None   # 제외 패턴 (없음)
    
    # 날짜 설정
    include_today: bool = True      # True면 오늘도 백필 대상에 포함
    
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
        # v6.4: 제외 패턴 없음 (빈 리스트)
        if self.exclude_patterns is None:
            self.exclude_patterns = []
    
    def get_active_ohlcv_dir(self) -> Path:
        """현재 활성화된 OHLCV 디렉토리 반환"""
        if self.data_source in ('kiwoom', 'kis'):
            return self.ohlcv_kiwoom_dir
        return self.ohlcv_dir
    
    def get_ohlcv_files(self) -> list:
        """OHLCV 파일 목록 (활성 소스 기준)"""
        active_dir = self.get_active_ohlcv_dir()
        if not active_dir.exists():
            return []
        return list(active_dir.glob("*.csv"))
    
    def validate(self) -> tuple:
        """설정 검증
        
        Returns:
            (is_valid, errors)
        """
        errors = []
        
        active_dir = self.get_active_ohlcv_dir()
        if not active_dir.exists():
            errors.append(f"OHLCV 디렉토리 없음: {active_dir} (소스: {self.data_source})")
        
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
