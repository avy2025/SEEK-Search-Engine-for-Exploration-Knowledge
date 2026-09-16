"""Phase 5B persistent-indexing acceptance tests.

These tests pin the persistent BM25 indexing pipeline contract:

* PostgreSQL is the canonical document source; the BM25 index under
  ``indexes/bm25`` is a derived, persistent artifact.
* The artifact survives restarts (load, don't rebuild).
* Refresh detects new / modified / deleted documents by comparing the
  PostgreSQL ``document_id -> content_hash`` set against the persisted index
  metadata, and reconstructs BM25 from the current PostgreSQL set whenever
  anything changed. It never mutates BM25 incrementally.
* Missing / corrupt artifacts never crash the application; while a valid
  artifact exists the search index loads even when PostgreSQL is unreachable.
* Index writes are atomic: a failed rebuild leaves the previous index usable.

Each test starts from a wiped ``documents`` table so counts are exact.
The module tears the table down at the end to leave the shared test database
clean for other test files (Phase 5A etc.).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.db.models import Document
from backend.db.repository import make_document_repository
from backend.db.repository_factory import create_initialised_document_repository
from backend.search import index_store
from backend.search.index_manager import (
    IndexManager,
    reset_index_manager,
)

_DB_URL_OVERRIDE = "SEEK_TEST_DATABASE_URL"
_DEFAULT_DB_URL = "postgresql+psycopg2://seek:seek@localhost:5432/seek"
_SKIP_REASON = "PostgreSQL unreachable; skipping Phase 5B persistence test"


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
    repo = _live_repository()
    if repo is None:
        pytest.skip(_SKIP_REASON)
    yield repo
    try:
        repo.close()
    except Exception:  # pragma: no cover - teardown best-effort
        pass


@pytest.fixture(scope="module", autouse=True)
def _wipe_after(live_repo):
    yield
    _wipe(live_repo)
    reset_index_manager()


@pytest.fixture()
def clean_db(live_repo):
    """Live repository with the ``documents`` table wiped for this test."""
    _wipe(live_repo)
    yield live_repo
    _wipe(live_repo)


def _wipe(repo) -> None:
    try:
        repo.session.query(Document).delete(synchronize_session=False)
        repo.session.commit()
    except Exception:
        repo.session.rollback()


# --------------------------------------------------------------------------- #
# data helpers
# --------------------------------------------------------------------------- #


def _make_row(i: int, *, topic: str = "quokka") -> Document:
    content = f"persistent {topic} document number {i} with unique content"
    return Document(
        title=f"Doc {i} {topic}",
        content=content,
        source=f"corpus/doc{i}.md",
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def _insert(repo, count: int, *, start: int = 1) -> list[Document]:
    inserted = []
    for i in range(start, start + count):
        row = _make_row(i)
        if repo.upsert(row):
            inserted.append(row)
    return inserted


def _make_manager(clean_db, tmp_path, **kw) -> IndexManager:
    defaults = dict(
        index_dir=str(Path(tmp_path) / "index"),
        repository=clean_db,
        repository_factory=lambda: make_document_repository(None),
        seed_corpus=False,
    )
    defaults.update(kw)
    return IndexManager(**defaults)


# --------------------------------------------------------------------------- #
# A. Full rebuild
# --------------------------------------------------------------------------- #


class TestFullRebuild:
    def test_rebuild_indexes_all_documents_from_postgresql(self, clean_db, tmp_path):
        inserted = _insert(clean_db, 10)
        assert len(inserted) == 10
        manager = _make_manager(clean_db, tmp_path)
        result = manager.rebuild(seed_corpus=False)
        assert result.documents_indexed == 10
        assert result.status == "rebuilt"
        assert result.source == "postgresql"
        assert manager.engine.document_count == 10
        assert index_store.is_index_present(manager.index_dir)
        md = index_store.read_metadata(manager.index_dir)
        assert md is not None
        assert md.document_count == 10
        assert manager.metadata.index_version >= 1


# --------------------------------------------------------------------------- #
# B + C. Search from persistent index / persistence across restart
# --------------------------------------------------------------------------- #


class TestSearchFromPersistentIndex:
    def test_search_hits_persisted_documents(self, clean_db, tmp_path):
        _insert(clean_db, 6)
        manager = _make_manager(clean_db, tmp_path)
        manager.rebuild(seed_corpus=False)
        resp = manager.engine.search("quokka", limit=10)
        assert resp.total == 6
        assert all(h.document_id for h in resp.hits)
        assert all(h.title for h in resp.hits)
        assert all(h.snippet for h in resp.hits)

    def test_persistence_across_restart(self, clean_db, tmp_path):
        _insert(clean_db, 5)
        manager = _make_manager(clean_db, tmp_path)
        manager.rebuild(seed_corpus=False)
        # "restart": new manager loads entirely from disk (not the DB).
        manager2 = _make_manager(
            clean_db, tmp_path,
            repository=make_document_repository(None),
        )
        state = manager2.load_on_startup()
        assert state["loaded"] is True
        assert state["source"] == "persistent_index"
        assert manager2.engine.document_count == 5
        assert manager2.engine.search("quokka", limit=5).total == 5
        # even a fully degraded repository still loads the cached index
        assert manager2.engine.document_count == 5

    def test_bm25_position_maps_to_document_id(self, clean_db, tmp_path):
        _insert(clean_db, 4)
        manager = _make_manager(clean_db, tmp_path)
        manager.rebuild(seed_corpus=False)
        rows = sorted(clean_db.list_all(), key=lambda r: r.document_id)
        resp = manager.engine.search("quokka", limit=4)
        indexed_ids = {h.document_id for h in resp.hits}
        assert indexed_ids == {str(r.document_id) for r in rows}


# --------------------------------------------------------------------------- #
# D–G. Change detection
# --------------------------------------------------------------------------- #


class TestChangeDetection:
    def test_new_document_detected(self, clean_db, tmp_path):
        _insert(clean_db, 5)
        manager = _make_manager(clean_db, tmp_path)
        manager.rebuild(seed_corpus=False)
        assert manager.engine.document_count == 5
        _insert(clean_db, 1, start=6)
        changes = manager.detect_changes()
        assert len(changes["new"]) == 1
        result = manager.refresh()
        assert result.status == "refreshed"
        assert manager.engine.document_count == 6
        assert result.document_count == 6

    def test_unchanged_refresh_does_not_rebuild(self, clean_db, tmp_path):
        _insert(clean_db, 4)
        manager = _make_manager(clean_db, tmp_path)
        manager.rebuild(seed_corpus=False)
        before_version = manager.metadata.index_version
        before_updated = manager.metadata.updated_at
        changes = manager.detect_changes()
        assert changes == {"new": [], "modified": [], "deleted": []}
        result = manager.refresh()
        assert result.status == "unchanged"
        assert manager.metadata.index_version == before_version
        assert manager.metadata.updated_at == before_updated

    def test_modified_document_detected(self, clean_db, tmp_path):
        _insert(clean_db, 3)
        manager = _make_manager(clean_db, tmp_path)
        manager.rebuild(seed_corpus=False)
        row = clean_db.session.query(Document).first()
        assert row is not None
        doc_id = row.document_id
        # modify content + hash in-place
        new_content = "completely rewritten numpy content with data"
        row.content = new_content
        row.content_hash = hashlib.sha256(new_content.encode("utf-8")).hexdigest()
        clean_db.session.commit()
        changes = manager.detect_changes()
        assert changes["modified"] == [str(doc_id)]
        result = manager.refresh()
        assert result.status == "refreshed"
        assert str(doc_id) in result.changed["modified"]
        hits = manager.engine.search("numpy", limit=5)
        assert any(h.document_id == str(doc_id) for h in hits.hits)

    def test_deleted_document_detected(self, clean_db, tmp_path):
        _insert(clean_db, 4)
        manager = _make_manager(clean_db, tmp_path)
        manager.rebuild(seed_corpus=False)
        row = clean_db.session.query(Document).first()
        assert row is not None
        doc_id = row.document_id
        clean_db.session.delete(row)
        clean_db.session.commit()
        changes = manager.detect_changes()
        assert changes["deleted"] == [str(doc_id)]
        result = manager.refresh()
        assert result.status == "refreshed"
        assert manager.engine.document_count == 3
        hits = manager.engine.search("quokka", limit=5)
        assert str(doc_id) not in {h.document_id for h in hits.hits}


# --------------------------------------------------------------------------- #
# H–J. Resilient startup states
# --------------------------------------------------------------------------- #


class TestResilientStartup:
    def test_missing_index_does_not_crash(self, clean_db, tmp_path):
        manager = _make_manager(clean_db, tmp_path)
        state = manager.load_on_startup()
        assert state["loaded"] is True
        assert isinstance(state["document_count"], int)

    def test_corrupt_index_does_not_crash(self, clean_db, tmp_path):
        index_dir = Path(tmp_path) / "corrupt"
        index_dir.mkdir(parents=True)
        (index_dir / index_store.ARTIFACT_FILE).write_bytes(b"not-a-pickle")
        (index_dir / index_store.METADATA_FILE).write_text("{bad json", encoding="utf-8")
        load = index_store.load_index(index_dir)
        assert load.valid is False
        assert load.reason
        manager = _make_manager(clean_db, tmp_path, index_dir=str(index_dir))
        state = manager.load_on_startup()
        # corrupted: rebuild from PostgreSQL succeeds (empty or populated)
        assert state["loaded"] is True
        assert manager.engine.document_count >= 0

    def test_postgresql_unavailable_with_valid_index(self, clean_db, tmp_path):
        _insert(clean_db, 5)
        manager = _make_manager(clean_db, tmp_path)
        manager.rebuild(seed_corpus=False)
        # load via a fully-degraded repository (simulates PG down at restart)
        degraded = _make_manager(
            clean_db, tmp_path,
            repository=make_document_repository(None),
        )
        state = degraded.load_on_startup()
        assert state["loaded"] is True
        assert state["source"] == "persistent_index"
        assert degraded.engine.search("quokka", limit=5).total == 5
        status = degraded.status()
        assert status["database_available"] is False
        assert status["index_exists"] is True
        assert status["loaded"] is True
        assert status["stale"] is None


# --------------------------------------------------------------------------- #
# K. Atomic rebuild failure
# --------------------------------------------------------------------------- #


class TestAtomicRebuild:
    def test_failed_rebuild_leaves_previous_index_usable(
        self, clean_db, tmp_path, monkeypatch
    ):
        _insert(clean_db, 4)
        manager = _make_manager(clean_db, tmp_path)
        manager.rebuild(seed_corpus=False)
        old_metadata = index_store.read_metadata(manager.index_dir)

        def _boom(*a, **kw):
            raise RuntimeError("simulated save failure")

        monkeypatch.setattr(index_store, "save_index", _boom)
        with pytest.raises(RuntimeError):
            manager.rebuild(seed_corpus=False)
        # artifact still valid + old engine still works
        assert index_store.is_index_present(manager.index_dir)
        assert index_store.read_metadata(manager.index_dir) == old_metadata
        assert manager.engine.document_count == 4
        assert manager.engine.search("quokka", limit=5).total == 4


# --------------------------------------------------------------------------- #
# L. API integration
# --------------------------------------------------------------------------- #


class TestIndexAPI:
    def test_status_endpoint_fields(self, clean_db, tmp_path, monkeypatch):
        _insert(clean_db, 3)
        monkeypatch.setattr(settings, "STORAGE_INDEX_PATH", str(tmp_path / "api"))
        monkeypatch.setattr(settings, "DATABASE_URL", _test_database_url())
        monkeypatch.setattr(settings, "SAMPLE_CORPUS_DIR", str(tmp_path / "corpus"))
        reset_index_manager()
        from backend.main import app as fastapi_app

        with TestClient(fastapi_app) as client:
            res = client.get("/api/index/status")
            assert res.status_code == 200
            data = res.json()
            for key in (
                "index_exists",
                "loaded",
                "document_count",
                "database_available",
                "index_version",
                "message",
            ):
                assert key in data
            assert data["loaded"] is True
            assert data["document_count"] >= 3

    def test_rebuild_search_refresh_via_api(self, clean_db, tmp_path, monkeypatch):
        _insert(clean_db, 6)
        monkeypatch.setattr(settings, "STORAGE_INDEX_PATH", str(tmp_path / "api2"))
        monkeypatch.setattr(settings, "DATABASE_URL", _test_database_url())
        monkeypatch.setattr(settings, "SAMPLE_CORPUS_DIR", str(tmp_path / "corpus2"))
        reset_index_manager()
        from backend.main import app as fastapi_app

        with TestClient(fastapi_app) as client:
            # --- rebuild ------------------------------------------------
            rebuild = client.post("/api/index/rebuild")
            assert rebuild.status_code == 200, rebuild.text
            data = rebuild.json()
            assert data["documents_indexed"] == 6
            assert data["source"] == "postgresql"
            assert data["status"] == "rebuilt"
            assert data["crawled_documents"] == 0
            assert "index_version" in data

            # --- status -------------------------------------------------
            status = client.get("/api/index/status").json()
            assert status["loaded"] is True
            assert status["document_count"] == 6
            assert status["stale"] is False

            # --- search -------------------------------------------------
            search = client.get(
                "/api/search", params={"q": "quokka", "limit": 10}
            )
            assert search.status_code == 200
            assert search.json()["total"] == 6
            titles = [h["title"].lower() for h in search.json()["hits"]]
            assert any("quokka" in t for t in titles)

            # --- refresh (unchanged) ------------------------------------
            refresh = client.post("/api/index/refresh")
            assert refresh.status_code == 200
            rdata = refresh.json()
            assert rdata["status"] == "unchanged"
            assert rdata["document_count"] == 6

    def test_empty_index_search_returns_hits_not_fake(
        self, clean_db, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(settings, "STORAGE_INDEX_PATH", str(tmp_path / "api3"))
        monkeypatch.setattr(settings, "DATABASE_URL", _test_database_url())
        monkeypatch.setattr(settings, "SAMPLE_CORPUS_DIR", str(tmp_path / "corpus3"))
        reset_index_manager()
        from backend.main import app as fastapi_app

        with TestClient(fastapi_app) as client:
            # auto-rebuild on lifespan (empty table)
            search = client.get("/api/search", params={"q": "xyzzy"})
            assert search.status_code == 200
            data = search.json()
            assert data["total"] == 0
            assert data["hits"] == []
            assert data["message"]  # non-empty status message