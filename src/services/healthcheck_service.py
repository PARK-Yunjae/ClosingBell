"""
Healthcheck service for external integrations.
"""

import os
import logging
from dataclasses import dataclass
from typing import List, Tuple

from src.config.settings import settings
from src.services.http_utils import request_with_retry, redact_url, mask_text

logger = logging.getLogger(__name__)


@dataclass
class HealthcheckItem:
    name: str
    status: str  # OK / WARN / FAIL
    message: str


def run_healthcheck() -> Tuple[List[HealthcheckItem], bool]:
    results: List[HealthcheckItem] = []

    dashboard_only = os.getenv("DASHBOARD_ONLY", "").lower() == "true"

    # Kiwoom
    if dashboard_only:
        results.append(HealthcheckItem("Kiwoom", "WARN", "DASHBOARD_ONLY"))
    elif not settings.kiwoom.app_key or not settings.kiwoom.secret_key:
        results.append(HealthcheckItem("Kiwoom", "WARN", "키 누락"))
    else:
        try:
            from src.adapters.kiwoom_rest_client import get_kiwoom_client
            client = get_kiwoom_client()
            token = None
            if hasattr(client, "get_access_token"):
                token = client.get_access_token()
            elif hasattr(client, "_get_token"):
                token = client._get_token()
            if token:
                results.append(HealthcheckItem("Kiwoom", "OK", "토큰 발급 성공"))
            else:
                results.append(HealthcheckItem("Kiwoom", "WARN", "토큰 응답 없음"))
        except Exception as e:
            results.append(HealthcheckItem("Kiwoom", "FAIL", mask_text(str(e))[:120]))

    # DART
    dart_key = os.getenv("DART_API_KEY", "")
    if not dart_key:
        results.append(HealthcheckItem("DART", "WARN", "API 키 누락"))
    else:
        try:
            from src.services.dart_service import get_dart_service
            dart = get_dart_service()
            data = dart.get_recent_disclosures("005930", days=1, limit=1)
            if data is not None:
                results.append(HealthcheckItem("DART", "OK", "응답 확인"))
            else:
                results.append(HealthcheckItem("DART", "WARN", "응답 없음/데이터 없음"))
        except Exception as e:
            results.append(HealthcheckItem("DART", "FAIL", mask_text(str(e))[:120]))

    # Naver News
    naver_id = os.getenv("NaverAPI_Client_ID", "")
    naver_secret = os.getenv("NaverAPI_Client_Secret", "")
    if not naver_id or not naver_secret:
        results.append(HealthcheckItem("News", "WARN", "네이버 API 키 누락"))
    else:
        try:
            from src.services.news_service import search_naver_news
            items = search_naver_news("삼성전자", display=1, sort="date")
            results.append(HealthcheckItem("News", "OK", f"items={len(items)}"))
        except Exception as e:
            results.append(HealthcheckItem("News", "FAIL", mask_text(str(e))[:120]))

    # Discord
    if not settings.discord.enabled:
        results.append(HealthcheckItem("Discord", "WARN", "DISCORD_ENABLED=false"))
    elif not settings.discord.webhook_url:
        results.append(HealthcheckItem("Discord", "WARN", "웹훅 URL 누락"))
    else:
        try:
            resp = request_with_retry(
                "GET",
                settings.discord.webhook_url,
                timeout=5,
                max_retries=1,
                backoff=1.0,
                logger=logger,
                context=f"Discord Healthcheck {redact_url(settings.discord.webhook_url)}",
            )
            if resp is None:
                results.append(HealthcheckItem("Discord", "FAIL", "응답 없음"))
            elif resp.status_code in (200, 204, 405):
                results.append(HealthcheckItem("Discord", "OK", f"HTTP {resp.status_code}"))
            elif resp.status_code in (401, 403):
                results.append(HealthcheckItem("Discord", "WARN", f"HTTP {resp.status_code}"))
            else:
                results.append(HealthcheckItem("Discord", "WARN", f"HTTP {resp.status_code}"))
        except Exception as e:
            results.append(HealthcheckItem("Discord", "FAIL", mask_text(str(e))[:120]))

    # AI (Gemini)
    ai_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not ai_key:
        results.append(HealthcheckItem("AI", "WARN", "API 키 누락"))
    else:
        try:
            from google import genai
            client = genai.Client(api_key=ai_key)
            response = client.models.generate_content(
                model=settings.ai.model,
                contents="healthcheck",
                config={
                    "max_output_tokens": 16,
                    "temperature": 0.0,
                },
            )
            if getattr(response, "text", ""):
                results.append(HealthcheckItem("AI", "OK", "응답 확인"))
            else:
                results.append(HealthcheckItem("AI", "WARN", "응답 없음"))
        except ImportError:
            results.append(HealthcheckItem("AI", "WARN", "google-genai 미설치"))
        except Exception as e:
            results.append(HealthcheckItem("AI", "FAIL", mask_text(str(e))[:120]))

    ok = not any(r.status == "FAIL" for r in results)
    return results, ok
