"""Crawl job management + crawled-document store (Phase 4).

Two public pieces:

* :class:`CrawlStore` — the crawl-scoped document store. It deduplicates URLs
  and content hashes **across** jobs, persists each page best-effort into the
  existing ``documents`` table, and converts crawled pages into
  :class:`~backend.processing.models.ProcessedDocument` values so they can be
  fed into the existing BM25 pipeline unchanged.
* :class:`CrawlManager` — an in-memory job registry that starts crawls on a
  background daemon thread (so ``POST /api/crawl`` returns immediately) and
  exposes thread-safe job snapshots for polling.

Both are intentionally Postgres-optional, matching the Phase 2 degraded-repo
philosophy: when the database is unreachable the crawler keeps working and the
pages remain available in-memory for reindexing.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from typing import Optional

import httpx

from backend.config import settings
from backend.crawler.models import (
    CrawlJob,
    CrawlJobConfig,
    CrawlPage,
    CrawlReport,
    CrawlStatus,
    FailedFetch,
)
from backend.crawler.robots import RobotsTxtPolicy
from backend.crawler.scheduler import a_crawl
from backend.processing.models import ProcessedDocument
from backend.processing.tokenizer import tokenize

logger = logging.getLogger("seek.crawler.service")

_PERSIST_REPO = None
_PERSIST_LOCK = threading.Lock()


def _persist_best_effort(page: CrawlPage) -> int:
    """Insert *page* into the documents table; returns 1 on success, else 0."""
    global _PERSIST_REPO
    try:
        from backend.db.models import Document
        from backend.db.repository_factory import (
            create_initialised_document_repository,
        )

        with _PERSIST_LOCK:
            if _PERSIST_REPO is None:
                _PERSIST_REPO = create_initialised_document_repository(
                    settings.DATABASE_URL
                )
        if _PERSIST_REPO is None or not _PERSIST_REPO.is_available():
            return 0
        inserted = _PERSIST_REPO.upsert(
            Document(
                title=page.title,
                content=page.text,
                source=page.url,
                content_hash=page.content_hash,
            )
        )
        return 1 if inserted else 0
    except Exception as exc:  # noqa: BLE001 - best-effort only
        logger.debug("crawled page not persisted: %s", exc)
        return 0


class CrawlStore:
    """Deduplicating store of crawled documents (shared across jobs)."""

    def __init__(self) -> None:
        self._visited: set[str] = set()
        self._seen_hashes: set[str] = set()
        self._pages: dict[str, CrawlPage] = {}
        self._lock = threading.Lock()

    def is_visited(self, url: str) -> bool:
        with self._lock:
            return url in self._visited

    def mark_visited(self, url: str) -> None:
        with self._lock:
            self._visited.add(url)

    def has_hash(self, content_hash: str) -> bool:
        with self._lock:
            return content_hash in self._seen_hashes

    def record(self, page: CrawlPage) -> bool:
        """Register a new page; returns False when content is already known."""
        with self._lock:
            if page.content_hash in self._seen_hashes:
                return False
            self._seen_hashes.add(page.content_hash)
            self._pages[page.url] = page
        _persist_best_effort(page)
        return True

    def crawled_pages(self) -> list[CrawlPage]:
        with self._lock:
            return list(self._pages.values())

    def count(self) -> int:
        with self._lock:
            return len(self._pages)

    def to_processed_documents(self) -> list[ProcessedDocument]:
        """Convert crawled pages to :class:`ProcessedDocument` for indexing."""
        docs: list[ProcessedDocument] = []
        for page in self.crawled_pages():
            tokens = tokenize(page.text)
            if not tokens:
                continue
            document_id = f"crawl-{page.content_hash[:12]}"
            docs.append(
                ProcessedDocument(
                    document_id=document_id,
                    title=page.title or page.url,
                    content=page.text,
                    source=page.url,
                    tokens=tuple(tokens),
                    content_hash=page.content_hash,
                )
            )
        return docs


class CrawlManager:
    """Job registry that runs crawls in the background (daemon threads)."""

    def __init__(self, store: Optional[CrawlStore] = None) -> None:
        self._store = store or CrawlStore()
        self._jobs: dict[str, CrawlJob] = {}
        self._lock = threading.Lock()

    @property
    def store(self) -> CrawlStore:
        return self._store

    def start_job(self, config: CrawlJobConfig) -> CrawlJob:
        """Register + launch *config*; returns the job (status ``pending``)."""
        job_config = config.sanitized()
        if not job_config.seed_urls:
            raise ValueError("crawl job requires at least one valid seed URL")
        job = CrawlJob(
            job_id=f"crawl_{uuid.uuid4().hex[:12]}",
            config=job_config,
        )
        with self._lock:
            self._jobs[job.job_id] = job
        thread = threading.Thread(
            target=self._run,
            args=(job,),
            name=f"seek-crawl-{job.job_id[-6:]}",
            daemon=True,
        )
        thread.start()
        return job

    def get_job(self, job_id: str) -> Optional[CrawlJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list[CrawlJob]:
        with self._lock:
            return list(self._jobs.values())

    # -- internal ------------------------------------------------------------
    def _run(self, job: CrawlJob) -> None:
        job.start()
        try:
            asyncio.run(self._execute(job))
        except Exception as exc:  # noqa: BLE001 - job must never kill the process
            logger.exception("crawl job %s failed: %s", job.job_id, exc)
            job.complete(
                CrawlReport(pages_crawled=len(job.pages), message="job failed"),
                error=f"{type(exc).__name__}: {exc}",
            )

    async def _execute(self, job: CrawlJob) -> None:
        config = job.config
        async with httpx.AsyncClient(
            follow_redirects=config.max_redirects > 0,
            max_redirects=config.max_redirects,
        ) as client:
            policy = RobotsTxtPolicy(
                config.user_agent,
                timeout_seconds=config.timeout_seconds,
                max_redirects=config.max_redirects,
            )
            report, _pages, failures = await a_crawl(
                config,
                self._store,
                policy,
                client,
                on_page=job.append_page,
            )
        for failure in failures:
            job.append_failure(failure)
        job.complete(report)


_manager: CrawlManager = CrawlManager()


def get_crawl_manager() -> CrawlManager:
    return _manager


__all__ = ["CrawlStore", "CrawlManager", "get_crawl_manager", "_persist_best_effort"]