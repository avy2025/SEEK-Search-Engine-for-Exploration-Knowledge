"""Persistent BM25 artifact storage (Phase 5B).

``backend.search.index_store`` owns every byte written under the configured
``indexes/bm25`` directory:

* ``index.pkl`` — a versioned pickle containing the BM25 construction
  parameters plus the ordered, tokenised document set the model was built
  from. The model itself is **reconstructed** from this plain data on load, so
  artifacts stay readable across ``rank_bm25``/Python version changes.
* ``metadata.json`` — a deterministic companion describing the build:
  format/index versions, build timestamps, document count, per-document
  ``document_id -> content_hash`` mapping and a corpus-level content
  signature used for change detection.

Design notes
------------
* The artifact is a **derived** representation of the PostgreSQL ``documents``
  table — it is never a source of truth; a missing/corrupt artifact is always
  rebuildable from PostgreSQL.
* Writes go to a same-directory ``*.tmp`` file then :func:`os.replace`, so a
  failed build can never truncate or corrupt a previously-valid index.
* Loading never raises: a missing, corrupt or unsupported artifact is reported
  as ``IndexLoadResult(valid=False, reason=...)``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import pickle
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from backend.processing.models import ProcessedDocument

logger = logging.getLogger("seek.search.index_store")

INDEX_FORMAT_VERSION = 1
ARTIFACT_FILE = "index.pkl"
METADATA_FILE = "metadata.json"


def now_iso() -> str:
    """UTC ISO-8601 timestamp used for index metadata."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class IndexMetadata:
    """Deterministic description of one persisted index build."""

    format_version: int = INDEX_FORMAT_VERSION
    index_version: int = 1
    created_at: str = ""
    updated_at: str = ""
    document_count: int = 0
    max_document_id: int = 0
    corpus_hash: str = ""
    documents: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "index_version": self.index_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "document_count": self.document_count,
            "max_document_id": self.max_document_id,
            "corpus_hash": self.corpus_hash,
            "documents": list(self.documents),
        }

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> "IndexMetadata":
        if not isinstance(data, dict):
            raise ValueError("index metadata is not a JSON object")
        return cls(
            format_version=int(data.get("format_version", INDEX_FORMAT_VERSION)),
            index_version=int(data.get("index_version", 1)),
            created_at=str(data.get("created_at", "") or ""),
            updated_at=str(data.get("updated_at", "") or ""),
            document_count=int(data.get("document_count", 0) or 0),
            max_document_id=int(data.get("max_document_id", 0) or 0),
            corpus_hash=str(data.get("corpus_hash", "") or ""),
            documents=tuple(dict(d) for d in (data.get("documents") or ())),
        )


@dataclass(frozen=True)
class IndexPayload:
    """Minimum data needed to reconstruct a live :class:`SearchEngine`."""

    documents: tuple[ProcessedDocument, ...]
    k1: float
    b: float
    epsilon: float
    default_limit: int
    max_limit: int


@dataclass(frozen=True)
class IndexLoadResult:
    """Outcome of a persistent-index load attempt (never raises)."""

    payload: Optional[IndexPayload]
    metadata: Optional[IndexMetadata]
    valid: bool
    reason: str = ""


# --------------------------------------------------------------------------- #
# low-level helpers
# --------------------------------------------------------------------------- #


def _atomic_write(path: Path, data: bytes) -> None:
    """Write *data* to *path* via a sibling temp file + :func:`os.replace`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def document_to_dict(doc: ProcessedDocument) -> dict[str, Any]:
    return {
        "document_id": str(doc.document_id or ""),
        "title": doc.title or "",
        "content": doc.content or "",
        "source": doc.source or "",
        "tokens": list(doc.tokens or ()),
        "snippet_tokens": list(doc.snippet_tokens or ()),
        "content_hash": doc.content_hash or "",
    }


def document_from_dict(data: dict[str, Any]) -> ProcessedDocument:
    return ProcessedDocument(
        document_id=str(data.get("document_id") or ""),
        title=data.get("title") or "",
        content=data.get("content") or "",
        source=data.get("source") or "",
        tokens=tuple(data.get("tokens") or ()),
        snippet_tokens=tuple(data.get("snippet_tokens") or ()),
        content_hash=data.get("content_hash") or "",
    )


def compute_document_signature(documents: Iterable[ProcessedDocument]) -> str:
    """Deterministic SHA-256 over sorted ``document_id|content_hash`` pairs.

    Two identical PostgreSQL document sets always produce the same signature;
    adding, removing or changing any document changes it.
    """
    pairs = sorted(
        (str(d.document_id or ""), d.content_hash or "")
        for d in documents
        if d is not None
    )
    digest = hashlib.sha256()
    for did, content_hash in pairs:
        digest.update(did.encode("utf-8"))
        digest.update(b"\n")
        digest.update(content_hash.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def max_document_id(documents: Iterable[ProcessedDocument]) -> int:
    """Greatest numeric document id in *documents* (0 when none convertible)."""
    best = 0
    for doc in documents:
        if doc is None:
            continue
        try:
            best = max(best, int(doc.document_id))
        except (TypeError, ValueError):
            continue
    return best


# --------------------------------------------------------------------------- #
# save / load
# --------------------------------------------------------------------------- #


def save_index(
    index_dir: str | Path,
    documents: Iterable[ProcessedDocument],
    metadata: IndexMetadata,
    *,
    k1: float,
    b: float,
    epsilon: float,
    default_limit: int,
    max_limit: int,
) -> None:
    """Persist the BM25 artifact + metadata (atomic on a per-file basis)."""
    root = Path(index_dir)
    docs = [d for d in documents if d is not None]
    payload: dict[str, Any] = {
        "format_version": INDEX_FORMAT_VERSION,
        "kind": "bm25",
        "k1": float(k1),
        "b": float(b),
        "epsilon": float(epsilon),
        "default_limit": int(default_limit),
        "max_limit": int(max_limit),
        "documents": [document_to_dict(d) for d in docs],
    }
    blob = pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)
    _atomic_write(root / ARTIFACT_FILE, blob)
    _atomic_write(
        root / METADATA_FILE,
        json.dumps(metadata.to_dict(), indent=2, ensure_ascii=False).encode("utf-8"),
    )


def is_index_present(index_dir: str | Path) -> bool:
    root = Path(index_dir)
    return (root / ARTIFACT_FILE).is_file() and (root / METADATA_FILE).is_file()


def read_metadata(index_dir: str | Path) -> Optional[IndexMetadata]:
    """Return persisted metadata, or ``None`` when absent/unreadable."""
    path = Path(index_dir) / METADATA_FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return IndexMetadata.from_dict(data)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("index metadata unreadable: %s", exc)
        return None


def remove_index(index_dir: str | Path) -> None:
    """Delete the persisted artifact and metadata (for tests/cleanup)."""
    root = Path(index_dir)
    for name in (ARTIFACT_FILE, METADATA_FILE):
        path = root / name
        if path.exists():
            path.unlink()


def load_index(index_dir: str | Path) -> IndexLoadResult:
    """Load + validate the persistent index; never raises.

    A valid artifact yields ``IndexLoadResult(valid=True, payload=..., metadata=...)``.
    Anything missing, corrupt, unsupported or internally inconsistent yields
    ``valid=False`` with a ``reason`` string.
    """
    root = Path(index_dir)
    try:
        metadata = read_metadata(root)
        artifact_path = root / ARTIFACT_FILE
        if artifact_path.is_file():
            with open(artifact_path, "rb") as fh:
                payload = pickle.load(fh)
        else:
            return IndexLoadResult(None, None, False, "index artifact missing")
    except (OSError, pickle.PickleError, EOFError, TypeError, ValueError) as exc:
        return IndexLoadResult(None, None, False, f"corrupt index artifact: {exc}")

    if not isinstance(payload, dict) or payload.get("kind") != "bm25":
        return IndexLoadResult(None, None, False, "unsupported index artifact kind")
    if int(payload.get("format_version", 0)) != INDEX_FORMAT_VERSION:
        return IndexLoadResult(
            None, None, False,
            f"unsupported index format version {payload.get('format_version')}",
        )
    if metadata is None:
        return IndexLoadResult(None, None, False, "index metadata missing")

    try:
        documents = tuple(
            document_from_dict(d)
            for d in payload.get("documents") or ()
        )
    except (TypeError, ValueError, KeyError) as exc:
        return IndexLoadResult(None, None, False, f"invalid document data: {exc}")

    if len(documents) != metadata.document_count:
        return IndexLoadResult(
            None, None, False,
            "index payload/metadata document count mismatch",
        )
    if compute_document_signature(documents) != metadata.corpus_hash:
        return IndexLoadResult(
            None, None, False,
            "index payload/metadata content signature mismatch",
        )

    return IndexLoadResult(
        payload=IndexPayload(
            documents=documents,
            k1=float(payload.get("k1", 1.5)),
            b=float(payload.get("b", 0.75)),
            epsilon=float(payload.get("epsilon", 0.25)),
            default_limit=int(payload.get("default_limit", 10)),
            max_limit=int(payload.get("max_limit", 50)),
        ),
        metadata=metadata,
        valid=True,
    )


__all__ = [
    "INDEX_FORMAT_VERSION",
    "ARTIFACT_FILE",
    "METADATA_FILE",
    "IndexMetadata",
    "IndexPayload",
    "IndexLoadResult",
    "now_iso",
    "compute_document_signature",
    "max_document_id",
    "save_index",
    "load_index",
    "read_metadata",
    "is_index_present",
    "remove_index",
]