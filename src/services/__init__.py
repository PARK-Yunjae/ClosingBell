"""
ClosingBell 서비스 패키지 (v9.0)

주의:
- 대시보드(읽기 전용) 환경에서는 일부 백필 의존 모듈이 필요하지 않습니다.
"""

import os

_DASHBOARD_ONLY = os.getenv("DASHBOARD_ONLY", "").lower() == "true"
_STREAMLIT = os.getenv("STREAMLIT_SERVER_HEADLESS", "").lower() == "true"

# v6.0: 백필 서비스 export
try:
    from src.services.backfill import (  # noqa: F401
        HistoricalBackfillService,
        backfill_top5,
        backfill_nomad,
        auto_fill_missing,
    )
except Exception:
    # 대시보드/Streamlit 환경에서는 백필 모듈 로드 실패를 무시
    if not (_DASHBOARD_ONLY or _STREAMLIT):
        raise
