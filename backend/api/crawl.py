"""Phase 4 crawl job API: trigger + poll.

``POST /api/crawl`` registers a crawl job (returns immediately with a
``job_id``); the crawl itself runs on a background daemon thread so the API
never blocks. ``GET /api/crawl/{job_id}`` polls progress. When no jobs exist a
health-style ``jobs`` list is also available on ``GET /api/crawl``.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.config import settings
from backend.crawler.models import CrawlJobConfig
from backend.crawler.service import get_crawl_manager

router = APIRouter(prefix="/api/crawl", tags=["crawl"])


class CrawlRequest(BaseModel):
    urls: list[str] = Field(..., min_length=1, description="Seed URLs to crawl")
    allowed_domains: Optional[list[str]] = Field(
        None, description="Extra host allowlist (blank scope = seed hosts)"
    )
    max_pages: int = Field(
        settings.CRAWLER_MAX_PAGES, ge=1, le=1000, description="Page budget"
    )
    max_depth: int = Field(
        settings.CRAWLER_MAX_DEPTH, ge=0, le=32, description="Link depth budget"
    )
    delay_seconds: float = Field(
        settings.CRAWLER_DELAY_SECONDS, ge=0.0, le=120.0, description="Politeness delay"
    )
    concurrency: int = Field(
        settings.CRAWLER_CONCURRENT_REQUESTS, ge=1, le=32, description="Parallel requests"
    )
    timeout_seconds: float = Field(
        settings.CRAWLER_TIMEOUT_SECONDS, ge=1.0, le=120.0
    )
    respect_robots: bool = Field(
        default=settings.CRAWLER_RESPECT_ROBOTS, description="Honour robots.txt"
    )
    allow_private_hosts: bool = Field(
        default=False, description="Permit loopback/private addresses (tests/local)"
    )


@router.post("", status_code=201, name="crawl")
def start_crawl(request: CrawlRequest) -> dict[str, object]:
    """Create and start a crawl job; returns the job envelope."""
    config = CrawlJobConfig(
        seed_urls=tuple(request.urls),
        allowed_domains=tuple(request.allowed_domains or ()),
        max_pages=request.max_pages,
        max_depth=request.max_depth,
        delay_seconds=request.delay_seconds,
        concurrency=request.concurrency,
        timeout_seconds=request.timeout_seconds,
        user_agent=settings.CRAWLER_USER_AGENT,
        respect_robots=request.respect_robots,
        allow_private_hosts=request.allow_private_hosts,
    )
    job = get_crawl_manager().start_job(config)
    snapshot = job.to_dict()
    return {
        "job_id": snapshot["job_id"],
        "status": snapshot["status"],
        "seed_urls": snapshot["seed_urls"],
        "allowed_domains": snapshot["allowed_domains"],
        "max_pages": snapshot["max_pages"],
        "message": "crawl job accepted; poll GET /api/crawl/{job_id}",
    }


@router.get("", name="list_crawl_jobs")
def list_jobs() -> dict[str, object]:
    """Return every known crawl job (id + status + counts)."""
    jobs = get_crawl_manager().list_jobs()
    return {
        "jobs": [
            {"job_id": j.job_id, "status": j.status.value, "pages_crawled": len(j.pages)}
            for j in jobs
        ],
        "total_jobs": len(jobs),
        "crawled_documents": get_crawl_manager().store.count(),
    }


@router.get("/{job_id}", name="crawl_job_status")
def get_job(job_id: str) -> dict[str, object]:
    """Poll one crawl job; 404 for unknown/job IDs that were never created."""
    job = get_crawl_manager().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"crawl job {job_id!r} not found")
    return job.to_dict()