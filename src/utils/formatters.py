"""
공통 포맷 유틸리티

중복 제거:
- format_market_cap: ai_pipeline, ai_service, discord_embed_builder
- format_trading_value: ai_pipeline, discord_embed_builder
- format_volume: discord_embed_builder
- get_grade_value: discord_embed_builder, top5_pipeline
"""


def format_market_cap(value: float) -> str:
    """시가총액 포맷 (억원 → 조/억 표시)"""
    if not value or value <= 0:
        return "-"
    if value >= 10000:
        return f"{value / 10000:.1f}조"
    return f"{value:,.0f}억"


def format_trading_value(value: float) -> str:
    """거래대금 포맷 (억원 → 조/억 표시)"""
    if not value:
        return "-"
    if value >= 1000:
        return f"{value / 1000:.1f}조"
    return f"{value:,.0f}억"


def format_volume(value: int) -> str:
    """거래량 포맷"""
    if not value:
        return "-"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}K"
    return f"{value:,}"


def get_grade_value(grade) -> str:
    """등급 값 추출 (Enum 또는 문자열 호환)

    처리 케이스:
    - StockGrade.S (Enum 객체) → 'S'
    - 'StockGrade.S' (문자열) → 'S'
    - 'S' (문자열) → 'S'
    - None → '-'
    """
    if grade is None:
        return "-"

    # Enum인 경우
    if hasattr(grade, 'value'):
        val = grade.value
        if hasattr(val, 'value'):
            val = str(val)
        s = str(val)
    else:
        s = str(grade)

    # 'StockGrade.S' → 'S'
    if '.' in s:
        s = s.split('.')[-1]

    return s if s else "-"
