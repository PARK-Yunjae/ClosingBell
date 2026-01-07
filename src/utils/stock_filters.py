"""
종목 필터링 유틸리티

책임:
- 인버스/레버리지/ETF/ETN/스팩/리츠 등 매매 대상 제외 종목 필터링
- 조건검색 결과의 2차 필터링
- 필터링 통계 로깅
"""

import os
import logging
from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass

from src.domain.models import StockInfo

logger = logging.getLogger(__name__)


# ============================================================
# 제외 키워드 (이름 기반 필터링)
# ============================================================

# 환경 변수에서 추가 키워드를 가져오거나 기본값 사용
_env_keywords = os.getenv("EXCLUDE_KEYWORDS", "")
_custom_keywords = [k.strip() for k in _env_keywords.split(",") if k.strip()]

EXCLUDE_KEYWORDS: List[str] = [
    # 인버스/레버리지
    "인버스",
    "레버리지",
    "레버",
    "2X",
    "2x",
    "3X",
    "3x",
    "-2X",
    "-2x",
    "곱버스",  # 인버스2X 별칭
    
    # ETF/ETN
    "ETF",
    "ETN",
    "KODEX",
    "TIGER",
    "KBSTAR",
    "ARIRANG",
    "HANARO",
    "KOSEF",
    "KINDEX",
    "SOL",
    "ACE",
    "RISE",
    "PLUS",
    "TIMEFOLIO",
    "WOORI",
    "BNK",
    "FOCUS",
    "VITA",
    
    # 선물/파생
    "선물",
    "파생",
    
    # 스팩/리츠
    "스팩",
    "SPAC",
    "리츠",
    "REIT",
    "REITs",
    
    # 우선주 (다양한 패턴)
    "우선주",
    "우B",
    "우C",
    "(1우)",
    "(2우)",
    "(1우B)",
    "(2우B)",
    "1우",
    "2우",
    "3우",
    "우)",  # "삼성전자우)" 패턴
    
    # 전환사채/신주인수권
    "전환",
    "CB",
    "BW",
    "신주인수권",
    "전환우선주",
    
    # 기타 제외 대상
    "채권",
    "채권형",
] + _custom_keywords


# ============================================================
# 종목코드 기반 제외 (ETF/ETN 코드 범위)
# ============================================================

# ETF 코드 범위 (일반적으로)
# KOSPI ETF: 코드가 대체로 1로 시작하지 않고 특정 범위
# KODEX/TIGER 등은 이름으로 제외하지만, 코드로도 추가 필터링

# ETN 코드 패턴
# 보통 Q로 시작하거나 특정 숫자 대역

EXCLUDED_CODE_PATTERNS = [
    # 코넥스 (K로 시작)
    # 스팩은 종목명으로 필터링
]


@dataclass
class FilterResult:
    """필터링 결과 통계"""
    raw_count: int
    eligible_count: int
    excluded_count: int
    reason_counts: Dict[str, int]
    
    def __str__(self) -> str:
        reasons = ", ".join(f"{k}:{v}" for k, v in self.reason_counts.items())
        return (
            f"필터링 결과: raw={self.raw_count}, "
            f"eligible={self.eligible_count}, "
            f"excluded={self.excluded_count} "
            f"({reasons})"
        )


def is_eligible_universe_stock(
    code: str,
    name: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    매매 대상 적격 종목 여부 확인
    
    Args:
        code: 종목코드 (6자리)
        name: 종목명 (None이면 이름 기반 필터링 스킵)
        
    Returns:
        (eligible, reason) 튜플
        - eligible: True면 적격, False면 제외
        - reason: 제외 사유 ("" if eligible)
    """
    code = code.zfill(6)
    
    # 1. 이름 기반 제외 (가장 효과적)
    if name:
        name_upper = name.upper()
        for keyword in EXCLUDE_KEYWORDS:
            keyword_upper = keyword.upper()
            if keyword_upper in name_upper:
                return (False, f"이름포함:{keyword}")
    
    # 2. 코드 기반 제외
    # ETF 코드 범위 체크 (5로 시작하는 6자리는 ETF인 경우 많음)
    # 하지만 정확한 구분은 상품유형 API가 필요
    
    # 스팩 코드 패턴 (4자리 숫자 + 스팩번호)
    # 예: 123456 형태지만 종목명으로 구분하는 게 더 정확
    
    # 3. 특수 코드 패턴
    for pattern in EXCLUDED_CODE_PATTERNS:
        if code.startswith(pattern):
            return (False, f"코드패턴:{pattern}")
    
    return (True, "")


def filter_universe_stocks(
    stocks: List[StockInfo],
    log_details: bool = True,
) -> Tuple[List[StockInfo], FilterResult]:
    """
    종목 리스트에서 매매 대상만 필터링
    
    Args:
        stocks: StockInfo 리스트
        log_details: 상세 로그 출력 여부
        
    Returns:
        (eligible_stocks, filter_result) 튜플
    """
    eligible_stocks: List[StockInfo] = []
    excluded_stocks: List[Tuple[StockInfo, str]] = []
    reason_counts: Dict[str, int] = {}
    
    for stock in stocks:
        eligible, reason = is_eligible_universe_stock(stock.code, stock.name)
        
        if eligible:
            eligible_stocks.append(stock)
        else:
            excluded_stocks.append((stock, reason))
            
            # 사유 집계
            reason_key = reason.split(":")[0] if ":" in reason else reason
            reason_counts[reason_key] = reason_counts.get(reason_key, 0) + 1
    
    result = FilterResult(
        raw_count=len(stocks),
        eligible_count=len(eligible_stocks),
        excluded_count=len(excluded_stocks),
        reason_counts=reason_counts,
    )
    
    # 로깅
    if log_details:
        logger.info(str(result))
        
        if excluded_stocks:
            # 제외된 종목 샘플 출력 (최대 10개)
            sample_excluded = excluded_stocks[:10]
            excluded_info = ", ".join(
                f"{s.name}({s.code}):{r}" for s, r in sample_excluded
            )
            logger.debug(f"제외 샘플: {excluded_info}")
    
    return eligible_stocks, result


def get_exclusion_stats(
    stocks: List[StockInfo],
) -> Dict[str, List[StockInfo]]:
    """
    제외 사유별 종목 분류 (디버깅용)
    
    Returns:
        사유별 종목 리스트 딕셔너리
    """
    stats: Dict[str, List[StockInfo]] = {
        "eligible": [],
        "인버스/레버": [],
        "ETF/ETN": [],
        "스팩/리츠": [],
        "기타": [],
    }
    
    inverse_keywords = ["인버스", "레버리지", "레버", "2X", "2x", "3X", "3x", "곱버스"]
    etf_keywords = ["ETF", "ETN", "KODEX", "TIGER", "KBSTAR", "ARIRANG", "HANARO", "KOSEF", "KINDEX", "SOL", "ACE", "RISE", "PLUS"]
    spac_keywords = ["스팩", "SPAC", "리츠", "REIT"]
    
    for stock in stocks:
        eligible, reason = is_eligible_universe_stock(stock.code, stock.name)
        
        if eligible:
            stats["eligible"].append(stock)
        else:
            # 사유 분류
            name_upper = (stock.name or "").upper()
            
            if any(kw.upper() in name_upper for kw in inverse_keywords):
                stats["인버스/레버"].append(stock)
            elif any(kw.upper() in name_upper for kw in etf_keywords):
                stats["ETF/ETN"].append(stock)
            elif any(kw.upper() in name_upper for kw in spac_keywords):
                stats["스팩/리츠"].append(stock)
            else:
                stats["기타"].append(stock)
    
    return stats


if __name__ == "__main__":
    # 테스트
    logging.basicConfig(level=logging.DEBUG)
    
    test_stocks = [
        StockInfo("005930", "삼성전자", "KOSPI"),
        StockInfo("000660", "SK하이닉스", "KOSPI"),
        StockInfo("252670", "KODEX 200선물인버스2X", "KOSPI"),
        StockInfo("122630", "KODEX 레버리지", "KOSPI"),
        StockInfo("114800", "KODEX 인버스", "KOSPI"),
        StockInfo("069500", "KODEX 200", "KOSPI"),
        StockInfo("278530", "삼성스팩2호", "KOSPI"),
        StockInfo("395400", "SK리츠", "KOSPI"),
        StockInfo("035720", "카카오", "KOSPI"),
    ]
    
    print("=== 개별 필터 테스트 ===")
    for stock in test_stocks:
        eligible, reason = is_eligible_universe_stock(stock.code, stock.name)
        status = "✓" if eligible else "✗"
        print(f"{status} {stock.name} ({stock.code}): {reason or 'OK'}")
    
    print("\n=== 일괄 필터 테스트 ===")
    eligible, result = filter_universe_stocks(test_stocks)
    print(result)
    print(f"적격 종목: {[s.name for s in eligible]}")
    
    print("\n=== 통계 테스트 ===")
    stats = get_exclusion_stats(test_stocks)
    for category, items in stats.items():
        print(f"{category}: {len(items)}개 - {[s.name for s in items]}")
