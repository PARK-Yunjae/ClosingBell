"""
어댑터 모듈

외부 서비스와의 통신을 담당하는 클라이언트들
"""

# 키움 REST API 클라이언트 (메인 브로커)
from src.adapters.kiwoom_rest_client import (
    KiwoomRestClient,
    get_kiwoom_client,
    get_broker_client,
)

# 디스코드 알림
from src.adapters.discord_notifier import (
    DiscordNotifier,
    get_discord_notifier,
)


__all__ = [
    'KiwoomRestClient',
    'get_kiwoom_client',
    'get_broker_client',
    'DiscordNotifier',
    'get_discord_notifier',
]
