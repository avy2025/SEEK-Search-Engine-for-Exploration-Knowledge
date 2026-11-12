"""Dedicated API for live internet search through Tavily."""
from __future__ import annotations

import re
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.config import settings
from backend.search.tavily import (
    LiveSearchBudgetExceeded,
    TavilyProviderError,
    UsageStoreError,
    get_live_search_service,
)

router = APIRouter(prefix="/api/live-search", tags=["live internet search"])

_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)"
    r"(?:\.(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?))*$"
)


class LiveSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=500)
    include_domains: list[str] = Field(default_factory=list, max_length=300)
    exclude_domains: list[str] = Field(default_factory=list, max_length=150)
    max_results: int = Field(default=5, ge=1, le=5)

    @field_validator("query", mode="before")
    @classmethod
    def normalize_query(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = " ".join(value.split())
            if not value:
                raise ValueError("query must not be blank")
        return value

    @field_validator("include_domains", "exclude_domains")
    @classmethod
    def normalize_domains(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            if not isinstance(value, str):
                raise ValueError("domains must be hostnames, not URLs")
            try:
                domain = value.strip().rstrip(".").encode("idna").decode("ascii").lower()
            except UnicodeError as exc:
                raise ValueError("invalid domain hostname") from exc
            if not _DOMAIN_RE.fullmatch(domain):
                raise ValueError("domains must be hostnames, not URLs")
            if domain not in normalized:
                normalized.append(domain)
        return normalized


class LiveSearchResultResponse(BaseModel):
    title: str
    url: str
    domain: str
    snippet: str
    score: float | None
    favicon: str | None


class LiveSearchUsageResponse(BaseModel):
    month: str
    monthly_allowance: int
    credits_consumed: int
    credits_remaining: int
    successful_searches: int
    failed_searches: int
    last_successful_search_at: str | None


class LiveSearchUsageStatusResponse(LiveSearchUsageResponse):
    provider_configured: bool


class LiveSearchResponse(BaseModel):
    mode: Literal["live"] = "live"
    query: str
    total: int
    results: list[LiveSearchResultResponse]
    took_ms: float
    cached: bool
    searched_at: str
    usage: LiveSearchUsageResponse
    message: str


def _provider_error(error: TavilyProviderError) -> HTTPException:
    messages = {
        "not_configured": (
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "tavily_not_configured",
            "Live internet search is not configured. Add TAVILY_API_KEY to the backend environment.",
        ),
        "authentication_error": (
            status.HTTP_502_BAD_GATEWAY,
            "tavily_authentication_error",
            "Tavily rejected the configured API key. Check the key in the backend environment.",
        ),
        "rate_limited": (
            status.HTTP_429_TOO_MANY_REQUESTS,
            "tavily_rate_limited",
            "Tavily is rate limiting requests. Please wait before trying again.",
        ),
        "credits_exhausted": (
            status.HTTP_429_TOO_MANY_REQUESTS,
            "tavily_credits_exhausted",
            "Tavily reports that its account credits are exhausted. Check the free-plan account limits.",
        ),
        "timeout": (
            status.HTTP_504_GATEWAY_TIMEOUT,
            "tavily_timeout",
            "Tavily did not respond before the configured timeout.",
        ),
        "network_error": (
            status.HTTP_502_BAD_GATEWAY,
            "tavily_network_error",
            "SEEK could not connect to Tavily.",
        ),
    }
    http_status, code, message = messages.get(
        error.code,
        (
            status.HTTP_502_BAD_GATEWAY,
            "tavily_unavailable",
            "Tavily is temporarily unavailable. No local-index fallback was used.",
        ),
    )
    return HTTPException(
        status_code=http_status,
        detail={"code": code, "message": message},
    )


@router.post(
    "",
    name="live_search",
    summary="Search the live internet through Tavily",
    response_model=LiveSearchResponse,
)
async def live_search(request: LiveSearchRequest) -> LiveSearchResponse:
    """Search Tavily without crawling or changing SEEK's local indexes."""
    service = get_live_search_service()
    try:
        result = await service.search(
            request.query,
            include_domains=tuple(request.include_domains),
            exclude_domains=tuple(request.exclude_domains),
            max_results=request.max_results,
        )
        return LiveSearchResponse(**result)
    except LiveSearchBudgetExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "seek_monthly_budget_exhausted",
                "message": (
                    "SEEK has reached its 900-credit monthly live-search budget. "
                    "The budget resets at the start of next month."
                ),
                "usage": exc.usage,
            },
        ) from exc
    except TavilyProviderError as exc:
        raise _provider_error(exc) from exc
    except UsageStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "usage_store_unavailable",
                "message": "Live search is temporarily unavailable because its usage ledger could not be accessed.",
            },
        ) from exc


@router.get(
    "/usage",
    name="live_search_usage",
    summary="Read SEEK's live-search budget",
    response_model=LiveSearchUsageStatusResponse,
)
def live_search_usage() -> LiveSearchUsageStatusResponse:
    """Return SEEK's application-side monthly budget; never returns credentials."""
    try:
        usage = get_live_search_service().usage()
    except UsageStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "usage_store_unavailable",
                "message": "Live-search usage is temporarily unavailable.",
            },
        ) from exc
    usage["provider_configured"] = bool(settings.TAVILY_API_KEY.get_secret_value())
    return LiveSearchUsageStatusResponse(**usage)


__all__ = [
    "LiveSearchRequest",
    "LiveSearchResponse",
    "LiveSearchResultResponse",
    "LiveSearchUsageResponse",
    "LiveSearchUsageStatusResponse",
    "live_search",
    "live_search_usage",
    "router",
]
