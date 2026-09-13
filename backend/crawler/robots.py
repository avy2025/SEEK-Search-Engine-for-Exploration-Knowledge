"""robots.txt policy for the SEEK crawler (Phase 4).

Wraps the standard-library :class:`urllib.robotparser.RobotFileParser` with a
per-host cache and best-effort fetch semantics:

* robots.txt is fetched **once per host** and cached for the life of a crawl;
* when robots.txt is missing (404) or unreachable the default is **allow**
  (RFC 9309); HTTP 401/403 means **deny**;
* :meth:`RobotsTxtPolicy.crawl_delay` surfaces the ``Crawl-delay`` directive so
  the scheduler can honour per-host rate limits on top of the global delay.
"""
from __future__ import annotations

import httpx
import logging
import urllib.robotparser
from typing import Optional
from urllib.parse import urlsplit

from backend.crawler.url import hostname_of

logger = logging.getLogger("seek.crawler.robots")


class RobotsTxtPolicy:
    """Thread-free cached robots.txt gate for one crawl run."""

    def __init__(
        self,
        user_agent: str,
        *,
        timeout_seconds: float = 10.0,
        max_redirects: int = 5,
    ) -> None:
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.max_redirects = max_redirects
        self._cache: dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}

    # -- internal ------------------------------------------------------------
    def _parser_for_host(self, host: str) -> Optional[urllib.robotparser.RobotFileParser]:
        return self._cache.get(host)

    def _set_parser(self, host: str, parser: Optional[urllib.robotparser.RobotFileParser]) -> None:
        self._cache[host] = parser

    def _robots_url(self, url: str) -> str:
        """robots.txt URL matching *url*'s scheme+host+port (dev-host friendly)."""
        parts = urlsplit(url)
        scheme = (parts.scheme or "http").lower()
        netloc = parts.netloc
        if netloc.startswith("https://") or netloc.startswith("http://"):
            netloc = netloc.split("://", 1)[1]
        return f"{scheme}://{netloc}/robots.txt"

    async def _fetch_robots(self, client: httpx.AsyncClient, url: str) -> str:
        """Return robots.txt body for *url* ("" on unreachable/not-found)."""
        robots_url = self._robots_url(url)
        try:
            response = await client.get(
                robots_url,
                timeout=self.timeout_seconds,
                follow_redirects=self.max_redirects > 0,
                headers={"User-Agent": self.user_agent},
            )
        except httpx.HTTPError as exc:  # noqa: BLE001 - robots failure = allow
            logger.debug("robots.txt unreachable for %s: %s", robots_url, exc)
            return ""
        if response.status_code in (401, 403):
            # Explicit block: robots.txt exists but forbids our agent broadly.
            return "Disallow: /"
        if response.status_code != 200:
            return ""
        try:
            return response.text
        except Exception as exc:  # noqa: BLE001 - never crash on decode
            logger.debug("robots.txt decode failed for %s: %s", robots_url, exc)
            return ""

    def _load(self, host: str, body: str) -> urllib.robotparser.RobotFileParser:
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(f"robots.txt://{host}")
        parser.parse((body or "").splitlines())
        return parser

    @classmethod
    def from_text(cls, user_agent: str, body: str, *, host: str = "") -> "RobotsTxtPolicy":
        """Build a fully offline policy from an already-fetched robots.txt body.

        The parser is preloaded under ``host`` (default ``""``) so
        :meth:`can_fetch` works without any network. Used by tests and callers
        that source robots.txt themselves.
        """
        policy = cls(user_agent)
        policy._set_parser(host, policy._load(host, body))
        return policy

    # -- public API ----------------------------------------------------------
    async def ensure_loaded(self, client: httpx.AsyncClient, url: str) -> None:
        """Fetch + cache robots.txt for *url*'s host, if not already loaded."""
        host = hostname_of(url)
        if not host or self._parser_for_host(host) is not None:
            return
        body = await self._fetch_robots(client, url)
        self._set_parser(host, self._load(host, body))

    def can_fetch(self, url: str) -> bool:
        """True when our user-agent may request *url* (defaults to allow)."""
        if not self.user_agent:
            return True
        host = hostname_of(url)
        parser = self._parser_for_host(host)
        if parser is None:
            return True
        try:
            return parser.can_fetch(self.user_agent, url)
        except Exception as exc:  # noqa: BLE001 - never crash policy
            logger.debug("can_fetch failed for %s: %s", url, exc)
            return True

    def crawl_delay(self, host: str) -> float:
        """Return a per-host ``Crawl-delay`` (0.0 when not configured)."""
        parser = self._parser_for_host(host)
        if parser is None:
            return 0.0
        try:
            raw = parser.crawl_delay(self.user_agent)
        except Exception as exc:  # noqa: BLE001
            logger.debug("crawl_delay failed for %s: %s", host, exc)
            return 0.0
        if raw is None:
            return 0.0
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            return 0.0


__all__ = ["RobotsTxtPolicy"]