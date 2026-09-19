"""Phase 7 Hybrid Ranking Engine (Score Normalization, Merging, Highlights & Orchestration).

Implements deterministic candidate retrieval, normalization, deduplication, reranking,
and safe term highlighting over BM25 and Semantic candidates.
"""
from __future__ import annotations

import logging
import math
import html
import re
from dataclasses import dataclass, field
from typing import Sequence, Iterable

from backend.config import settings
from backend.processing.snippets import build_snippet
from backend.processing.tokenizer import tokenize
from backend.search.models import SearchResult, SearchResponse
from backend.search.query import QueryProcessor

logger = logging.getLogger("seek.search.hybrid")


class InvalidHybridWeightsError(ValueError):
    """Raised when hybrid weights are invalid (negative or both zero)."""


@dataclass(frozen=True)
class NormalizedWeights:
    bm25: float
    semantic: float


def validate_and_normalize_weights(
    bm25_weight: float | None = None,
    semantic_weight: float | None = None,
) -> NormalizedWeights:
    """Validate and normalize weights so w_bm25 + w_semantic == 1.0.

    Raises InvalidHybridWeightsError if any weight is negative or if both are zero.
    """
    w_bm25 = float(settings.HYBRID_BM25_WEIGHT if bm25_weight is None else bm25_weight)
    w_sem = float(settings.HYBRID_SEMANTIC_WEIGHT if semantic_weight is None else semantic_weight)

    if w_bm25 < 0.0 or w_sem < 0.0:
        raise InvalidHybridWeightsError(
            f"Hybrid weights must be non-negative. Got bm25={w_bm25}, semantic={w_sem}"
        )
    total = w_bm25 + w_sem
    if total <= 0.0:
        raise InvalidHybridWeightsError("Hybrid weights cannot both be zero.")

    return NormalizedWeights(bm25=w_bm25 / total, semantic=w_sem / total)


def min_max_normalize(scores: Sequence[float]) -> list[float]:
    """Deterministically scale scores to [0.0, 1.0] using Min-Max normalization.

    Handles edge cases safely:
    - Empty sequence: returns []
    - All scores equal / single element: returns [1.0] if score > 0 else [0.0]
    - NaN / Infinity checks: sanitized to 0.0 before min/max calculation
    - Mixed candidate sets: maps min_score -> 0.0 and max_score -> 1.0
    """
    if not scores:
        return []

    cleaned = [0.0 if math.isnan(s) or math.isinf(s) else float(s) for s in scores]
    min_s = min(cleaned)
    max_s = max(cleaned)

    if math.isclose(min_s, max_s, abs_tol=1e-9):
        # All scores equal (or single element)
        fill_val = 1.0 if max_s > 0.0 else 0.0
        return [fill_val for _ in cleaned]

    span = max_s - min_s
    return [(s - min_s) / span for s in cleaned]


@dataclass
class CandidateDoc:
    document_id: str
    title: str
    source: str
    snippet: str
    bm25_raw_score: float = 0.0
    semantic_raw_score: float = 0.0
    matched_terms: set[str] = field(default_factory=set)


def highlight_matched_terms(text: str, query_terms: Iterable[str]) -> str:
    """Safely highlight matched query terms in plain text snippet.

    Wraps matched terms in <mark>...</mark> tags.
    First escapes any existing HTML characters to prevent XSS.
    Case-insensitive matching that preserves original casing inside tags.
    """
    if not text:
        return ""
    terms = [t.strip() for t in query_terms if t and t.strip()]
    if not terms:
        return html.escape(text)

    # Sort terms by length descending so longer phrases match first
    terms.sort(key=len, reverse=True)
    pattern = re.compile(r"(" + "|".join(re.escape(t) for t in terms) + r")", re.IGNORECASE)

    parts = pattern.split(text)
    out = []
    for part in parts:
        if not part:
            continue
        if pattern.fullmatch(part):
            out.append(f"<mark>{html.escape(part)}</mark>")
        else:
            out.append(html.escape(part))

    return "".join(out)


def merge_and_rerank_hybrid(
    bm25_hits: Sequence[SearchResult],
    semantic_hits: Sequence[SearchResult],
    query: str,
    limit: int,
    *,
    bm25_weight: float | None = None,
    semantic_weight: float | None = None,
) -> tuple[list[SearchResult], dict[str, float]]:
    """Merge BM25 and Semantic candidates by document_id and rerank deterministically.

    Steps:
    1. Collect unique document candidates.
    2. Extract component scores.
    3. Normalize component scores independently via min_max_normalize.
    4. Compute weighted hybrid_score = w_bm25 * norm_bm25 + w_sem * norm_sem.
    5. Sort candidates descending by (hybrid_score, document_id).
    6. Truncate to limit, assign ranks 1..K, and highlight matched terms in snippets.
    """
    weights = validate_and_normalize_weights(bm25_weight, semantic_weight)

    # 1. Merge by document_id
    candidates: dict[str, CandidateDoc] = {}

    for hit in bm25_hits:
        doc_id = str(hit.document_id)
        if doc_id not in candidates:
            candidates[doc_id] = CandidateDoc(
                document_id=doc_id,
                title=hit.title,
                source=hit.source,
                snippet=hit.snippet,
                bm25_raw_score=float(hit.score),
                matched_terms=set(hit.matched_terms),
            )
        else:
            c = candidates[doc_id]
            c.bm25_raw_score = float(hit.score)
            c.matched_terms.update(hit.matched_terms)
            if not c.snippet and hit.snippet:
                c.snippet = hit.snippet

    for hit in semantic_hits:
        doc_id = str(hit.document_id)
        if doc_id not in candidates:
            candidates[doc_id] = CandidateDoc(
                document_id=doc_id,
                title=hit.title,
                source=hit.source,
                snippet=hit.snippet,
                semantic_raw_score=float(hit.score),
                matched_terms=set(hit.matched_terms),
            )
        else:
            c = candidates[doc_id]
            c.semantic_raw_score = float(hit.score)
            c.matched_terms.update(hit.matched_terms)
            if not c.snippet and hit.snippet:
                c.snippet = hit.snippet

    if not candidates:
        return [], {"bm25": weights.bm25, "semantic": weights.semantic}

    doc_list = list(candidates.values())

    # 2 & 3. Normalize component scores
    raw_bm25 = [c.bm25_raw_score for c in doc_list]
    raw_sem = [c.semantic_raw_score for c in doc_list]

    norm_bm25 = min_max_normalize(raw_bm25)
    norm_sem = min_max_normalize(raw_sem)

    # 4. Compute hybrid scores
    scored_candidates: list[tuple[float, CandidateDoc]] = []
    qp = QueryProcessor()
    q_tokens = [w.token for w in qp.process(query)]

    for idx, cand in enumerate(doc_list):
        nb = norm_bm25[idx]
        ns = norm_sem[idx]
        h_score = (weights.bm25 * nb) + (weights.semantic * ns)
        scored_candidates.append((h_score, cand))

    # 5. Deterministic sorting: hybrid_score desc, document_id asc (string or int safe)
    def _sort_key(item: tuple[float, CandidateDoc]):
        score, cand = item
        # Attempt integer conversion for document_id for natural numeric sorting if possible
        doc_id_val: int | str
        try:
            doc_id_val = int(cand.document_id)
        except ValueError:
            doc_id_val = cand.document_id
        return (score, doc_id_val if isinstance(doc_id_val, str) else -doc_id_val)

    scored_candidates.sort(
        key=lambda pair: (pair[0], _sort_key_doc_id(pair[1].document_id)),
        reverse=True
    )

    # 6. Truncate, assign rank, highlight snippet
    final_hits: list[SearchResult] = []
    for rank, (score, cand) in enumerate(scored_candidates[:limit], start=1):
        # Ensure matched terms include query tokens present in matched_terms or fallback
        all_terms = sorted(cand.matched_terms)
        snippet_raw = cand.snippet
        # Highlight query terms if available
        snippet_hl = highlight_matched_terms(snippet_raw, q_tokens if q_tokens else all_terms)

        final_hits.append(
            SearchResult(
                rank=rank,
                document_id=cand.document_id,
                title=cand.title,
                source=cand.source,
                snippet=snippet_hl,
                score=round(float(score), 4),
                matched_terms=tuple(all_terms)[:8],
            )
        )

    return final_hits, {"bm25": round(weights.bm25, 4), "semantic": round(weights.semantic, 4)}


def _sort_key_doc_id(doc_id_str: str):
    """Secondary tie-breaker sorting helper. Higher doc_id string/int as tie-breaker or stable string reverse."""
    try:
        return -int(doc_id_str)
    except ValueError:
        return doc_id_str


__all__ = [
    "InvalidHybridWeightsError",
    "NormalizedWeights",
    "validate_and_normalize_weights",
    "min_max_normalize",
    "highlight_matched_terms",
    "merge_and_rerank_hybrid",
]
