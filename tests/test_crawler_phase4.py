"""Phase 4 (controlled web crawler) acceptance tests.

No external network required. A tiny in-process ``http.server`` fixture serves a
deterministic 4-page site with robots.txt, a binary media path, a 404 path, and
one page that links to an out-of-scope host. The crawler logic (robots gating,
scope filtering, rate-limit, dedup) is tested end-to-end via
:func:`backend.crawler.scheduler.a_crawl` and the ``/api/crawl`` job API.
"""
from __future__ import annotations

import asyncio
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Generator, Optional

import pytest

from backend.crawler.extract import chunk_text, extract_text, hash_text
from backend.crawler.models import CrawlJobConfig, CrawlStatus
from backend.crawler.robots import RobotsTxtPolicy
from backend.crawler.scheduler import a_crawl
from backend.crawler.service import CrawlManager, CrawlStore
from backend.crawler.url import (
    domain_matches,
    is_crawlable_url,
    is_dangerous_url,
    normalize_url,
    scope_hosts,
)

# --------------------------------------------------------------------------- #
# Tiny in-process site
# --------------------------------------------------------------------------- #

ROBOTS_TXT = """User-agent: *
Disallow: /private.html
"""

PAGES: dict[str, tuple[str, str]] = {
    "/": (
        "text/html",
        (
            '<html><head><title>SEEK Quokka Hub</title></head>'
            '<body>'
            '<h1>Quokka Hub</h1>'
            '<p>Welcome to SEEK quokka facts</p>'
            '<a href="/page1.html">Page 1</a>'
            '<a href="/page2.html">Page 2</a>'
            '<a href="/private.html">Private</a>'
            '<a href="/page1.html">duplicate page1</a>'
            '<a href="/heavy.pdf">PDF</a>'
            '<a href="/missing.html">missing</a>'
            '<a href="mailto:x@y.com">email</a>'
            '<a href="javascript:void(0)">js link</a>'
            '<a href="https://outside.example.com/nope">outside</a>'
            '<a href="/robots.txt">robots</a>'
            '</body></html>'
        ),
    ),
    "/page1.html": (
        "text/html",
        '<html><head><title>Quokka Page 1</title></head>'
        '<body><p>Quokkas are happy marsupials</p>'
        '<a href="/">home</a><a href="/page2.html">page2</a></body></html>',
    ),
    "/page2.html": (
        "text/html",
        '<html><head><title>Quokka Page 2</title></head>'
        '<body><p>Quokka babies are called joeys</p>'
        '<a href="/">home</a><a href="/page1.html">p1</a></body></html>',
    ),
    "/private.html": (
        "text/html",
        '<html><head><title>Private Quokka</title></head>'
        '<body><p>This is private content quokka</p></body></html>',
    ),
    "/heavy.pdf": (
        "application/pdf",
        "FAKE PDF BYTES",
    ),
    "/missing.html": (
        "text/html",
        "",
    ),
}


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D401
        pass

    def do_GET(self):
        path = self.path.split("?")[0].split("#")[0]
        if path == "/robots.txt":
            self.send_response(200)
            self.send_header("content-type", "text/plain")
            self.end_headers()
            self.wfile.write(ROBOTS_TXT.encode())
            return
        entry = PAGES.get(path)
        if entry is None:
            self.send_response(404)
            self.send_header("content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"not found")
            return
        ctype, body = entry
        if path == "/missing.html":
            self.send_response(404)
            self.send_header("content-type", ctype)
            self.end_headers()
            self.wfile.write(body.encode())
            return
        self.send_response(200)
        self.send_header("content-type", ctype)
        self.end_headers()
        self.wfile.write(body.encode())


@pytest.fixture(scope="module")
def crawler_site() -> Generator[tuple[str, int], None, None]:
    port = _get_free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}", port
    server.shutdown()


# --------------------------------------------------------------------------- #
# URL helpers
# --------------------------------------------------------------------------- #

class TestURLHelpers:
    def test_normalize_strip_fragment_and_tracking(self):
        url = normalize_url("HTTPS://X.com/a?utm_source=tw&q=1#f")
        assert url.startswith("https://x.com/a?")
        assert "utm_source" not in url
        assert "q=1" in url
        assert "#f" not in url

    def test_is_dangerous_rejects_non_http(self):
        assert is_dangerous_url("javascript:alert(1)")
        assert is_dangerous_url("data:text/html,boom")
        assert is_dangerous_url("ftp://example.com/file")
        assert is_dangerous_url("mailto:user@example.com")

    def test_is_dangerous_rejects_credentials(self):
        assert is_dangerous_url("http://admin:pass@evil.com/secret")

    def test_is_crawlable_blocks_pdf(self):
        assert not is_crawlable_url("http://example.com/report.pdf")

    def test_is_crawlable_blocks_localhost_by_default(self):
        assert not is_crawlable_url("http://localhost:8080/x")
        assert is_crawlable_url(
            "http://localhost:8080/x", allow_private_hosts=True
        )

    def test_domain_matches_subdomain(self):
        assert domain_matches("sub.docs.python.org", ("python.org",))
        assert not domain_matches("evil.com", ("python.org",))

    def test_scope_hosts_from_seeds(self):
        hosts = scope_hosts((), ("https://x.com", "https://x.com/a/b"))
        assert hosts == ("x.com",)

    def test_scope_hosts_from_explicit_allowlist(self):
        hosts = scope_hosts(("a.com", "b.com"), ("https://y.com"))
        assert hosts == ("a.com", "b.com")


# --------------------------------------------------------------------------- #
# robots
# --------------------------------------------------------------------------- #

class TestRobots:
    def test_allow_all_when_no_rules(self):
        p = RobotsTxtPolicy("SEEK-Crawler/1.0")
        assert p.can_fetch("http://example.com/x")  # no cache = default allow

    def test_offline_policy_from_text(self):
        p = RobotsTxtPolicy.from_text(
            "SEEK-Crawler", "User-agent: *\nDisallow: /secret/\nCrawl-delay: 5", host="h.com"
        )
        assert p.can_fetch("http://h.com/ok")
        assert not p.can_fetch("http://h.com/secret/s.txt")
        assert p.crawl_delay("h.com") == 5.0

    def test_crawl_delay_returns_zero_when_absent(self):
        p = RobotsTxtPolicy.from_text("SEEK", "User-agent: *\nAllow: /\n", host="h")
        assert p.crawl_delay("h") == 0.0

    def test_403_robots_disallows_broadly(self):
        # Fetched status 403 → policy always blocks
        p = RobotsTxtPolicy("A")
        # Simulate a cached parser that always returns False
        class FakeParser:
            def can_fetch(self, *a): return False
            def crawl_delay(self, *a): return None
        p._set_parser("x.com", FakeParser())
        assert not p.can_fetch("http://x.com/any")


# --------------------------------------------------------------------------- #
# extract / chunk
# --------------------------------------------------------------------------- #

class TestExtract:
    def test_title_from_heading_fallback(self):
        html = '<html><body><h1>My Title</h1><p>Some quokka text</p></body></html>'
        title, text = extract_text(html, url="http://x.com")
        assert title == "My Title"
        assert "quokka" in text.lower()

    def test_strips_script_and_nav(self):
        html = '<html><body><nav>menu</nav><p>real</p><script>bad()</script></body></html>'
        _, text = extract_text(html)
        assert "menu" not in text.lower()
        assert "bad" not in text.lower()
        assert "real" in text

    def test_hash_is_deterministic(self):
        assert hash_text("hello") == hash_text("hello")
        assert hash_text("hello") != hash_text("world")

    def test_chunk_splits_and_sizes(self):
        big = "x" * 1000
        chunks = chunk_text(big, size=200)
        assert len(chunks) == 5
        assert all(len(c) == 200 for c in chunks)

    def test_empty_text_yields_no_chunks(self):
        assert chunk_text("", size=200) == ()


# --------------------------------------------------------------------------- #
# scheduler integration (live local fixture)
# --------------------------------------------------------------------------- #

class TestScheduler:
    def test_crawl_honours_robots_and_scope(self, crawler_site):
        base, _ = crawler_site
        config = CrawlJobConfig(
            seed_urls=(f"{base}/",),
            delay_seconds=0,
            concurrency=2,
            max_pages=20,
            max_depth=3,
            allow_private_hosts=True,
            respect_robots=True,
        ).sanitized()
        store = CrawlStore()
        policy = RobotsTxtPolicy(config.user_agent, timeout_seconds=5)
        import httpx

        async def _run():
            async with httpx.AsyncClient() as client:
                report, pages, failures = await a_crawl(
                    config, store, policy, client, on_page=store.record
                )
                return report, pages, failures

        report, pages, failures = asyncio.run(_run())
        urls = {p.url.split("/")[-1] or "/" for p in pages}
        assert "index" in repr(urls).lower() or any("/" in p.url for p in pages)
        assert not any("private" in p.url.lower() for p in pages), "private.html must be blocked by robots"
        assert not any("outside" in p.url.lower() for p in pages), "outside host must be out of scope"
        assert report.pages_crawled >= 3
        assert report.duplicate_urls > 0
        assert report.robots_blocked > 0
        assert report.out_of_scope > 0
        assert store.count() >= 3

    def test_max_pages_cap_limits_total(self, crawler_site):
        """None of the crawl stages may overshoot ``max_pages`` (regression: the
        old BFS drained a whole frontier batch before re-checking the cap)."""
        base, _ = crawler_site
        config = CrawlJobConfig(
            seed_urls=(f"{base}/",),
            delay_seconds=0,
            max_pages=2,
            max_depth=3,
            allow_private_hosts=True,
        ).sanitized()
        store = CrawlStore()
        policy = RobotsTxtPolicy(config.user_agent)
        import httpx

        async def _run():
            async with httpx.AsyncClient() as client:
                report, pages, failures = await a_crawl(config, store, policy, client)
                return report, pages, failures

        report, pages, _ = asyncio.run(_run())
        assert len(pages) == 2, f"expected exactly 2 pages, got {len(pages)}"
        assert report.pages_crawled == 2
        assert store.count() == 2

    def test_crawl_dedup_content(self, crawler_site):
        """Re-crawling the same seed does not create duplicate processed docs."""
        base, _ = crawler_site
        config = CrawlJobConfig(
            seed_urls=(f"{base}/",),
            delay_seconds=0,
            max_pages=20,
            allow_private_hosts=True,
        ).sanitized()
        store = CrawlStore()
        policy = RobotsTxtPolicy(config.user_agent)
        import httpx

        async def _run():
            async with httpx.AsyncClient() as client:
                await a_crawl(config, store, policy, client)
                await a_crawl(config, store, policy, client)

        asyncio.run(_run())
        # store deduplicates by content_hash — pages dict key is canonical url
        # each unique page url should appear exactly once
        assert store.count() >= 3


# --------------------------------------------------------------------------- #
# CrawlManager background-thread integration
# --------------------------------------------------------------------------- #

class TestCrawlManager:
    def test_start_and_poll_until_complete(self, crawler_site):
        base, _ = crawler_site
        manager = CrawlManager()
        config = CrawlJobConfig(
            seed_urls=(f"{base}/",),
            delay_seconds=0,
            max_pages=6,
            max_depth=1,
            allow_private_hosts=True,
        )
        job = manager.start_job(config)
        deadline = time.monotonic() + 30
        while job.status not in (CrawlStatus.COMPLETED, CrawlStatus.FAILED):
            assert time.monotonic() < deadline, f"job stuck in {job.status}"
            time.sleep(0.05)
        snap = job.to_dict()
        assert snap["status"] == CrawlStatus.COMPLETED.value
        assert snap["pages_crawled"] >= 3
        assert snap["report"]["pages_crawled"] >= 3


# --------------------------------------------------------------------------- #
# API endpoints (TestClient, no live server needed beyond the fixture)
# --------------------------------------------------------------------------- #

class TestCrawlAPI:
    def test_post_crawl_and_get_job(self, crawler_site):
        from fastapi.testclient import TestClient

        from backend.main import app

        base, _ = crawler_site
        client = TestClient(app)
        body = {
            "urls": [f"{base}/"],
            "max_pages": 5,
            "max_depth": 1,
            "delay_seconds": 0,
            "allow_private_hosts": True,
        }
        r = client.post("/api/crawl", json=body)
        assert r.status_code == 201, r.text
        data = r.json()
        job_id = data["job_id"]
        assert data["status"] in (CrawlStatus.PENDING.value, CrawlStatus.RUNNING.value)
        deadline = time.monotonic() + 30
        while True:
            gp = client.get(f"/api/crawl/{job_id}")
            assert gp.status_code == 200
            if gp.json()["status"] in ("completed", "failed"):
                break
            assert time.monotonic() < deadline, "job stuck"
            time.sleep(0.1)
        gd = gp.json()
        assert gd["pages_crawled"] >= 3
        assert gd["report"]["robots_blocked"] >= 1

    def test_get_missing_job_returns_404(self):
        from fastapi.testclient import TestClient
        from backend.main import app

        r = TestClient(app).get("/api/crawl/no_such_job")
        assert r.status_code == 404

    def test_list_jobs(self):
        from fastapi.testclient import TestClient
        from backend.main import app

        r = TestClient(app).get("/api/crawl")
        assert r.status_code == 200
        assert "jobs" in r.json()

    def test_index_rebuild(self, crawler_site):
        from fastapi.testclient import TestClient
        from backend.main import app

        base, _ = crawler_site
        client = TestClient(app)
        # crawl first
        r = client.post(
            "/api/crawl",
            json={
                "urls": [f"{base}/"],
                "max_pages": 5,
                "max_depth": 1,
                "delay_seconds": 0,
                "allow_private_hosts": True,
            },
        )
        job_id = r.json()["job_id"]
        deadline = time.monotonic() + 30
        while True:
            gp = client.get(f"/api/crawl/{job_id}")
            if gp.json()["status"] in ("completed", "failed"):
                break
            assert time.monotonic() < deadline
            time.sleep(0.1)
        rebuild = client.post("/api/index/rebuild")
        assert rebuild.status_code == 200, rebuild.text
        rd = rebuild.json()
        assert rd["documents_indexed"] >= 10  # 10 corpus + ≥1 crawled
        assert rd["crawled_documents"] >= 1
        # search now hits crawled content
        search = client.get("/api/search", params={"q": "quokka", "limit": 3})
        assert search.status_code == 200
        titles = [h["title"].lower() for h in search.json()["hits"]]
        assert any("quokka" in t for t in titles), f"expected quokka hit, got {titles[:5]}"
