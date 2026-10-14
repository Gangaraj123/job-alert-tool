"""Shared HTTP helpers: timeout + retry with backoff, used by every fetch tier."""
from __future__ import annotations

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ..config import load_config

_cfg = load_config().get("fetch", {})
TIMEOUT = _cfg.get("request_timeout_seconds", 20)
MAX_RETRIES = _cfg.get("max_retries", 3)
BACKOFF = _cfg.get("retry_backoff_seconds", 2)

_RETRYABLE = (requests.ConnectionError, requests.Timeout)


class FetchError(Exception):
    """Raised when a fetch tier fails outright for a company."""


def _retrying():
    return retry(
        reraise=True,
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=BACKOFF, max=30),
        retry=retry_if_exception_type(_RETRYABLE),
    )


@_retrying()
def http_get(url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", TIMEOUT)
    kwargs.setdefault("headers", {"User-Agent": "job-alert-tool/1.0"})
    resp = requests.get(url, **kwargs)
    resp.raise_for_status()
    return resp


@_retrying()
def http_post(url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", TIMEOUT)
    kwargs.setdefault("headers", {"User-Agent": "job-alert-tool/1.0"})
    resp = requests.post(url, **kwargs)
    resp.raise_for_status()
    return resp


def http_get_json(url: str, **kwargs) -> dict | list:
    return http_get(url, **kwargs).json()
