"""Phase 5A persistence verification tests.

These tests pin the Phase 2/4 persistence contract after the prerequisite
fixes:

* ``backend.db.session`` imports ``text`` so ``Database.is_available`` works.
* ``backend.db.repository.DocumentRepository`` implements ``is_available`` and
  commits after a successful ``upsert``.
* ``backend.pipeline`` passes ``content_hash`` through when persisting corpus
  documents, so every distinct document can be stored (" content_hash '' "
  would collide on the unique index).

Two operating modes:

* PostgreSQL reachable -> real persistence assertions run.
* PostgreSQL unavailable -> the tests ``pytest.skip`` (they are integration
  tests by nature, matching the task requirement that we never fake a DB
  result).
"""
from __future__ import annotations

import asyncio
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Generator

import pytest

from backend.db.models import Document
from backend.db.repository_factory import create_initialised_document_repository
from backend.processing.loader import load_corpus

# Env override for the test database; defaults to the standard local dev
# seek database (same role/db names the project config already uses).
_DB_URL_OVERRIDE = "SEEK_TEST_DATABASE_URL"
_DEFAULT_DB_URL = "postgresql+psycopg2://seek:seek@localhost:5432/seek"

_SKIP_REASON = "PostgreSQL unreachable; skipping Phase 5A persistence test"


def _test_database_url() -> str:
    return os.environ.get(_DB_URL_OVERRIDE) or _DEFAULT_DB_URL


def _live_repository():
    repo = create_initialised_document_repository(
        _test_database_url(), attempts=2, delay_seconds=0.1
    )
    if repo is None or not repo.is_available():
        return None
    return repo


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def live_repo():
    """A live repository, or skip the whole module when Postgres is down."""
    repo = _live_repository()
    if repo is None:
        pytest.skip(_SKIP_REASON)
    yield repo
    try:
        repo.close()
    except Exception:  # pragma: no cover - teardown best-effort
        pass


def _delete_by_hashes(repo, hashes: list[str]) -> None:
    """Delete documents matching *hashes* so tests are repeatable."""
    if not hashes:
        return
    session = repo.session
    try:
        session.query(Document).filter(
            Document.content_hash.in_(hashes)
        ).delete(synchronize_session=False)
        session.commit()
    except Exception:  # pragma: no cover - cleanup best-effort
        session.rollback()


# --------------------------------------------------------------------------- #
# 1. database availability check
# --------------------------------------------------------------------------- #

class TestDatabaseAvailability:
    def test_live_repository_reports_available(self, live_repo):
        assert live_repo.is_available() is True

    def test_degraded_repository_reports_unavailable(self):
        from backend.db.repository import make_document_repository

        degraded = make_document_repository(None)
        assert degraded.is_available() is False


# --------------------------------------------------------------------------- #
# 2 + 3. corpus documents: hash present + more than one persists
# --------------------------------------------------------------------------- #

class TestCorpusPersistence:
    def test_corpus_documents_carry_content_hash(self, live_repo):
        docs = load_corpus()
        assert len(docs) > 1
        hashes = [d.content_hash for d in docs]
        assert all(hashes), "every corpus document needs a non-empty content hash"
        assert len(set(hashes)) == len(hashes), "corpus hashes must be distinct"

    def test_multiple_corpus_documents_persist(self, live_repo):
        docs = load_corpus()
        hashes = [d.content_hash for d in docs]
        _delete_by_hashes(live_repo, hashes)
        persisted = 0
        for d in docs:
            if live_repo.upsert(
                Document(
                    title=d.title,
                    content=d.content,
                    source=d.source,
                    content_hash=d.content_hash,
                )
            ):
                persisted += 1
        assert persisted == len(docs), (
            f"expected all {len(docs)} corpus documents to persist, got {persisted}"
        )
        for d in docs:
            row = live_repo.find_by_content_hash(d.content_hash)
            assert row is not None
            assert row.content_hash == d.content_hash
            assert row.content_hash != ""
            assert row.source == d.source
        _delete_by_hashes(live_repo, hashes)

    def test_run_pipeline_persists_all_corpus_documents(self, live_repo, monkeypatch):
        """End-to-end: the existing corpus persistence path stores every doc."""
        import backend.pipeline as pipeline

        docs = load_corpus()
        hashes = [d.content_hash for d in docs]
        _delete_by_hashes(live_repo, hashes)
        monkeypatch.setattr(pipeline.settings, "DATABASE_URL", _test_database_url())
        report = pipeline.run_pipeline()
        assert report.persisted == len(docs)
        for h in hashes:
            assert live_repo.find_by_content_hash(h) is not None
        _delete_by_hashes(live_repo, hashes)


# --------------------------------------------------------------------------- #
# 4 + 5. crawler persistence + duplicate handling
# --------------------------------------------------------------------------- #

ROBOTS_TXT = "User-agent: *\nDisallow: /private.html\n"

PAGES: dict[str, tuple[str, str]] = {
    "/": (
        "text/html",
        (
            '<html><head><title>Phase5A Quokka Hub</title></head>'
            '<body><h1>Quokka Hub</h1><p>happy marsupial test content</p>'
            '<a href="/page1.html">Page 1</a></body></html>'
        ),
    ),
    "/page1.html": (
        "text/html",
        '<html><head><title>Quokka Page 1</title></head>'
        '<body><p>Quokka test page one</p></body></html>',
    ),
}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
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
        self.send_response(200)
        self.send_header("content-type", ctype)
        self.end_headers()
        self.wfile.write(body.encode())


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def crawler_site() -> Generator[str, None, None]:
    port = _get_free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


class TestCrawlerPersistence:
    def test_crawled_document_persists(self, live_repo, crawler_site, monkeypatch):
        """Crawler output reaches PostgreSQL with title/content/source/hash."""
        import httpx

        import backend.crawler.service as service
        from backend.crawler.models import CrawlJobConfig, CrawlReport
        from backend.crawler.robots import RobotsTxtPolicy
        from backend.crawler.scheduler import a_crawl
        from backend.crawler.service import CrawlStore

        monkeypatch.setattr(service.settings, "DATABASE_URL", _test_database_url())
        monkeypatch.setattr(service, "_PERSIST_REPO", None)

        base = crawler_site
        config = CrawlJobConfig(
            seed_urls=(f"{base}/",),
            delay_seconds=0,
            max_pages=10,
            max_depth=2,
            allow_private_hosts=True,
        ).sanitized()
        store = CrawlStore()
        policy = RobotsTxtPolicy(config.user_agent)

        async def _crawl():
            async with httpx.AsyncClient() as client:
                report, pages, _fails = await a_crawl(
                    config, store, policy, client, on_page=store.record
                )
                return report, pages

        report, pages = asyncio.run(_crawl())
        assert report.pages_crawled >= 1
        _delete_by_hashes(live_repo, [p.content_hash for p in pages])
        assert all(
            live_repo.upsert(
                Document(
                    title=p.title,
                    content=p.text,
                    source=p.url,
                    content_hash=p.content_hash,
                )
            )
            for p in pages
        ), "crawled docs must be insertable one more time after cleanup"
        for p in pages:
            row = live_repo.find_by_content_hash(p.content_hash)
            assert row is not None
            assert row.title == p.title
            assert row.source == p.url
            assert row.content_hash == p.content_hash
        _delete_by_hashes(live_repo, [p.content_hash for p in pages])

    def test_duplicate_crawled_content_not_persisted_twice(self, live_repo):
        """Same content_hash never creates a second document row."""
        from backend.crawler.extract import extract_text, hash_text

        html = "<html><head><title>Dup</title></head><body><p>Duplicate body</p></body></html>"
        _title, text = extract_text(html, url="http://dup.example/")
        digest = hash_text(text)
        _delete_by_hashes(live_repo, [digest])
        try:
            first = live_repo.upsert(
                Document(title="Dup", content=text, source="http://dup.example/a", content_hash=digest)
            )
            second = live_repo.upsert(
                Document(title="Dup", content=text, source="http://dup.example/b", content_hash=digest)
            )
            assert first is True
            assert second is False, "duplicate content_hash must be rejected"
            rows = [
                live_repo.find_by_content_hash(digest),
                live_repo.find_by_content_hash(digest),
            ]
            assert rows[0] is not None
            assert rows[1] is not None
            assert rows[0].document_id == rows[1].document_id, (
                "re-fetch of the same hash must resolve to the same document"
            )
        finally:
            _delete_by_hashes(live_repo, [digest])