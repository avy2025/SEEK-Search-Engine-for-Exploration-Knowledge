"""Wire models for the SEEK controlled web crawler (Phase 4).

Dataclasses only — the crawler deliberately mirrors the Phase 2 philosophy: no
database required, best-effort persistence, and a small stable surface for the
``/api/crawl`` job API, the crawler scheduler and the Phase 4 test suite.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CrawlStatus(str, Enum):
    """Lifecycle of a single crawl job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class CrawlJobConfig:
    """Per-job crawl constraints (all fields default to global settings)."""

    seed_urls: tuple[str, ...]
    allowed_domains: tuple[str, ...] = ()
    max_pages: int = 25
    max_depth: int = 2
    delay_seconds: float = 1.0
    concurrency: int = 1
    timeout_seconds: float = 10.0
    max_redirects: int = 5
    max_content_chars: int = 200_000
    user_agent: str = "SEEK-Crawler/1.0"
    respect_robots: bool = True
    allow_private_hosts: bool = False

    def sanitized(self) -> "CrawlJobConfig":
        """Return a copy with hardened bounds (no negative/zero weirdness)."""
        return CrawlJobConfig(
            seed_urls=tuple(s.strip() for s in self.seed_urls if s and s.strip()),
            allowed_domains=tuple(
                d.strip().lower().lstrip(".")
                for d in self.allowed_domains
                if d and d.strip()
            ),
            max_pages=max(1, min(1000, int(self.max_pages))),
            max_depth=max(0, min(32, int(self.max_depth))),
            delay_seconds=max(0.0, float(self.delay_seconds)),
            concurrency=max(1, min(32, int(self.concurrency))),
            timeout_seconds=max(1.0, float(self.timeout_seconds)),
            max_redirects=max(0, min(32, int(self.max_redirects))),
            max_content_chars=max(1_000, int(self.max_content_chars)),
            user_agent=(self.user_agent or "SEEK-Crawler/1.0").strip(),
            respect_robots=bool(self.respect_robots),
            allow_private_hosts=bool(self.allow_private_hosts),
        )


@dataclass(frozen=True)
class CrawlPage:
    """One successfully fetched and extracted page."""

    url: str
    final_url: str
    status_code: int
    title: str
    text: str
    content_hash: str
    chunks: tuple[str, ...] = field(default_factory=tuple)
    fetched_at: str = ""


@dataclass(frozen=True)
class CrawlReport:
    """Immutable summary produced by one crawl run."""

    pages_crawled: int = 0
    pages_failed: int = 0
    robots_blocked: int = 0
    urls_seen: int = 0
    duplicate_urls: int = 0
    duplicate_content: int = 0
    out_of_scope: int = 0
    took_ms: float = 0.0
    message: str = ""


@dataclass(frozen=True)
class FailedFetch:
    """A URL that could not be fetched (error categories preserved)."""

    url: str
    status_code: int = 0
    error_code: str = ""
    error: str = ""


@dataclass
class CrawlJob:
    """Mutable per-job state tracked by :class:`CrawlManager` (thread-safe)."""

    job_id: str
    config: CrawlJobConfig
    status: CrawlStatus = CrawlStatus.PENDING
    pages: list[CrawlPage] = field(default_factory=list)
    failures: list[FailedFetch] = field(default_factory=list)
    report: Optional[CrawlReport] = None
    error: str = ""
    started_at: str = ""
    finished_at: str = ""

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def set_status(self, status: CrawlStatus) -> None:
        with self._lock:
            self.status = status

    def append_page(self, page: CrawlPage) -> None:
        with self._lock:
            self.pages.append(page)

    def append_failure(self, failure: FailedFetch) -> None:
        with self._lock:
            self.failures.append(failure)

    def complete(self, report: CrawlReport, error: str = "") -> None:
        with self._lock:
            self.report = report
            self.error = error
            self.status = (
                CrawlStatus.FAILED if error else CrawlStatus.COMPLETED
            )
            self.finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def start(self) -> None:
        with self._lock:
            self.status = CrawlStatus.RUNNING
            self.started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def to_dict(self) -> dict[str, object]:
        with self._lock:
            return {
                "job_id": self.job_id,
                "status": self.status.value,
                "seed_urls": list(self.config.seed_urls),
                "allowed_domains": list(self.config.allowed_domains),
                "max_pages": self.config.max_pages,
                "pages_crawled": len(self.pages),
                "pages_failed": len(self.failures),
                "report": {
                    "pages_crawled": self.report.pages_crawled if self.report else 0,
                    "pages_failed": self.report.pages_failed if self.report else 0,
                    "robots_blocked": self.report.robots_blocked if self.report else 0,
                    "urls_seen": self.report.urls_seen if self.report else 0,
                    "duplicate_urls": self.report.duplicate_urls if self.report else 0,
                    "duplicate_content": self.report.duplicate_content if self.report else 0,
                    "out_of_scope": self.report.out_of_scope if self.report else 0,
                    "took_ms": self.report.took_ms if self.report else 0.0,
                    "message": (self.report.message if self.report else ""),
                },
                "error": self.error,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }


__all__ = [
    "CrawlStatus",
    "CrawlJobConfig",
    "CrawlPage",
    "CrawlReport",
    "FailedFetch",
    "CrawlJob",
]