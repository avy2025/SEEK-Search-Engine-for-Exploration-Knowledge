"""Async HTTP fetching for the SEEK crawler (Phase 4).

Wraps ``httpx.AsyncClient`` with a small, typed result so the scheduler can
classify failures (timeout, redirect loop, transport error, HTTP status) without
touching httpx internals. Every request carries the configured User-Agent and
an HTML-focused Accept header; responses larger than *max_bytes* are rejected.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Awaitable, Callable

import httpx

from backend.browser.reader import (
    MAX_REDIRECTS,
    ReaderError,
    fetch_public_response,
)
ERR_TIMEOUT = "timeout"
ERR_REDIRECTS = "too_many_redirects"
ERR_TRANSPORT = "connection_error"
ERR_TOO_LARGE = "content_too_large"
ERR_NON_HTML = "non_html_content"
ERR_BLOCKED = "blocked_destination"
ERR_INVALID_URL = "invalid_url"

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


async def fetch(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout_seconds: float = 10.0,
    max_redirects: int = 5,
    user_agent: str = "SEEK-Crawler/1.0",
    max_bytes: int = MAX_FETCHED_BYTES,
    allowed_types: tuple[str, ...] = ("text/html", "application/xhtml+xml", ""),
    before_request: Callable[[str], Awaitable[None]] | None = None,
) -> FetchResult:
    """GET *url* and return a :class:`FetchResult` (never raises)."""
    timeout = httpx.Timeout(timeout_seconds, connect=min(3.0, timeout_seconds))
    try:
        final_url, content_type, body, status_code = await fetch_public_response(
            client,
            url,
            max_bytes=max_bytes,
            allowed_types=allowed_types,
            max_redirects=min(max_redirects, MAX_REDIRECTS),
            before_request=before_request,
            timeout=timeout,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                "Accept-Encoding": "identity",
            },
            return_http_errors=True,
        )
    except ReaderError as exc:
        error_code = {
            "reader_timeout": ERR_TIMEOUT,
            "too_many_redirects": ERR_REDIRECTS,
            "page_too_large": ERR_TOO_LARGE,
            "unsupported_content": ERR_NON_HTML,
            "blocked_destination": ERR_BLOCKED,
            "invalid_url": ERR_INVALID_URL,
            "out_of_scope_redirect": "out_of_scope_redirect",
            "robots_disallowed": "robots_disallowed",
        }.get(exc.code, ERR_TRANSPORT)
        return FetchResult(
            url=url,
            error_code=error_code,
            error=exc.message,
        )
    except (httpx.HTTPError, OSError, TimeoutError):
        return FetchResult(url=url, error_code=ERR_TRANSPORT, error="The page could not be fetched.")
    return FetchResult(
        url=url,
        final_url=final_url,
        status_code=status_code,
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
    "ERR_BLOCKED",
    "ERR_INVALID_URL",
]