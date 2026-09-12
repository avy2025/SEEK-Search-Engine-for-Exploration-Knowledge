"""Wire models for the SEEK Phase 2 search API + engine.

Dataclasses (not Pydantic) at the engine boundary so ``backend.search`` stays
dependency-light; the FastAPI layer maps them onto the Pydantic response at the
edge. All of these are frozen and hashable so results can be cached/tested
cheaply.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SearchQuery:
    """A user-entered, already-normalised search query.

    Carried through ``backend.search.query`` (token stream + rewritten form)
    and used to drive the BM25 scorer and API response echo.
    """

    text: str
    tokens: tuple[str, ...] = field(default_factory=tuple)
    rewritten: str = ""


@dataclass(frozen=True)
class SearchResult:
    """One ranked, snippet-bearing hit the engine hands to the API layer."""

    rank: int
    document_id: str
    title: str
    source: str
    snippet: str
    score: float = 0.0
    matched_terms: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SearchResponse:
    """Phase 2 envelope: ranked hits + query echo + timing metadata."""

    query: str
    total: int
    limit: int
    hits: tuple[SearchResult, ...] = field(default_factory=tuple)
    took_ms: float = 0.0
    message: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchErrorResponse:
    """Structured error envelope used for search API failures."""

    detail: str
    code: str = "search_error"
    query: str = ""
