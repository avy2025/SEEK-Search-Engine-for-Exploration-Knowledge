"""Async HTTP fetching for the SEEK crawler (Phase 4).

Wraps ``httpx.AsyncClient`` with a small, typed result so the scheduler can
classify failures (timeout, redirect loop, transport error, HTTP status) without
touching httpx internals. Every request carries the configured User-Agent and
an HTML-focused Accept header; responses larger than *max_bytes* are rejected.
"""
from __future__ import annotations

import httpx
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("seek.crawler.fetcher")

ERR_TIMEOUT = "timeout"
ERR_REDIRECTS = "too_many_redirects"
ERR_TRANSPORT = "connection_error"
ERR_TOO_LARGE = "content_too_large"
ERR_NON_HTML = "non_html_content"

MAX_FETCHED_BYTES = 2_000_000


@dataclass(frozen=True)
class FetchResult:
    """Outcome of one HTTP GET (errors are represented, not raised)."""

    url: str
    final_url: str = ""
    status_code: int = 0
    content_type: str = ""
    body: bytes = b""
    error: str = ""
    error_code: str = ""

    @property
    def ok(self) -> bool:
        return not self.error_code

    def as_dict(self) -> dict[str, object]:
        return {
            "url": self.url,
            "final_url": self.final_url,
            "status_code": self.status_code,
            "content_type": self.content_type,
            "body_bytes": len(self.body),
            "error": self.error,
            "error_code": self.error_code,
        }


def _is_html(content_type: str) -> bool:
    return "html" in (content_type or "").lower() or not content_type


async def fetch(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout_seconds: float = 10.0,
    max_redirects: int = 5,
    user_agent: str = "SEEK-Crawler/1.0",
    max_bytes: int = MAX_FETCHED_BYTES,
) -> FetchResult:
    """GET *url* and return a :class:`FetchResult` (never raises)."""
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }
    timeout = httpx.Timeout(timeout_seconds, connect=timeout_seconds)
    try:
        response = await client.get(
            url,
            headers=headers,
            timeout=timeout,
            follow_redirects=max_redirects > 0,
        )
    except httpx.TimeoutException as exc:  # noqa: BLE001 - typed error
        return FetchResult(url=url, error_code=ERR_TIMEOUT, error=str(exc))
    except httpx.TooManyRedirects as exc:  # noqa: BLE001 - typed error
        return FetchResult(url=url, error_code=ERR_REDIRECTS, error=str(exc))
    except httpx.HTTPError as exc:  # noqa: BLE001 - transport errors
        return FetchResult(url=url, error_code=ERR_TRANSPORT, error=str(exc))

    content_type = response.headers.get("content-type", "")
    if not _is_html(content_type):
        return FetchResult(
            url=url,
            final_url=str(response.url),
            status_code=response.status_code,
            content_type=content_type,
            error_code=ERR_NON_HTML,
            error=f"content-type {content_type!r} is not HTML",
        )
    body = response.content
    if body and len(body) > max_bytes:
        return FetchResult(
            url=url,
            final_url=str(response.url),
            status_code=response.status_code,
            content_type=content_type,
            error_code=ERR_TOO_LARGE,
            error=f"body exceeds {max_bytes} bytes",
        )
    return FetchResult(
        url=url,
        final_url=str(response.url),
        status_code=response.status_code,
        content_type=content_type,
        body=body,
    )


__all__ = [
    "FetchResult",
    "fetch",
    "ERR_TIMEOUT",
    "ERR_REDIRECTS",
    "ERR_TRANSPORT",
    "ERR_TOO_LARGE",
    "ERR_NON_HTML",
]