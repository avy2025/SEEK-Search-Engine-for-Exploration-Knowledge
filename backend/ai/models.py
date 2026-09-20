"""Phase 8 AI / RAG Models & Data Structures.

Defines Pydantic request and response schemas for answer generation, source citations,
context passages, and retrieval metadata.
"""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class SourceCitation(BaseModel):
    """Source reference for grounded answer attribution."""

    citation_id: int = Field(..., description="Numeric citation ID used in answer text, e.g. [1]")
    document_id: str = Field(..., description="Canonical document ID from SEEK persistence layer")
    title: str = Field(..., description="Document title")
    source: str = Field(..., description="Document URL or relative source path")
    rank: int = Field(..., description="Rank in retrieved hit list")
    score: float = Field(0.0, description="Relevance score from retrieval engine")


class ContextPassage(BaseModel):
    """Selected passage chunk passed into LLM prompt context."""

    citation_id: int = Field(..., description="Numeric citation ID assigned to passage")
    document_id: str = Field(..., description="Canonical document ID")
    title: str = Field(..., description="Document title")
    content: str = Field(..., description="Clean text chunk or snippet used in prompt")


class AnswerRequest(BaseModel):
    """Request payload for POST /api/answer."""

    query: str = Field(..., min_length=1, max_length=500, description="Free-text user question")
    mode: Literal["hybrid", "lexical", "bm25", "semantic"] = Field(
        "hybrid", description="Retrieval mode for passage fetching"
    )
    limit: int = Field(5, ge=1, le=20, description="Max passages to consider for context")
    temperature: float | None = Field(None, ge=0.0, le=2.0, description="Optional LLM temperature override")


class RetrievalMetadata(BaseModel):
    """Metadata regarding candidate retrieval for RAG."""

    mode: str = Field(..., description="Retrieval mode executed")
    passages_considered: int = Field(0, description="Number of candidate hits evaluated")
    passages_used: int = Field(0, description="Number of candidate passages injected into context")
    took_ms: float = Field(0.0, description="Retrieval latency in milliseconds")


class GenerationMetadata(BaseModel):
    """Metadata regarding LLM answer generation."""

    provider: str = Field(..., description="LLM provider name (e.g. fake, ollama, transformers)")
    model: str = Field(..., description="Model identifier used")
    took_ms: float = Field(0.0, description="Generation latency in milliseconds")


class AnswerResponse(BaseModel):
    """Structured response envelope for POST /api/answer."""

    query: str = Field(..., description="Normalized query")
    answer: str = Field(..., description="Synthesized grounded answer or fallback message")
    status: Literal["ok", "degraded", "unavailable", "error"] = Field("ok", description="RAG processing status")
    fallback_mode: bool = Field(False, description="True if answer is a fallback message or search fallback")
    sources: list[SourceCitation] = Field(default_factory=list, description="Validated source citations")
    retrieval: RetrievalMetadata = Field(..., description="Retrieval metadata")
    generation: GenerationMetadata = Field(..., description="Generation metadata")
    search_hits: list[dict[str, Any]] = Field(
        default_factory=list, description="Raw search hits returned on fallback"
    )
    message: str = Field("ok", description="Human-readable status or diagnostic message")


__all__ = [
    "SourceCitation",
    "ContextPassage",
    "AnswerRequest",
    "RetrievalMetadata",
    "GenerationMetadata",
    "AnswerResponse",
]
