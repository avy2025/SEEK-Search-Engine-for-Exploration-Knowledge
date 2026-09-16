"""Index lifecycle orchestration for the persistent BM25 pipeline (Phase 5B).

``backend.search.index_manager.IndexManager`` is the single object that owns
the **live** :class:`~backend.search.engine.SearchEngine` plus the persistent
artifact state. It performs:

* **full rebuild** — read every document from PostgreSQL (after idempotently
  seeding the committed corpus), reconstruct the BM25 engine, persist the
  artifact atomically and hot-swap the live engine;
* **refresh** — detect new/modified/deleted documents by comparing the
  PostgreSQL ``document_id -> content_hash`` set against the persisted index
  metadata, and rebuild (reconstruct) the BM25 index from the current
  PostgreSQL set only when something changed;
* **startup load** — load a valid persisted artifact without requiring
  PostgreSQL, rebuild from PostgreSQL when the artifact is missing/corrupt and
  the database is reachable, or start with an empty engine otherwise.

Important: the persisted artifact is a **derived** representation — PostgreSQL
is the canonical document source. BM25 is never mutated incrementally; when
change detection reports any difference the whole model is reconstructed from
the current PostgreSQL document set.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from backend.config import settings
from backend.db.repository import DocumentRepository, make_document_repository
from backend.db.repository_factory import create_best_effort_repository
from backend.processing.models import ProcessedDocument
from backend.processing.tokenizer import tokenize
from backend.search import index_store
from backend.search.engine import SearchEngine

logger = logging.getLogger("seek.search.index_manager")

_HTTP_SOURCE_PREFIXES = ("http://", "https://")


class IndexUnavailableError(RuntimeError):
    """Raised when a rebuild/refresh needs PostgreSQL but it is unavailable."""


@dataclass(frozen=True)
class IndexBuildResult:
    """Outcome of a full BM25 rebuild from PostgreSQL."""

    status: str
    documents_indexed: int
    crawled_documents: int
    index_version: int
    built_at: str
    updated_at: str
    took_ms: float
    source: str
    message: str


@dataclass(frozen=True)
class IndexRefreshResult:
    """Outcome of an incremental change-detection refresh."""

    status: str  # "unchanged" | "refreshed" | "error"
    document_count: int
    index_version: Optional[int]
    changed: dict[str, list[str]] = field(default_factory=dict)
    message: str = ""
    took_ms: float = 0.0


class IndexManager:
    """Owns the live search engine + persistent artifact lifecycle."""

    def __init__(
        self,
        *,
        index_dir: Optional[str] = None,
        repository: Optional[DocumentRepository] = None,
        repository_factory: Optional[Callable[[], DocumentRepository]] = None,
        k1: Optional[float] = None,
        b: Optional[float] = None,
        epsilon: float = 0.25,
        default_limit: Optional[int] = None,
        max_limit: Optional[int] = None,
        seed_corpus: bool = True,
    ) -> None:
        self._index_dir: Path = Path(index_dir or settings.index_dir)
        self._repository: Optional[DocumentRepository] = repository
        self._repo_factory: Callable[[], DocumentRepository] = (
            repository_factory
            or (lambda: create_best_effort_repository(settings.DATABASE_URL))
        )
        self._k1 = float(k1 if k1 is not None else settings.BM25_K1)
        self._b = float(b if b is not None else settings.BM25_B)
        self._epsilon = float(epsilon)
        self._default_limit = int(
            default_limit if default_limit is not None else settings.SEARCH_DEFAULT_LIMIT
        )
        self._max_limit = int(
            max_limit if max_limit is not None else settings.SEARCH_MAX_LIMIT
        )
        self._seed_corpus = bool(seed_corpus)
        self._lock = threading.RLock()
        self._engine: SearchEngine = self._make_engine(())
        self._metadata: Optional[index_store.IndexMetadata] = None
        self._loaded = False

    # ------------------------------------------------------------------ #
    # engine / repository plumbing
    # ------------------------------------------------------------------ #

    def _make_engine(self, documents) -> SearchEngine:
        return SearchEngine(
            documents,
            k1=self._k1,
            b=self._b,
            default_limit=self._default_limit,
            max_limit=self._max_limit,
        )

    def _repo(self) -> Optional[DocumentRepository]:
        if self._repository is not None:
            return self._repository
        with self._lock:
            if self._repository is None:
                try:
                    self._repository = self._repo_factory()
                except Exception as exc:  # noqa: BLE001 - degraded path is fine
                    logger.warning("repository factory failed: %s", exc)
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
            logger.debug("repository availability check failed: %s", exc)
            return None
        # An explicitly-injected repository may be degraded while the factory
        # could produce a live one (e.g. PostgreSQL came up after startup).
        if self._repository is not None:
            try:
                fresh = self._repo_factory()
                if fresh is not None:
                    try:
                        if fresh.is_available():
                            with self._lock:
                                self._repository = fresh
                            return fresh
                    except Exception:  # noqa: BLE001
                        return None
            except Exception as exc:  # noqa: BLE001
                logger.debug("repository refresh attempt failed: %s", exc)
        return None

    # ------------------------------------------------------------------ #
    # public surface
    # ------------------------------------------------------------------ #

    @property
    def engine(self) -> SearchEngine:
        with self._lock:
            return self._engine

    @property
    def index_dir(self) -> Path:
        return self._index_dir

    @property
    def loaded(self) -> bool:
        with self._lock:
            return self._loaded

    @property
    def metadata(self) -> Optional[index_store.IndexMetadata]:
        with self._lock:
            return self._metadata

    def set_engine(self, engine: SearchEngine) -> None:
        """Swap the live engine (legacy/offline path). Not persisted."""
        with self._lock:
            self._engine = engine
            self._loaded = True

    def close(self) -> None:
        with self._lock:
            if self._repository is not None:
                try:
                    self._repository.close()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("repository close skipped: %s", exc)
                self._repository = None

    # ------------------------------------------------------------------ #
    # document conversion + metadata
    # ------------------------------------------------------------------ #

    @staticmethod
    def _rows_to_processed(
        rows: list, *, include_crawled: bool = True
    ) -> list[ProcessedDocument]:
        docs: list[ProcessedDocument] = []
        for row in sorted(rows, key=lambda r: getattr(r, "document_id", 0) or 0):
            source = getattr(row, "source", "") or ""
            if not include_crawled and source.startswith(_HTTP_SOURCE_PREFIXES):
                continue
            content = (getattr(row, "content", "") or "").strip()
            tokens = tokenize(content)
            if not tokens:
                continue
            docs.append(
                ProcessedDocument(
                    document_id=str(getattr(row, "document_id", "") or ""),
                    title=getattr(row, "title", "") or "",
                    content=content,
                    source=source,
                    tokens=tuple(tokens),
                    snippet_tokens=tuple(tokenize(content, keep_stopwords=True)),
                    content_hash=getattr(row, "content_hash", "") or "",
                )
            )
        return docs

    def _make_metadata(
        self,
        documents: list[ProcessedDocument],
        previous: Optional[index_store.IndexMetadata],
    ) -> index_store.IndexMetadata:
        now = index_store.now_iso()
        return index_store.IndexMetadata(
            format_version=index_store.INDEX_FORMAT_VERSION,
            index_version=(previous.index_version + 1 if previous else 1),
            created_at=(previous.created_at or now) if previous else now,
            updated_at=now,
            document_count=len(documents),
            max_document_id=index_store.max_document_id(documents),
            corpus_hash=index_store.compute_document_signature(documents),
            documents=tuple(
                {
                    "document_id": d.document_id,
                    "content_hash": d.content_hash or "",
                }
                for d in documents
            ),
        )

    # ------------------------------------------------------------------ #
    # change detection
    # ------------------------------------------------------------------ #

    def _db_digest(self, repo: Optional[DocumentRepository]) -> dict[str, str]:
        if repo is None:
            return {}
        try:
            rows = repo.list_all()
        except Exception as exc:  # noqa: BLE001 - degraded path
            logger.debug("list_all failed during change detection: %s", exc)
            return {}
        return {
            str(getattr(r, "document_id", "") or ""): (getattr(r, "content_hash", "") or "")
            for r in rows
        }

    def _index_digest(self) -> Optional[dict[str, str]]:
        md = self._metadata
        if md is None:
            md = index_store.read_metadata(self._index_dir)
        if md is None:
            return None
        return {
            str(d.get("document_id", "")): str(d.get("content_hash", "") or "")
            for d in md.documents
        }

    def detect_changes(
        self, repository: Optional[DocumentRepository] = None
    ) -> dict[str, list[str]]:
        """Compare PostgreSQL vs persisted index identity/hash sets."""
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

    def rebuild(
        self, *, include_crawled: bool = True, seed_corpus: Optional[bool] = None
    ) -> IndexBuildResult:
        """Reconstruct BM25 from the current PostgreSQL document set.

        The build writes to a temporary state and only swaps the live engine
        after the artifact has been persisted, so a mid-build failure leaves
        the previous engine and artifact untouched.
        """
        started = time.perf_counter()
        repo = self._live_repository()
        if repo is None or not repo.is_available():
            raise IndexUnavailableError(
                "PostgreSQL unavailable; the persistent index cannot be rebuilt"
            )
        should_seed = self._seed_corpus if seed_corpus is None else seed_corpus
        if should_seed:
            try:
                from backend.pipeline import persist_corpus

                persist_corpus(repo)
            except Exception as exc:  # noqa: BLE001 - corpus seeding is optional
                logger.debug("corpus seeding skipped during rebuild: %s", exc)

        rows = repo.list_all()
        documents = self._rows_to_processed(rows, include_crawled=include_crawled)
        previous = self._metadata or index_store.read_metadata(self._index_dir)
        metadata = self._make_metadata(documents, previous)
        engine = self._make_engine(documents)

        index_store.save_index(
            self._index_dir,
            documents,
            metadata,
            k1=self._k1,
            b=self._b,
            epsilon=self._epsilon,
            default_limit=self._default_limit,
            max_limit=self._max_limit,
        )
        with self._lock:
            self._engine = engine
            self._metadata = metadata
            self._loaded = True

        took_ms = (time.perf_counter() - started) * 1000.0
        crawled = sum(
            1 for d in documents if d.source.startswith(_HTTP_SOURCE_PREFIXES)
        )
        return IndexBuildResult(
            status="rebuilt",
            documents_indexed=len(documents),
            crawled_documents=crawled if include_crawled else 0,
            index_version=metadata.index_version,
            built_at=metadata.created_at,
            updated_at=metadata.updated_at,
            took_ms=round(took_ms, 3),
            source="postgresql",
            message=(
                f"index rebuilt from {len(documents)} PostgreSQL documents "
                f"(version {metadata.index_version})"
            ),
        )

    def refresh(self) -> IndexRefreshResult:
        """Change-detection refresh; rebuild only when the index is stale."""
        started = time.perf_counter()
        repo = self._live_repository()
        if repo is None or not repo.is_available():
            return IndexRefreshResult(
                status="error",
                document_count=self.engine.document_count,
                index_version=self._metadata.index_version if self._metadata else None,
                message="PostgreSQL unavailable; index refresh skipped",
                took_ms=round((time.perf_counter() - started) * 1000.0, 3),
            )

        if not self._loaded:
            if index_store.is_index_present(self._index_dir):
                self.load_on_startup()
            else:
                build = self.rebuild()
                return IndexRefreshResult(
                    status="refreshed",
                    document_count=build.documents_indexed,
                    index_version=build.index_version,
                    changed={"new": [""], "modified": [], "deleted": []},
                    message="index built from PostgreSQL",
                    took_ms=round((time.perf_counter() - started) * 1000.0, 3),
                )

        changes = self.detect_changes(repo)
        total_changed = (
            len(changes["new"]) + len(changes["modified"]) + len(changes["deleted"])
        )
        if total_changed == 0:
            return IndexRefreshResult(
                status="unchanged",
                document_count=self.engine.document_count,
                index_version=self._metadata.index_version if self._metadata else None,
                changed=changes,
                message="index is up to date with PostgreSQL",
                took_ms=round((time.perf_counter() - started) * 1000.0, 3),
            )

        build = self.rebuild()
        took_ms = (time.perf_counter() - started) * 1000.0
        return IndexRefreshResult(
            status="refreshed",
            document_count=build.documents_indexed,
            index_version=build.index_version,
            changed=changes,
            message=(
                f"index rebuilt from PostgreSQL after detecting "
                f"{total_changed} changed document(s)"
            ),
            took_ms=round(took_ms, 3),
        )

    def load_on_startup(self) -> dict[str, object]:
        """Load the persistent index, or rebuild/start-empty (never raises)."""
        if index_store.is_index_present(self._index_dir):
            result = index_store.load_index(self._index_dir)
            if result.valid and result.payload is not None:
                engine = self._make_engine(result.payload.documents)
                with self._lock:
                    self._engine = engine
                    self._metadata = result.metadata
                    self._loaded = True
                return {
                    "loaded": True,
                    "source": "persistent_index",
                    "document_count": engine.document_count,
                    "index_version": (
                        result.metadata.index_version if result.metadata else None
                    ),
                }
            logger.warning(
                "Persistent index invalid (%s); attempting rebuild from PostgreSQL",
                result.reason,
            )
        repo = self._live_repository()
        if repo is not None:
            try:
                build = self.rebuild()
                return {
                    "loaded": True,
                    "source": "rebuilt_from_postgresql",
                    "document_count": build.documents_indexed,
                    "index_version": build.index_version,
                }
            except IndexUnavailableError as exc:  # noqa: BLE001
                logger.warning("Startup rebuild skipped: %s", exc)
        with self._lock:
            self._engine = self._make_engine(())
            self._metadata = None
            self._loaded = False
        return {
            "loaded": False,
            "source": "empty",
            "document_count": 0,
            "index_version": None,
            "message": "no valid persistent index and PostgreSQL unavailable",
        }

    # ------------------------------------------------------------------ #
    # status
    # ------------------------------------------------------------------ #

    def status(self) -> dict[str, object]:
        with self._lock:
            engine = self._engine
            loaded = self._loaded
            metadata = self._metadata
        persisted = metadata
        if persisted is None:
            persisted = index_store.read_metadata(self._index_dir)
        repo = self._live_repository()
        database_available = bool(repo is not None and repo.is_available())

        stale: Optional[bool] = None
        if database_available and persisted is not None:
            db_digest = self._db_digest(repo)
            index_digest = {
                str(d.get("document_id", "")): str(d.get("content_hash", "") or "")
                for d in persisted.documents
            }
            stale = db_digest != index_digest

        message = _status_message(
            loaded=loaded,
            exists=index_store.is_index_present(self._index_dir),
            database_available=database_available,
            stale=stale,
        )
        return {
            "index_exists": index_store.is_index_present(self._index_dir),
            "loaded": loaded,
            "document_count": engine.document_count,
            "database_available": database_available,
            "index_version": persisted.index_version if persisted else None,
            "created_at": persisted.created_at if persisted else None,
            "updated_at": persisted.updated_at if persisted else None,
            "corpus_hash": persisted.corpus_hash if persisted else None,
            "stale": stale,
            "message": message,
        }


def _status_message(*, loaded: bool, exists: bool, database_available: bool, stale: Optional[bool]) -> str:
    if loaded and exists and stale is False:
        return "persistent index is loaded and up to date with PostgreSQL"
    if loaded and exists and stale is True:
        return "persistent index is loaded but stale relative to PostgreSQL; run refresh"
    if loaded and not exists:
        return "in-memory index active (not persisted)"
    if not loaded and exists:
        return "index artifact present but not loaded"
    if not loaded and not database_available:
        return "no index available and PostgreSQL unreachable; run rebuild when available"
    return "no index built yet; run /api/index/rebuild"


# --------------------------------------------------------------------------- #
# process-wide singleton (default wiring, used by the API + lifespan)
# --------------------------------------------------------------------------- #

_manager: Optional[IndexManager] = None
_manager_lock = threading.Lock()


def get_index_manager() -> IndexManager:
    """Return the process-wide :class:`IndexManager` (lazily created)."""
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = IndexManager()
        return _manager


def reset_index_manager() -> None:
    """Drop the process-wide manager (used by tests for isolation)."""
    global _manager
    with _manager_lock:
        if _manager is not None:
            _manager.close()
        _manager = None


__all__ = [
    "IndexManager",
    "IndexBuildResult",
    "IndexRefreshResult",
    "IndexUnavailableError",
    "get_index_manager",
    "reset_index_manager",
]