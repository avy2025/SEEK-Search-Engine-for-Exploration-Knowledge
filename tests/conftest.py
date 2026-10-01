"""Shared, fully offline fixtures for the SEEK pytest suite (Phase 10).

Phase 10 consolidates the per-phase test modules, so the fixtures that every
group needs live here instead of being copy-pasted:

* :func:`make_document` / :data:`SAMPLE_DOCUMENTS` — deterministic corpus
  doubles, so ranking/snippet/enrichment assertions never depend on
  ``data/sample_corpus``;
* :class:`FakeRepository` — an in-memory stand-in for
  :class:`~backend.db.repository.DocumentRepository` (the ``documents`` rows are
  ``SimpleNamespace`` objects, exactly like the real SQLAlchemy rows for every
  attribute SEEK reads);
* :func:`degraded_repository` — the "PostgreSQL is down" repository, so the
  degraded code paths are exercised instead of paid for with a connect timeout;
* :func:`offline_index` — a process-wide ``IndexManager`` wired to a temporary
  index directory and the degraded repository, which is what makes the API
  tests hermetic (no ``indexes/`` writes, no database round-trip);
* :func:`client` — a ``TestClient`` for the real ASGI app.

**No fixture downloads a model, opens a socket to the internet or requires
PostgreSQL.** The tests that genuinely need those are gated explicitly (FAISS
availability, ``SEEK_TEST_DATABASE_URL``) and skip cleanly when unavailable.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Optional

import pytest
from fastapi.testclient import TestClient

from backend.db.models import Document
from backend.db.repository import DocumentRepository, make_document_repository
from backend.main import app
from backend.processing.models import ProcessedDocument
from backend.search.engine import SearchEngine
from backend.search.index_manager import get_index_manager, reset_index_manager
from backend.search.models import SearchResponse, SearchResult
from backend.search.semantic import (
    get_semantic_index_manager,
    reset_semantic_index_manager,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = REPO_ROOT / "frontend"


# --------------------------------------------------------------------------- #
# corpus doubles
# --------------------------------------------------------------------------- #

_PY_BODY = (
    "Python is a high-level programming language. Use `def greet(name):` to define "
    "a function and then call greet() from your module."
)
_DOCKER_BODY = (
    "Docker packages an application in a container. Run `docker run -it ubuntu` to "
    "start a container image."
)
_README_BODY = (
    "# SearchEngine reference\n\n"
    "The SearchEngine builds a BM25 index. Call create_engine() to load documents.\n\n"
    "```python\n"
    "def create_engine():\n"
    "    return SearchEngine(documents)\n"
    "```\n"
)
_ML_BODY = "Machine learning models learn patterns from training data."


def make_document(
    document_id: str,
    title: str,
    content: str,
    source: str = "",
) -> ProcessedDocument:
    """Build one deterministic :class:`ProcessedDocument` from raw text."""
    return ProcessedDocument(
        document_id=document_id,
        title=title,
        content=content,
        source=source or f"corpus/{document_id}.md",
        tokens=tuple(content.lower().split()),
        snippet_tokens=tuple(content.split()),
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


@pytest.fixture
def doc():
    """Factory fixture: :func:`make_document` bound into the test namespace."""
    return make_document


@pytest.fixture
def sample_documents() -> list[ProcessedDocument]:
    """Four documents covering the Python / Docker / code / ML vocabulary."""
    return [
        make_document("py-1", "Python Guide", _PY_BODY, "https://docs.python.org/tutorial"),
        make_document("dk-1", "Docker Guide", _DOCKER_BODY, "https://docs.docker.com/guide"),
        make_document("rd-1", "SearchEngine reference", _README_BODY, "docs/reference.md"),
        make_document("ml-1", "Machine Learning", _ML_BODY, "https://example.org/ml"),
    ]


# --------------------------------------------------------------------------- #
# repository doubles
# --------------------------------------------------------------------------- #


class FakeRepository(DocumentRepository):
    """In-memory ``DocumentRepository`` over plain row objects.

    SEEK only ever reads ``document_id`` / ``title`` / ``content`` / ``source`` /
    ``content_hash`` off a row, so a ``SimpleNamespace`` row is indistinguishable
    from a SQLAlchemy one for every code path under test. Extra in-memory state
    (``available``, ``fail_with``) makes the degraded/error branches reachable
    without a database.
    """

    def __init__(
        self,
        rows: Iterable[Any] = (),
        *,
        available: bool = True,
        fail_with: Optional[Exception] = None,
    ) -> None:
        super().__init__(session=object())  # non-None so is_available() probes
        self.rows: list[Any] = list(rows)
        self.available = available
        self.fail_with = fail_with
        self.closed = False
        self.list_all_calls: list[Optional[int]] = []
        self.upserted: list[Any] = []

    # -- helpers ---------------------------------------------------------------
    @staticmethod
    def row(
        document_id: Any,
        *,
        title: str = "",
        content: str = "",
        source: str = "",
        content_hash: str = "",
    ) -> SimpleNamespace:
        return SimpleNamespace(
            document_id=document_id,
            title=title,
            content=content,
            source=source,
            content_hash=content_hash,
        )

    @classmethod
    def from_documents(
        cls, documents: Iterable[ProcessedDocument], **kw: Any
    ) -> "FakeRepository":
        return cls(
            [
                cls.row(
                    doc.document_id,
                    title=doc.title,
                    content=doc.content,
                    source=doc.source,
                    content_hash=doc.content_hash,
                )
                for doc in documents
            ],
            **kw,
        )

    # -- DocumentRepository surface -------------------------------------------
    def is_available(self) -> bool:
        if self.fail_with is not None:
            return False
        return bool(self.available)

    def list_all(self, *, limit: Optional[int] = None) -> list[Any]:
        self.list_all_calls.append(limit)
        if self.fail_with is not None:
            return []
        rows = sorted(self.rows, key=lambda r: _as_sort_key(r.document_id))
        if limit is not None:
            rows = rows[: max(0, int(limit))]
        return list(rows)

    def count(self) -> int:
        return len(self.list_all())

    def find_by_content_hash(self, content_hash: str) -> Optional[Any]:
        """Return the seeded row *or* the document this instance already wrote."""
        for row in self.rows:
            if row.content_hash == content_hash:
                return row
        for document in self.upserted:
            if document.content_hash == content_hash:
                return document
        return None

    def upsert(self, document: Document) -> bool:
        if self.find_by_content_hash(document.content_hash) is not None:
            return False
        self.upserted.append(document)
        return True

    def upsert_many(self, documents: list[Document]) -> int:
        return sum(1 for doc in documents if self.upsert(doc))

    def close(self) -> None:
        self.closed = True


def _as_sort_key(value: Any):
    """Order rows numerically when possible, lexicographically otherwise."""
    try:
        return (0, int(value), "")
    except (TypeError, ValueError):
        return (1, 0, str(value))


@pytest.fixture
def degraded_repository() -> DocumentRepository:
    """The canonical "PostgreSQL unreachable" repository (never raises)."""
    return make_document_repository(None)


@pytest.fixture
def fake_repository() -> FakeRepository:
    """An available in-memory repository, ready for rows."""
    return FakeRepository()


# --------------------------------------------------------------------------- #
# process-wide singletons
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _isolate_process_singletons():
    """Drop the process-wide managers around every test.

    ``backend.search.index_manager``, ``backend.search.semantic`` and
    ``backend.crawler.service._manager`` are process-wide singletons (that is
    what makes ``/api/search``, ``/api/index/rebuild`` and ``/api/crawl`` share
    one live engine / job registry). Without this reset a test that installs a
    temporary engine, or registers a crawl job, would leak it into the next one.

    Only the managers are reset - the embedding generator singleton is left alone
    so a real model loaded by the Phase 6 live tier stays cached.
    """
    reset_index_manager()
    reset_semantic_index_manager()
    _reset_crawl_manager()
    yield
    reset_index_manager()
    reset_semantic_index_manager()
    _reset_crawl_manager()


def _reset_crawl_manager() -> None:
    """Replace the crawl manager singleton with a fresh, empty one."""
    import backend.crawler.service as crawl_service

    manager = crawl_service.get_crawl_manager()
    with manager._lock:  # noqa: SLF001 - test-only reset of a documented singleton
        manager._jobs.clear()  # noqa: SLF001
    manager._store = crawl_service.CrawlStore()  # noqa: SLF001


@pytest.fixture
def offline_semantic(monkeypatch, tmp_path):
    """The *real* semantic manager with a degraded database and an isolated
    artifact directory.

    ``SemanticIndexManager.status()`` / ``rebuild()`` probe PostgreSQL on every
    call, which costs a multi-second connect timeout when the database is down.
    Pinning the repository factory to the degraded repository keeps the API
    suite fast **and** exercises the genuine "PostgreSQL unreachable" branches
    instead of monkeypatching the manager away.
    """
    from backend.search.semantic import get_semantic_index_manager

    manager = get_semantic_index_manager()
    monkeypatch.setattr(
        manager, "_repo_factory", lambda: make_document_repository(None)
    )
    monkeypatch.setattr(manager, "_repository", make_document_repository(None))
    monkeypatch.setattr(manager, "_index_dir", tmp_path / "faiss")
    return manager


@pytest.fixture
def offline_index(monkeypatch, tmp_path, sample_documents):
    """A live ``IndexManager`` with the sample corpus, an isolated index dir
    and a degraded repository.

    This is the fixture that makes the whole API suite hermetic: no database
    probe (the degraded repository answers instantly), and every artifact write
    lands under ``tmp_path`` instead of the repository's ``indexes/`` tree.

    It pins the *semantic* manager too. ``_lexical_search`` appends
    ``get_semantic_index_manager().status()`` to every response, and that status
    call re-probes PostgreSQL — which is a multi-second (occasionally very long)
    connect timeout whenever the database is unreachable.
    """
    manager = get_index_manager()
    monkeypatch.setattr(
        manager, "_repo_factory", lambda: make_document_repository(None)
    )
    monkeypatch.setattr(manager, "_repository", make_document_repository(None))
    index_dir = tmp_path / "bm25"
    index_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(manager, "_index_dir", index_dir)

    semantic = get_semantic_index_manager()
    monkeypatch.setattr(
        semantic, "_repo_factory", lambda: make_document_repository(None)
    )
    monkeypatch.setattr(semantic, "_repository", make_document_repository(None))
    monkeypatch.setattr(semantic, "_index_dir", tmp_path / "faiss")

    manager.set_engine(SearchEngine(sample_documents))
    return manager


@pytest.fixture
def empty_index(offline_index):
    """The same isolated manager as :func:`offline_index` but with no documents.

    An installed-but-empty engine is the "index not built yet" state the API has
    to report explicitly rather than answer with an empty result set.
    """
    offline_index.set_engine(SearchEngine([]))
    return offline_index


@pytest.fixture
def offline_semantic(monkeypatch, tmp_path):
    """The *real* semantic manager with a degraded database and an isolated
    artifact directory.

    ``SemanticIndexManager.status()`` / ``rebuild()`` probe PostgreSQL on every
    call, which costs a multi-second connect timeout when the database is down.
    Pinning the repository factory to the degraded repository keeps the API
    suite fast **and** exercises the genuine "PostgreSQL unreachable" branches
    instead of monkeypatching the manager away.
    """
    from backend.search.semantic import get_semantic_index_manager

    manager = get_semantic_index_manager()
    monkeypatch.setattr(
        manager, "_repo_factory", lambda: make_document_repository(None)
    )
    monkeypatch.setattr(manager, "_repository", make_document_repository(None))
    monkeypatch.setattr(manager, "_index_dir", tmp_path / "faiss")
    return manager


# --------------------------------------------------------------------------- #
# semantic doubles
# --------------------------------------------------------------------------- #


class StubSemanticManager:
    """Deterministic stand-in for :class:`SemanticIndexManager`.

    Ranks by query/content token overlap so an unrelated query scores exactly
    ``0.0`` (mirroring cosine similarity) instead of ranking everything.
    """

    def __init__(self, documents: Iterable[ProcessedDocument] = ()) -> None:
        self._docs = {str(d.document_id): d for d in documents}
        self.searches: list[tuple[str, int]] = []

    @property
    def loaded(self) -> bool:
        return bool(self._docs)

    @property
    def document_count(self) -> int:
        return len(self._docs)

    def status(self) -> dict[str, Any]:
        loaded = bool(self._docs)
        return {
            "available": True,
            "loaded": loaded,
            "message": "" if loaded else "semantic index not built",
            "documents": len(self._docs),
        }

    def search(
        self, query: str, limit: int = 10, max_limit: int = 50
    ) -> SearchResponse:
        self.searches.append((query, int(limit)))
        tokens = set(query.lower().split())
        scored = [
            (len(tokens & set(doc.content.lower().split())) / max(1, len(tokens)), doc)
            for doc in self._docs.values()
        ]
        scored.sort(key=lambda pair: -pair[0])
        hits = tuple(
            SearchResult(
                rank=index,
                document_id=doc.document_id,
                title=doc.title,
                source=doc.source,
                snippet=doc.content[:80],
                score=round(float(score), 4),
                matched_terms=(),
            )
            for index, (score, doc) in enumerate(scored[: int(limit)], start=1)
        )
        return SearchResponse(
            query=query, total=len(hits), limit=int(limit), hits=hits, message="ok"
        )

    def get_document(self, document_id: str) -> Optional[ProcessedDocument]:
        return self._docs.get(str(document_id))


class UnavailableSemanticManager:
    """A semantic layer that reports itself unavailable (never a silent fallback)."""

    def __init__(self, message: str = "embedding backend offline") -> None:
        self._message = message
        self.searches: list[tuple[str, int]] = []

    @property
    def loaded(self) -> bool:
        return False

    @property
    def document_count(self) -> int:
        return 0

    def status(self) -> dict[str, Any]:
        return {"available": False, "loaded": False, "message": self._message}

    def search(self, *args: Any, **kwargs: Any) -> SearchResponse:
        self.searches.append((args, kwargs))
        raise AssertionError("semantic search must not run while unavailable")

    def get_document(self, document_id: str) -> None:
        return None


@pytest.fixture
def semantic_present(monkeypatch, sample_documents):
    """Semantic layer available and covering the same documents as BM25."""
    stub = StubSemanticManager(sample_documents)
    monkeypatch.setattr(
        "backend.api.search.get_semantic_index_manager", lambda: stub
    )
    return stub


@pytest.fixture
def semantic_missing(monkeypatch):
    """Semantic layer explicitly unavailable (the degraded path)."""
    stub = UnavailableSemanticManager()
    monkeypatch.setattr(
        "backend.api.search.get_semantic_index_manager", lambda: stub
    )
    return stub


# --------------------------------------------------------------------------- #
# HTTP client
# --------------------------------------------------------------------------- #


@pytest.fixture
def client() -> TestClient:
    """``TestClient`` over the real app (lifespan is *not* run, so no artifact
    is loaded from disk and no index directory is written)."""
    return TestClient(app)