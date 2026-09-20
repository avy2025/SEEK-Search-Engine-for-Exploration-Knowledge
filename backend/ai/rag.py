"""Phase 8 AI / RAG Orchestrator Module.

Coordinates candidate search retrieval, context selection, prompt construction,
LLM generation, citation validation, and fallback handling.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Sequence

from backend.ai.models import (
    AnswerRequest,
    AnswerResponse,
    GenerationMetadata,
    RetrievalMetadata,
    SourceCitation,
)
from backend.ai.pipeline import (
    construct_grounded_prompt,
    extract_and_select_passages,
)
from backend.ai.providers import (
    LLMProvider,
    LLMProviderError,
    get_llm_provider,
)
from backend.api.search import _hybrid_search, _lexical_search, _semantic_search
from backend.config import settings

logger = logging.getLogger("seek.ai.rag")


def generate_rag_answer(
    request: AnswerRequest,
    provider: LLMProvider | None = None,
) -> AnswerResponse:
    """Execute end-to-end RAG pipeline and return structured AnswerResponse.

    Gracefully handles RAG disabled state, insufficient context, LLM failures,
    and timeouts by falling back to search hits with explicit status reporting.
    """
    start_time = time.perf_counter()
    query = request.query.strip()
    mode = request.mode.lower()
    limit = request.limit

    # 1. Check if RAG is globally enabled
    if not settings.RAG_ENABLED:
        ret_payload = _execute_retrieval(query, mode, limit)
        return _build_fallback_response(
            query=query,
            mode=mode,
            ret_payload=ret_payload,
            status="unavailable",
            message="RAG answer generation is disabled in settings.",
            start_time=start_time,
        )

    # 2. Execute candidate search retrieval
    ret_start = time.perf_counter()
    ret_payload = _execute_retrieval(query, mode, limit)
    ret_took_ms = (time.perf_counter() - ret_start) * 1000.0

    raw_hits = ret_payload.get("hits", [])
    if not isinstance(raw_hits, list):
        raw_hits = []

    # 3. Check for empty retrieval or insufficient score
    if not raw_hits:
        return _build_fallback_response(
            query=query,
            mode=mode,
            ret_payload=ret_payload,
            status="ok",
            message="I couldn't find enough relevant information in SEEK's indexed sources.",
            start_time=start_time,
            ret_took_ms=ret_took_ms,
        )

    top_score = float(raw_hits[0].get("score", 0.0)) if raw_hits else 0.0
    if top_score < settings.RAG_MIN_SCORE_THRESHOLD:
        return _build_fallback_response(
            query=query,
            mode=mode,
            ret_payload=ret_payload,
            status="ok",
            message="I couldn't find enough relevant information in SEEK's indexed sources.",
            start_time=start_time,
            ret_took_ms=ret_took_ms,
        )

    # 4. Extract passages and citations
    passages, citations = extract_and_select_passages(
        hits=raw_hits,
        max_passages=limit,
        max_chars=settings.RAG_MAX_CONTEXT_CHARS,
    )

    if not passages:
        return _build_fallback_response(
            query=query,
            mode=mode,
            ret_payload=ret_payload,
            status="ok",
            message="I couldn't find enough relevant information in SEEK's indexed sources.",
            start_time=start_time,
            ret_took_ms=ret_took_ms,
        )

    # 5. Construct grounded prompt
    system_prompt, user_prompt = construct_grounded_prompt(query, passages)

    # 6. Invoke LLM provider
    active_provider = provider or get_llm_provider()
    gen_start = time.perf_counter()

    try:
        llm_result = active_provider.generate(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=request.temperature,
            timeout=settings.RAG_LLM_TIMEOUT_SECONDS,
        )
        gen_took_ms = llm_result.took_ms if llm_result.took_ms > 0 else (time.perf_counter() - gen_start) * 1000.0

        # Filter citations to only those actually cited in the answer (e.g. [1], [2])
        valid_citations = _filter_valid_citations(llm_result.text, citations)

        return AnswerResponse(
            query=query,
            answer=llm_result.text,
            status="ok",
            fallback_mode=False,
            sources=valid_citations if valid_citations else citations,
            retrieval=RetrievalMetadata(
                mode=mode,
                passages_considered=len(raw_hits),
                passages_used=len(passages),
                took_ms=round(ret_took_ms, 3),
            ),
            generation=GenerationMetadata(
                provider=llm_result.provider,
                model=llm_result.model,
                took_ms=round(gen_took_ms, 3),
            ),
            search_hits=[],
            message="ok",
        )

    except LLMProviderError as exc:
        logger.warning(f"RAG LLM provider error: {exc}")
        return _build_fallback_response(
            query=query,
            mode=mode,
            ret_payload=ret_payload,
            status="degraded",
            message=f"AI answer generation unavailable ({exc}). Showing search results.",
            start_time=start_time,
            ret_took_ms=ret_took_ms,
        )
    except Exception as exc:
        logger.error(f"Unexpected RAG generation failure: {exc}", exc_info=True)
        return _build_fallback_response(
            query=query,
            mode=mode,
            ret_payload=ret_payload,
            status="degraded",
            message=f"AI answer generation failed: {exc}. Showing search results.",
            start_time=start_time,
            ret_took_ms=ret_took_ms,
        )


def _execute_retrieval(query: str, mode: str, limit: int) -> dict[str, object]:
    """Execute retrieval query using existing search handlers."""
    if mode == "hybrid":
        return _hybrid_search(query, limit)
    if mode == "semantic":
        return _semantic_search(query, limit)
    return _lexical_search(query, limit)


def _build_fallback_response(
    query: str,
    mode: str,
    ret_payload: dict[str, object],
    status: str,
    message: str,
    start_time: float,
    ret_took_ms: float = 0.0,
) -> AnswerResponse:
    """Construct structured fallback AnswerResponse containing raw search hits."""
    raw_hits = ret_payload.get("hits", [])
    search_hits = raw_hits if isinstance(raw_hits, list) else []

    p_name = settings.RAG_LLM_PROVIDER
    p_model = settings.RAG_OLLAMA_MODEL if p_name == "ollama" else settings.RAG_TRANSFORMERS_MODEL

    return AnswerResponse(
        query=query,
        answer=message,
        status=status,  # type: ignore
        fallback_mode=True,
        sources=[],
        retrieval=RetrievalMetadata(
            mode=mode,
            passages_considered=len(search_hits),
            passages_used=0,
            took_ms=round(ret_took_ms, 3),
        ),
        generation=GenerationMetadata(
            provider=p_name,
            model=p_model,
            took_ms=0.0,
        ),
        search_hits=search_hits,
        message=message,
    )


def _filter_valid_citations(
    answer_text: str,
    citations: Sequence[SourceCitation],
) -> list[SourceCitation]:
    """Extract numeric citation IDs from generated answer text and match against candidates."""
    found_ids = set()
    matches = re.findall(r"\[(\d+)\]", answer_text)
    for m in matches:
        try:
            found_ids.add(int(m))
        except ValueError:
            pass

    if not found_ids:
        # Return top citation if no explicit citation tags were matched
        return list(citations[:1]) if citations else []

    valid = [c for c in citations if c.citation_id in found_ids]
    return valid if valid else list(citations[:1])


__all__ = [
    "generate_rag_answer",
]
