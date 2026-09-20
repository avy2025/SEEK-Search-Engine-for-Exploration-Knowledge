"""Phase 8 AI / RAG Answer API Endpoint Router."""
from __future__ import annotations

import logging

from fastapi import APIRouter, status

from backend.ai.models import AnswerRequest, AnswerResponse
from backend.ai.rag import generate_rag_answer

logger = logging.getLogger("seek.api.answer")

router = APIRouter(prefix="/answer", tags=["answer"])


@router.post(
    "",
    response_model=AnswerResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate grounded AI answer using retrieved SEEK context",
    description=(
        "Executes RAG pipeline on top of SEEK search retrieval. "
        "Selects top-K passages, constructs grounded prompt context, "
        "and synthesizes an answer with inline citations using local/free LLM backends."
    ),
)
def answer_question(request: AnswerRequest) -> AnswerResponse:
    """Generate grounded answer with source citations from retrieved search passages."""
    return generate_rag_answer(request)


__all__ = ["router"]
