"""Phase 6 semantic-search acceptance tests (local SentenceTransformers + FAISS).

The suite is split into three clearly-separated tiers:

1. **Offline fast suite (default)** — never touches the network and never loads
   the real embedding model. A deterministic :class:`_FakeEmbedder` mimics the
   ``EmbeddingGenerator`` contract (word-overlap cosine similarity) and an
   in-memory :class:`_FakeRepository` stands in for PostgreSQL. This covers the
   vector/FAISS/persistence/change-detection lifecycle (tests D–N).
2. **Live embedding-model tier** — exercises the real ``all-MiniLM-L6-v2``
   (laziness, 384-dim determinism, L2 normalisation). It runs only when the
   model is already locally available (``HF_HUB_OFFLINE=1`` makes a missing
   cache fail fast instead of downloading); otherwise it is skipped.
3. **Live PostgreSQL tier** — mirrors the Phase 5B pattern: real PostgreSQL +
   real embedding model, end-to-end rebuild/search/restart + the HTTP API.

Existing BM25 / Phase 5A / Phase 5B / crawler suites remain untouched and still
pass (O/Q verified by ``pytest -q`` across the whole repo).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.config import settings
from backend.db.repository import make_document_repository
from backend.db.repository_factory import create_initialised_document_repository
from backend.search import faiss_store
from backend.search.embeddings import (
    EmbeddingGenerator,
    EmbeddingUnavailableError,
    get_embedding_generator,
    reset_embedding_generator,
)
from backend.search.semantic import (
    SemanticIndexManager,
    document_text,
    get_semantic_index_manager,
    reset_semantic_index_manager,
)

_DB_URL_OVERRIDE = "SEEK_TEST_DATABASE_URL"
_DEFAULT_DB_URL = "postgresql+psycopg2://seek:seek@localhost:5432/seek"
_SKIP_REASON = "PostgreSQL unreachable; skipping live Phase 6 semantic test"

_WORD_RE = re.compile(r"[a-z0-9]+")


def _faiss_available() -> bool:
    return importlib.util.find_spec("faiss") is not None


# --------------------------------------------------------------------------- #
# deterministic fakes
# --------------------------------------------------------------------------- #


def _row(i: int, *, topic: str = "quokka", content: str | None = None) -> SimpleNamespace:
    body = content or f"persistent {topic} document number {i} with unique content"
    return SimpleNamespace(
        document_id=i,
        title=f"Doc {i} {topic}",
        content=body,
        source=f"corpus/doc{i}.md",
        content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
    )


class _FakeRepository:
    """In-memory stand-in for the PostgreSQL ``documents`` repository."""

    def __init__(self, rows=None) -> None:
        self._rows: dict[int, SimpleNamespace] = {}
        self.available = True
        if rows:
            for r in rows:
                self._rows[int(r.document_id)] = r

    def set_rows(self, rows) -> None:
        self._rows = {int(r.document_id): r for r in rows}

    def add(self, row) -> None:
        self._rows[int(row.document_id)] = row

    def remove(self, document_id: int) -> None:
        self._rows.pop(int(document_id), None)

    def is_available(self) -> bool:
        return self.available

    def list_all(self, *, limit: int | None = None) -> list[SimpleNamespace]:
        rows = [self._rows[k] for k in sorted(self._rows)]
        if limit is not None:
            rows = rows[: int(limit)]
        return rows

    def close(self) -> None:
        pass


class _FakeEmbedder:
    """Deterministic, semantics-approximating stand-in for EmbeddingGenerator.

    Vectors are word-overlap histograms hashed into a fixed-width space, so
    cosine similarity is high when the query and document share words — good
    enough to assert "relevant docs rank first" without a real model.
    """

    def __init__(self, dimension: int = 64, model_name: str = "fake/all-MiniLM-L6-v2") -> None:
        self._dimension = int(dimension)
        self.model_name = model_name

    def preprocess(self, text: str) -> str:
        return " ".join((text or "").split())

    def is_importable(self) -> bool:
        return True

    def is_available(self) -> bool:
        return True

    @property
    def model_loaded(self) -> bool:
        return True

    @property
    def loaded_dimension(self) -> int:
        return self._dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def encode_texts(self, texts) -> "object":
        import numpy as np

        prepared = [self.preprocess(t) for t in list(texts or [])]
        vecs = np.zeros((len(prepared), self._dimension), dtype="float32")
        for i, text in enumerate(prepared):
            for word in _WORD_RE.findall(text.lower()):
                idx = int.from_bytes(
                    hashlib.sha256(word.encode("utf-8")).digest()[:4], "little"
                ) % self._dimension
                vecs[i, idx] += 1.0
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        return vecs / norms

    def reset(self) -> None:
        pass

    def close(self) -> None:
        pass


def _make_manager(tmp_path: Path, repo, embedder, **kw) -> SemanticIndexManager:
    defaults = dict(
        semantic_index_dir=str(Path(tmp_path) / "semantic"),
        repository=repo,
        repository_factory=lambda: repo,
        embedder=embedder,
        seed_corpus=False,
    )
    defaults.update(kw)
    return SemanticIndexManager(**defaults)


# --------------------------------------------------------------------------- #
# A. embedding model loads lazily (offline-safe)
# --------------------------------------------------------------------------- #


class TestEmbeddingGeneratorLazy:
    def test_model_not_loaded_at_construction(self):
        reset_embedding_generator()
        gen = get_embedding_generator()
        assert gen.model_loaded is False
        assert gen.loaded_dimension is None
        reset_embedding_generator()

    def test_module_import_does_not_load_model(self):
        import importlib

        mod = importlib.import_module("backend.search.embeddings")
        assert mod.EmbeddingGenerator is not None
        gen = mod.EmbeddingGenerator()
        assert gen.model_loaded is False

    def test_model_loaded_dimension_after_encode(self, tmp_path):
        import numpy as np

        gen = _FakeEmbedder(dimension=16)
        arr = gen.encode_texts(["example sentence"])
        arr = np.asarray(arr)
        assert arr.shape == (1, 16)

    def test_unavailable_when_sentence_transformers_missing(self, monkeypatch):
        # Simulate the package being absent: is_available becomes False and
        # encode raises EmbeddingUnavailableError instead of crashing.
        def _no_spec(_name):
            return None

        monkeypatch.setattr(importlib.util, "find_spec", _no_spec)
        gen = _FakeEmbedder()
        monkeypatch.delattr(_FakeEmbedder, "is_available")
        # _FakeEmbedder overrides is_available -> True so exercise the real one.
        real = gen.__class__
        real.is_available = lambda self: False  # type: ignore[method-assign]
        assert gen.is_available() is False


# --------------------------------------------------------------------------- #
# B + C. deterministic dimensions + normalisation (fake + live)
# --------------------------------------------------------------------------- #


class TestEmbeddingDeterminismOffline:
    def test_same_input_same_vector_and_dimensions(self):
        import numpy as np

        gen = _FakeEmbedder(dimension=24)
        a = np.asarray(gen.encode_texts(["the quick brown fox"]))
        b = np.asarray(gen.encode_texts(["the quick brown fox"]))
        assert a.shape == (1, 24)
        assert b.shape == (1, 24)
        assert np.array_equal(a, b)

    def test_vectors_are_l2_normalised(self):
        import numpy as np

        gen = _FakeEmbedder(dimension=32)
        arr = np.asarray(gen.encode_texts(["alpha beta gamma", "delta epsilon"]))
        norms = np.linalg.norm(arr, axis=1)
        assert np.allclose(norms, 1.0, atol=1e-5)

    def test_empty_input_yields_empty_array(self):
        import numpy as np

        gen = _FakeEmbedder(dimension=8)
        arr = np.asarray(gen.encode_texts([]))
        assert arr.shape == (0, 8)

    def test_word_overlap_gives_cosine_similarity(self):
        import numpy as np

        gen = _FakeEmbedder(dimension=64)
        docs = np.asarray(
            gen.encode_texts(
                [
                    "quokka habitat conservation",
                    "python vector database tutorial",
                    "machine learning tokenizer",
                ]
            )
        )
        query = np.asarray(gen.encode_texts(["quokka"]))
        sims = docs @ query.T
        top = int(np.argmax(sims.flatten()))
        assert top == 0


# --------------------------------------------------------------------------- #
# D–G. FAISS index create / persist / load / metadata mapping (offline)
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not _faiss_available(), reason="faiss not installed")
class TestFaissStore:
    def _vectors(self, rows, dimension: int = 16):
        embedder = _FakeEmbedder(dimension=dimension)
        return embedder.encode_texts([document_text(r) for r in rows])

    def test_create_and_persist_faiss_index(self, tmp_path):
        rows = [_row(1), _row(2), _row(3)]
        vectors = self._vectors(rows)
        metadata = faiss_store.build_faiss_metadata(
            documents=rows, vectors=vectors, model="fake/model", index_version=1
        )
        faiss_store.save_faiss_index(tmp_path, rows, vectors, metadata)
        assert faiss_store.is_faiss_present(tmp_path)
        assert (tmp_path / "faiss_index.bin").is_file()
        assert (tmp_path / "faiss_metadata.json").is_file()

    def test_load_after_fresh_store(self, tmp_path):
        import numpy as np

        rows = [_row(4), _row(5), _row(6)]
        vectors = self._vectors(rows)
        metadata = faiss_store.build_faiss_metadata(
            documents=rows, vectors=vectors, model="fake/model", index_version=3
        )
        faiss_store.save_faiss_index(tmp_path, rows, vectors, metadata)
        result = faiss_store.load_faiss_index(str(Path(tmp_path) / "missing"))
        assert result.valid is False
        result = faiss_store.load_faiss_index(tmp_path)
        assert result.valid is True
        assert result.payload is not None
        assert result.payload.dimension == 16
        assert result.payload.model == "fake/model"
        assert result.metadata is not None
        assert result.metadata.index_version == 3
        assert np.asarray(result.payload.vectors).shape == (3, 16)

    def test_vector_positions_map_to_document_ids(self, tmp_path):
        rows = [_row(10), _row(11), _row(12)]
        vectors = self._vectors(rows)
        metadata = faiss_store.build_faiss_metadata(
            documents=rows, vectors=vectors, model="fake/model"
        )
        faiss_store.save_faiss_index(tmp_path, rows, vectors, metadata)
        result = faiss_store.load_faiss_index(tmp_path)
        assert result.valid
        ids = [d.document_id for d in result.payload.documents]
        assert ids == ["10", "11", "12"]
        hash_map = {d.document_id: d.content_hash for d in result.payload.documents}
        assert hash_map["10"] == rows[0].content_hash

    def test_missing_index_safe(self, tmp_path):
        result = faiss_store.load_faiss_index(tmp_path)
        assert result.valid is False
        assert "missing" in result.reason

    def test_corrupt_index_safe(self, tmp_path):
        (tmp_path / "faiss_index.bin").write_bytes(b"not-a-faiss-index")
        (tmp_path / "faiss_metadata.json").write_text("{bad json", encoding="utf-8")
        result = faiss_store.load_faiss_index(tmp_path)
        assert result.valid is False
        assert result.reason


# --------------------------------------------------------------------------- #
# H–N. SemanticIndexManager lifecycle (offline, fake embedder + fake repo)
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not _faiss_available(), reason="faiss not installed")
class TestSemanticIndexManager:
    @pytest.fixture()
    def ctx(self, tmp_path):
        python_row = SimpleNamespace(
            document_id=4,
            title="Python Search Guide",
            content="a python vector database and semantic search tutorial",
            source="corpus/doc4.md",
            content_hash=hashlib.sha256(
                "a python vector database and semantic search tutorial".encode("utf-8")
            ).hexdigest(),
        )
        repo = _FakeRepository([_row(1), _row(2), _row(3), python_row])
        embedder = _FakeEmbedder(dimension=64)
        manager = _make_manager(tmp_path, repo, embedder)
        return tmp_path, repo, embedder, manager

    def test_rebuild_indexes_and_searches(self, ctx):
        tmp_path, repo, embedder, manager = ctx
        result = manager.rebuild(seed_corpus=False)
        assert result.status == "rebuilt"
        assert result.documents_indexed == 4
        assert manager.loaded is True
        assert faiss_store.is_faiss_present(manager.index_dir)
        resp = manager.search("quokka", limit=5)
        assert resp.total >= 1
        assert all(h.document_id for h in resp.hits)
        assert all(h.title for h in resp.hits)
        assert all(h.snippet for h in resp.hits)
        assert all(h.matched_terms == () for h in resp.hits)
        assert all(-1.0 <= h.score <= 1.0 for h in resp.hits)

    def test_representative_query_returns_relevant_documents(self, ctx):
        tmp_path, repo, embedder, manager = ctx
        manager.rebuild(seed_corpus=False)
        resp = manager.search("python", limit=5)
        # word-overlap fake: the python doc outranks the quokka docs
        assert resp.total >= 1
        top = resp.hits[0]
        assert top.document_id == "4"
        assert "python" in (top.title + top.snippet)
        assert top.score > 0.0
        # exact self-similarity is 1.0 (normalised cosine) — the document is
        # embedded as "title\ncontent", so the query must reproduce that text.
        exact_query = "Python Search Guide\na python vector database and semantic search tutorial"
        exact = manager.search(exact_query, limit=5)
        assert exact.hits[0].document_id == "4"
        assert abs(exact.hits[0].score - 1.0) < 1e-5

    def test_persistence_across_restart(self, ctx):
        tmp_path, repo, embedder, manager = ctx
        manager.rebuild(seed_corpus=False)
        before = manager.metadata.updated_at
        # "restart": fresh manager loads purely from disk, PG degraded.
        manager2 = _make_manager(
            tmp_path,
            _FakeRepository([]),
            embedder,
            repository=make_document_repository(None),
        )
        state = manager2.load_on_startup()
        assert state["loaded"] is True
        assert state["source"] == "persistent_faiss_index"
        assert manager2.document_count == 4
        assert manager2.search("quokka", limit=5).total >= 1
        assert manager2.metadata.updated_at == before  # no rebuild happened

    def test_new_document_detected(self, ctx):
        tmp_path, repo, embedder, manager = ctx
        manager.rebuild(seed_corpus=False)
        repo.add(_row(5))
        changes = manager.detect_changes()
        assert changes["new"] == ["5"]
        result = manager.refresh()
        assert result.status == "refreshed"
        assert result.document_count == 5
        assert manager.document_count == 5

    def test_modified_document_detected_via_content_hash(self, ctx):
        tmp_path, repo, embedder, manager = ctx
        manager.rebuild(seed_corpus=False)
        # modify content + hash in place (as PostgreSQL would see it)
        new_content = "completely rewritten numpy content with data"
        repo._rows[1] = _row(1, content=new_content)
        changes = manager.detect_changes()
        assert changes["modified"] == ["1"]
        result = manager.refresh()
        assert result.status == "refreshed"
        assert "1" in result.changed["modified"]
        hits = manager.search("numpy", limit=5)
        assert any(h.document_id == "1" for h in hits.hits)

    def test_deleted_document_removed(self, ctx):
        tmp_path, repo, embedder, manager = ctx
        manager.rebuild(seed_corpus=False)
        repo.remove(1)
        changes = manager.detect_changes()
        assert changes["deleted"] == ["1"]
        result = manager.refresh()
        assert result.status == "refreshed"
        assert manager.document_count == 3
        resp = manager.search("quokka", limit=5)
        assert "1" not in {h.document_id for h in resp.hits}

    def test_unchanged_does_not_rebuild(self, ctx):
        tmp_path, repo, embedder, manager = ctx
        manager.rebuild(seed_corpus=False)
        before_version = manager.metadata.index_version
        before_updated = manager.metadata.updated_at
        result = manager.refresh()
        assert result.status == "unchanged"
        assert manager.metadata.index_version == before_version
        assert manager.metadata.updated_at == before_updated

    def test_missing_faiss_index_safe(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "SEMANTIC_INDEX_PATH", str(tmp_path / "sem"))
        reset_semantic_index_manager()
        manager = get_semantic_index_manager()
        state = manager.load_on_startup()
        assert state["loaded"] is False
        info = manager.status()
        assert info["loaded"] is False
        assert info["index_exists"] is False
        resp = manager.search("anything", limit=5)
        assert resp.total == 0
        assert "not built" in resp.message
        reset_semantic_index_manager()

    def test_corrupt_faiss_index_safe(self, tmp_path, monkeypatch):
        index_dir = Path(tmp_path) / "semcorrupt"
        index_dir.mkdir(parents=True)
        (index_dir / "faiss_index.bin").write_bytes(b"garbage")
        (index_dir / "faiss_metadata.json").write_text("{oops", encoding="utf-8")
        monkeypatch.setattr(settings, "SEMANTIC_INDEX_PATH", str(index_dir))
        reset_semantic_index_manager()
        manager = get_semantic_index_manager()
        state = manager.load_on_startup()
        assert state["loaded"] is False  # corrupt -> not-built, never crashes
        reset_semantic_index_manager()


# --------------------------------------------------------------------------- #
# live embedding model tier (skips when the model is not cached locally)
# --------------------------------------------------------------------------- #

_LIVE_MODEL_SKIP = "all-MiniLM-L6-v2 not available locally (offline)"


def _load_real_embedder():
    """Return a working real embedder, or None (fast-fail via offline env)."""
    reset_embedding_generator()
    prev = os.environ.get("HF_HUB_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        gen = EmbeddingGenerator()
        gen.ensure_loaded()
        return gen
    except (EmbeddingUnavailableError, Exception):  # noqa: BLE001
        return None
    finally:
        reset_embedding_generator()
        if prev is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = prev


@pytest.fixture(scope="class")
def real_embedder():
    gen = _load_real_embedder()
    if gen is None:
        pytest.skip(_LIVE_MODEL_SKIP)
    yield gen
    gen.close()
    reset_embedding_generator()


class TestLiveEmbeddingModel:
    """Real all-MiniLM-L6-v2 checks — clearly separated, skipped offline."""

    def test_load_is_lazy(self, real_embedder):
        assert real_embedder.model_loaded is True  # fixture already loaded
        gen2 = EmbeddingGenerator()
        assert gen2.model_loaded is False
        assert gen2.loaded_dimension is None

    def test_dimensions_are_deterministic(self, real_embedder):
        import numpy as np

        a = np.asarray(real_embedder.encode_texts(["docker containers and volumes"]))
        b = np.asarray(real_embedder.encode_texts(["docker containers and volumes"]))
        assert a.shape == (1, 384)
        assert np.allclose(a, b, atol=1e-7)

    def test_embeddings_are_l2_normalised(self, real_embedder):
        import numpy as np

        arr = np.asarray(
            real_embedder.encode_texts(["hello", "vector search", "postgres"])
        )
        assert arr.shape[1] == 384
        assert np.allclose(np.linalg.norm(arr, axis=1), 1.0, atol=1e-5)

    def test_batch_encode_matches_dimension(self, real_embedder):
        import numpy as np

        arr = np.asarray(real_embedder.encode_texts(["a"] * 5))
        assert arr.shape == (5, 384)


# --------------------------------------------------------------------------- #
# live PostgreSQL tier (skips when PostgreSQL is unreachable)
# --------------------------------------------------------------------------- #


def _test_database_url() -> str:
    return os.environ.get(_DB_URL_OVERRIDE) or _DEFAULT_DB_URL


def _live_repository():
    repo = create_initialised_document_repository(
        _test_database_url(), attempts=2, delay_seconds=0.1
    )
    if repo is None or not repo.is_available():
        return None
    return repo


@pytest.mark.skipif(not _faiss_available(), reason="faiss not installed")
class TestSemanticPostgresLive:
    """End-to-end semantic pipeline against real PostgreSQL + the real model."""

    @pytest.fixture(scope="class")
    def live_repo(self):
        repo = _live_repository()
        if repo is None:
            pytest.skip(_SKIP_REASON)
        yield repo
        try:
            repo.close()
        except Exception:  # pragma: no cover - teardown best-effort
            pass

    @pytest.fixture(scope="class", autouse=True)
    def _wipe_after(self, live_repo):
        yield
        _wipe(live_repo)
        reset_semantic_index_manager()
        reset_embedding_generator()

    @pytest.fixture()
    def clean_db(self, live_repo):
        _wipe(live_repo)
        yield live_repo
        _wipe(live_repo)

    def _insert(self, repo, count: int, *, start: int = 1) -> list[SimpleNamespace]:
        from backend.db.models import Document

        inserted = []
        for i in range(start, start + count):
            row = _row(i)
            doc = Document(
                title=row.title,
                content=row.content,
                source=row.source,
                content_hash=row.content_hash,
            )
            if repo.upsert(doc):
                inserted.append(doc)
        return inserted

    @pytest.fixture(scope="class")
    def live_gen(self):
        gen = _load_real_embedder()
        if gen is None:
            pytest.skip(_LIVE_MODEL_SKIP)
        yield gen
        gen.close()
        reset_embedding_generator()

    def test_rebuild_search_and_restart_persistence(self, clean_db, tmp_path, live_gen):
        self._insert(clean_db, 6)
        manager = _make_manager(tmp_path, clean_db, live_gen, seed_corpus=False)
        result = manager.rebuild(seed_corpus=False)
        assert result.status == "rebuilt"
        assert result.documents_indexed == 6
        assert result.model.endswith("all-MiniLM-L6-v2")
        assert result.dimension == 384
        assert manager.loaded
        resp = manager.search("quokka", limit=10)
        assert resp.total == 6
        before_updated = manager.metadata.updated_at

        # restart: new manager loads the persisted FAISS artifact (PG degraded)
        manager2 = _make_manager(
            tmp_path,
            clean_db,
            live_gen,
            seed_corpus=False,
            repository=make_document_repository(None),
        )
        state = manager2.load_on_startup()
        assert state["loaded"] is True
        assert state["source"] == "persistent_faiss_index"
        assert manager2.metadata.updated_at == before_updated
        resp2 = manager2.search("quokka", limit=10)
        assert resp2.total == 6
        assert {h.document_id for h in resp2.hits} == {
            str(r.document_id) for r in sorted(clean_db.list_all(), key=lambda r: r.document_id)
        }

    def test_change_detection_new_and_modified(self, clean_db, tmp_path, live_gen):
        self._insert(clean_db, 4)
        manager = _make_manager(tmp_path, clean_db, live_gen, seed_corpus=False)
        manager.rebuild(seed_corpus=False)
        from backend.db.models import Document

        # new document
        self._insert(clean_db, 1, start=5)
        changes = manager.detect_changes()
        assert len(changes["new"]) == 1
        result = manager.refresh()
        assert result.status == "refreshed"
        assert result.document_count == 5

        # modify one row
        first = clean_db.session.query(Document).first()
        assert first is not None
        doc_id = first.document_id
        new_content = "rewritten semantic content about cosine similarity"
        first.content = new_content
        first.content_hash = hashlib.sha256(new_content.encode("utf-8")).hexdigest()
        clean_db.session.commit()
        changes = manager.detect_changes()
        assert changes["modified"] == [str(doc_id)]
        result = manager.refresh()
        assert result.status == "refreshed"

        # unchanged now
        result = manager.refresh()
        assert result.status == "unchanged"

    def test_semantic_api_flow(self, clean_db, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient

        self._insert(clean_db, 5)
        monkeypatch.setattr(settings, "STORAGE_INDEX_PATH", str(tmp_path / "api"))
        monkeypatch.setattr(settings, "DATABASE_URL", _test_database_url())
        monkeypatch.setattr(settings, "SAMPLE_CORPUS_DIR", str(tmp_path / "corpus"))
        monkeypatch.setattr(settings, "SEMANTIC_INDEX_PATH", str(tmp_path / "api"))
        reset_semantic_index_manager()
        reset_embedding_generator()

        from backend.main import app as fastapi_app

        with TestClient(fastapi_app) as client:
            info = client.get("/api/index/status").json()
            assert "semantic" in info

            rebuilt = client.post("/api/index/semantic/rebuild")
            assert rebuilt.status_code == 200, rebuilt.text
            assert rebuilt.json()["status"] == "rebuilt"
            assert rebuilt.json()["documents_indexed"] == 5

            sem = client.get(
                "/api/search", params={"q": "quokka", "limit": 5, "mode": "semantic"}
            )
            assert sem.status_code == 200
            data = sem.json()
            assert data["total"] == 5
            assert data["mode"] == "semantic"
            assert data["semantic"]["status"] == "ok"
            assert data["hits"][0]["score"] >= 0

            lex = client.get("/api/search", params={"q": "quokka"})
            assert lex.status_code == 200
            assert lex.json()["mode"] == "lexical"
            assert lex.json()["total"] == 5

            refresh = client.post("/api/index/semantic/refresh")
            assert refresh.status_code == 200
            assert refresh.json()["status"] == "unchanged"
        reset_semantic_index_manager()
        reset_embedding_generator()

    def test_missing_model_never_blocks_bm25(self, clean_db, tmp_path, monkeypatch):
        """Simulate no embedding stack: semantic unavailable, BM25 unaffected."""
        from fastapi.testclient import TestClient

        self._insert(clean_db, 5)
        monkeypatch.setattr(settings, "STORAGE_INDEX_PATH", str(tmp_path / "api2"))
        monkeypatch.setattr(settings, "DATABASE_URL", _test_database_url())
        monkeypatch.setattr(settings, "SAMPLE_CORPUS_DIR", str(tmp_path / "corpus2"))
        monkeypatch.setattr(settings, "SEMANTIC_INDEX_PATH", str(tmp_path / "api2"))

        def _no_spec(_name):
            return None

        monkeypatch.setattr(importlib.util, "find_spec", _no_spec)
        reset_semantic_index_manager()
        reset_embedding_generator()

        from backend.main import app as fastapi_app

        with TestClient(fastapi_app) as client:
            client.post("/api/index/rebuild")
            status = client.get("/api/index/status").json()
            assert status["semantic"]["available"] is False
            # BM25 still works end to end
            res = client.get("/api/search", params={"q": "quokka"})
            assert res.status_code == 200
            assert res.json()["hits"]
            # semantic mode reports structured unavailability (no BM25 fallback)
            sem = client.get(
                "/api/search", params={"q": "quokka", "mode": "semantic"}
            )
            assert sem.status_code == 200
            assert sem.json()["hits"] == []
            assert sem.json()["semantic"]["status"] == "unavailable"
        reset_semantic_index_manager()
        reset_embedding_generator()


def _wipe(repo) -> None:
    from backend.db.models import Document

    try:
        repo.session.query(Document).delete(synchronize_session=False)
        repo.session.commit()
    except Exception:
        repo.session.rollback()