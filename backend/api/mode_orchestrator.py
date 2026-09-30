"""Phase 9 specialized search-mode orchestration (web / ai / research / code).

This is the **orchestration layer** over the existing SEEK retrieval/RAG stack.
It never re-implements scoring:

* retrieval is delegated to the existing handlers in
  :mod:`backend.api.search` (``_hybrid_search``, ``_semantic_search``,
  ``_lexical_search``),
* AI answers are produced by the existing Phase 8 RAG orchestrator
  (:func:`backend.ai.rag.generate_rag_answer`),
* mode decisions come from :mod:`backend.search.modes`.

Every response shares one explicit envelope so clients can always tell *which
mode* ran and *how healthy* it was:

``{query, mode, status, total, limit, hits, took_ms, message, answer, sources, metadata}``

``status`` is one of ``ok`` / ``degraded`` / ``unavailable``:

* ``ok`` — retrieval answered (and, for RAG modes, an answer was generated when
  the pipeline could ground one);
* ``degraded`` — a preferred capability was unavailable and the request was
  served with an explicitly reported fallback (e.g. lexical instead of hybrid);
* ``unavailable`` — nothing could be served (index not built / RAG disabled).

Retrieval failures are never hidden: every fallback is described in ``message``,
``metadata.degraded_reason`` and ``metadata.index``.
"""
from __future__ import annotations

import time
from typing import Any

from backend.config import settings
from backend.search.modes import (
    ModeSpec,
    SearchMode,
    attach_code_snippets,
    build_source_entries,
    diversify_hits,
    drop_unmatched_hits,
    enrich_snippets,
    expand_technical_query,
    prioritize_documentation_hits,
    resolve_limit,
    resolve_mode_spec,
)

STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"
STATUS_UNAVAILABLE = "unavailable"


# --------------------------------------------------------------------------- #
# availability probes (delegated to the existing managers)
# --------------------------------------------------------------------------- #


def _index_availability() -> dict[str, Any]:
    """Report BM25 / semantic availability without hiding retrieval problems.

    Availability is read from each manager's **in-memory** state, never from
    ``IndexManager.status()``. ``status()`` deliberately re-probes PostgreSQL on
    every call (so a late-starting database is picked up), which costs a full
    connect timeout when the database is unreachable — that made every mode
    search pay two extra database round-trips for information it did not need.

    The in-memory counters are the more direct answer anyway: a mode can only
    retrieve what the live engines hold, so ``document_count``/``loaded`` describe
    retrieval capability exactly, with no database round-trip and no caching (and
    therefore no stale status). The retrieval handlers still call ``status()``
    themselves, so the authoritative database view is unchanged and remains in
    the response.
    """
    from backend.api import search as search_api
    from backend.search.index_manager import get_index_manager

    bm25_manager = get_index_manager()
    bm25_documents = int(getattr(bm25_manager.engine, "document_count", 0) or 0)
    bm25_loaded = bool(getattr(bm25_manager, "loaded", False))
    bm25_available = bool(bm25_documents > 0 or bm25_loaded)

    semantic_documents = 0
    semantic_loaded = False
    semantic_error = ""
    try:
        semantic_manager = search_api.get_semantic_index_manager()
        semantic_documents = int(getattr(semantic_manager, "document_count", 0) or 0)
        semantic_loaded = bool(getattr(semantic_manager, "loaded", False))
    except Exception as exc:  # noqa: BLE001 - availability is best-effort reporting
        semantic_error = str(exc)
    semantic_available = bool(semantic_documents > 0 and semantic_loaded)

    return {
        "bm25": bm25_available,
        "bm25_documents": bm25_documents,
        "bm25_message": "" if bm25_available else "no documents indexed",
        "semantic": semantic_available,
        "semantic_documents": semantic_documents,
        "semantic_message": (
            semantic_error
            or ("" if semantic_available else "semantic index not loaded")
        ),
    }


def _content_lookup():
    """Return a ``document_id -> content`` resolver over the live indexes."""

    def lookup(document_id: str) -> str | None:
        from backend.api import search as search_api

        try:
            doc = search_api._get_engine().get_document(document_id)
            if doc is not None:
                return doc.content
        except Exception:  # noqa: BLE001 - enrichment is best-effort
            pass
        try:
            doc = search_api.get_semantic_index_manager().get_document(document_id)
        except Exception:  # noqa: BLE001 - enrichment is best-effort
            return None
        return doc.content if doc is not None else None

    return lookup


# --------------------------------------------------------------------------- #
# retrieval delegation
# --------------------------------------------------------------------------- #


def _retrieve(
    spec: ModeSpec,
    query: str,
    candidate_limit: int,
    bm25_weight: float | None,
    semantic_weight: float | None,
    index_state: dict[str, Any],
) -> dict[str, Any]:
    """Run the mode's retrieval strategy through the existing handlers.

    Returns the handler payload plus the *effective* strategy, an explicit
    status and a human-readable degraded reason (or ``None``).
    """
    from backend.api import search as search_api

    semantic_message = index_state.get("semantic_message") or "semantic index not available"

    if spec.retrieval == "semantic":
        payload = search_api._semantic_search(query, candidate_limit)
        hits = payload.get("hits")
        if hits:
            return {
                "payload": payload,
                "strategy": "semantic",
                "status": STATUS_OK,
                "message": str(payload.get("message") or ""),
                "degraded_reason": None,
            }
        reason = (
            "semantic retrieval unavailable: "
            f"{payload.get('message') or semantic_message}"
        )
        return {
            "payload": payload,
            "strategy": "semantic",
            "status": STATUS_UNAVAILABLE,
            "message": reason,
            "degraded_reason": reason,
        }

    if spec.retrieval == "hybrid" and index_state["bm25"] and index_state["semantic"]:
        payload = search_api._hybrid_search(
            query,
            candidate_limit,
            spec.bm25_weight if bm25_weight is None else bm25_weight,
            spec.semantic_weight if semantic_weight is None else semantic_weight,
        )
        status = str(payload.get("status") or STATUS_OK)
        if status == STATUS_OK:
            return {
                "payload": payload,
                "strategy": "hybrid",
                "status": STATUS_OK,
                "message": str(payload.get("message") or ""),
                "degraded_reason": None,
            }
        # Hybrid itself failed -> try the lexical path, but keep the explanation.
        lexical_payload = search_api._lexical_search(query, candidate_limit)
        if lexical_payload.get("hits"):
            reason = (
                f"hybrid retrieval unavailable: {payload.get('message') or status}; "
                "serving lexical BM25 ranking instead"
            )
            return {
                "payload": lexical_payload,
                "strategy": "lexical",
                "status": STATUS_DEGRADED,
                "message": reason,
                "degraded_reason": reason,
            }
        return {
            "payload": payload,
            "strategy": "hybrid",
            "status": status,
            "message": str(payload.get("message") or ""),
            "degraded_reason": (
                None if status == STATUS_OK else str(payload.get("message") or status)
            ),
        }

    # Lexical strategy, or hybrid with a missing component.
    payload = search_api._lexical_search(query, candidate_limit)
    payload_status = STATUS_OK if index_state["bm25"] else STATUS_UNAVAILABLE
    degraded_reason: str | None = None
    if spec.retrieval == "hybrid":
        if not index_state["bm25"]:
            degraded_reason = (
                "hybrid retrieval unavailable: BM25 index is not available "
                f"({index_state.get('bm25_message') or 'no documents indexed'})"
            )
        else:
            degraded_reason = (
                "hybrid retrieval unavailable: semantic index is not available "
                f"({semantic_message}); serving lexical BM25 ranking"
            )
    return {
        "payload": payload,
        "strategy": "lexical",
        "status": (
            STATUS_DEGRADED if degraded_reason and payload.get("hits") else payload_status
        ),
        "message": degraded_reason or str(payload.get("message") or ""),
        "degraded_reason": degraded_reason,
    }


# --------------------------------------------------------------------------- #
# RAG delegation (AI Answers / Research synthesis)
# --------------------------------------------------------------------------- #


def _run_rag(
    *,
    spec: ModeSpec,
    query: str,
    retrieval_payload: dict[str, Any],
    limit: int,
    retrieval_status: str,
) -> dict[str, Any]:
    """Run the Phase 8 RAG pipeline and normalise it for a mode response."""
    if not settings.RAG_ENABLED:
        return {
            "status": "disabled",
            "generated": False,
            "answer": None,
            "sources": [],
            "message": "RAG answer generation is disabled in settings.",
            "detail": {
                "enabled": False,
                "status": "disabled",
                "generated": False,
                "message": "RAG answer generation is disabled in settings.",
            },
        }

    if retrieval_status == STATUS_UNAVAILABLE:
        return {
            "status": "skipped",
            "generated": False,
            "answer": None,
            "sources": [],
            "message": "AI synthesis skipped: retrieval is unavailable.",
            "detail": {
                "enabled": True,
                "status": "skipped",
                "generated": False,
                "message": "AI synthesis skipped: retrieval is unavailable.",
            },
        }

    from backend.ai.models import AnswerRequest
    from backend.ai.rag import generate_rag_answer

    passages = max(1, min(int(limit), int(settings.RAG_MAX_PASSAGES), 20))
    request = AnswerRequest(query=query, mode=spec.retrieval, limit=passages)
    response = generate_rag_answer(request, retrieval_payload=retrieval_payload)

    answer_text = None if response.fallback_mode else response.answer
    if response.fallback_mode:
        rag_status = "no_context" if response.status == STATUS_OK else response.status
    else:
        rag_status = STATUS_OK

    return {
        "status": rag_status,
        "generated": bool(answer_text),
        "answer": answer_text,
        "sources": list(response.sources),
        "message": str(response.message or ""),
        "detail": {
            "enabled": True,
            "status": rag_status,
            "generated": bool(answer_text),
            "fallback_mode": bool(response.fallback_mode),
            "provider": response.generation.provider,
            "model": response.generation.model,
            "generation_took_ms": response.generation.took_ms,
            "passages": response.retrieval.passages_used,
            "retrieval": response.retrieval.model_dump(),
            "message": str(response.message or ""),
        },
    }


def _rag_mode_status(retrieval_status: str, rag: dict[str, Any]) -> str:
    """Combine retrieval health and RAG outcome into the mode status.

    Retrieval health always wins: a degraded/unavailable retrieval path is never
    reported as a clean ``ok`` just because an answer was still produced from
    the fallback evidence.
    """
    if retrieval_status in {STATUS_DEGRADED, STATUS_UNAVAILABLE}:
        return retrieval_status
    if rag["generated"]:
        return STATUS_OK
    if rag["status"] in {STATUS_DEGRADED, STATUS_UNAVAILABLE, "disabled"}:
        return STATUS_UNAVAILABLE
    return STATUS_OK


# --------------------------------------------------------------------------- #
# public orchestration entry point
# --------------------------------------------------------------------------- #


def execute_search_mode(
    *,
    query: str,
    mode: Any,
    limit: int | None = None,
    bm25_weight: float | None = None,
    semantic_weight: float | None = None,
) -> dict[str, Any]:
    """Execute a Phase 9 specialized search mode and return its envelope."""
    started = time.perf_counter()
    spec = resolve_mode_spec(mode)
    effective_limit = resolve_limit(spec, limit)
    original_query = (query or "").strip()

    retrieval_query = original_query
    technical_terms: list[str] = []
    added_terms: list[str] = []
    if spec.technical_term_expansion:
        retrieval_query, technical_terms, added_terms = expand_technical_query(
            original_query
        )

    index_state = _index_availability()
    retrieval = _retrieve(
        spec,
        retrieval_query,
        spec.candidate_limit(effective_limit),
        bm25_weight,
        semantic_weight,
        index_state,
    )
    payload = retrieval["payload"]
    retrieval_status = retrieval["status"]

    # An installed-but-empty index is a retrieval *failure*, not an empty
    # result set: report it as unavailable so callers can tell "nothing matched"
    # apart from "there is nothing to search yet".
    index_is_empty = (
        not payload.get("hits")
        and int(index_state["bm25_documents"]) <= 0
        and int(index_state["semantic_documents"]) <= 0
    )
    if index_is_empty and retrieval_status == STATUS_OK:
        retrieval_status = STATUS_UNAVAILABLE
        retrieval["degraded_reason"] = (
            "search index is not built: no documents are available in the BM25 "
            "or semantic index; run /api/index/rebuild"
        )
        retrieval["message"] = retrieval["degraded_reason"]

    hits: list[dict[str, Any]] = [
        dict(hit) for hit in (payload.get("hits") or []) if isinstance(hit, dict)
    ]

    # BM25/hybrid always pad the candidate list with 0.0-scored documents. Those
    # are not matches, so they never reach the specialised-mode envelope (nor the
    # RAG context); the legacy retrieval modes keep their original behaviour.
    hits, match_stats = drop_unmatched_hits(
        hits, score_floor=settings.MODE_MATCH_SCORE_FLOOR
    )
    payload["hits"] = hits

    metadata: dict[str, Any] = {
        "mode": spec.mode.value,
        "retrieval_strategy": retrieval["strategy"],
        "limits": {
            "requested": limit,
            "effective": effective_limit,
            "candidates": spec.candidate_limit(effective_limit),
            "max": spec.max_limit,
        },
        "capabilities": spec.capabilities(),
        "matching": match_stats,
        "index": {
            # ``bm25``/``semantic`` report whether this mode can actually serve
            # results (documents present), not merely whether a manager object
            # is installed - an empty index must never look available.
            "bm25": int(index_state["bm25_documents"]) > 0,
            "bm25_documents": index_state["bm25_documents"],
            "semantic": int(index_state["semantic_documents"]) > 0,
            "semantic_documents": index_state["semantic_documents"],
        },
    }

    if spec.technical_term_expansion:
        metadata["query_expansion"] = {
            "original": original_query,
            "retrieval_query": retrieval_query,
            "technical_terms": technical_terms,
            "added_terms": added_terms,
        }

    content_lookup = _content_lookup()

    if spec.snippet_words:
        hits, snippet_stats = enrich_snippets(
            hits,
            query=retrieval_query,
            words=int(spec.snippet_words or 0),
            content_lookup=content_lookup,
        )
        metadata["snippets"] = snippet_stats

    if spec.code_mode:
        hits, code_stats = attach_code_snippets(
            hits,
            query=retrieval_query,
            content_lookup=content_lookup,
            max_chars=int(settings.CODE_SNIPPET_MAX_CHARS),
        )
        hits, doc_stats = prioritize_documentation_hits(
            hits, enabled=spec.doc_source_priority
        )
        metadata["code"] = {**code_stats, **doc_stats}

    if spec.diversify_sources:
        hits, diversity_stats = diversify_hits(
            hits, per_source_cap=spec.per_source_cap, limit=effective_limit
        )
        metadata["diversification"] = diversity_stats
    else:
        hits = hits[:effective_limit]
        for index, hit in enumerate(hits, start=1):
            hit["rank"] = index

    rag_detail: dict[str, Any] | None = None
    answer: str | None = None
    sources: list[dict[str, Any]] = []
    status = retrieval_status
    message = retrieval["message"]

    if spec.rag_enabled:
        rag = _run_rag(
            spec=spec,
            query=original_query,
            retrieval_payload=payload,
            limit=effective_limit,
            retrieval_status=retrieval_status,
        )
        answer = rag["answer"]
        sources = build_source_entries(hits, rag["sources"] or None)
        rag_detail = rag["detail"]
        status = _rag_mode_status(retrieval_status, rag)
        message = (
            retrieval["message"] if retrieval["message"] else rag["message"]
        )
        if not rag["generated"] and retrieval_status != STATUS_UNAVAILABLE:
            metadata["answer_note"] = rag["message"]
    else:
        sources = build_source_entries(hits)

    if retrieval["degraded_reason"]:
        metadata["degraded_reason"] = retrieval["degraded_reason"]

    if spec.diversify_sources:
        metadata["evidence"] = {
            "documents_returned": len(hits),
            "distinct_sources": len({s["domain"] or s["document_id"] for s in sources}),
            "cited_sources": len(sources),
            "kind": "retrieved_evidence",
        }
    if rag_detail is not None:
        metadata["rag"] = rag_detail
        if spec.mode is SearchMode.RESEARCH:
            metadata["synthesis"] = {
                **rag_detail,
                "kind": "generated_synthesis",
                "generated": bool(answer),
            }

    if not hits and status == STATUS_OK:
        message = "no indexed SEEK sources matched this query"

    return {
        "query": original_query,
        "mode": spec.mode.value,
        "status": status,
        "total": len(hits),
        "limit": effective_limit,
        "hits": hits,
        "took_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "message": message,
        "answer": answer,
        "sources": sources,
        "metadata": metadata,
    }


__all__ = [
    "execute_search_mode",
    "STATUS_OK",
    "STATUS_DEGRADED",
    "STATUS_UNAVAILABLE",
]