"""Local SentenceTransformers embedding generator (SEEK Phase 6).

:class:`EmbeddingGenerator` wraps ``sentence-transformers`` (default model
``all-MiniLM-L6-v2``) so semantic retrieval runs on **local, free** models with
no external/cloud embedding service.

Design rules
------------
* **Lazy loading** — nothing is imported or materialised at module import time.
  The first :meth:`EmbeddingGenerator.encode_texts` call (or an explicit
  :meth:`EmbeddingGenerator.ensure_loaded`) pays the one-time cost of loading
  the model into memory. Subsequent calls reuse the same cached model.
* **Thread-safe** — a single generator instance is shared process-wide; encoding
  is serialised under a re-entrant lock so two threads never feed the same
  torch model concurrently.
* **Never a hard dependency** — with ``sentence-transformers``/``torch`` absent
  the generator still imports; :meth:`EmbeddingGenerator.is_available` reports
  ``False`` and encode attempts raise :class:`EmbeddingUnavailableError` instead
  of crashing the application. BM25 never touches this module.
* **Deterministic** — text is run through a light, pure-string normaliser
  (strip + whitespace collapse) and the model runs in evaluation mode, so the
  same input string always produces the same vector.
* **Cosine semantics** — every returned vector is L2-normalised, so an inner
  product (``IndexFlatIP``) equals cosine similarity.
"""
from __future__ import annotations

import importlib.util
import logging
import re
import threading
from typing import Optional, Sequence

logger = logging.getLogger("seek.search.embeddings")


class EmbeddingUnavailableError(RuntimeError):
    """Raised when the embedding model cannot be imported or loaded."""


_WHITESPACE_RE = re.compile(r"\s+")


class EmbeddingGenerator:
    """Lazy, thread-safe wrapper around a local SentenceTransformers model."""

    def __init__(
        self,
        model_name: Optional[str] = None,
        batch_size: Optional[int] = None,
    ) -> None:
        from backend.config import settings

        self._model_name = model_name or settings.EMBEDDING_MODEL
        self._batch_size = int(batch_size or settings.EMBEDDING_BATCH_SIZE)
        self._lock = threading.RLock()
        self._model = None
        self._load_attempted = False
        self._load_error: Optional[BaseException] = None
        self._dimension: Optional[int] = None

    # ------------------------------------------------------------------ #
    # availability / lifecycle
    # ------------------------------------------------------------------ #

    @property
    def model_name(self) -> str:
        """Canonical model identifier (e.g. ``sentence-transformers/all-MiniLM-L6-v2``)."""
        return self._model_name

    @property
    def batch_size(self) -> int:
        return self._batch_size

    def is_importable(self) -> bool:
        """True when ``sentence_transformers`` is installed (never loads it)."""
        try:
            return importlib.util.find_spec("sentence_transformers") is not None
        except (ImportError, ValueError):
            return False

    def is_available(self) -> bool:
        """True if the model is loaded, or loadable (import present).

        This is intentionally cheap: it never downloads or materialises the
        model. The real load (and its failure reason) happens on the first
        :meth:`ensure_loaded`/:meth:`encode_texts` call.
        """
        with self._lock:
            if self._model is not None:
                return True
        if self._load_attempted and self._load_error is not None:
            return False
        return self.is_importable()

    def ensure_loaded(self) -> object:
        """Load the model once; reuse thereafter. Never leaves a half state.

        Raises :class:`EmbeddingUnavailableError` when the model cannot be
        loaded (missing package, failed download, corrupt cache, ...). The
        failure is remembered so we do not retry a doomed load on every request.
        """
        with self._lock:
            if self._model is not None:
                return self._model
            if self._load_attempted:
                if self._load_error is not None:
                    raise EmbeddingUnavailableError(str(self._load_error))
                return self._model
            try:
                # Imported lazily so `import backend.main` works without the
                # optional ML stack installed.
                from sentence_transformers import SentenceTransformer

                model = SentenceTransformer(self._model_name)
                model.eval()
            except EmbeddingUnavailableError:
                raise
            except Exception as exc:  # noqa: BLE001 - surface reason gracefully
                self._load_attempted = True
                self._load_error = exc
                logger.warning(
                    "Embedding model %r unavailable: %s", self._model_name, exc
                )
                raise EmbeddingUnavailableError(
                    f"could not load embedding model {self._model_name!r}: {exc}"
                ) from exc
            self._load_attempted = True
            self._load_error = None
            self._model = model
            return model

    def reset(self) -> None:
        """Drop the loaded model (used by tests / teardown)."""
        with self._lock:
            self._model = None
            self._load_attempted = False
            self._load_error = None
            self._dimension = None

    def close(self) -> None:
        self.reset()

    # ------------------------------------------------------------------ #
    # embedding
    # ------------------------------------------------------------------ #

    @property
    def model_loaded(self) -> bool:
        """True once the model has been materialised in memory."""
        with self._lock:
            return self._model is not None

    @property
    def loaded_dimension(self) -> Optional[int]:
        """Embedding width without triggering a model load (None if unknown)."""
        with self._lock:
            return self._dimension

    @property
    def dimension(self) -> int:
        """Embedding vector width once the model is loaded (None otherwise)."""
        with self._lock:
            if self._dimension is not None:
                return self._dimension
            model = self.ensure_loaded()
            try:
                dim = model.get_sentence_embedding_dimension()
            except Exception:  # noqa: BLE001 - fall back to a probe vector
                dim = None
            if not dim:
                dim = int(self.encode_texts(["probe"]).shape[1])
            self._dimension = int(dim)
            return self._dimension

    @staticmethod
    def preprocess(text: str) -> str:
        """Deterministic light text normalisation for embedding input.

        Strips leading/trailing whitespace and collapses any internal run of
        whitespace to a single space. Deliberately *not* the aggressive BM25
        normaliser (no case-folding/stop-word removal) so the transformer sees
        natural language; case-folding would only weakly affect this model.
        """
        return _WHITESPACE_RE.sub(" ", (text or "")).strip()

    def encode_texts(self, texts: Sequence[str]) -> "object":
        """Embed *texts* into an L2-normalised ``float32`` array ``(n, dim)``.

        The returned numpy array is normalised so cosine similarity reduces to
        an inner product. Raises :class:`EmbeddingUnavailableError` when the
        model cannot be loaded.
        """
        model = self.ensure_loaded()
        prepared = [self.preprocess(t) for t in texts or ()]
        if not prepared:
            return _empty_array()
        try:
            import numpy as np
        except ImportError as exc:
            raise EmbeddingUnavailableError(
                f"numpy is required for embeddings: {exc}"
            ) from exc
        try:
            # Serialised under the generator lock so one torch model is never
            # fed by two threads concurrently.
            with self._lock:
                vectors = model.encode(
                    prepared,
                    batch_size=self._batch_size,
                    convert_to_numpy=True,
                )
        except Exception as exc:  # noqa: BLE001 - encode-time failure
            raise EmbeddingUnavailableError(
                f"embedding inference failed: {exc}"
            ) from exc
        arr = np.asarray(vectors, dtype="float32")
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        arr = arr / norms
        return arr


def _empty_array() -> "object":
    """Return a ``(0, 0)`` float32 array when there is nothing to embed."""
    try:
        import numpy as np

        return np.zeros((0, 0), dtype="float32")
    except ImportError:  # pragma: no cover - numpy is a transitive dependency
        return []


# --------------------------------------------------------------------------- #
# process-wide singleton (default wiring)
# --------------------------------------------------------------------------- #

_embedder: Optional[EmbeddingGenerator] = None
_embedder_lock = threading.Lock()


def get_embedding_generator() -> EmbeddingGenerator:
    """Return the process-wide :class:`EmbeddingGenerator` (lazily created)."""
    global _embedder
    with _embedder_lock:
        if _embedder is None:
            _embedder = EmbeddingGenerator()
        return _embedder


def reset_embedding_generator() -> None:
    """Drop the process-wide generator (used by tests for isolation)."""
    global _embedder
    with _embedder_lock:
        if _embedder is not None:
            _embedder.close()
        _embedder = None


__all__ = [
    "EmbeddingGenerator",
    "EmbeddingUnavailableError",
    "get_embedding_generator",
    "reset_embedding_generator",
]