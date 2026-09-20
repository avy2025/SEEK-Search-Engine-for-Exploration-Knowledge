"""Phase 8 Passage Selection & Context Pipeline.

Extracts top-K passages from search hits, enforces context length limits,
deduplicates sources, and constructs hallucination-resistant grounded prompts.
"""
from __future__ import annotations

import logging
from typing import Sequence

from backend.ai.models import ContextPassage, SourceCitation
from backend.config import settings
from backend.search.models import SearchResult

logger = logging.getLogger("seek.ai.pipeline")


def extract_and_select_passages(
    hits: Sequence[SearchResult | dict[str, object]],
    max_passages: int | None = None,
    max_chars: int | None = None,
) -> tuple[list[ContextPassage], list[SourceCitation]]:
    """Extract top-K passages and corresponding citations from search hits.

    Enforces passage count caps, total character length caps, and document deduplication.
    """
    limit_passages = max_passages if max_passages is not None else settings.RAG_MAX_PASSAGES
    limit_chars = max_chars if max_chars is not None else settings.RAG_MAX_CONTEXT_CHARS

    passages: list[ContextPassage] = []
    citations: list[SourceCitation] = []
    seen_doc_ids: set[str] = set()
    current_chars = 0

    citation_id = 1
    for rank_idx, raw_hit in enumerate(hits, start=1):
        if len(passages) >= limit_passages or current_chars >= limit_chars:
            break

        # Normalize dict or SearchResult object
        if isinstance(raw_hit, dict):
            doc_id = str(raw_hit.get("document_id", ""))
            title = str(raw_hit.get("title", ""))
            source = str(raw_hit.get("source", ""))
            snippet = str(raw_hit.get("snippet", ""))
            score = float(raw_hit.get("score", 0.0))
        else:
            doc_id = str(raw_hit.document_id)
            title = str(raw_hit.title)
            source = str(raw_hit.source)
            snippet = str(raw_hit.snippet)
            score = float(raw_hit.score)

        if not doc_id or doc_id in seen_doc_ids:
            continue

        clean_text = _clean_snippet_text(snippet)
        if not clean_text:
            continue

        # Check total character cap
        added_len = len(clean_text)
        if current_chars + added_len > limit_chars and passages:
            # If adding this passage exceeds max_chars limit and we already have passages, stop
            break

        seen_doc_ids.add(doc_id)
        current_chars += added_len

        passages.append(
            ContextPassage(
                citation_id=citation_id,
                document_id=doc_id,
                title=title,
                content=clean_text,
            )
        )
        citations.append(
            SourceCitation(
                citation_id=citation_id,
                document_id=doc_id,
                title=title,
                source=source,
                rank=rank_idx,
                score=score,
            )
        )
        citation_id += 1

    return passages, citations


def construct_grounded_prompt(query: str, passages: Sequence[ContextPassage]) -> tuple[str, str]:
    """Construct system prompt and user prompt for grounded RAG answer generation.

    Instructs model to use strictly supplied sources, avoid inventing facts,
    and include inline numeric citations [1], [2].
    """
    system_prompt = (
        "You are SEEK AI, an accurate search assistant. Your task is to answer the user's question "
        "STRICTLY using only the provided source context passages.\n\n"
        "STRICT RULES:\n"
        "1. Base your answer ONLY on the provided SOURCES below.\n"
        "2. Do NOT use outside knowledge or extrapolate beyond the facts mentioned.\n"
        "3. Every factual statement in your answer MUST include inline citation numbers matching "
        "the sources used (e.g., [1], [2]).\n"
        "4. If the provided SOURCES do not contain enough information to answer the question, state clearly: "
        "\"I couldn't find enough relevant information in SEEK's indexed sources.\"\n"
        "5. Do NOT invent source IDs or citations that were not provided."
    )

    formatted_sources = []
    for p in passages:
        formatted_sources.append(
            f"--- SOURCE [{p.citation_id}] ---\n"
            f"Title: {p.title}\n"
            f"Document ID: {p.document_id}\n"
            f"Content: {p.content}"
        )

    sources_block = "\n\n".join(formatted_sources)
    user_prompt = (
        f"SOURCES:\n"
        f"{sources_block}\n\n"
        f"USER QUESTION:\n"
        f"{query}\n\n"
        f"ANSWER:"
    )

    return system_prompt, user_prompt


def _clean_snippet_text(text: str) -> str:
    """Strip HTML mark tags or formatting for clean LLM context input."""
    if not text:
        return ""
    # Remove <mark> and </mark> tags added during highlighting
    cleaned = text.replace("<mark>", "").replace("</mark>", "")
    return cleaned.strip()


__all__ = [
    "extract_and_select_passages",
    "construct_grounded_prompt",
]
