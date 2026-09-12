"""SEEK document-processing stage (Phase 2).

Turns a raw local markdown corpus into :class:`~backend.processing.models.ProcessedDocument`
value objects ready for BM25 indexing: a deterministic, stop-word-stripped token
stream per document plus the raw content needed for keyword snippet extraction.
"""
from __future__ import annotations

from backend.processing.loader import load_corpus
from backend.processing.models import ProcessedDocument
from backend.processing.snippets import build_snippet
from backend.processing.tokenizer import STOPWORDS, normalize, snippet_tokens, tokenize

__all__ = [
    "ProcessedDocument",
    "load_corpus",
    "build_snippet",
    "tokenize",
    "normalize",
    "snippet_tokens",
    "STOPWORDS",
]
