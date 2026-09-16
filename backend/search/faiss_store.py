"""Persistent FAISS semantic index storage (SEEK Phase 6).

``backend.search.faiss_store`` owns every byte written for the semantic
vector index under the configured directory (default ``indexes/``):

* ``faiss_index.bin`` — a FAISS "inner product" index over **L2-normalised**
  vectors, so ``score = cosine similarity``. The vector at position ``i``
  corresponds to ``metadata.documents[i]``.
* ``faiss_metadata.json`` — a deterministic companion describing the build:
  model, dimension, format/index versions, build timestamps, per-vector
  ``document_id -> {title, source, content, content_hash}`` mapping and a
  corpus-level content signature used for change detection.

Design notes
------------
* Mirror of the Phase 5B BM25 store (:mod:`backend.search.index_store`): the
  artifact is a **derived** representation of the PostgreSQL ``documents``
  table — a missing/corrupt artifact is always rebuildable from PostgreSQL.
* Writes are **atomic** on a per-file basis: a sibling ``*.tmp`` file is
  written + fsynced, then :func:`os.replace` swaps it in. A failed build can
  never truncate a previously-valid index.
* **Lazy imports** — ``numpy``/``faiss`` are imported inside functions only, so
  importing this module (and therefore ``backend.main``) never fails when the
  optional ML stack is missing.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from backend.processing.models import ProcessedDocument
from backend.search.index_store import (
    compute_document_signature,
    document_from_dict,
    document_to_dict,
    now_iso,
)

logger = logging.getLogger("seek.search.faiss_store")

FAISS_FORMAT_VERSION = 1
FAISS_INDEX_FILE = "faiss_index.bin"
FAISS_METADATA_FILE = "faiss_metadata.json"


@dataclass(frozen=True)
class FaissIndexMetadata:
    """Deterministic description of one persisted FAISS semantic build."""

    format_version: int = FAISS_FORMAT_VERSION
    index_version: int = 1
    model: str = ""
    dimension: int = 0
    created_at: str = ""
    updated_at: str = ""
    document_count: int = 0
    corpus_hash: str = ""
    documents: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "index_version": self.index_version,
            "model": self.model,
            "dimension": self.dimension,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "document_count": self.document_count,
            "corpus_hash": self.corpus_hash,
            "documents": [
                {
                    "document_id": str(d.get("document_id") or ""),
                    "title": d.get("title") or "",
                    "source": d.get("source") or "",
                    "content": d.get("content") or "",
                    "content_hash": d.get("content_hash") or "",
                }
                for d in self.documents
            ],
        }

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> "FaissIndexMetadata":
        if not isinstance(data, dict):
            raise ValueError("faiss metadata is not a JSON object")
        documents = tuple(
            {
                "document_id": str(d.get("document_id") or ""),
                "title": d.get("title") or "",
                "source": d.get("source") or "",
                "content": d.get("content") or "",
                "content_hash": d.get("content_hash") or "",
            }
            for d in (data.get("documents") or ())
        )
        return cls(
            format_version=int(data.get("format_version", FAISS_FORMAT_VERSION)),
            index_version=int(data.get("index_version", 1)),
            model=str(data.get("model", "") or ""),
            dimension=int(data.get("dimension", 0) or 0),
            created_at=str(data.get("created_at", "") or ""),
            updated_at=str(data.get("updated_at", "") or ""),
            document_count=int(data.get("document_count", 0) or 0),
            corpus_hash=str(data.get("corpus_hash", "") or ""),
            documents=documents,
        )


@dataclass(frozen=True)
class FaissIndexPayload:
    """Reconstructed semantic index: vectors + ordered documents."""

    documents: tuple[ProcessedDocument, ...]
    vectors: Any  # numpy.ndarray (n, dimension), L2-normalised float32
    model: str
    dimension: int


@dataclass(frozen=True)
class FaissLoadResult:
    """Outcome of a FAISS load attempt (never raises)."""

    payload: Optional[FaissIndexPayload]
    metadata: Optional[FaissIndexMetadata]
    valid: bool
    reason: str = ""


# --------------------------------------------------------------------------- #
# low-level helpers
# --------------------------------------------------------------------------- #


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# save / load
# --------------------------------------------------------------------------- #


def save_faiss_index(
    index_dir: str | Path,
    documents: Iterable[ProcessedDocument],
    vectors: Any,
    metadata: FaissIndexMetadata,
) -> None:
    """Persist the FAISS index + metadata (atomic on a per-file basis)."""
    try:
        import faiss
    except ImportError as exc:  # pragma: no cover - environment w/o faiss
        raise RuntimeError(f"faiss is not installed: {exc}") from exc

    root = Path(index_dir)
    root.mkdir(parents=True, exist_ok=True)
    docs = [d for d in documents if d is not None]
    dim = int(metadata.dimension)
    if dim <= 0:
        raise ValueError("cannot persist a FAISS index with dimension <= 0")
    index = faiss.IndexFlatIP(dim)
    if len(docs):
        index.add(vectors)

    index_path = root / FAISS_INDEX_FILE
    tmp_index = root / (FAISS_INDEX_FILE + ".tmp")
    try:
        faiss.write_index(index, str(tmp_index))
        os.replace(tmp_index, index_path)
    finally:
        if tmp_index.exists():
            try:
                tmp_index.unlink()
            except OSError:  # pragma: no cover - best-effort cleanup
                pass

    _write_bytes_atomic(
        root / FAISS_METADATA_FILE,
        json.dumps(metadata.to_dict(), indent=2, ensure_ascii=False).encode("utf-8"),
    )


def is_faiss_present(index_dir: str | Path) -> bool:
    root = Path(index_dir)
    return (root / FAISS_INDEX_FILE).is_file() and (root / FAISS_METADATA_FILE).is_file()


def read_faiss_metadata(index_dir: str | Path) -> Optional[FaissIndexMetadata]:
    """Return persisted metadata, or ``None`` when absent/unreadable."""
    path = Path(index_dir) / FAISS_METADATA_FILE
    if not path.is_file():
        return None
    try:
        return FaissIndexMetadata.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("faiss metadata unreadable: %s", exc)
        return None


def remove_faiss_index(index_dir: str | Path) -> None:
    """Delete the persisted artifact + metadata (for tests/cleanup)."""
    root = Path(index_dir)
    for name in (FAISS_INDEX_FILE, FAISS_METADATA_FILE):
        path = root / name
        if path.exists():
            path.unlink()


def load_faiss_index(index_dir: str | Path) -> FaissLoadResult:
    """Load + validate the persistent FAISS index; never raises.

    A valid artifact yields ``FaissLoadResult(valid=True, payload=..., metadata=...)``.
    Anything missing, corrupt, unsupported or internally inconsistent yields
    ``valid=False`` with a ``reason`` string.
    """
    root = Path(index_dir)
    try:
        metadata = read_faiss_metadata(root)
        index_path = root / FAISS_INDEX_FILE
        if not index_path.is_file():
            return FaissLoadResult(None, None, False, "faiss index file missing")
        if metadata is None:
            return FaissLoadResult(None, None, False, "faiss metadata missing")
        if int(metadata.format_version) != FAISS_FORMAT_VERSION:
            return FaissLoadResult(
                None,
                None,
                False,
                f"unsupported faiss format version {metadata.format_version}",
            )
        if not metadata.model or metadata.dimension <= 0:
            return FaissLoadResult(None, None, False, "faiss metadata missing model/dimension")
        try:
            import faiss
        except ImportError as exc:  # pragma: no cover - env without faiss
            return FaissLoadResult(None, None, False, f"faiss is not installed: {exc}")
        try:
            index = faiss.read_index(str(index_path))
        except Exception as exc:  # noqa: BLE001 - corrupt artifact
            return FaissLoadResult(None, None, False, f"corrupt faiss index: {exc}")
        if index.d != metadata.dimension:
            return FaissLoadResult(
                None,
                None,
                False,
                f"faiss dimension {index.d} != metadata dimension {metadata.dimension}",
            )
        if int(index.ntotal) != metadata.document_count:
            return FaissLoadResult(
                None,
                None,
                False,
                f"faiss count {index.ntotal} != metadata count {metadata.document_count}",
            )
    except Exception as exc:  # noqa: BLE001 - never raise while loading
        return FaissLoadResult(None, None, False, f"faiss load failed: {exc}")

    try:
        documents = tuple(
            document_from_dict(
                {
                    **d,
                    "tokens": (),
                    "snippet_tokens": (),
                }
            )
            for d in metadata.documents
        )
    except (TypeError, ValueError, KeyError) as exc:
        return FaissLoadResult(None, None, False, f"invalid faiss document data: {exc}")

    if len(documents) != metadata.document_count:
        return FaissLoadResult(
            None,
            None,
            False,
            "faiss metadata document count mismatch",
        )
    if compute_document_signature(documents) != metadata.corpus_hash:
        return FaissLoadResult(
            None,
            None,
            False,
            "faiss metadata content signature mismatch",
        )

    try:
        vectors = index.reconstruct_n(0, int(index.ntotal))
    except Exception as exc:  # noqa: BLE001 - runtime extraction failure
        return FaissLoadResult(None, None, False, f"faiss vector extraction failed: {exc}")

    return FaissLoadResult(
        payload=FaissIndexPayload(
            documents=documents,
            vectors=vectors,
            model=metadata.model,
            dimension=metadata.dimension,
        ),
        metadata=metadata,
        valid=True,
    )


def build_faiss_metadata(
    *,
    documents: Iterable[ProcessedDocument],
    vectors: Any,
    model: str,
    index_version: int = 1,
    previous: Optional[FaissIndexMetadata] = None,
) -> FaissIndexMetadata:
    """Assemble metadata for a fresh FAISS build (versioned timestamps)."""
    docs = [d for d in documents if d is not None]
    now = now_iso()
    dim = int(getattr(vectors, "shape", (0, 0))[1] or 0)
    return FaissIndexMetadata(
        format_version=FAISS_FORMAT_VERSION,
        index_version=(previous.index_version + 1 if previous else index_version),
        model=model,
        dimension=dim,
        created_at=(previous.created_at or now) if previous else now,
        updated_at=now,
        document_count=len(docs),
        corpus_hash=compute_document_signature(docs),
        documents=tuple(
            {
                "document_id": d.document_id,
                "title": d.title or "",
                "source": d.source or "",
                "content": d.content or "",
                "content_hash": d.content_hash or "",
            }
            for d in docs
        ),
    )


__all__ = [
    "FAISS_FORMAT_VERSION",
    "FAISS_INDEX_FILE",
    "FAISS_METADATA_FILE",
    "FaissIndexMetadata",
    "FaissIndexPayload",
    "FaissLoadResult",
    "build_faiss_metadata",
    "save_faiss_index",
    "load_faiss_index",
    "read_faiss_metadata",
    "is_faiss_present",
    "remove_faiss_index",
]