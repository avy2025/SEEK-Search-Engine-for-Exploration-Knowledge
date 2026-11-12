"""Offline tests for Tavily live search, budgeting, caching and its API."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.config import settings
from backend.search.tavily import (
    BASIC_SEARCH_CREDITS,
    LiveSearchBudgetExceeded,
    LiveSearchService,
    TavilyProviderError,
    TavilySearchProvider,
    UsageLedger,
)

API_KEY = "tavily-test-secret"


def _provider(handler, *, key: str = API_KEY) -> TavilySearchProvider:
    return TavilySearchProvider(key, transport=httpx.MockTransport(handler))


def _tavily_result(**overrides):
    return {
        "title": "FastAPI",
        "url": "https://fastapi.tiangolo.com/",
        "content": "FastAPI is a modern Python web framework.",
        "score": 0.91,
        "favicon": "https://fastapi.tiangolo.com/img/favicon.png",
        **overrides,
    }


@pytest.mark.asyncio
async def test_provider_sends_basic_search_and_parses_results():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"results": [_tavily_result()]})

    response = await _provider(handler).search(
        "FastAPI docs", include_domains=("fastapi.tiangolo.com",)
    )

    assert seen["url"] == "https://api.tavily.com/search"
    assert seen["body"] == {
        "api_key": API_KEY,
        "query": "FastAPI docs",
        "search_depth": "basic",
        "max_results": 5,
        "topic": "general",
        "include_answer": False,
        "include_raw_content": False,
        "include_favicon": True,
        "include_domains": ["fastapi.tiangolo.com"],
    }
    assert response.results[0].title == "FastAPI"
    assert response.results[0].score == pytest.approx(0.91)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code,expected,credits",
    [
        (401, "authentication_error", 0),
        (429, "rate_limited", 0),
        (432, "credits_exhausted", 0),
        (503, "provider_unavailable", BASIC_SEARCH_CREDITS),
    ],
)
async def test_provider_maps_http_failures_without_exposing_provider_body(
    status_code, expected, credits
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text="private provider response")

    with pytest.raises(TavilyProviderError) as error:
        await _provider(handler).search("query")
    assert error.value.code == expected
    assert error.value.credits_consumed == credits
    assert "private provider response" not in str(error.value)


@pytest.mark.asyncio
async def test_provider_handles_timeout_network_failure_and_empty_results():
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("test timeout")

    with pytest.raises(TavilyProviderError, match="timeout") as timeout:
        await _provider(timeout_handler).search("query")
    assert timeout.value.credits_consumed == BASIC_SEARCH_CREDITS

    def network_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("test network failure")

    with pytest.raises(TavilyProviderError) as network:
        await _provider(network_handler).search("query")
    assert network.value.code == "network_error"

    def empty_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    response = await _provider(empty_handler).search("no matching page")
    assert response.results == ()


def test_usage_ledger_persists_and_resets_by_utc_calendar_month(tmp_path):
    current = [datetime(2026, 11, 12, 12, tzinfo=timezone.utc)]
    path = tmp_path / "usage.sqlite3"
    ledger = UsageLedger(path, allowance=3, clock=lambda: current[0])

    reservation = ledger.reserve()
    ledger.settle(reservation, credits=1, succeeded=True)
    ledger = UsageLedger(path, allowance=3, clock=lambda: current[0])
    assert ledger.usage()["credits_consumed"] == 1
    assert ledger.usage()["successful_searches"] == 1
    assert ledger.usage()["last_successful_search_at"] == current[0].isoformat()

    current[0] += timedelta(days=20)
    assert ledger.usage()["credits_consumed"] == 0
    assert ledger.usage()["successful_searches"] == 0


def test_usage_ledger_reserves_concurrently_without_exceeding_allowance(tmp_path):
    ledger = UsageLedger(tmp_path / "concurrent.sqlite3", allowance=7)

    def consume_one() -> bool:
        try:
            reservation = ledger.reserve()
        except LiveSearchBudgetExceeded:
            return False
        ledger.settle(reservation, credits=1, succeeded=True)
        return True

    with ThreadPoolExecutor(max_workers=16) as pool:
        completed = list(pool.map(lambda _: consume_one(), range(32)))

    assert sum(completed) == 7
    usage = ledger.usage()
    assert usage["credits_consumed"] == 7
    assert usage["successful_searches"] == 7
    assert usage["credits_remaining"] == 0


@pytest.mark.asyncio
async def test_cache_normalizes_queries_and_does_not_consume_extra_credits(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"results": [_tavily_result()]})

    ledger = UsageLedger(tmp_path / "cache.sqlite3")
    service = LiveSearchService(_provider(handler), ledger, cache_ttl_seconds=600)
    first = await service.search("  FastAPI   docs ")
    cached = await service.search("fastapi docs")

    assert len(calls) == 1
    assert first["cached"] is False
    assert cached["cached"] is True
    assert cached["searched_at"] == first["searched_at"]
    assert cached["usage"]["credits_consumed"] == 1


@pytest.mark.asyncio
async def test_usage_report_from_tavily_overrides_the_basic_cost_estimate(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"results": [], "usage": {"credits_used": 2}},
        )

    service = LiveSearchService(
        _provider(handler),
        UsageLedger(tmp_path / "reported-usage.sqlite3", allowance=3),
    )
    response = await service.search("query")
    assert response["usage"]["credits_consumed"] == 2
    assert response["usage"]["credits_remaining"] == 1


@pytest.mark.asyncio
async def test_budget_rejects_before_call_and_missing_key_costs_no_credits(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"results": []})

    ledger = UsageLedger(tmp_path / "budget.sqlite3", allowance=1)
    service = LiveSearchService(_provider(handler), ledger)
    await service.search("one")
    with pytest.raises(LiveSearchBudgetExceeded):
        await service.search("two")
    assert len(calls) == 1

    missing_key_ledger = UsageLedger(tmp_path / "missing-key.sqlite3")
    missing_key_service = LiveSearchService(_provider(handler, key=""), missing_key_ledger)
    with pytest.raises(TavilyProviderError, match="not_configured"):
        await missing_key_service.search("query")
    assert missing_key_ledger.usage()["credits_consumed"] == 0
    assert missing_key_ledger.usage()["failed_searches"] == 1


def _api_service(tmp_path, handler, *, key: str = API_KEY, allowance: int = 900):
    return LiveSearchService(
        _provider(handler, key=key),
        UsageLedger(tmp_path / "api-usage.sqlite3", allowance=allowance),
    )


def test_live_search_api_normalizes_results_filters_domains_and_hides_api_key(
    client: TestClient, monkeypatch, tmp_path
):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"results": [_tavily_result()], "usage": {"credits": 1}}
        )

    monkeypatch.setattr(
        "backend.api.live_search.get_live_search_service",
        lambda: _api_service(tmp_path, handler),
    )
    monkeypatch.setattr(settings, "TAVILY_API_KEY", SecretStr(API_KEY))

    response = client.post(
        "/api/live-search",
        json={
            "query": "  FastAPI   docs ",
            "include_domains": ["FASTAPI.TIANGOLO.COM"],
            "exclude_domains": ["spam.example"],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "FastAPI docs"
    assert data["results"][0]["domain"] == "fastapi.tiangolo.com"
    assert data["results"][0]["url"] == "https://fastapi.tiangolo.com/"
    assert data["results"][0]["snippet"].startswith("FastAPI is")
    assert data["results"][0]["score"] == pytest.approx(0.91)
    assert seen["body"]["include_domains"] == ["fastapi.tiangolo.com"]
    assert seen["body"]["exclude_domains"] == ["spam.example"]
    assert API_KEY not in response.text


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"query": "   "},
        {"query": "q" * 501},
        {"query": "query", "include_domains": ["https://example.com"]},
        {"query": "query", "exclude_domains": ["example.com/path"]},
        {"query": "query", "max_results": 6},
        {"query": "query", "search_depth": "advanced"},
    ],
)
def test_live_search_api_rejects_invalid_requests(client: TestClient, body):
    response = client.post("/api/live-search", json=body)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "status_code,expected_status,expected_code",
    [
        (401, 502, "tavily_authentication_error"),
        (429, 429, "tavily_rate_limited"),
        (432, 429, "tavily_credits_exhausted"),
        (503, 502, "tavily_unavailable"),
    ],
)
def test_live_search_api_returns_explicit_provider_errors(
    client: TestClient,
    monkeypatch,
    tmp_path,
    status_code,
    expected_status,
    expected_code,
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=f"do-not-leak-{API_KEY}")

    monkeypatch.setattr(
        "backend.api.live_search.get_live_search_service",
        lambda: _api_service(tmp_path, handler),
    )
    response = client.post("/api/live-search", json={"query": "query"})
    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == expected_code
    assert API_KEY not in response.text
    assert "do-not-leak" not in response.text


def test_live_search_usage_endpoint_discloses_only_budget_state(
    client: TestClient, monkeypatch, tmp_path
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    monkeypatch.setattr(
        "backend.api.live_search.get_live_search_service",
        lambda: _api_service(tmp_path, handler),
    )
    monkeypatch.setattr(settings, "TAVILY_API_KEY", SecretStr(API_KEY))

    response = client.get("/api/live-search/usage")
    assert response.status_code == 200
    assert response.json()["provider_configured"] is True
    assert response.json()["monthly_allowance"] == 900
    assert API_KEY not in response.text
