"""Independent Tavily live-web provider and SEEK-side usage controls."""
from __future__ import annotations

import asyncio
import hashlib
import math
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from backend.config import settings

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
MONTHLY_CREDIT_ALLOWANCE = 900
BASIC_SEARCH_CREDITS = 1


class TavilyProviderError(Exception):
    """Sanitized provider failure; raw external response text is never exposed."""

    def __init__(
        self,
        code: str,
        *,
        credits_consumed: int | None = None,
    ) -> None:
        self.code = code
        self.credits_consumed = credits_consumed
        super().__init__(code)


class LiveSearchBudgetExceeded(Exception):
    """Raised when SEEK's monthly application-side allowance is exhausted."""

    def __init__(self, usage: dict[str, Any]) -> None:
        self.usage = usage
        super().__init__("SEEK's monthly live-search credit budget is exhausted.")


class UsageStoreError(Exception):
    """Raised when the persistent usage ledger cannot be read or updated."""


@dataclass(frozen=True)
class TavilyResult:
    title: str
    url: str
    content: str
    score: float | None
    favicon: str | None


@dataclass(frozen=True)
class TavilyResponse:
    results: tuple[TavilyResult, ...]
    credits_used: int | None


class TavilySearchProvider:
    """Small async client for Tavily's official Search REST endpoint."""

    def __init__(
        self,
        api_key: str,
        *,
        connect_timeout: float = 3.0,
        read_timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._timeout = httpx.Timeout(
            connect=connect_timeout,
            read=read_timeout,
            write=connect_timeout,
            pool=connect_timeout,
        )
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    async def search(
        self,
        query: str,
        *,
        include_domains: tuple[str, ...] = (),
        exclude_domains: tuple[str, ...] = (),
        max_results: int = 5,
    ) -> TavilyResponse:
        if not self._api_key:
            raise TavilyProviderError("not_configured")

        payload: dict[str, Any] = {
            "api_key": self._api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": max_results,
            "topic": "general",
            "include_answer": False,
            "include_raw_content": False,
            "include_favicon": True,
        }
        if include_domains:
            payload["include_domains"] = list(include_domains)
        if exclude_domains:
            payload["exclude_domains"] = list(exclude_domains)

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = await client.post(TAVILY_SEARCH_URL, json=payload)
        except httpx.TimeoutException as exc:
            raise TavilyProviderError(
                "timeout", credits_consumed=BASIC_SEARCH_CREDITS
            ) from exc
        except httpx.RequestError as exc:
            raise TavilyProviderError(
                "network_error", credits_consumed=BASIC_SEARCH_CREDITS
            ) from exc

        if response.status_code in (401, 403):
            raise TavilyProviderError("authentication_error", credits_consumed=0)
        if response.status_code == 429:
            raise TavilyProviderError("rate_limited", credits_consumed=0)
        if response.status_code == 408:
            raise TavilyProviderError("timeout", credits_consumed=BASIC_SEARCH_CREDITS)
        if response.status_code in (402, 432):
            raise TavilyProviderError("credits_exhausted", credits_consumed=0)
        if response.status_code >= 500 or response.status_code == 434:
            raise TavilyProviderError(
                "provider_unavailable", credits_consumed=BASIC_SEARCH_CREDITS
            )
        if response.status_code >= 400:
            raise TavilyProviderError("provider_unavailable", credits_consumed=0)

        try:
            body = response.json()
        except ValueError as exc:
            raise TavilyProviderError(
                "invalid_provider_response", credits_consumed=BASIC_SEARCH_CREDITS
            ) from exc
        if not isinstance(body, dict) or not isinstance(body.get("results"), list):
            raise TavilyProviderError(
                "invalid_provider_response", credits_consumed=BASIC_SEARCH_CREDITS
            )

        results: list[TavilyResult] = []
        for item in body["results"][:max_results]:
            if not isinstance(item, dict):
                continue
            title = item.get("title")
            url = item.get("url")
            content = item.get("content")
            if not isinstance(title, str) or not isinstance(url, str):
                continue
            if not _is_public_web_url(url):
                continue
            score_value = item.get("score")
            score = _finite_float(score_value)
            favicon = item.get("favicon")
            if (
                not isinstance(favicon, str)
                or not _is_public_web_url(favicon)
                or not _same_https_host(favicon, url)
            ):
                favicon = None
            results.append(
                TavilyResult(
                    title=title.strip()[:500] or url,
                    url=url,
                    content=content.strip()[:3000] if isinstance(content, str) else "",
                    score=score,
                    favicon=favicon,
                )
            )

        return TavilyResponse(
            results=tuple(results),
            credits_used=_reported_credits(body),
        )


class UsageLedger:
    """SQLite-backed monthly credit ledger with cross-thread/process reserves."""

    def __init__(
        self,
        path: str | Path,
        *,
        allowance: int = MONTHLY_CREDIT_ALLOWANCE,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self.path = Path(path)
        self.allowance = allowance
        self._clock = clock
        self._init_lock = threading.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            str(self.path), timeout=10, isolation_level=None
        )
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        try:
            with self._init_lock, self._connection() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tavily_monthly_usage (
                        month TEXT PRIMARY KEY,
                        credits_consumed INTEGER NOT NULL DEFAULT 0,
                        successful_searches INTEGER NOT NULL DEFAULT 0,
                        failed_searches INTEGER NOT NULL DEFAULT 0,
                        last_successful_search_at TEXT
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tavily_reservations (
                        reservation_id TEXT PRIMARY KEY,
                        month TEXT NOT NULL,
                        credits INTEGER NOT NULL
                    )
                    """
                )
        except (OSError, sqlite3.Error) as exc:
            raise UsageStoreError("Could not initialize the live-search usage store.") from exc

    def reserve(self, credits: int = BASIC_SEARCH_CREDITS) -> str:
        month = self._month()
        reservation_id = uuid.uuid4().hex
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT OR IGNORE INTO tavily_monthly_usage (month) VALUES (?)",
                    (month,),
                )
                row = connection.execute(
                    "SELECT credits_consumed FROM tavily_monthly_usage WHERE month = ?",
                    (month,),
                ).fetchone()
                reserved = connection.execute(
                    "SELECT COALESCE(SUM(credits), 0) FROM tavily_reservations WHERE month = ?",
                    (month,),
                ).fetchone()[0]
                if row[0] + reserved + credits > self.allowance:
                    usage = self._usage_in_transaction(connection, month)
                    connection.rollback()
                    raise LiveSearchBudgetExceeded(usage)
                connection.execute(
                    "INSERT INTO tavily_reservations (reservation_id, month, credits) VALUES (?, ?, ?)",
                    (reservation_id, month, credits),
                )
                connection.commit()
        except LiveSearchBudgetExceeded:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise UsageStoreError("Could not reserve live-search credits.") from exc
        return reservation_id

    def settle(
        self,
        reservation_id: str,
        *,
        credits: int,
        succeeded: bool,
    ) -> None:
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                reservation = connection.execute(
                    "SELECT month FROM tavily_reservations WHERE reservation_id = ?",
                    (reservation_id,),
                ).fetchone()
                if reservation is None:
                    raise UsageStoreError("The live-search credit reservation was not found.")
                month = reservation[0]
                connection.execute(
                    "DELETE FROM tavily_reservations WHERE reservation_id = ?",
                    (reservation_id,),
                )
                if succeeded:
                    connection.execute(
                        """
                        UPDATE tavily_monthly_usage
                        SET credits_consumed = credits_consumed + ?,
                            successful_searches = successful_searches + 1,
                            last_successful_search_at = ?
                        WHERE month = ?
                        """,
                        (credits, self._now().isoformat(), month),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE tavily_monthly_usage
                        SET credits_consumed = credits_consumed + ?,
                            failed_searches = failed_searches + 1
                        WHERE month = ?
                        """,
                        (credits, month),
                    )
                connection.commit()
        except UsageStoreError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise UsageStoreError("Could not update the live-search usage store.") from exc

    def record_failed_without_charge(self) -> None:
        month = self._month()
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT OR IGNORE INTO tavily_monthly_usage (month) VALUES (?)",
                    (month,),
                )
                connection.execute(
                    """
                    UPDATE tavily_monthly_usage
                    SET failed_searches = failed_searches + 1
                    WHERE month = ?
                    """,
                    (month,),
                )
                connection.commit()
        except (OSError, sqlite3.Error) as exc:
            raise UsageStoreError("Could not update the live-search usage store.") from exc

    def usage(self) -> dict[str, Any]:
        month = self._month()
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT OR IGNORE INTO tavily_monthly_usage (month) VALUES (?)",
                    (month,),
                )
                usage = self._usage_in_transaction(connection, month)
                connection.commit()
            return usage
        except (OSError, sqlite3.Error) as exc:
            raise UsageStoreError("Could not read the live-search usage store.") from exc

    def _usage_in_transaction(
        self, connection: sqlite3.Connection, month: str
    ) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT credits_consumed, successful_searches, failed_searches,
                   last_successful_search_at
            FROM tavily_monthly_usage WHERE month = ?
            """,
            (month,),
        ).fetchone()
        reserved = connection.execute(
            "SELECT COALESCE(SUM(credits), 0) FROM tavily_reservations WHERE month = ?",
            (month,),
        ).fetchone()[0]
        consumed = row[0] + reserved
        return {
            "month": month,
            "monthly_allowance": self.allowance,
            "credits_consumed": consumed,
            "credits_remaining": max(0, self.allowance - consumed),
            "successful_searches": row[1],
            "failed_searches": row[2],
            "last_successful_search_at": row[3],
        }

    def _month(self) -> str:
        return self._now().strftime("%Y-%m")

    def _now(self) -> datetime:
        return self._clock().astimezone(timezone.utc)


class LiveSearchService:
    """Connect the Tavily provider to the cache and persistent credit ledger."""

    def __init__(
        self,
        provider: TavilySearchProvider,
        ledger: UsageLedger,
        *,
        cache_ttl_seconds: int = 600,
        clock=time.monotonic,
    ) -> None:
        self.provider = provider
        self.ledger = ledger
        self.cache_ttl_seconds = cache_ttl_seconds
        self._clock = clock
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._cache_lock = threading.Lock()
        self._query_lock_guard = threading.Lock()
        self._query_locks: dict[str, tuple[asyncio.Lock, int]] = {}

    async def search(
        self,
        query: str,
        *,
        include_domains: tuple[str, ...] = (),
        exclude_domains: tuple[str, ...] = (),
        max_results: int = 5,
    ) -> dict[str, Any]:
        normalized_query = " ".join(query.split())
        cache_key = self._cache_key(normalized_query, include_domains, exclude_domains, max_results)
        cached = self._get_cached(cache_key)
        if cached is not None:
            cached["query"] = normalized_query
            cached["usage"] = self.ledger.usage()
            cached["cached"] = True
            cached["took_ms"] = 0.0
            return cached

        lock = self._retain_query_lock(cache_key)
        try:
            async with lock:
                cached = self._get_cached(cache_key)
                if cached is not None:
                    cached["query"] = normalized_query
                    cached["usage"] = self.ledger.usage()
                    cached["cached"] = True
                    cached["took_ms"] = 0.0
                    return cached
                return await self._search_uncached(
                    normalized_query,
                    cache_key,
                    include_domains=include_domains,
                    exclude_domains=exclude_domains,
                    max_results=max_results,
                )
        finally:
            self._release_query_lock(cache_key, lock)

    async def _search_uncached(
        self,
        query: str,
        cache_key: str,
        *,
        include_domains: tuple[str, ...],
        exclude_domains: tuple[str, ...],
        max_results: int,
    ) -> dict[str, Any]:
        if not self.provider.configured:
            self.ledger.record_failed_without_charge()
            raise TavilyProviderError("not_configured", credits_consumed=0)

        reservation_id = self.ledger.reserve()
        started = time.perf_counter()
        try:
            provider_response = await self.provider.search(
                query,
                include_domains=include_domains,
                exclude_domains=exclude_domains,
                max_results=max_results,
            )
        except TavilyProviderError as exc:
            self.ledger.settle(
                reservation_id,
                credits=(
                    BASIC_SEARCH_CREDITS
                    if exc.credits_consumed is None
                    else exc.credits_consumed
                ),
                succeeded=False,
            )
            raise

        credits_used = (
            provider_response.credits_used
            if provider_response.credits_used is not None
            else BASIC_SEARCH_CREDITS
        )
        self.ledger.settle(reservation_id, credits=credits_used, succeeded=True)
        searched_at = datetime.now(timezone.utc).isoformat()
        results = [
            {
                "title": item.title,
                "url": item.url,
                "domain": urlsplit(item.url).hostname or "",
                "snippet": item.content,
                "score": item.score,
                "favicon": item.favicon,
            }
            for item in provider_response.results
        ]
        response = {
            "mode": "live",
            "query": query,
            "total": len(results),
            "results": results,
            "took_ms": round((time.perf_counter() - started) * 1000, 3),
            "cached": False,
            "searched_at": searched_at,
            "usage": self.ledger.usage(),
            "message": "ok" if results else "no results found",
        }
        self._set_cached(cache_key, response)
        return response

    def _retain_query_lock(self, key: str) -> asyncio.Lock:
        with self._query_lock_guard:
            entry = self._query_locks.get(key)
            if entry is None:
                lock, users = asyncio.Lock(), 0
            else:
                lock, users = entry
            self._query_locks[key] = (lock, users + 1)
            return lock

    def _release_query_lock(self, key: str, lock: asyncio.Lock) -> None:
        with self._query_lock_guard:
            entry = self._query_locks.get(key)
            if entry is None or entry[0] is not lock:
                return
            if entry[1] == 1:
                del self._query_locks[key]
            else:
                self._query_locks[key] = (lock, entry[1] - 1)

    def usage(self) -> dict[str, Any]:
        return self.ledger.usage()

    def _cache_key(
        self,
        query: str,
        include_domains: tuple[str, ...],
        exclude_domains: tuple[str, ...],
        max_results: int,
    ) -> str:
        parts = (
            query.casefold(),
            ",".join(sorted(include_domains)),
            ",".join(sorted(exclude_domains)),
            str(max_results),
        )
        return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()

    def _get_cached(self, cache_key: str) -> dict[str, Any] | None:
        with self._cache_lock:
            item = self._cache.get(cache_key)
            if item is None:
                return None
            expires_at, response = item
            if expires_at <= self._clock():
                del self._cache[cache_key]
                return None
            return {**response, "results": [dict(row) for row in response["results"]]}

    def _set_cached(self, cache_key: str, response: dict[str, Any]) -> None:
        if self.cache_ttl_seconds <= 0:
            return
        with self._cache_lock:
            now = self._clock()
            self._cache = {
                key: value for key, value in self._cache.items() if value[0] > now
            }
            self._cache[cache_key] = (
                now + self.cache_ttl_seconds,
                {**response, "results": [dict(row) for row in response["results"]]},
            )


def _reported_credits(body: dict[str, Any]) -> int | None:
    candidates = [body.get("credits_used"), body.get("credits"), body.get("usage")]
    for candidate in candidates:
        if isinstance(candidate, dict):
            candidates.extend(
                (
                    candidate.get("credits_used"),
                    candidate.get("credits"),
                    candidate.get("api_credits"),
                )
            )
        elif isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            try:
                value = float(candidate)
            except OverflowError:
                continue
            if math.isfinite(value) and value >= 0 and value.is_integer():
                return int(value)
    return None


def _finite_float(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        converted = float(value)
    except OverflowError:
        return None
    return converted if math.isfinite(converted) else None


def _is_public_web_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
        _ = parts.port
        return (
            parts.scheme.lower() in {"http", "https"}
            and bool(parts.hostname)
            and not parts.username
            and not parts.password
            and value == value.strip()
            and not any(character.isspace() for character in value)
        )
    except ValueError:
        return False


def _same_https_host(favicon: str, page_url: str) -> bool:
    try:
        icon = urlsplit(favicon)
        page = urlsplit(page_url)
        return icon.scheme.lower() == "https" and icon.hostname == page.hostname
    except ValueError:
        return False


def create_live_search_service() -> LiveSearchService:
    provider = TavilySearchProvider(
        settings.TAVILY_API_KEY.get_secret_value(),
        connect_timeout=settings.TAVILY_CONNECT_TIMEOUT_SECONDS,
        read_timeout=settings.TAVILY_READ_TIMEOUT_SECONDS,
    )
    return LiveSearchService(
        provider,
        UsageLedger(settings.TAVILY_USAGE_DB_PATH),
        cache_ttl_seconds=settings.TAVILY_CACHE_TTL_SECONDS,
    )


_service: LiveSearchService | None = None
_service_lock = threading.Lock()


def get_live_search_service() -> LiveSearchService:
    global _service
    with _service_lock:
        if _service is None:
            _service = create_live_search_service()
        return _service


def reset_live_search_service() -> None:
    """Reset the process-local service instance (used by tests and config reloads)."""
    global _service
    with _service_lock:
        _service = None


__all__ = [
    "BASIC_SEARCH_CREDITS",
    "LiveSearchBudgetExceeded",
    "LiveSearchService",
    "MONTHLY_CREDIT_ALLOWANCE",
    "TavilyProviderError",
    "TavilyResponse",
    "TavilyResult",
    "TavilySearchProvider",
    "UsageLedger",
    "UsageStoreError",
    "create_live_search_service",
    "get_live_search_service",
    "reset_live_search_service",
]
