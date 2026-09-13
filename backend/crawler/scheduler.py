"""Controlled crawl scheduler (Phase 4) — politeness + scope + dedup.

Runs a BFS frontier crawl with these guarantees:

* every URL passes the :mod:`backend.crawler.url` safety gate and the seed /
  allowlist domain scope,
* robots.txt is honoured per host (allow-by-default when unreachable),
* per-host rate limiting uses ``max(config.delay, robots Crawl-delay)``,
* canonical URLs and content hashes are deduplicated **across** runs through
  the shared :class:`~backend.crawler.service.CrawlStore`,
* HTTP failures are classified and reported, never raised,
* concurrency is capped by ``config.concurrency`` (default 1,
  fully deterministic).
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Iterable, Optional

import httpx

from backend.crawler.extract import chunk_text, extract_text, hash_text
from backend.crawler.fetcher import ERR_NON_HTML, fetch
from backend.crawler.models import (
    CrawlJobConfig,
    CrawlPage,
    CrawlReport,
    FailedFetch,
)
from backend.crawler.robots import RobotsTxtPolicy
from backend.crawler.url import (
    domain_matches,
    hostname_of,
    is_crawlable_url,
    is_dangerous_url,
    normalize_url,
    resolve_url,
    scope_hosts,
)

logger = logging.getLogger("seek.crawler.scheduler")

FRONTIER_CAP = 2000


def _links_from(html: str) -> Iterable[str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = (anchor.get("href") or "").strip()
        if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
            yield href


async def a_crawl(
    config: CrawlJobConfig,
    store,
    policy: RobotsTxtPolicy,
    client: httpx.AsyncClient,
    *,
    on_page=None,
    frontier_cap: int = FRONTIER_CAP,
) -> tuple[CrawlReport, list[CrawlPage], list[FailedFetch]]:
    """Execute one crawl run, mutating *store*; never raises."""
    started = time.perf_counter()
    scope = scope_hosts(config.allowed_domains, config.seed_urls)
    frontier: deque[tuple[str, int]] = deque()
    queued: set[str] = set()
    pages: list[CrawlPage] = []
    failures: list[FailedFetch] = []
    seen_urls_in_run: set[str] = set()

    dup_urls = 0
    dup_content = 0
    out_of_scope = 0
    robots_blocked = 0
    urls_seen = 0
    last_request: dict[str, float] = {}

    def _seed(url: str, depth: int = 0) -> None:
        nonlocal out_of_scope
        canonical = normalize_url(url)
        if is_dangerous_url(canonical):
            failures.append(
                FailedFetch(url=url, error_code="unparsable_seed", error="unsafe or unparsable seed URL")
            )
            return
        host = hostname_of(canonical)
        if scope and not domain_matches(host, scope):
            out_of_scope += 1
            failures.append(
                FailedFetch(url=url, error_code="out_of_scope", error=f"host {host} not in scope")
            )
            return
        if canonical in queued or store.is_visited(canonical):
            return
        queued.add(canonical)
        frontier.append((canonical, depth))

    for seed in config.seed_urls:
        _seed(seed)

    async def _throttle(host: str, delay: float) -> None:
        if delay <= 0:
            return
        now = time.monotonic()
        last = last_request.get(host)
        if last is not None:
            gap = delay - (now - last)
            if gap > 0:
                await asyncio.sleep(gap)
        last_request[host] = time.monotonic()

    async def _process(url: str, depth: int) -> None:
        nonlocal robots_blocked, dup_urls, dup_content, out_of_scope, urls_seen
        if store.is_visited(url):
            dup_urls += 1
            return
        urls_seen += 1

        await policy.ensure_loaded(client, url)
        if not policy.can_fetch(url):
            robots_blocked += 1
            store.mark_visited(url)
            return

        host = hostname_of(url)
        delay = max(config.delay_seconds, policy.crawl_delay(host))
        await _throttle(host, delay)

        result = await fetch(
            client,
            url,
            timeout_seconds=config.timeout_seconds,
            max_redirects=config.max_redirects,
            user_agent=config.user_agent,
        )
        if not result.ok:
            if result.error_code == ERR_NON_HTML:
                store.mark_visited(url)
                return
            failures.append(
                FailedFetch(
                    url=url,
                    status_code=result.status_code,
                    error_code=result.error_code,
                    error=result.error,
                )
            )
            store.mark_visited(url)
            return
        if result.status_code >= 400:
            failures.append(
                FailedFetch(url=url, status_code=result.status_code, error_code="http_status", error=f"HTTP {result.status_code}")
            )
            store.mark_visited(url)
            return

        final = normalize_url(result.final_url or url)
        if store.is_visited(final):
            dup_urls += 1
            return
        html = result.body.decode("utf-8", errors="replace") if result.body else ""
        if not html:
            return
        title, text = extract_text(html, url=final, max_chars=config.max_content_chars)
        if not text:
            return
        content_hash = hash_text(text)
        if store.has_hash(content_hash):
            dup_content += 1
            return

        page = CrawlPage(
            url=final,
            final_url=final,
            status_code=result.status_code,
            title=title,
            text=text,
            content_hash=content_hash,
            chunks=chunk_text(text),
            fetched_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        added = store.record(page)
        store.mark_visited(final)
        if not added:
            dup_content += 1
            return
        pages.append(page)
        if on_page is not None:
            on_page(page)

        if depth >= config.max_depth:
            return
        for link in _links_from(result.body.decode("utf-8", errors="replace") if result.body else html):
            target = normalize_url(resolve_url(final, link))
            if not is_crawlable_url(
                target, allow_private_hosts=config.allow_private_hosts
            ):
                out_of_scope += 1
                continue
            t_host = hostname_of(target)
            if scope and not domain_matches(t_host, scope):
                out_of_scope += 1
                continue
            if target in queued or store.is_visited(target):
                dup_urls += 1
                continue
            if len(queued) >= frontier_cap:
                continue
            queued.add(target)
            frontier.append((target, depth + 1))

    while frontier and len(pages) < config.max_pages:
        remaining = config.max_pages - len(pages)
        batch = [frontier.popleft() for _ in range(min(remaining, len(frontier)))]
        await asyncio.gather(*(_process(url, depth) for url, depth in batch))

    took_ms = (time.perf_counter() - started) * 1000.0
    report = CrawlReport(
        pages_crawled=len(pages),
        pages_failed=len(failures),
        robots_blocked=robots_blocked,
        urls_seen=urls_seen,
        duplicate_urls=dup_urls,
        duplicate_content=dup_content,
        out_of_scope=out_of_scope,
        took_ms=took_ms,
        message=(
            f"crawled {len(pages)} page(s) with {len(failures)} failure(s) "
            f"in {took_ms:.0f}ms"
        ),
    )
    return report, pages, failures


__all__ = ["a_crawl", "_links_from", "FRONTIER_CAP"]