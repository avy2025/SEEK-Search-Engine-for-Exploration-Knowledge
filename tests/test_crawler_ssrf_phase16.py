from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
from pathlib import Path

import httpx

from backend.browser import reader
from backend.browser.reader import ReaderError
from backend.crawler.fetcher import ERR_BLOCKED, fetch
from backend.crawler.url import is_crawlable_url

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_reader_can_be_imported_before_the_crawler_package():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import backend.browser.reader; "
                "from backend.crawler import CrawlManager, CrawlStore, get_crawl_manager"
            ),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _mock_client(handler):
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
        trust_env=False,
    )


def test_crawler_dns_private_address_is_rejected_before_request(monkeypatch):
    requests = []

    async def private_address(_host, _port, **_kwargs):
        raise ReaderError(
            "blocked_destination",
            "Reader Mode cannot access local, private, or reserved network addresses.",
            403,
        )

    monkeypatch.setattr(reader, "resolve_public_addresses", private_address)

    async def run():
        def handler(request):
            requests.append(request)
            return httpx.Response(200, request=request)

        async with _mock_client(handler) as client:
            return await fetch(client, "https://rebind.example/")

    result = asyncio.run(run())
    assert result.error_code == ERR_BLOCKED
    assert requests == []


def test_crawler_redirect_to_private_ip_is_rejected_before_second_request(monkeypatch):
    requests = []

    async def validate_address(host, _port, **_kwargs):
        if host == "127.0.0.1":
            raise ReaderError("blocked_destination", "Blocked destination.", 403)
        return [(socket.AF_INET, "93.184.216.34")]

    def handler(request):
        requests.append(request)
        return httpx.Response(
            302,
            headers={"location": "http://127.0.0.1/admin"},
            request=request,
        )

    monkeypatch.setattr(reader, "resolve_public_addresses", validate_address)

    async def run():
        async with _mock_client(handler) as client:
            return await fetch(client, "https://public.example/start")

    result = asyncio.run(run())
    assert result.error_code == ERR_BLOCKED
    assert len(requests) == 1


def test_crawler_redirect_is_checked_against_scope_before_request(monkeypatch):
    requests = []

    async def public_address(_host, _port, **_kwargs):
        return [(socket.AF_INET, "93.184.216.34")]

    def handler(request):
        requests.append(request)
        return httpx.Response(
            302,
            headers={"location": "https://outside.example/page"},
            request=request,
        )

    async def in_scope(destination):
        if "outside.example" in destination:
            raise ReaderError(
                "out_of_scope_redirect",
                "A redirect left the approved crawl scope.",
                403,
            )

    monkeypatch.setattr(reader, "resolve_public_addresses", public_address)

    async def run():
        async with _mock_client(handler) as client:
            return await fetch(
                client,
                "https://crawl.example/start",
                before_request=in_scope,
            )

    result = asyncio.run(run())
    assert result.error_code == "out_of_scope_redirect"
    assert len(requests) == 1


def test_crawler_url_gate_has_no_private_host_or_nonstandard_port_override():
    assert not is_crawlable_url("http://127.0.0.1/")
    assert not is_crawlable_url("http://localhost:8080/")
    assert not is_crawlable_url("http://example.com:8080/")
    assert not is_crawlable_url("https://metadata.google.internal/")
