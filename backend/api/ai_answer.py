"""Grounded AI Answers using Tavily live research and Gemini synthesis."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.ai.gemini import GeminiProviderError
from backend.ai.live_answer import (
    AIAnswerDailyLimitExceeded,
    AIAnswerPipelineError,
    AIAnswerQuotaExhausted,
    AIAnswerStoreError,
    get_ai_answer_service,
)
from backend.config import settings
from backend.search.tavily import (
    LiveSearchBudgetExceeded,
    TavilyProviderError,
    UsageStoreError,
)

router = APIRouter(prefix="/api/ai-answer", tags=["AI Answers"])


class AIAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=500)

    @field_validator("query", mode="before")
    @classmethod
    def normalize_query(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = " ".join(value.split())
            if not value:
                raise ValueError("query must not be blank")
        return value


class AIAnswerSource(BaseModel):
    id: int
    title: str
    url: str
    domain: str
    content: str


class AIAnswerUsageResponse(BaseModel):
    day: str
    daily_limit: int
    requests_used: int
    requests_remaining: int
    failed_requests: int
    quota_exhausted: bool
    last_successful_request_at: str | None


class AIAnswerUsageStatusResponse(AIAnswerUsageResponse):
    gemini_configured: bool
    tavily_configured: bool


class AIAnswerResponse(BaseModel):
    mode: Literal["ai"] = "ai"
    query: str
    answer: str
    sources: list[AIAnswerSource]
    model: str
    provider: Literal["gemini"] = "gemini"
    cached: bool
    searched_at: str
    took_ms: float
    usage: AIAnswerUsageResponse
    message: str


def _error(
    http_status: int,
    code: str,
    message: str,
    *,
    usage: dict[str, Any] | None = None,
) -> HTTPException:
    detail: dict[str, Any] = {"code": code, "message": message}
    if usage is not None:
        detail["usage"] = usage
    return HTTPException(status_code=http_status, detail=detail)


def _gemini_error(error: GeminiProviderError) -> HTTPException:
    errors = {
        "not_configured": (
            503,
            "gemini_not_configured",
            "AI Answers needs a backend GEMINI_API_KEY. Live Internet Search remains available.",
        ),
        "model_not_free": (
            503,
            "gemini_model_not_free",
            "The configured Gemini model is not on SEEK's verified free-tier allowlist.",
        ),
        "model_unavailable": (
            503,
            "gemini_model_unavailable",
            "The configured Gemini free-tier model is not available for this API key.",
        ),
        "authentication_error": (
            502,
            "gemini_authentication_error",
            "Google rejected the Gemini API key. Check the backend key configured for Google AI Studio.",
        ),
        "quota_exhausted": (
            429,
            "gemini_quota_exhausted",
            "Gemini reports that today's available free quota is exhausted. Use Live Internet Search or try again after its quota resets.",
        ),
        "rate_limited": (
            429,
            "gemini_rate_limited",
            "Gemini is rate limiting requests. Please wait before trying again.",
        ),
        "timeout": (
            504,
            "gemini_timeout",
            "Gemini did not respond before the configured timeout.",
        ),
        "network_error": (
            502,
            "gemini_network_error",
            "SEEK could not connect to Gemini.",
        ),
        "empty_response": (
            502,
            "gemini_empty_response",
            "Gemini returned no answer. No response was substituted.",
        ),
        "invalid_provider_response": (
            502,
            "gemini_invalid_response",
            "Gemini returned a response SEEK could not validate.",
        ),
        "provider_unavailable": (
            502,
            "gemini_unavailable",
            "Gemini is temporarily unavailable.",
        ),
    }
    http_status, code, message = errors.get(
        error.code,
        (502, "gemini_unavailable", "Gemini is temporarily unavailable."),
    )
    return _error(http_status, code, message)


def _tavily_error(error: TavilyProviderError) -> HTTPException:
    errors = {
        "not_configured": (
            503,
            "tavily_not_configured",
            "AI Answers needs a backend TAVILY_API_KEY to research the live web.",
        ),
        "authentication_error": (
            502,
            "tavily_authentication_error",
            "Tavily rejected the configured API key. Check the backend key.",
        ),
        "rate_limited": (
            429,
            "tavily_rate_limited",
            "Tavily is rate limiting requests. Please wait before trying again.",
        ),
        "credits_exhausted": (
            429,
            "tavily_credits_exhausted",
            "Tavily reports that its available credits are exhausted.",
        ),
        "timeout": (
            504,
            "tavily_timeout",
            "Tavily did not respond before the configured timeout.",
        ),
        "network_error": (
            502,
            "tavily_network_error",
            "SEEK could not connect to Tavily to research this question.",
        ),
    }
    http_status, code, message = errors.get(
        error.code,
        (502, "tavily_unavailable", "Tavily research is temporarily unavailable."),
    )
    return _error(http_status, code, message)


@router.post(
    "",
    response_model=AIAnswerResponse,
    summary="Answer a question using Tavily research and Gemini",
)
async def ai_answer(request: AIAnswerRequest) -> AIAnswerResponse:
    """Return one cited answer grounded in current Tavily search results."""
    try:
        return AIAnswerResponse(**(await get_ai_answer_service().answer(request.query)))
    except AIAnswerDailyLimitExceeded as exc:
        raise _error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "seek_daily_ai_limit",
            "SEEK's daily AI-answer limit has been reached. Use Live Internet Search or try again tomorrow.",
            usage=exc.usage,
        ) from exc
    except AIAnswerQuotaExhausted as exc:
        raise _error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "gemini_quota_exhausted",
            "Gemini's free quota is exhausted for today. Use Live Internet Search or try again after the quota resets.",
            usage=exc.usage,
        ) from exc
    except GeminiProviderError as exc:
        raise _gemini_error(exc) from exc
    except TavilyProviderError as exc:
        raise _tavily_error(exc) from exc
    except LiveSearchBudgetExceeded as exc:
        raise _error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "seek_monthly_budget_exhausted",
            "SEEK has reached its monthly Tavily credit budget. AI research is unavailable until it resets.",
            usage=exc.usage,
        ) from exc
    except AIAnswerPipelineError as exc:
        if exc.code == "research_no_results":
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "research_no_results",
                "Tavily returned no usable web research. Gemini was not asked to answer.",
            ) from exc
        if exc.code == "missing_citations":
            raise _error(
                status.HTTP_502_BAD_GATEWAY,
                "gemini_missing_citations",
                "Gemini did not cite any supplied research, so SEEK withheld the answer.",
            ) from exc
        raise _error(
            status.HTTP_502_BAD_GATEWAY,
            "gemini_invalid_citations",
            "Gemini returned no valid citations to the supplied research, so SEEK withheld the answer.",
        ) from exc
    except (AIAnswerStoreError, UsageStoreError) as exc:
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "ai_usage_store_unavailable",
            "AI Answers is temporarily unavailable because its usage ledger could not be accessed.",
        ) from exc


@router.get(
    "/usage",
    response_model=AIAnswerUsageStatusResponse,
    summary="Read SEEK's daily AI-answer request allowance",
)
def ai_answer_usage() -> AIAnswerUsageStatusResponse:
    try:
        usage = get_ai_answer_service().usage()
    except AIAnswerStoreError as exc:
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "ai_usage_store_unavailable",
            "AI-answer usage is temporarily unavailable.",
        ) from exc
    usage["gemini_configured"] = bool(settings.GEMINI_API_KEY.get_secret_value())
    usage["tavily_configured"] = bool(settings.TAVILY_API_KEY.get_secret_value())
    return AIAnswerUsageStatusResponse(**usage)


__all__ = [
    "AIAnswerRequest",
    "AIAnswerResponse",
    "AIAnswerSource",
    "AIAnswerUsageResponse",
    "AIAnswerUsageStatusResponse",
    "ai_answer",
    "ai_answer_usage",
    "router",
]
