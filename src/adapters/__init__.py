"""
어댑터 모듈

외부 서비스와의 통신을 담당하는 클라이언트들
"""

# 키움 REST API 클라이언트 (메인 브로커)
from src.adapters.kiwoom_rest_client import (
    KiwoomRestClient,
    get_kiwoom_client,
    get_broker_client,  # 브로커 추상화 (키움 사용)
)

# 디스코드 알림
from src.adapters.discord_notifier import (
    DiscordNotifier,
    get_discord_notifier,
)

# KIS 클라이언트 (레거시 - 제거 예정)
# 기존 코드 호환을 위해 별칭 제공
def get_kis_client():
    """KIS 클라이언트 (레거시) - 키움으로 리다이렉트"""
    import warnings
    warnings.warn(
        "get_kis_client()는 deprecated입니다. get_broker_client()를 사용하세요.",
        DeprecationWarning,
        stacklevel=2
    )
    return get_kiwoom_client()


__all__ = [
    # 키움 (메인)
    'KiwoomRestClient',
    'get_kiwoom_client',
    'get_broker_client',
    
    # 디스코드
    'DiscordNotifier',
    'get_discord_notifier',
    
    # 레거시 (호환용)
    'get_kis_client',
]
