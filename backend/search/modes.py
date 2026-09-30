"""Phase 9 specialized search modes (Web / AI / Research / Code Docs).

This module is the **single definition point** for the four SEEK search modes.
It owns:

* the controlled :class:`SearchMode` enum + validation layer
  (:func:`normalize_mode_param`, :class:`InvalidSearchModeError`),
* the per-mode :class:`ModeSpec` (retrieval strategy, ranking preferences,
  result limits, candidate width, RAG toggle, context/snippet behaviour,
  source diversification and documentation/code-source handling),
* deterministic, corpus-only post-processing helpers used by the orchestration
  layer in :mod:`backend.api.mode_orchestrator`
  (source diversification, documentation-source prioritisation, richer snippets,
  technical-term query handling and code-snippet extraction).

Design rules (deliberate):

* **No duplicated retrieval logic.** Nothing here scores, indexes or embeds;
  BM25 (:mod:`backend.search.engine`), semantic search
  (:mod:`backend.search.semantic`), hybrid ranking
  (:mod:`backend.search.hybrid`) and RAG (:mod:`backend.ai.rag`) stay the only
  implementations. This module only *chooses and arranges* them.
* **No new capabilities.** Code Docs mode does not crawl documentation sites and
  Research mode does not invent external research; both work strictly on the
  documents SEEK already indexed.
* **No fabrication.** Snippets and code excerpts are re-rendered from the indexed
  document content that the existing engines already hold.
* **Deterministic.** Same index + same query + same settings => same response.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any
from urllib.parse import urlsplit

from backend.config import settings
from backend.processing.snippets import make_snippet
from backend.search.query import QueryProcessor

# --------------------------------------------------------------------------- #
# mode identity + validation
# --------------------------------------------------------------------------- #


class SearchMode(str, Enum):
    """Controlled enum of the Phase 9 specialized search modes."""

    WEB = "web"
    AI = "ai"
    RESEARCH = "research"
    CODE = "code"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


#: Pre-Phase-9 retrieval modes. They keep their original request/response
#: contracts untouched and are dispatched by the legacy handlers.
LEGACY_SEARCH_MODES: frozenset[str] = frozenset({"lexical", "bm25", "semantic", "hybrid"})

#: Retrieval strategies a mode may orchestrate.
RETRIEVAL_STRATEGIES: tuple[str, ...] = ("hybrid", "lexical", "semantic")


class InvalidSearchModeError(ValueError):
    """Raised when a caller supplies a mode string outside the controlled enum."""

    def __init__(self, value: Any, allowed: Sequence[str]) -> None:
        self.value = value
        self.allowed: tuple[str, ...] = tuple(allowed)
        super().__init__(
            f"invalid search mode {value!r}; supported modes: {', '.join(self.allowed)}"
        )


def specialized_modes() -> tuple[SearchMode, ...]:
    """Ordered tuple of the Phase 9 modes (web, ai, research, code)."""
    return (SearchMode.WEB, SearchMode.AI, SearchMode.RESEARCH, SearchMode.CODE)


def supported_mode_values() -> tuple[str, ...]:
    """All accepted ``mode`` query values (legacy first, then specialized)."""
    legacy = ("lexical", "bm25", "semantic", "hybrid")
    return legacy + tuple(mode.value for mode in specialized_modes())


def is_specialized_mode(value: Any) -> bool:
    """True when *value* is one of the Phase 9 mode identifiers."""
    if isinstance(value, SearchMode):
        return True
    if not isinstance(value, str):
        return False
    return value.strip().lower() in {mode.value for mode in specialized_modes()}


def normalize_mode_param(raw: Any) -> str:
    """Validate + normalise the ``mode`` query parameter.

    Accepts the legacy retrieval modes (``lexical``, ``bm25``, ``semantic``,
    ``hybrid``) and the Phase 9 modes (``web``, ``ai``, ``research``, ``code``)
    case-insensitively. Raises :class:`InvalidSearchModeError` for anything
    else so the API can answer with a clean HTTP 422.
    """
    normalized = str(raw or "").strip().lower()
    if normalized in LEGACY_SEARCH_MODES:
        return "lexical" if normalized == "bm25" else normalized
    if normalized in {mode.value for mode in specialized_modes()}:
        return normalized
    raise InvalidSearchModeError(raw, supported_mode_values())


def parse_search_mode(raw: Any) -> SearchMode:
    """Parse *raw* into a :class:`SearchMode` (legacy values are rejected)."""
    normalized = normalize_mode_param(raw)
    if normalized in LEGACY_SEARCH_MODES:
        raise InvalidSearchModeError(raw, supported_mode_values())
    return SearchMode(normalized)


def try_parse_search_mode(raw: Any) -> SearchMode | None:
    """Non-raising variant of :func:`parse_search_mode`."""
    try:
        return parse_search_mode(raw)
    except InvalidSearchModeError:
        return None


# --------------------------------------------------------------------------- #
# mode specifications
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ModeSpec:
    """Declarative description of one specialized search mode."""

    mode: SearchMode
    label: str
    description: str
    retrieval: str
    default_limit: int
    max_limit: int
    candidate_multiplier: int
    rag_enabled: bool
    bm25_weight: float | None
    semantic_weight: float | None
    diversify_sources: bool
    per_source_cap: int
    snippet_words: int | None
    code_mode: bool
    doc_source_priority: bool
    technical_term_expansion: bool

    def candidate_limit(self, limit: int) -> int:
        """Widened retrieval width used *before* mode post-processing."""
        widened = max(1, int(limit)) * max(1, int(self.candidate_multiplier))
        return max(1, min(widened, int(settings.MODE_MAX_CANDIDATES)))

    def capabilities(self) -> dict[str, bool]:
        return {
            "ai_answer": bool(self.rag_enabled),
            "diversified_sources": bool(self.diversify_sources),
            "code_snippets": bool(self.code_mode),
            "documentation_priority": bool(self.doc_source_priority),
            "richer_snippets": bool(self.snippet_words),
            "technical_query_handling": bool(self.technical_term_expansion),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.mode.value,
            "label": self.label,
            "description": self.description,
            "retrieval": self.retrieval,
            "default_limit": self.default_limit,
            "max_limit": self.max_limit,
            "candidate_multiplier": self.candidate_multiplier,
            "ai_answer": bool(self.rag_enabled),
            "weights": {"bm25": self.bm25_weight, "semantic": self.semantic_weight},
            "source_diversity_cap": self.per_source_cap,
            "snippet_words": self.snippet_words,
            "capabilities": self.capabilities(),
        }


# Static (settings-independent) part of each mode definition. Settings-derived
# values are resolved by :func:`resolve_mode_spec` so tests / deployments can
# patch ``backend.config.settings`` without reimporting this module.
_STATIC_SPECS: dict[SearchMode, dict[str, Any]] = {
    SearchMode.WEB: {
        "label": "Web Search",
        "description": (
            "Broad SEEK search: hybrid retrieval over the whole index, ranked "
            "results with snippets and source metadata, no generated answer."
        ),
        "retrieval": "hybrid",
        "rag_enabled": False,
        "diversify_sources": False,
        "code_mode": False,
    },
    SearchMode.AI: {
        "label": "AI Answers",
        "description": (
            "Answer the question with the Phase 8 RAG pipeline using SEEK's "
            "retrieved sources, returning citations plus the supporting hits."
        ),
        "retrieval": "hybrid",
        "rag_enabled": True,
        "diversify_sources": False,
        "code_mode": False,
    },
    SearchMode.RESEARCH: {
        "label": "Research",
        "description": (
            "Deeper evidence gathering: wider candidate retrieval, source "
            "diversification, richer snippets and optional grounded synthesis."
        ),
        "retrieval": "hybrid",
        "rag_enabled": True,
        "diversify_sources": True,
        "code_mode": False,
    },
    SearchMode.CODE: {
        "label": "Code Docs",
        "description": (
            "Technical search over the already indexed corpus: lexical-leaning "
            "ranking, technical query handling, documentation-source priority "
            "and code snippets extracted from indexed documents."
        ),
        "retrieval": "hybrid",
        "rag_enabled": False,
        "diversify_sources": False,
        "code_mode": True,
    },
}


def resolve_mode_spec(mode: Any) -> ModeSpec:
    """Build the effective :class:`ModeSpec` for *mode* from live settings."""
    parsed = parse_search_mode(mode)
    static = _STATIC_SPECS[parsed]
    max_limit = max(1, int(settings.MODE_MAX_LIMIT))
    code_mode = bool(static["code_mode"])
    research_mode = parsed is SearchMode.RESEARCH

    default_limit = int(
        settings.MODE_WEB_LIMIT
        if parsed is SearchMode.WEB
        else settings.MODE_AI_LIMIT
        if parsed is SearchMode.AI
        else settings.MODE_RESEARCH_LIMIT
        if research_mode
        else settings.MODE_CODE_LIMIT
    )

    if research_mode:
        default_limit = int(settings.MODE_RESEARCH_LIMIT)
    elif code_mode:
        default_limit = int(settings.MODE_CODE_LIMIT)

    candidate_multiplier = 1
    if research_mode:
        candidate_multiplier = int(settings.RESEARCH_CANDIDATE_MULTIPLIER)
    elif code_mode:
        candidate_multiplier = int(settings.CODE_CANDIDATE_MULTIPLIER)

    rag_enabled = bool(static["rag_enabled"])
    if research_mode:
        rag_enabled = rag_enabled and bool(settings.MODE_RESEARCH_RAG_ENABLED)
    if parsed is SearchMode.AI:
        rag_enabled = rag_enabled and bool(settings.MODE_AI_ENABLED)

    snippet_words: int | None = None
    if research_mode:
        snippet_words = int(settings.RESEARCH_SNIPPET_WORDS)
    elif code_mode:
        snippet_words = int(settings.CODE_SNIPPET_WORDS)

    bm25_weight = float(settings.CODE_BM25_WEIGHT) if code_mode else None
    semantic_weight = float(settings.CODE_SEMANTIC_WEIGHT) if code_mode else None

    return ModeSpec(
        mode=parsed,
        label=str(static["label"]),
        description=str(static["description"]),
        retrieval=str(static["retrieval"]),
        default_limit=max(1, min(default_limit, max_limit)),
        max_limit=max_limit,
        candidate_multiplier=max(1, candidate_multiplier),
        rag_enabled=rag_enabled,
        bm25_weight=bm25_weight,
        semantic_weight=semantic_weight,
        diversify_sources=bool(static["diversify_sources"]),
        per_source_cap=int(settings.RESEARCH_SOURCE_DIVERSITY_CAP)
        if research_mode
        else 0,
        snippet_words=snippet_words,
        code_mode=code_mode,
        doc_source_priority=bool(settings.CODE_DOC_SOURCE_PRIORITY) if code_mode else False,
        technical_term_expansion=bool(settings.CODE_TECHNICAL_TERM_EXPANSION)
        if code_mode
        else False,
    )


def resolve_limit(spec: ModeSpec, requested: int | None) -> int:
    """Resolve the effective result limit (caller value wins, then mode default)."""
    if requested is None:
        limit = spec.default_limit
    else:
        limit = int(requested)
    return max(1, min(limit, spec.max_limit))


def mode_catalog() -> dict[str, Any]:
    """Machine-readable catalog of the specialized modes (served by the API)."""
    return {
        "default_mode": str(settings.MODE_DEFAULT).strip().lower(),
        "modes": [resolve_mode_spec(mode).to_dict() for mode in specialized_modes()],
        "legacy_modes": sorted(LEGACY_SEARCH_MODES),
    }


# --------------------------------------------------------------------------- #
# source helpers
# --------------------------------------------------------------------------- #

_DOC_SUFFIXES: tuple[str, ...] = (
    ".md",
    ".mdx",
    ".rst",
    ".txt",
    ".adoc",
    ".py",
    ".js",
    ".mjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cs",
    ".rb",
    ".php",
    ".sh",
    ".sql",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".json",
    ".html",
)
_DOC_NAME_HINTS: tuple[str, ...] = (
    "readme",
    "docs",
    "doc/",
    "documentation",
    "reference",
    "guide",
    "manual",
    "handbook",
    "tutorial",
    "howto",
    "how-to",
    "cheatsheet",
    "faq",
    "changelog",
    "example",
    "cookbook",
    "api/",
    "/api",
    "wiki",
)
_DOC_PATH_HINTS: tuple[str, ...] = (
    "/docs/",
    "/doc/",
    "/documentation/",
    "/reference/",
    "/guide/",
    "/guides/",
    "/dev/",
    "/developer/",
    "/manual/",
    "/wiki/",
    "/tutorial/",
    "/learn/",
)
_DOC_TITLE_HINTS: tuple[str, ...] = (
    "documentation",
    "reference",
    "guide",
    "tutorial",
    "readme",
    "manual",
    "api reference",
    "changelog",
    "cookbook",
    "cheatsheet",
)


def source_host(source: str | None) -> str:
    """Return the host of an ``http(s)`` source, else ``""``.

    Corpus documents carry file paths rather than URLs; they deliberately report
    no host so per-host diversity caps never suppress local corpus results.
    """
    raw = (source or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    if parts.scheme in {"http", "https"} and parts.netloc:
        return parts.netloc.lower()
    return ""


def is_documentation_source(source: str | None, title: str | None = None) -> bool:
    """Heuristic: does this indexed document look like code/documentation?"""
    src = (source or "").strip().lower()
    ttl = (title or "").strip().lower()
    if not src and not ttl:
        return False
    if any(hint in src for hint in _DOC_PATH_HINTS):
        return True
    leaf = src.rsplit("/", 1)[-1]
    if any(hint in leaf for hint in _DOC_NAME_HINTS):
        return True
    if any(src.endswith(suffix) for suffix in _DOC_SUFFIXES):
        return True
    if any(hint in ttl for hint in _DOC_TITLE_HINTS):
        return True
    return False


def build_source_entries(
    hits: Sequence[Mapping[str, Any]],
    citations: Sequence[Any] | None = None,
) -> list[dict[str, Any]]:
    """Build the ``sources`` list for a specialized-mode response.

    Uses RAG citations when available (they carry ``citation_id``); otherwise
    derives the supporting sources directly from the retrieved hits.
    """
    entries: list[dict[str, Any]] = []
    if citations:
        for citation in citations:
            data = getattr(citation, "model_dump", None)
            payload = data() if callable(data) else dict(citation)  # type: ignore[arg-type]
            entries.append(
                {
                    "document_id": str(payload.get("document_id", "")),
                    "title": str(payload.get("title", "")),
                    "source": str(payload.get("source", "")),
                    "domain": source_host(payload.get("source")),
                    "rank": int(payload.get("rank", 0) or 0),
                    "score": round(float(payload.get("score", 0.0) or 0.0), 4),
                    "citation_id": payload.get("citation_id"),
                }
            )
        return entries

    for hit in hits:
        src = str(hit.get("source", ""))
        entries.append(
            {
                "document_id": str(hit.get("document_id", "")),
                "title": str(hit.get("title", "")),
                "source": src,
                "domain": source_host(src),
                "rank": int(hit.get("rank", 0) or 0),
                "score": round(float(hit.get("score", 0.0) or 0.0), 4),
                "citation_id": None,
            }
        )
    return entries


# --------------------------------------------------------------------------- #
# hit post-processing (diversification, documentation priority, snippets)
# --------------------------------------------------------------------------- #


def drop_unmatched_hits(
    hits: Sequence[Mapping[str, Any]],
    *,
    score_floor: float = 0.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Keep only hits that actually matched the query.

    The BM25 engine (and the hybrid merge) always return up to ``limit``
    documents, scoring non-matching documents ``0.0``. Reporting those as
    results would invent relevance the ranking never found, so the specialized
    modes drop them. Ranks are renumbered ``1..K``.
    """
    floor = float(score_floor)
    kept = [dict(hit) for hit in hits if float(hit.get("score", 0.0) or 0.0) > floor]
    for index, hit in enumerate(kept, start=1):
        hit["rank"] = index
    return kept, {
        "candidates": len(hits),
        "returned": len(kept),
        "dropped_unmatched": len(hits) - len(kept),
        "score_floor": floor,
    }


def diversify_hits(
    hits: Sequence[Mapping[str, Any]],
    *,
    per_source_cap: int,
    limit: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Deduplicate documents and cap hits per web host (Research mode).

    * a ``document_id`` is only kept once (duplicate documents removed);
    * each ``http(s)`` host contributes at most *per_source_cap* hits so one
      domain cannot fill the whole page (local corpus files are never capped);
    * ranks are renumbered ``1..K`` and the result truncated to *limit*.
    """
    cap = max(0, int(per_source_cap))
    kept: list[dict[str, Any]] = []
    seen_docs: set[str] = set()
    per_host: dict[str, int] = {}
    duplicates = 0
    host_capped = 0

    for hit in hits:
        document_id = str(hit.get("document_id", ""))
        if document_id and document_id in seen_docs:
            duplicates += 1
            continue
        host = source_host(hit.get("source"))
        if host and cap > 0 and per_host.get(host, 0) >= cap:
            host_capped += 1
            continue
        if host and cap > 0:
            per_host[host] = per_host.get(host, 0) + 1
        if document_id:
            seen_docs.add(document_id)
        kept.append(dict(hit))

    if limit is not None:
        kept = kept[: max(0, int(limit))]

    for index, hit in enumerate(kept, start=1):
        hit["rank"] = index

    stats = {
        "documents_considered": len(hits),
        "documents_returned": len(kept),
        "duplicates_removed": duplicates,
        "host_capped": host_capped,
        "per_source_cap": cap,
        "distinct_sources": len(
            {
                source_host(h.get("source")) or f"doc:{h.get('document_id')}"
                for h in kept
            }
        ),
    }
    return kept, stats


def prioritize_documentation_hits(
    hits: Sequence[Mapping[str, Any]],
    *,
    enabled: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Promote code/documentation-looking sources ahead of other hits.

    This is a *preference*, not a filter: documentation-like hits are moved to
    the front while every other hit is preserved (with stable relative order) so
    nothing is silently hidden. Ranks are renumbered ``1..K``.
    """
    ordered = [dict(hit) for hit in hits]
    docs: list[dict[str, Any]] = []
    others: list[dict[str, Any]] = []
    for hit in ordered:
        if enabled and is_documentation_source(hit.get("source"), hit.get("title")):
            docs.append(hit)
        else:
            others.append(hit)

    result = docs + others
    for index, hit in enumerate(result, start=1):
        hit["rank"] = index
    stats = {
        "documentation_priority": bool(enabled),
        "documentation_hits": len(docs),
        "other_hits": len(others),
        "promoted": sum(1 for index, hit in enumerate(result) if index < len(docs)),
    }
    return result, stats


# --------------------------------------------------------------------------- #
# technical query handling + snippet enrichment (Code Docs / Research)
# --------------------------------------------------------------------------- #

_TECH_CHUNK_RE = re.compile(r"[A-Za-z0-9_.:/\\-]+")
_TECH_PUNCT = set("_.:/\\-()[]{}<>=+*&|^%$#@!~`'\";,")
_TECH_KEYWORDS: frozenset[str] = frozenset(
    {
        "api", "apis", "async", "await", "bool", "cdk", "cli", "cls", "const",
        "cpp", "css", "db", "def", "dict", "dns", "enum", "false", "fn", "func",
        "go", "html", "http", "https", "impl", "import", "int", "io", "java",
        "js", "json", "lambda", "let", "list", "ml", "none", "null", "orm",
        "os", "package", "py", "python", "react", "rest", "return", "rpc",
        "sdk", "sql", "str", "struct", "tcp", "toml", "ts", "tuple", "ui",
        "url", "var", "xml", "yaml", "yml",
    }
)


def _looks_technical(chunk: str) -> bool:
    if not chunk:
        return False
    if any(ch in _TECH_PUNCT for ch in chunk):
        return True
    if any(ch.isdigit() for ch in chunk):
        return True
    if chunk.lower() in _TECH_KEYWORDS:
        return True
    # camelCase / PascalCase identifiers (``SearchEngine``).
    return bool(re.search(r"[a-z0-9][A-Z]", chunk))


def _split_identifier(chunk: str) -> list[str]:
    parts = re.split(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])", chunk)
    return [p for p in (part.strip() for part in parts) if p]


def expand_technical_query(raw_query: str) -> tuple[str, list[str], list[str]]:
    """Expand technical identifiers into their spaced sub-terms.

    ``"faiss_store.SearchEngine"`` becomes ``"faiss_store.SearchEngine faiss
    store searchengine"``. This helps the sentence-embedding encoder (which sees
    the raw string) and keeps the original identifiers intact for the lexical
    path. Returns ``(expanded_query, technical_terms, added_phrases)``.
    """
    query = (raw_query or "").strip()
    if not query:
        return "", [], []

    folded = query.casefold()
    technical: list[str] = []
    added: list[str] = []
    for chunk in query.split():
        if not _looks_technical(chunk):
            continue
        parts = _split_identifier(chunk)
        if len(parts) < 2:
            continue
        if chunk not in technical:
            technical.append(chunk)
        phrase = " ".join(part.casefold() for part in parts)
        if phrase and phrase not in folded and phrase not in added:
            added.append(phrase)

    if not added:
        return query, technical, []
    return f"{query} {' '.join(added)}", technical, added


def enrich_snippets(
    hits: Sequence[Mapping[str, Any]],
    *,
    query: str,
    words: int,
    content_lookup: Callable[[str], str | None],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Re-render wider snippets from the indexed document content.

    Only documents the existing indexes already hold are used; hits whose
    document cannot be resolved keep their original snippet untouched.
    """
    if words <= 0:
        return [dict(hit) for hit in hits], {"enriched": 0, "words": 0}

    tokens = [token.token for token in QueryProcessor().process(query)]
    enriched: list[dict[str, Any]] = []
    count = 0
    for hit in hits:
        item = dict(hit)
        content = content_lookup(str(item.get("document_id", "")))
        if content:
            snippet = make_snippet(content, tokens, words=int(words))
            if snippet:
                item["snippet"] = snippet
                count += 1
        enriched.append(item)
    return enriched, {"enriched": count, "words": int(words)}


_FENCE_RE = re.compile(r"```[^\n`]*\n(.*?)```", re.DOTALL)
_CODE_LINE_RE = re.compile(
    r"^\s*(?:from|import|def|class|return|async|await|const|let|var|function|export|"
    r"public|private|protected|static|package|func|fn|struct|impl|interface|echo|"
    r"SELECT|INSERT|UPDATE|DELETE|CREATE|#include|using|namespace|require)\b",
    re.IGNORECASE,
)
_INLINE_CODE_RE = re.compile(r"`([^`\n]{2,160})`")


def extract_code_snippet(
    content: str | None,
    query_tokens: Iterable[str] = (),
    *,
    max_chars: int = 600,
) -> str:
    """Extract a code excerpt from indexed document content.

    Preference order: fenced code block most related to the query, then the
    most query-relevant code-like line block, then inline code spans. Returns
    ``""`` when the document simply has no code — nothing is invented.
    """
    text = content or ""
    if not text.strip():
        return ""
    tokens = {t for t in query_tokens if t}
    budget = max(80, int(max_chars))

    blocks = [block.strip() for block in _FENCE_RE.findall(text) if block.strip()]
    if blocks:
        def _overlap(block: str) -> tuple[int, int]:
            hits = sum(1 for t in tokens if t in block.casefold())
            return (hits, -len(block))

        best = max(blocks, key=_overlap)
        return best[:budget]

    lines = text.splitlines()
    candidates = [i for i, line in enumerate(lines) if _CODE_LINE_RE.match(line)]
    if candidates:
        def _line_score(index: int) -> tuple[int, int, int]:
            window = " ".join(lines[index : index + 3]).casefold()
            return (sum(1 for t in tokens if t in window), -index, -index)

        start = max(candidates, key=_line_score)
        excerpt = "\n".join(lines[start : start + 3]).strip()
        if excerpt:
            return excerpt[:budget]

    spans = [span.strip() for span in _INLINE_CODE_RE.findall(text) if span.strip()]
    if spans:
        ranked = sorted(spans, key=lambda s: -sum(1 for t in tokens if t in s.casefold()))
        return " ".join(ranked[:4])[:budget]
    return ""


def attach_code_snippets(
    hits: Sequence[Mapping[str, Any]],
    *,
    query: str,
    content_lookup: Callable[[str], str | None],
    max_chars: int = 600,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Add a ``code_snippet`` field to hits whose document contains code."""
    tokens = [token.token for token in QueryProcessor().process(query)]
    enriched: list[dict[str, Any]] = []
    count = 0
    for hit in hits:
        item = dict(hit)
        content = content_lookup(str(item.get("document_id", "")))
        snippet = extract_code_snippet(content, tokens, max_chars=max_chars)
        item["code_snippet"] = snippet or None
        if snippet:
            count += 1
        enriched.append(item)
    return enriched, {"hits_with_code": count}


__all__ = [
    "SearchMode",
    "ModeSpec",
    "InvalidSearchModeError",
    "LEGACY_SEARCH_MODES",
    "RETRIEVAL_STRATEGIES",
    "specialized_modes",
    "supported_mode_values",
    "is_specialized_mode",
    "normalize_mode_param",
    "parse_search_mode",
    "try_parse_search_mode",
    "resolve_mode_spec",
    "resolve_limit",
    "mode_catalog",
    "source_host",
    "is_documentation_source",
    "build_source_entries",
    "drop_unmatched_hits",
    "diversify_hits",
    "prioritize_documentation_hits",
    "expand_technical_query",
    "enrich_snippets",
    "extract_code_snippet",
    "attach_code_snippets",
]