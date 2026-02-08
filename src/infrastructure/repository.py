"""
repository.py - 호환성 레이어 (re-export)

실제 구현은 repo_*.py 파일에 분리됨:
- repo_screening.py: ScreeningRepository, NextDayResultRepository
- repo_top5.py: Top5HistoryRepository, Top5DailyPricesRepository
- repo_nomad.py: NomadCandidatesRepository, NomadNewsRepository
- repo_signals.py: BrokerSignalRepository, PullbackRepository
- repo_company.py: CompanyProfileRepository, TV200SnapshotRepository
"""

# --- Screening ---
from src.infrastructure.repo_screening import (  # noqa: F401
    ScreeningRepository,
    NextDayResultRepository,
    get_screening_repository,
    get_next_day_result_repository as get_next_day_repository,
)

# --- Top5 ---
from src.infrastructure.repo_top5 import (  # noqa: F401
    Top5HistoryRepository,
    Top5DailyPricesRepository,
    get_top5_history_repository,
    get_top5_daily_prices_repository as get_top5_prices_repository,
)

# --- Nomad ---
from src.infrastructure.repo_nomad import (  # noqa: F401
    NomadCandidatesRepository,
    NomadNewsRepository,
    get_nomad_candidates_repository,
    get_nomad_news_repository,
)

# --- Signals ---
from src.infrastructure.repo_signals import (  # noqa: F401
    BrokerSignalRepository,
    PullbackRepository,
    get_broker_signal_repository,
    get_pullback_repository,
)

# --- Company & TV200 ---
from src.infrastructure.repo_company import (  # noqa: F401
    CompanyProfileRepository,
    TV200SnapshotRepository,
    get_company_profile_repository,
    get_tv200_snapshot_repository,
)
