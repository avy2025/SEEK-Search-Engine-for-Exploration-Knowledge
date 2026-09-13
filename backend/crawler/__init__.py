"""SEEK controlled web crawler package (Phase 4).

Public surface
--------------
* :func:`~backend.crawler.scheduler.a_crawl` — the crawl loop.
* :class:`~backend.crawler.models.CrawlJobConfig` — per-job constraints.
* :class:`~backend.crawler.service.CrawlManager` / ``CrawlStore`` — jobs and
  crawled-document storage feeding the existing BM25 pipeline.
* :func:`~backend.crawler.url.normalize_url` — canonical URL helper.
"""
from __future__ import annotations

from backend.crawler.models import (
    CrawlJob,
    CrawlJobConfig,
    CrawlPage,
    CrawlReport,
    CrawlStatus,
)
from backend.crawler.service import (
    CrawlManager,
    CrawlStore,
    get_crawl_manager,
)
from backend.crawler.url import normalize_url

__all__ = [
    "CrawlJob",
    "CrawlJobConfig",
    "CrawlPage",
    "CrawlReport",
    "CrawlStatus",
    "CrawlManager",
    "CrawlStore",
    "get_crawl_manager",
    "normalize_url",
]