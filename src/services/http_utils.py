"""
HTTP helper utilities with retry, timeout, and safe logging.
"""

import re
import time
from typing import Optional, Dict, Any
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import requests
from requests import Response
import urllib.request


def redact_url(url: str) -> str:
    """Redact query values and webhook tokens in URLs."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        path = parsed.path

        if "/api/webhooks/" in path:
            prefix = path.split("/api/webhooks/")[0]
            path = f"{prefix}/api/webhooks/<REDACTED>"

        query = parse_qsl(parsed.query, keep_blank_values=True)
        if query:
            redacted = [(k, "<REDACTED>") for k, _ in query]
            new_query = urlencode(redacted)
        else:
            new_query = ""

        return urlunparse(parsed._replace(path=path, query=new_query))
    except Exception:
        return "<REDACTED_URL>"


def mask_text(text: str) -> str:
    """Mask sensitive tokens in error messages."""
    if not text:
        return ""
    masked = text
    masked = re.sub(
        r"https://discord\.com/api/webhooks/\S+",
        "https://discord.com/api/webhooks/<REDACTED>",
        masked,
    )
    masked = re.sub(
        r"(api[_-]?key|token|secret|webhook)\s*=\s*([^\s&]+)",
        r"\1=<REDACTED>",
        masked,
        flags=re.IGNORECASE,
    )
    return masked


def request_with_retry(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
    timeout: int = 10,
    max_retries: int = 2,
    backoff: float = 1.0,
    logger=None,
    context: str = "",
    retry_statuses=(429, 500, 502, 503, 504),
) -> Optional[Response]:
    """Requests wrapper with exponential backoff and safe logging."""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json,
                timeout=timeout,
            )
            if response.status_code in retry_statuses and attempt < max_retries:
                wait = backoff * (2 ** attempt)
                if logger:
                    logger.warning(
                        f"{context} 재시도 {attempt + 1}/{max_retries} "
                        f"(HTTP {response.status_code}) - {wait:.1f}s 대기"
                    )
                time.sleep(wait)
                continue
            return response
        except requests.exceptions.RequestException as exc:
            last_error = exc
            if attempt < max_retries:
                wait = backoff * (2 ** attempt)
                if logger:
                    logger.warning(
                        f"{context} 네트워크 오류, {wait:.1f}s 후 재시도: {mask_text(str(exc))}"
                    )
                time.sleep(wait)
                continue

    if logger and last_error:
        logger.error(f"{context} 요청 실패: {mask_text(str(last_error))}")
    return None


def urlopen_with_retry(
    req,
    timeout: int = 10,
    max_retries: int = 2,
    backoff: float = 1.0,
    logger=None,
    context: str = "",
):
    """urllib wrapper with exponential backoff and safe logging."""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                wait = backoff * (2 ** attempt)
                if logger:
                    logger.warning(
                        f"{context} 네트워크 오류, {wait:.1f}s 후 재시도: {mask_text(str(exc))}"
                    )
                time.sleep(wait)
                continue

    if logger and last_error:
        logger.error(f"{context} 요청 실패: {mask_text(str(last_error))}")
    return None
