"""Phase 10 integration tests — offline end-to-end flows and artifact lifecycle.

Three families of tests live here:

**1. Pipeline integration (fully offline).**
   Corpus on disk -> loader -> BM25 engine -> API response, and
   crawler store -> processed documents -> engine -> search. Nothing in this
   family opens a socket or touches PostgreSQL.

**2. Persistence / restart matrix.**
   A fresh :class:`IndexManager` is built over a real ``IndexManager`` +
   :class:`SearchEngine`, restarted, and asked to load its artifact. For every
   state of the two on-disk files (valid / missing / corrupt / stale /
   metadata-mismatch / failed atomic write / interrupted write) the suite pins
   the *observable contract*: never raise, always explain, never leave a stray
   ``.tmp`` behind.

**3. Failure + resilience combinations.**
   "What happens when X *and* Y both go wrong" - the combinations that no single
   failure test covers: corrupt artifact + no database, unavailable repository +
   rebuild, unavailable repository + refresh, unreachable embedding stack +
   semantic search, broken repository factory + status, ...

FAISS-specific persistence runs only when ``faiss`` imports (it does not need a
model or a download - only the local library); everything else is unconditional.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import pytest

from backend.db.repository import make_document_repository
from backend.pipeline import build_pipeline
from backend.processing.loader import load_corpus
from backend.processing.models import ProcessedDocument
from backend.processing.tokenizer import tokenize
from backend.search import index_store
from backend.search.engine import SearchEngine
from backend.search.index_manager import IndexManager, IndexUnavailableError
from backend.search.index_store import (
    ARTIFACT_FILE,
    INDEX_FORMAT_VERSION,
    METADATA_FILE,
    IndexMetadata,
    compute_document_signature,
    load_index,
    now_iso,
)

from conftest import FakeRepository, make_document


# --------------------------------------------------------------------------- #
# 1. offline pipeline integration
# --------------------------------------------------------------------------- #


class TestCorpusToSearchIntegration:
    def test_the_committed_corpus_indexes_and_answers_every_topic(
        self, client, monkeypatch, tmp_path
    ):
        """The whole Phase 2 chain, offline: files -> loader -> BM25 -> HTTP."""
        monkeypatch.setattr("backend.api.index.get_index_manager", None, raising=False)
        engine = build_pipeline()
        assert engine.document_count >= 8

        from backend.api.search import set_engine

        set_engine(engine)
        for query in ("python", "docker", "machine learning", "database"):
            data = client.get("/api/search", params={"q": query}).json()
            assert data["hits"], f"the committed corpus must answer {query!r}"
            assert data["message"] == "ok"
            assert data["hits"][0]["score"] > 0
            assert data["hits"][0]["snippet"]

    def test_ranks_are_stable_across_repeated_requests(self, client, monkeypatch):
        from backend.api.search import set_engine

        set_engine(build_pipeline())
        first = client.get("/api/search", params={"q": "python"}).json()["hits"]
        for _ in range(3):
            assert client.get("/api/search", params={"q": "python"}).json()["hits"] == first

    def test_every_indexed_document_is_retrievable_by_its_own_words(self):
        """No committed document can become unreachable through indexing."""
        engine = build_pipeline()
        for doc in engine._bm25.documents:  # noqa: SLF001 - the indexed corpus
            unique = next(
                (t for t in doc.tokens if t not in ("the", "and", "of")), None
            )
            if not unique:
                continue
            response = engine.search(unique, limit=50)
            ids = {hit.document_id for hit in response.hits}
            assert doc.document_id in ids, f"{doc.document_id} not findable via {unique!r}"

    def test_a_crawled_page_becomes_a_searchable_document(self, monkeypatch):
        """Crawler store -> ProcessedDocument -> engine -> ranked hit."""
        from backend.crawler.models import CrawlPage
        from backend.crawler.service import CrawlStore

        store = CrawlStore()
        page = CrawlPage(
            url="https://example.com/kubernetes",
            final_url="https://example.com/kubernetes",
            status_code=200,
            title="Kubernetes Operators",
            text="A kubernetes operator automates application deployment on a cluster.",
            content_hash="b" * 64,
        )
        assert store.record(page) is True
        assert store.record(page) is False, "identical content must not be stored twice"

        crawled = store.to_processed_documents()
        assert len(crawled) == 1
        assert crawled[0].document_id.startswith("crawl-")
        assert crawled[0].source == page.url

        engine = build_pipeline(extra=crawled)
        response = engine.search("kubernetes operator", limit=10)
        assert response.hits[0].document_id == crawled[0].document_id

    def test_loader_output_is_directly_indexable(self, tmp_path, monkeypatch):
        (tmp_path / "alpha.md").write_text(
            "---\ntitle: Alpha\n---\nalpha beta gamma delta epsilon", encoding="utf-8"
        )
        (tmp_path / "nested").mkdir()
        (tmp_path / "nested" / "beta.md").write_text(
            "beta gamma delta zeta eta", encoding="utf-8"
        )
        documents = load_corpus(tmp_path)
        assert [d.document_id for d in documents] == ["alpha", "beta"]

        # Only the freshly loaded documents, so the count assertion is exact.
        monkeypatch.setattr("backend.pipeline.load_corpus", lambda *a, **k: [])
        engine = build_pipeline(extra=documents)
        assert engine.document_count == 2
        assert engine.search("epsilon").hits[0].document_id == "alpha"


class TestPersistenceThroughTheRepository:
    def test_rebuild_persists_and_restart_reloads_identically(self, tmp_path, sample_documents):
        repository = FakeRepository.from_documents(sample_documents)
        first = IndexManager(
            index_dir=tmp_path / "bm25", repository=repository, seed_corpus=False
        )
        build = first.rebuild()
        assert build.status == "rebuilt"
        assert build.documents_indexed == len(sample_documents)
        assert [h.document_id for h in first.engine.search("python").hits]

        # "Restart": a brand new manager over the same directory.
        second = IndexManager(index_dir=tmp_path / "bm25", repository=repository, seed_corpus=False)
        state = second.load_on_startup()
        assert state == {
            "loaded": True,
            "source": "persistent_index",
            "document_count": len(sample_documents),
            "index_version": build.index_version,
        }
        assert [h.document_id for h in second.engine.search("python").hits] == [
            h.document_id for h in first.engine.search("python").hits
        ]
        assert second.metadata.corpus_hash == first.metadata.corpus_hash

    def test_rebuild_is_idempotent_and_bumps_the_version_only_on_change(
        self, tmp_path, sample_documents
    ):
        repository = FakeRepository.from_documents(sample_documents)
        manager = IndexManager(
            index_dir=tmp_path / "bm25", repository=repository, seed_corpus=False
        )
        assert manager.rebuild().index_version == 1
        assert manager.rebuild().index_version == 2, "rebuild always bumps the version"

        second = IndexManager(
            index_dir=tmp_path / "bm25", repository=repository, seed_corpus=False
        )
        refresh = second.refresh()
        assert refresh.status == "unchanged"
        assert refresh.changed == {"new": [], "modified": [], "deleted": []}
        # The version on disk is what survived the second rebuild; the point of
        # the assertion is that the no-op refresh itself did not bump it.
        assert refresh.index_version == 2
        assert manager.metadata.index_version == 2

    def test_refresh_detects_added_modified_and_deleted_documents(self, tmp_path, sample_documents):
        repository = FakeRepository.from_documents(sample_documents)
        manager = IndexManager(
            index_dir=tmp_path / "bm25", repository=repository, seed_corpus=False
        )
        manager.rebuild()

        removed = repository.rows.pop()                # deleted
        repository.rows[0].content_hash = "d" * 64      # modified
        repository.rows.append(
            FakeRepository.row("zz-9", title="New", content="new body", content_hash="c" * 64)
        )

        result = manager.refresh()
        assert result.status == "refreshed"
        assert result.changed["new"] == ["zz-9"]
        assert result.changed["modified"] == ["py-1"]
        assert result.changed["deleted"] == [removed.document_id]
        # One deleted, one added: the engine size is unchanged.
        assert manager.engine.document_count == len(sample_documents)
        assert manager.engine.get_document(removed.document_id) is None
        assert manager.engine.get_document("zz-9") is not None

    def test_crawled_http_sources_can_be_excluded_from_the_index(self, tmp_path):
        """``include_crawled`` is defined by the ``http(s)://`` source prefix."""
        rows = [
            FakeRepository.row(
                "local-1", title="Local", content="local corpus body text",
                source="docs/local.md", content_hash="a" * 64,
            ),
            FakeRepository.row(
                "crawl-1", title="Crawled", content="crawled body text",
                source="https://example.com/a", content_hash="e" * 64,
            ),
        ]
        repository = FakeRepository(rows)
        manager = IndexManager(
            index_dir=tmp_path / "bm25", repository=repository, seed_corpus=False
        )
        excluded = manager.rebuild(include_crawled=False)
        assert excluded.crawled_documents == 0
        assert excluded.documents_indexed == 1

        included = manager.rebuild(include_crawled=True)
        assert included.crawled_documents == 1
        assert included.documents_indexed == 2

    def test_rows_without_usable_tokens_are_skipped(self, tmp_path, sample_documents):
        rows = [FakeRepository.row(d.document_id, title=d.title, content=d.content,
                                   source=d.source, content_hash=d.content_hash)
                for d in sample_documents]
        rows.append(FakeRepository.row("stop-1", content="the and of but", content_hash="f" * 64))
        manager = IndexManager(
            index_dir=tmp_path / "bm25", repository=FakeRepository(rows), seed_corpus=False
        )
        assert manager.rebuild().documents_indexed == len(sample_documents)


# --------------------------------------------------------------------------- #
# 2. BM25 artifact persistence / restart matrix
# --------------------------------------------------------------------------- #


def _save(root: Path, documents, **meta_overrides) -> IndexMetadata:
    payload = {
        "format_version": INDEX_FORMAT_VERSION,
        "index_version": 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "document_count": len(documents),
        "max_document_id": 0,
        "corpus_hash": compute_document_signature(documents),
        "documents": tuple(
            {"document_id": d.document_id, "content_hash": d.content_hash}
            for d in documents
        ),
    }
    payload.update(meta_overrides)
    metadata = IndexMetadata(**payload)
    index_store.save_index(
        root, documents, metadata, k1=1.5, b=0.75, epsilon=0.25,
        default_limit=10, max_limit=50,
    )
    return metadata


class TestBm25PersistenceMatrix:
    @pytest.fixture
    def index_dir(self, tmp_path, sample_documents):
        root = tmp_path / "bm25"
        root.mkdir()
        _save(root, sample_documents)
        return root

    def test_valid_artifact_reloads_with_identical_ranking(self, index_dir, sample_documents):
        result = load_index(index_dir)
        assert result.valid, result.reason
        assert [d.document_id for d in result.payload.documents] == [
            d.document_id for d in sample_documents
        ]
        assert result.metadata.document_count == len(sample_documents)

        engine = SearchEngine(result.payload.documents)
        assert engine.search("docker").hits[0].document_id == "dk-1"

    def test_missing_artifact_is_reported_not_raised(self, index_dir):
        (index_dir / ARTIFACT_FILE).unlink()
        result = load_index(index_dir)
        assert result.valid is False
        assert result.reason == "index artifact missing"

    def test_missing_metadata_is_reported_not_raised(self, index_dir):
        (index_dir / METADATA_FILE).unlink()
        assert "metadata missing" in load_index(index_dir).reason

    def test_missing_directory_is_reported_not_raised(self, tmp_path):
        assert load_index(tmp_path / "nowhere").valid is False

    @pytest.mark.parametrize("corrupt", [b"", b"\x00\x01\x02", b"not a pickle at all"])
    def test_corrupt_artifact_is_reported_not_raised(self, index_dir, corrupt):
        (index_dir / ARTIFACT_FILE).write_bytes(corrupt)
        result = load_index(index_dir)
        assert result.valid is False
        assert "corrupt" in result.reason or "artifact" in result.reason

    def test_truncated_artifact_is_reported_not_raised(self, index_dir):
        blob = (index_dir / ARTIFACT_FILE).read_bytes()
        (index_dir / ARTIFACT_FILE).write_bytes(blob[: len(blob) // 2])
        assert load_index(index_dir).valid is False

    def test_interrupted_write_leaves_the_previous_artifact_intact(self, index_dir, sample_documents):
        """Simulate a crash mid-write: a stray ``.tmp`` must never be preferred."""
        (index_dir / (ARTIFACT_FILE + ".tmp")).write_bytes(b"half written garbage")
        result = load_index(index_dir)
        assert result.valid, "the committed artifact is still the authoritative one"
        assert len(result.payload.documents) == len(sample_documents)

    def test_stale_artifact_is_detected_through_the_corpus_hash(self, index_dir):
        metadata = index_store.read_metadata(index_dir)
        (index_dir / METADATA_FILE).write_text(
            json.dumps({**metadata.to_dict(), "corpus_hash": "0" * 64}), encoding="utf-8"
        )
        assert "content signature mismatch" in load_index(index_dir).reason

    def test_document_count_mismatch_is_detected(self, index_dir, sample_documents):
        metadata = index_store.read_metadata(index_dir)
        (index_dir / METADATA_FILE).write_text(
            json.dumps({**metadata.to_dict(), "document_count": 99}), encoding="utf-8"
        )
        assert "document count mismatch" in load_index(index_dir).reason

    def test_metadata_of_a_different_format_version_is_rejected(self, index_dir):
        metadata = index_store.read_metadata(index_dir)
        (index_dir / METADATA_FILE).write_text(
            json.dumps({**metadata.to_dict(), "format_version": 999}), encoding="utf-8"
        )
        result = load_index(index_dir)
        assert result.valid is False
        assert result.reason == "unsupported index metadata format version 999"

    def test_a_failed_atomic_write_keeps_the_previous_artifact(
        self, index_dir, sample_documents, monkeypatch
    ):
        original = (index_dir / ARTIFACT_FILE).read_bytes()
        import os as _os

        def _boom(src, dst):
            raise OSError("disk full")

        monkeypatch.setattr(index_store.os, "replace", _boom)
        with pytest.raises(OSError):
            _save(index_dir, sample_documents[:2])

        monkeypatch.undo()
        assert (index_dir / ARTIFACT_FILE).read_bytes() == original
        assert load_index(index_dir).valid is True

    def test_a_successful_rewrite_leaves_no_temporary_files(self, index_dir, sample_documents):
        _save(index_dir, sample_documents[:1])
        assert sorted(p.name for p in index_dir.glob("*.tmp")) == []

    def test_restart_after_a_corrupt_artifact_reports_empty_not_a_crash(
        self, index_dir, sample_documents
    ):
        (index_dir / ARTIFACT_FILE).write_bytes(b"\xff\xfe\x00broken")
        manager = IndexManager(
            index_dir=index_dir,
            repository=make_document_repository(None),   # PostgreSQL is down
            seed_corpus=False,
        )
        state = manager.load_on_startup()
        assert state["loaded"] is False
        assert state["source"] == "empty"
        assert manager.engine.document_count == 0
        # ...and the service is still alive and honest about it.
        assert manager.status()["message"]
        assert manager.engine.search("python").hits == ()

    def test_restart_with_a_corrupt_artifact_and_a_live_database_rebuilds(
        self, index_dir, sample_documents
    ):
        (index_dir / ARTIFACT_FILE).write_bytes(b"garbage")
        manager = IndexManager(
            index_dir=index_dir,
            repository=FakeRepository.from_documents(sample_documents),
            seed_corpus=False,
        )
        state = manager.load_on_startup()
        assert state == {
            "loaded": True,
            "source": "rebuilt_from_postgresql",
            "document_count": len(sample_documents),
            # The *metadata* file survived the corrupted artifact, so the
            # recovery rebuild continues that version sequence.
            "index_version": 2,
        }
        assert load_index(index_dir).valid is True
        assert manager.engine.document_count == len(sample_documents)

    def test_metadata_write_is_the_second_half_of_the_commit(
        self, index_dir, sample_documents
    ):
        """A crash between artifact and metadata must never look 'valid'."""
        _save(index_dir, sample_documents)
        metadata = index_store.read_metadata(index_dir)
        (index_dir / METADATA_FILE).write_text("{ truncated", encoding="utf-8")
        result = load_index(index_dir)
        assert result.valid is False
        assert result.metadata is None
        assert metadata is not None   # the in-memory copy was readable before

    def test_metadata_whose_documents_are_not_objects_is_reported_not_raised(
        self, index_dir
    ):
        """Garbage inside the metadata makes it unreadable - never an exception."""
        metadata = index_store.read_metadata(index_dir)
        (index_dir / METADATA_FILE).write_text(
            json.dumps({**metadata.to_dict(), "documents": ["not-a-mapping"]}),
            encoding="utf-8",
        )
        result = load_index(index_dir)
        assert result.valid is False
        assert result.reason == "index metadata missing"
        assert index_store.read_metadata(index_dir) is None


# --------------------------------------------------------------------------- #
# 3. FAISS artifact persistence matrix
# --------------------------------------------------------------------------- #


class TestFaissPersistenceMatrix:
    @pytest.fixture
    def vectors(self, sample_documents):
        # Only the local libraries are needed - no model, no download.
        pytest.importorskip("faiss")
        np = pytest.importorskip("numpy")
        rng = np.random.default_rng(1234)
        raw = rng.random((len(sample_documents), 8)).astype("float32")
        norms = np.linalg.norm(raw, axis=1, keepdims=True)
        return raw / norms

    @pytest.fixture
    def artifact(self, tmp_path, sample_documents, vectors):
        from backend.search.faiss_store import FaissIndexMetadata, save_faiss_index

        root = tmp_path / "faiss"
        metadata = FaissIndexMetadata(
            index_version=1,
            model="phase10-fake-model",
            dimension=8,
            created_at=now_iso(),
            updated_at=now_iso(),
            document_count=len(sample_documents),
            corpus_hash=compute_document_signature(sample_documents),
            documents=tuple(
                {
                    "document_id": d.document_id,
                    "title": d.title,
                    "source": d.source,
                    "content": d.content,
                    "content_hash": d.content_hash,
                }
                for d in sample_documents
            ),
        )
        save_faiss_index(root, sample_documents, vectors, metadata)
        return root

    def _load(self, root):
        from backend.search.faiss_store import load_faiss_index

        return load_faiss_index(root)

    def test_valid_artifact_round_trips_vectors_and_documents(
        self, artifact, sample_documents
    ):
        result = self._load(artifact)
        assert result.valid, result.reason
        assert result.payload.dimension == 8
        assert result.payload.model == "phase10-fake-model"
        assert [d.document_id for d in result.payload.documents] == [
            d.document_id for d in sample_documents
        ]
        assert result.payload.vectors.shape == (len(sample_documents), 8)

    def test_missing_artifact_directory_is_reported_not_raised(self, tmp_path):
        result = self._load(tmp_path / "nowhere")
        assert result.valid is False
        assert result.reason

    def test_missing_metadata_is_reported_not_raised(self, artifact, tmp_path, sample_documents, vectors):
        from backend.search.faiss_store import FAISS_METADATA_FILE

        (artifact / FAISS_METADATA_FILE).unlink()
        result = self._load(artifact)
        assert result.valid is False
        assert "metadata" in result.reason

    def test_corrupt_index_file_is_reported_not_raised(self, artifact):
        from backend.search.faiss_store import FAISS_INDEX_FILE

        (artifact / FAISS_INDEX_FILE).write_bytes(b"\x00\x01\x02\x03")
        result = self._load(artifact)
        assert result.valid is False
        assert "corrupt" in result.reason or "faiss" in result.reason

    def test_corrupt_metadata_is_reported_not_raised(self, artifact):
        from backend.search.faiss_store import FAISS_METADATA_FILE

        (artifact / FAISS_METADATA_FILE).write_text("{ not json", encoding="utf-8")
        result = self._load(artifact)
        assert result.valid is False

    def test_dimension_mismatch_is_detected(self, artifact):
        import json

        from backend.search.faiss_store import FAISS_METADATA_FILE

        raw = json.loads((artifact / FAISS_METADATA_FILE).read_text(encoding="utf-8"))
        raw["dimension"] = raw["dimension"] + 4
        (artifact / FAISS_METADATA_FILE).write_text(json.dumps(raw), encoding="utf-8")
        result = self._load(artifact)
        assert result.valid is False
        assert "dimension" in result.reason

    def test_document_count_mismatch_is_detected(self, artifact):
        import json

        from backend.search.faiss_store import FAISS_METADATA_FILE

        raw = json.loads((artifact / FAISS_METADATA_FILE).read_text(encoding="utf-8"))
        raw["document_count"] = raw["document_count"] + 3
        (artifact / FAISS_METADATA_FILE).write_text(json.dumps(raw), encoding="utf-8")
        result = self._load(artifact)
        assert result.valid is False
        assert "count" in result.reason

    def test_corpus_hash_mismatch_is_detected(self, artifact):
        import json

        from backend.search.faiss_store import FAISS_METADATA_FILE

        raw = json.loads((artifact / FAISS_METADATA_FILE).read_text(encoding="utf-8"))
        raw["corpus_hash"] = "9" * 64
        (artifact / FAISS_METADATA_FILE).write_text(json.dumps(raw), encoding="utf-8")
        result = self._load(artifact)
        assert result.valid is False

    def test_unreadable_document_payload_is_reported_not_raised(self, artifact):
        """Garbage inside the metadata is unreadable metadata, not an exception."""
        import json

        from backend.search.faiss_store import FAISS_METADATA_FILE

        raw = json.loads((artifact / FAISS_METADATA_FILE).read_text(encoding="utf-8"))
        raw["documents"] = ["not-a-mapping"]
        (artifact / FAISS_METADATA_FILE).write_text(json.dumps(raw), encoding="utf-8")
        result = self._load(artifact)
        assert result.valid is False
        assert result.reason == "faiss metadata missing"
        assert result.payload is None and result.metadata is None

    def test_interrupted_write_leaves_the_previous_artifact_intact(self, artifact, sample_documents, vectors):
        from backend.search.faiss_store import FAISS_INDEX_FILE, save_faiss_index

        blob = (artifact / FAISS_INDEX_FILE).read_bytes()
        (artifact / (FAISS_INDEX_FILE + ".tmp")).write_bytes(b"half")
        assert self._load(artifact).valid is True
        assert (artifact / FAISS_INDEX_FILE).read_bytes() == blob

    def test_saving_leaves_no_temporary_files(self, artifact, sample_documents, vectors):
        assert sorted(artifact.glob("*.tmp")) == []

    def test_a_failed_write_keeps_the_previous_artifact(self, artifact, sample_documents, vectors, monkeypatch):
        import os

        from backend.search import faiss_store
        from backend.search.faiss_store import FAISS_INDEX_FILE, save_faiss_index

        blob = (artifact / FAISS_INDEX_FILE).read_bytes()

        def _boom(src, dst):
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", _boom)
        metadata = faiss_store.FaissIndexMetadata(
            dimension=8, document_count=len(sample_documents),
            corpus_hash=compute_document_signature(sample_documents),
        )
        with pytest.raises(OSError):
            save_faiss_index(artifact, sample_documents, vectors, metadata)

        monkeypatch.undo()
        assert (artifact / FAISS_INDEX_FILE).read_bytes() == blob
        assert self._load(artifact).valid is True

    def test_a_zero_dimension_artifact_is_refused_before_writing(self, tmp_path, sample_documents, vectors):
        from backend.search.faiss_store import FaissIndexMetadata, save_faiss_index

        with pytest.raises(ValueError):
            save_faiss_index(
                tmp_path / "faiss",
                sample_documents,
                vectors,
                FaissIndexMetadata(dimension=0),
            )
        assert not (tmp_path / "faiss").exists() or list(
            (tmp_path / "faiss").glob("*.tmp")
        ) == []


# --------------------------------------------------------------------------- #
# 4. failure / resilience combinations
# --------------------------------------------------------------------------- #


class TestFailureCombinations:
    def test_unavailable_database_plus_corrupt_artifact_still_serves_status(
        self, tmp_path, sample_documents
    ):
        root = tmp_path / "bm25"
        root.mkdir()
        _save(root, sample_documents)
        (root / ARTIFACT_FILE).write_bytes(b"corrupt")

        manager = IndexManager(
            index_dir=root, repository=make_document_repository(None), seed_corpus=False
        )
        state = manager.load_on_startup()
        assert state["loaded"] is False
        status = manager.status()
        assert status["database_available"] is False
        assert status["index_exists"] is True
        assert status["loaded"] is False

    def test_rebuild_without_a_database_raises_the_dedicated_error(self, tmp_path):
        manager = IndexManager(
            index_dir=tmp_path / "bm25",
            repository=make_document_repository(None),
            seed_corpus=False,
        )
        with pytest.raises(IndexUnavailableError):
            manager.rebuild()

    def test_a_repository_that_fails_mid_flight_is_contained(self, tmp_path, sample_documents):
        manager = IndexManager(
            index_dir=tmp_path / "bm25",
            repository=FakeRepository.from_documents(sample_documents, fail_with=RuntimeError("boom")),
            seed_corpus=False,
        )
        with pytest.raises(IndexUnavailableError):
            manager.rebuild()
        assert manager.engine.document_count == 0

    def test_a_repository_factory_that_explodes_degrades_instead_of_crashing(self, tmp_path):
        def _boom():
            raise RuntimeError("no database here")

        manager = IndexManager(index_dir=tmp_path / "bm25", repository_factory=_boom, seed_corpus=False)
        assert manager.load_on_startup()["source"] == "empty"
        assert manager.status()["database_available"] is False

    def test_refresh_without_a_database_reports_error_and_keeps_the_engine(
        self, tmp_path, sample_documents
    ):
        repository = FakeRepository.from_documents(sample_documents)
        manager = IndexManager(index_dir=tmp_path / "bm25", repository=repository, seed_corpus=False)
        manager.rebuild()
        repository.available = False

        result = manager.refresh()
        assert result.status == "error"
        assert "PostgreSQL unavailable" in result.message
        assert manager.engine.document_count == len(sample_documents), "engine untouched"

    def test_a_semantic_layer_that_raises_never_breaks_the_bm25_path(self, client, offline_index, monkeypatch):
        def _boom():
            raise RuntimeError("semantic manager exploded")

        monkeypatch.setattr("backend.api.search.get_semantic_index_manager", _boom)
        response = client.get("/api/search", params={"q": "python"})
        assert response.status_code == 200
        assert response.json()["hits"]
        assert response.json()["semantic"]["available"] is False

    @pytest.mark.parametrize("mode", ["hybrid", "semantic"])
    def test_a_semantic_manager_that_cannot_be_built_degrades_not_500(
        self, client, offline_index, monkeypatch, mode
    ):
        """``get_semantic_index_manager()`` raising is a *degraded* semantic layer.

        The lexical path already treated it that way; semantic and hybrid now
        report the same structured unavailability instead of a 500.
        """
        monkeypatch.setattr(
            "backend.api.search.get_semantic_index_manager",
            lambda: (_ for _ in ()).throw(RuntimeError("semantic manager down")),
        )
        response = client.get("/api/search", params={"q": "python", "mode": mode})
        assert response.status_code == 200
        data = response.json()
        assert data["hits"] == []
        if mode == "hybrid":
            assert data["status"] == "degraded"
            assert data["semantic_status"]["available"] is False
            assert "semantic index manager unavailable" in data["message"]
        else:
            assert data["semantic"]["available"] is False
            assert "semantic search unavailable" in data["message"]
            assert data["semantic"]["status"] == "unavailable"

    def test_a_specialized_mode_degrades_to_lexical_when_semantic_is_gone(
        self, client, offline_index, monkeypatch
    ):
        """A Phase 9 mode keeps serving BM25 hits when the semantic side dies."""
        monkeypatch.setattr(
            "backend.api.search.get_semantic_index_manager",
            lambda: (_ for _ in ()).throw(RuntimeError("semantic manager down")),
        )
        response = client.get("/api/search", params={"q": "docker container", "mode": "web"})
        assert response.status_code == 200
        data = response.json()
        assert data["mode"] == "web"
        assert data["status"] == "degraded"
        assert data["metadata"]["retrieval_strategy"] == "lexical"
        assert "semantic" in data["metadata"]["degraded_reason"]
        assert [h["document_id"] for h in data["hits"]] == ["dk-1"]

    def test_every_mode_survives_an_empty_index_and_a_dead_semantic_layer(
        self, client, empty_index, monkeypatch
    ):
        """The worst realistic case: nothing indexed and no semantic layer."""
        monkeypatch.setattr(
            "backend.api.search.get_semantic_index_manager",
            lambda: (_ for _ in ()).throw(RuntimeError("semantic manager down")),
        )
        for mode in ("web", "ai", "research", "code"):
            response = client.get("/api/search", params={"q": "python", "mode": mode})
            assert response.status_code == 200, mode
            data = response.json()
            assert data["status"] == "unavailable", mode
            assert data["hits"] == [], mode
            assert data["answer"] is None, mode

    def test_crawl_store_and_index_rebuild_compose(self, monkeypatch, tmp_path):
        """Crawl -> index rebuild -> search, with the database faked but alive."""
        from backend.crawler.models import CrawlPage
        from backend.crawler.service import CrawlStore

        store = CrawlStore()
        store.record(CrawlPage(
            url="https://example.com/redis",
            final_url="https://example.com/redis",
            status_code=200,
            title="Redis",
            text="Redis is an in-memory key value data store used for caching.",
            content_hash="c" * 64,
        ))
        rows = [
            FakeRepository.row(
                "local-1", title="Local", content="local reference body text",
                source="docs/local.md", content_hash="a" * 64,
            )
        ]
        rows += [
            FakeRepository.row(
                f"crawl-{p.content_hash[:12]}", title=p.title, content=p.text,
                source=p.url, content_hash=p.content_hash,
            )
            for p in store.crawled_pages()
        ]
        manager = IndexManager(
            index_dir=tmp_path / "bm25", repository=FakeRepository(rows), seed_corpus=False
        )
        result = manager.rebuild(include_crawled=True)
        assert result.crawled_documents == 1
        assert result.documents_indexed == 2
        assert manager.engine.search("redis cache").hits[0].document_id.startswith("crawl-")

        restarted = IndexManager(
            index_dir=tmp_path / "bm25", repository=FakeRepository(rows), seed_corpus=False
        )
        assert restarted.load_on_startup()["source"] == "persistent_index"
        assert restarted.engine.search("redis cache").hits[0].document_id.startswith("crawl-")

    def test_an_index_write_that_fails_midway_leaves_the_live_engine_usable(
        self, tmp_path, sample_documents, monkeypatch
    ):
        repository = FakeRepository.from_documents(sample_documents)
        manager = IndexManager(
            index_dir=tmp_path / "bm25", repository=repository, seed_corpus=False
        )
        manager.rebuild()
        before = manager.engine.search("python").hits[0].document_id

        monkeypatch.setattr(
            index_store, "_atomic_write", lambda *_a, **_k: (_ for _ in ()).throw(OSError("full"))
        )
        with pytest.raises(OSError):
            manager.rebuild()

        # The engine is only swapped *after* the artifact is persisted.
        assert manager.engine.search("python").hits[0].document_id == before