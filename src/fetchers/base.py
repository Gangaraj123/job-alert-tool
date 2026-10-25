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


class BrowserUnavailable(FetchError):
    """No usable Chromium in this environment.

    Distinct from a normal FetchError because it says nothing about the
    company: the daily GitHub Actions run installs a browser and fetches it
    fine. Marking the company broken on that basis would be wrong, so
    callers skip it instead.
    """

    def __str__(self) -> str:  # noqa: D105
        # Prefixed so the reason survives being flattened to a string as it
        # passes back through the per-company error channel.
        return f"BROWSER_UNAVAILABLE: {super().__str__()}"


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


def to_iso_date(value) -> str | None:
    """Normalise an ATS date into YYYY-MM-DD, or None if unreadable.

    Boards express the posting date half a dozen ways -- ISO strings with
    and without a zone, epoch seconds, epoch milliseconds -- and a wrong
    date is worse than none, since the UI would sort and filter on it.
    """
    if value in (None, "", 0):
        return None

    # Epoch, in seconds or milliseconds.
    if isinstance(value, (int, float)) or (
        isinstance(value, str) and value.isdigit()
    ):
        n = float(value)
        if n > 1e11:  # milliseconds
            n /= 1000.0
        try:
            import datetime as _dt
            return _dt.datetime.fromtimestamp(n, _dt.timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None

    text = str(value).strip()
    if not text:
        return None
    try:
        import datetime as _dt
        cleaned = text.replace("Z", "+00:00")
        return _dt.datetime.fromisoformat(cleaned).date().isoformat()
    except ValueError:
        pass

    # Human formats: Amazon says "September 24, 2026", others "24 Sep 2026".
    import datetime as _dt
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return _dt.datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue

    import re as _re
    m = _re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    return m.group(0) if m else None
