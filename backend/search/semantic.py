"""Semantic vector-index lifecycle + query orchestration (SEEK Phase 6).

:class:`SemanticIndexManager` is the FAISS/SentenceTransformers equivalent of
the Phase 5B BM25 :class:`~backend.search.index_manager.IndexManager`. It owns:

* **full rebuild** — read every document from PostgreSQL (after idempotently
  seeding the committed corpus), embed ``title + content`` with the local
  SentenceTransformers model, build an L2-normalised ``IndexFlatIP`` FAISS
  index (cosine similarity), persist it atomically and hot-swap the live state;
* **refresh** — change detection via the PostgreSQL ``document_id ->
  content_hash`` set (new / modified / deleted); when anything changed the whole
  FAISS index is deterministically rebuilt (never a fake "incremental" update);
* **startup load** — load a valid persisted FAISS artifact without touching the
  embedding model; a missing/corrupt artifact never blocks boot;
* **semantic search** — encode the query, run a top-k inner-product search and
  return the same :class:`SearchResponse` envelope as BM25.

Resilience contract (mirrors BM25 but stricter on laziness):
* BM25 never depends on this module — with ``sentence-transformers`` or ``faiss``
  missing, semantic is simply *unavailable* and BM25 keeps working.
* The embedding model is **never** loaded at module import time: importing
  ``backend.main`` must stay cheap and offline.
* ``load_on_startup`` loads the persisted FAISS artifact only; the model loads on
  the first semantic operation (search/rebuild).
* If PostgreSQL is unavailable but a valid persisted FAISS index exists, semantic
  search still works (content is cached alongside the vectors for snippets).
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from backend.config import settings
from backend.db.repository import DocumentRepository, make_document_repository
from backend.db.repository_factory import create_best_effort_repository
from backend.processing.models import ProcessedDocument
from backend.processing.snippets import build_snippet
from backend.search import faiss_store
from backend.search.embeddings import (
    EmbeddingGenerator,
    EmbeddingUnavailableError,
    get_embedding_generator,
)
from backend.search.index_manager import IndexManager
from backend.search.models import SearchResponse, SearchResult
from backend.search.query import QueryProcessor

logger = logging.getLogger("seek.search.semantic")

_HTTP_SOURCE_PREFIXES = ("http://", "https://")


class SemanticIndexError(RuntimeError):
    """Base error for the semantic index layer."""


class SemanticIndexUnavailableError(SemanticIndexError):
    """Raised when a rebuild/refresh needs PG or the ML stack and it is absent."""


@dataclass(frozen=True)
class SemanticBuildResult:
    """Outcome of a full FAISS rebuild from PostgreSQL."""

    status: str  # "rebuilt" | "empty"
    documents_indexed: int
    model: str
    dimension: Optional[int]
    index_version: Optional[int]
    built_at: str
    updated_at: str
    took_ms: float
    source: str
    message: str


@dataclass(frozen=True)
class SemanticRefreshResult:
    """Outcome of a semantic change-detection refresh."""

    status: str  # "unchanged" | "refreshed" | "error"
    document_count: int
    index_version: Optional[int]
    changed: dict[str, list[str]] = field(default_factory=dict)
    message: str = ""
    took_ms: float = 0.0


def document_text(doc: ProcessedDocument) -> str:
    """Deterministic embeddable text for one document (title + content)."""
    title = (doc.title or "").strip()
    content = (doc.content or "").strip()
    if title and content:
        return f"{title}\n{content}"
    return title or content


class SemanticIndexManager:
    """Owns the live FAISS index + persistent semantic artifact lifecycle."""

    def __init__(
        self,
        *,
        semantic_index_dir: Optional[str] = None,
        repository: Optional[DocumentRepository] = None,
        repository_factory: Optional[Callable[[], DocumentRepository]] = None,
        embedder: Optional[EmbeddingGenerator] = None,
        default_limit: Optional[int] = None,
        max_limit: Optional[int] = None,
        seed_corpus: bool = True,
    ) -> None:
        self._index_dir: Path = Path(
            semantic_index_dir or settings.semantic_index_dir
        )
        self._repository: Optional[DocumentRepository] = repository
        self._repo_factory: Callable[[], DocumentRepository] = (
            repository_factory
            or (lambda: create_best_effort_repository(settings.DATABASE_URL))
        )
        self._embedder: EmbeddingGenerator = embedder or get_embedding_generator()
        self._default_limit = int(
            default_limit if default_limit is not None else settings.SEARCH_DEFAULT_LIMIT
        )
        self._max_limit = int(
            max_limit if max_limit is not None else settings.SEARCH_MAX_LIMIT
        )
        self._seed_corpus = bool(seed_corpus)
        self._query = QueryProcessor()
        self._lock = threading.RLock()
        self._index: Any = None  # live faiss IndexFlatIP
        self._vectors: Any = None  # numpy.ndarray (n, dim) normalised float32
        self._documents: tuple[ProcessedDocument, ...] = ()
        self._metadata: Optional[faiss_store.FaissIndexMetadata] = None
        self._loaded = False

    # ------------------------------------------------------------------ #
    # plumbing
    # ------------------------------------------------------------------ #

    @property
    def index_dir(self) -> Path:
        return self._index_dir

    @property
    def embedder(self) -> EmbeddingGenerator:
        return self._embedder

    @property
    def loaded(self) -> bool:
        with self._lock:
            return self._loaded

    @property
    def metadata(self) -> Optional[faiss_store.FaissIndexMetadata]:
        with self._lock:
            return self._metadata

    @property
    def document_count(self) -> int:
        with self._lock:
            return len(self._documents)

    def _repo(self) -> Optional[DocumentRepository]:
        if self._repository is not None:
            return self._repository
        with self._lock:
            if self._repository is None:
                try:
                    self._repository = self._repo_factory()
                except Exception as exc:  # noqa: BLE001 - degraded path is fine
                    logger.warning("semantic repository factory failed: %s", exc)
                    self._repository = make_document_repository(None)
        return self._repository

    def _live_repository(self) -> Optional[DocumentRepository]:
        """Return a usable repository or ``None`` (never raises)."""
        repo = self._repo()
        if repo is None:
            return None
        try:
            if repo.is_available():
                return repo
        except Exception as exc:  # noqa: BLE001
            logger.debug("semantic repo availability check failed: %s", exc)
            return None
        if self._repository is not None:
            try:
                fresh = self._repo_factory()
                if fresh is not None and fresh.is_available():
                    with self._lock:
                        self._repository = fresh
                    return fresh
            except Exception as exc:  # noqa: BLE001
                logger.debug("semantic repo refresh attempt failed: %s", exc)
        return None

    def _rows_to_documents(self, rows: list, *, include_crawled: bool) -> list[ProcessedDocument]:
        # Reuse the exact BM25 document-conversion (deterministic, token-aware)
        # so BM25 and semantic indexes cover the same PostgreSQL document set.
        return IndexManager._rows_to_processed(rows, include_crawled=include_crawled)

    # ------------------------------------------------------------------ #
    # change detection
    # ------------------------------------------------------------------ #

    def _db_digest(self, repo: Optional[DocumentRepository]) -> dict[str, str]:
        if repo is None:
            return {}
        try:
            rows = repo.list_all()
        except Exception as exc:  # noqa: BLE001 - degraded path
            logger.debug("semantic list_all failed during change detection: %s", exc)
            return {}
        return {
            str(getattr(r, "document_id", "") or ""): (getattr(r, "content_hash", "") or "")
            for r in rows
        }

    def _index_digest(self) -> Optional[dict[str, str]]:
        md = self._metadata
        if md is None:
            md = faiss_store.read_faiss_metadata(self._index_dir)
        if md is None:
            return None
        return {
            str(d.get("document_id", "")): str(d.get("content_hash", "") or "")
            for d in md.documents
        }

    def detect_changes(
        self, repository: Optional[DocumentRepository] = None
    ) -> dict[str, list[str]]:
        """Compare PostgreSQL vs persisted FAISS identity/hash sets."""
        repo = repository or self._repo()
        db = self._db_digest(repo)
        index_digest = self._index_digest() or {}
        db_keys, index_keys = set(db), set(index_digest)
        return {
            "new": sorted(db_keys - index_keys),
            "modified": sorted(
                k for k in (db_keys & index_keys) if db.get(k) != index_digest.get(k)
            ),
            "deleted": sorted(index_keys - db_keys),
        }

    # ------------------------------------------------------------------ #
    # build / refresh / startup
    # ------------------------------------------------------------------ #

    def _build_index(self, vectors: Any, dimension: int) -> Any:
        try:
            import faiss
        except ImportError as exc:
            raise SemanticIndexUnavailableError(
                f"faiss is not available: {exc}"
            ) from exc
        index = faiss.IndexFlatIP(dimension)
        if len(vectors):
            index.add(vectors)
        return index

    def rebuild(
        self,
        *,
        include_crawled: bool = True,
        seed_corpus: Optional[bool] = None,
    ) -> SemanticBuildResult:
        """Reconstruct the FAISS index from the current PostgreSQL document set.

        This is a **deterministic full rebuild** after change detection — the
        semantic index is never mutated incrementally, and a mid-build failure
        leaves the previous index + artifact untouched (persist happens before
        the live state is swapped).
        """
        started = time.perf_counter()
        repo = self._live_repository()
        if repo is None or not repo.is_available():
            raise SemanticIndexUnavailableError(
                "PostgreSQL unavailable; the semantic index cannot be rebuilt"
            )
        should_seed = self._seed_corpus if seed_corpus is None else seed_corpus
        if should_seed:
            try:
                from backend.pipeline import persist_corpus

                persist_corpus(repo)
            except Exception as exc:  # noqa: BLE001 - corpus seeding is optional
                logger.debug("semantic corpus seeding skipped during rebuild: %s", exc)

        rows = repo.list_all()
        documents = self._rows_to_documents(rows, include_crawled=include_crawled)
        if not documents:
            with self._lock:
                self._index = None
                self._vectors = None
                self._documents = ()
                self._metadata = None
                self._loaded = False
            try:
                faiss_store.remove_faiss_index(self._index_dir)
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
            return SemanticBuildResult(
                status="empty",
                documents_indexed=0,
                model=self._embedder.model_name,
                dimension=None,
                index_version=None,
                built_at=faiss_store.now_iso(),
                updated_at=faiss_store.now_iso(),
                took_ms=round((time.perf_counter() - started) * 1000.0, 3),
                source="postgresql",
                message="no documents in PostgreSQL; semantic index cleared",
            )

        try:
            vectors = self._embedder.encode_texts(
                [document_text(d) for d in documents]
            )
        except EmbeddingUnavailableError as exc:
            raise SemanticIndexUnavailableError(
                f"semantic rebuild failed (embedding model unavailable): {exc}"
            ) from exc

        previous = self._metadata or faiss_store.read_faiss_metadata(self._index_dir)
        metadata = faiss_store.build_faiss_metadata(
            documents=documents,
            vectors=vectors,
            model=self._embedder.model_name,
            previous=previous,
        )
        index = self._build_index(vectors, metadata.dimension)

        faiss_store.save_faiss_index(
            self._index_dir, documents, vectors, metadata
        )
        with self._lock:
            self._index = index
            self._vectors = vectors
            self._documents = tuple(documents)
            self._metadata = metadata
            self._loaded = True

        took_ms = (time.perf_counter() - started) * 1000.0
        return SemanticBuildResult(
            status="rebuilt",
            documents_indexed=len(documents),
            model=metadata.model,
            dimension=metadata.dimension,
            index_version=metadata.index_version,
            built_at=metadata.created_at,
            updated_at=metadata.updated_at,
            took_ms=round(took_ms, 3),
            source="postgresql",
            message=(
                f"semantic index rebuilt from {len(documents)} PostgreSQL "
                f"documents (version {metadata.index_version})"
            ),
        )

    def refresh(self) -> SemanticRefreshResult:
        """Change-detection refresh; full FAISS rebuild only when stale."""
        started = time.perf_counter()
        repo = self._live_repository()
        if repo is None or not repo.is_available():
            return SemanticRefreshResult(
                status="error",
                document_count=self.document_count,
                index_version=self._metadata.index_version if self._metadata else None,
                message="PostgreSQL unavailable; semantic index refresh skipped",
                took_ms=round((time.perf_counter() - started) * 1000.0, 3),
            )

        if not self._loaded:
            if faiss_store.is_faiss_present(self._index_dir):
                self.load_on_startup()
            else:
                build = self.rebuild()
                return SemanticRefreshResult(
                    status="refreshed",
                    document_count=build.documents_indexed,
                    index_version=build.index_version,
                    changed={"new": [""], "modified": [], "deleted": []},
                    message="semantic index built from PostgreSQL",
                    took_ms=round((time.perf_counter() - started) * 1000.0, 3),
                )

        changes = self.detect_changes(repo)
        total_changed = (
            len(changes["new"]) + len(changes["modified"]) + len(changes["deleted"])
        )
        if total_changed == 0:
            return SemanticRefreshResult(
                status="unchanged",
                document_count=self.document_count,
                index_version=self._metadata.index_version if self._metadata else None,
                changed=changes,
                message="semantic index is up to date with PostgreSQL",
                took_ms=round((time.perf_counter() - started) * 1000.0, 3),
            )

        build = self.rebuild()
        took_ms = (time.perf_counter() - started) * 1000.0
        return SemanticRefreshResult(
            status="refreshed",
            document_count=build.documents_indexed,
            index_version=build.index_version,
            changed=changes,
            message=(
                f"semantic index rebuilt from PostgreSQL after detecting "
                f"{total_changed} changed document(s)"
            ),
            took_ms=round(took_ms, 3),
        )

    def load_on_startup(self) -> dict[str, object]:
        """Load a persisted FAISS index, or start not-built (never raises).

        Deliberately does **not** load the embedding model and never attempts a
        rebuild here — model loading is deferred to the first semantic
        operation, and a missing semantic index must not block boot (BM25 is
        untouched by this method).
        """
        if faiss_store.is_faiss_present(self._index_dir):
            result = faiss_store.load_faiss_index(self._index_dir)
            if result.valid and result.payload is not None:
                try:
                    index = self._build_index(
                        result.payload.vectors, result.payload.dimension
                    )
                except SemanticIndexUnavailableError as exc:
                    logger.warning(
                        "Persistent FAISS index present but faiss unavailable: %s", exc
                    )
                    self._clear_live()
                    return {
                        "loaded": False,
                        "source": "faiss_unavailable",
                        "document_count": 0,
                        "index_version": None,
                        "message": "faiss unavailable; cannot load semantic index",
                    }
                with self._lock:
                    self._index = index
                    self._vectors = result.payload.vectors
                    self._documents = result.payload.documents
                    self._metadata = result.metadata
                    self._loaded = True
                return {
                    "loaded": True,
                    "source": "persistent_faiss_index",
                    "document_count": len(result.payload.documents),
                    "index_version": (
                        result.metadata.index_version if result.metadata else None
                    ),
                    "model": result.payload.model,
                }
            logger.warning(
                "Persistent FAISS index invalid (%s); semantic starts not-built",
                result.reason,
            )
        self._clear_live()
        return {
            "loaded": False,
            "source": "no_persistent_faiss_index",
            "document_count": 0,
            "index_version": None,
            "message": "no valid semantic index; run /api/index/semantic/rebuild",
        }

    def _clear_live(self) -> None:
        with self._lock:
            self._index = None
            self._vectors = None
            self._documents = ()
            self._metadata = None
            self._loaded = False

    def close(self) -> None:
        with self._lock:
            if self._repository is not None:
                try:
                    self._repository.close()
                except Exception as exc:  # noqa: BLE001 - best-effort
                    logger.debug("semantic repository close skipped: %s", exc)
                self._repository = None
            self._clear_live()

    # ------------------------------------------------------------------ #
    # search
    # ------------------------------------------------------------------ #

    def search(
        self,
        query: str,
        *,
        limit: Optional[int] = None,
        max_limit: Optional[int] = None,
    ) -> SearchResponse:
        """Cosine-similarity semantic search; returns the shared envelope.

        ``score`` is the cosine similarity between the (L2-normalised) query and
        document embeddings, in ``[-1, 1]`` — higher is more similar.
        ``matched_terms`` is always empty because semantic similarity does not
        depend on lexical term matching.

        Raises :class:`EmbeddingUnavailableError` when the model cannot run.
        """
        start = time.perf_counter()
        folded = self._query.normalize_query(query or "")
        limit = max(1, int(limit if limit is not None else self._default_limit))
        cap = int(max_limit if max_limit is not None else self._max_limit)
        limit = min(limit, cap)

        with self._lock:
            index = self._index
            documents = self._documents
            metadata = self._metadata

        if index is None or not self._loaded or not documents or metadata is None:
            return SearchResponse(
                query=folded,
                total=0,
                limit=limit,
                hits=(),
                took_ms=(time.perf_counter() - start) * 1000.0,
                message="semantic index not built; run /api/index/semantic/rebuild",
            )

        try:
            qv = self._embedder.encode_texts([folded or query or ""])
        except EmbeddingUnavailableError:
            raise
        if int(qv.shape[1]) != metadata.dimension:
            raise EmbeddingUnavailableError(
                f"embedding dimension {qv.shape[1]} != index dimension "
                f"{metadata.dimension}; rebuild the semantic index"
            )

        n = len(documents)
        k = min(limit, n)
        scores, idxs = index.search(qv.reshape(1, -1).astype("float32"), k)

        tokens = [w.token for w in self._query.process(folded)]
        hits: list[SearchResult] = []
        for rank in range(k):
            idx = int(idxs[0][rank])
            if idx < 0 or idx >= n:
                continue
            doc = documents[idx]
            hits.append(
                SearchResult(
                    rank=len(hits) + 1,
                    document_id=doc.document_id,
                    title=doc.title,
                    source=doc.source,
                    snippet=build_snippet(doc.content, tokens),
                    score=float(scores[0][rank]),
                    matched_terms=(),
                )
            )

        return SearchResponse(
            query=folded,
            total=len(hits),
            limit=limit,
            hits=tuple(hits),
            took_ms=(time.perf_counter() - start) * 1000.0,
            message="ok",
            metadata={
                "mode": "semantic",
                "model": metadata.model,
                "dimension": metadata.dimension,
                "semantic": True,
            },
        )

    # ------------------------------------------------------------------ #
    # status
    # ------------------------------------------------------------------ #

    def status(self) -> dict[str, object]:
        """Safe, never-raises report of the semantic index / ML stack state."""
        with self._lock:
            metadata = self._metadata
            loaded = self._loaded
            document_count = len(self._documents)
        persisted = metadata
        if persisted is None:
            persisted = faiss_store.read_faiss_metadata(self._index_dir)
        repo = self._live_repository()
        database_available = bool(repo is not None and repo.is_available())

        model_available = bool(self._embedder.is_available())
        model = self._embedder.model_name
        dimension = (
            persisted.dimension
            if persisted and persisted.dimension
            else self._embedder.loaded_dimension
        )

        stale: Optional[bool] = None
        if database_available and persisted is not None:
            db_digest = self._db_digest(repo)
            index_digest = {
                str(d.get("document_id", "")): str(d.get("content_hash", "") or "")
                for d in persisted.documents
            }
            stale = db_digest != index_digest

        index_exists = faiss_store.is_faiss_present(self._index_dir)
        message = _semantic_status_message(
            loaded=loaded,
            exists=index_exists,
            model_available=model_available,
            database_available=database_available,
            stale=stale,
        )
        return {
            "available": model_available,
            "model": model,
            "model_loaded": self._embedder.model_loaded,
            "dimension": dimension,
            "loaded": loaded,
            "index_exists": index_exists,
            "document_count": document_count,
            "database_available": database_available,
            "index_version": persisted.index_version if persisted else None,
            "created_at": persisted.created_at if persisted else None,
            "updated_at": persisted.updated_at if persisted else None,
            "corpus_hash": persisted.corpus_hash if persisted else None,
            "stale": stale,
            "message": message,
        }


def _semantic_status_message(
    *,
    loaded: bool,
    exists: bool,
    model_available: bool,
    database_available: bool,
    stale: Optional[bool],
) -> str:
    if not model_available:
        return "semantic search unavailable (sentence-transformers not installed)"
    if loaded and exists and stale is False:
        return "semantic index is loaded and up to date with PostgreSQL"
    if loaded and exists and stale is True:
        return "semantic index is loaded but stale relative to PostgreSQL; run refresh"
    if loaded and not exists:
        return "in-memory semantic index active (not persisted)"
    if exists and not loaded:
        return "semantic artifact present but not loaded"
    if database_available:
        return "semantic index not built; run /api/index/semantic/rebuild"
    return (
        "no semantic index and PostgreSQL unreachable; "
        "a persisted FAISS index would still serve search"
    )


# --------------------------------------------------------------------------- #
# process-wide singleton (default wiring, used by the API + lifespan)
# --------------------------------------------------------------------------- #

_manager: Optional[SemanticIndexManager] = None
_manager_lock = threading.Lock()


def get_semantic_index_manager() -> SemanticIndexManager:
    """Return the process-wide :class:`SemanticIndexManager` (lazily created)."""
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = SemanticIndexManager()
        return _manager


def reset_semantic_index_manager() -> None:
    """Drop the process-wide manager (used by tests for isolation)."""
    global _manager
    with _manager_lock:
        if _manager is not None:
            _manager.close()
        _manager = None


__all__ = [
    "SemanticIndexManager",
    "SemanticIndexError",
    "SemanticIndexUnavailableError",
    "SemanticBuildResult",
    "SemanticRefreshResult",
    "document_text",
    "get_semantic_index_manager",
    "reset_semantic_index_manager",
]