from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProcessedDocument:
    """A corpus document that has passed through the SEEK processing pipeline.

    ``tokens`` is the stop-word-stripped, lowercased token sequence used by BM25;
    ``snippet_tokens`` preserves the original wording (including stop-words) for the
    human-readable keyword snippet builder.
    """

    document_id: str
    title: str
    content: str
    source: str
    tokens: tuple[str, ...] = field(default_factory=tuple)
    snippet_tokens: tuple[str, ...] = field(default_factory=tuple)
    content_hash: str = ""
