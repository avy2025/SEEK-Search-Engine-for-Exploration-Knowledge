from __future__ import annotations

import asyncio
import socket

import httpx
import pytest

from backend.browser import reader
from backend.browser.reader import (
    ReaderBlock,
    ReaderError,
    ReaderPage,
    _PublicNetworkBackend,
    _get_with_validated_redirects,
    _read_limited_response,
    extract_reader_page,
    read_public_page,
    resolve_public_addresses,
    validate_reader_url,
)


class MockBody(httpx.AsyncByteStream):
    def __init__(self, content: bytes):
        self.content = content

    async def __aiter__(self):
        yield self.content

    async def aclose(self):
        return None


def test_reader_url_rejects_non_web_schemes_credentials_and_nonstandard_ports():
    for url in (
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://user:password@example.com/",
        "http://example.com:8080/",
        "https://example.com:8443/",
    ):
        with pytest.raises(ReaderError):
            validate_reader_url(url)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.2", "169.254.169.254", "::1", "fc00::1"])
def test_reader_blocks_private_and_metadata_ip_ranges(address):
    with pytest.raises(ReaderError, match="local, private"):
        asyncio.run(resolve_public_addresses(address, 443))


def test_dns_resolution_rejects_private_addresses_in_mixed_results(monkeypatch):
    async def private_records(*_args, **_kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.4", 443)),
        ]

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: type("Loop", (), {"getaddrinfo": private_records})())
    with pytest.raises(ReaderError, match="local, private"):
        asyncio.run(resolve_public_addresses("mixed.example", 443))


def test_network_backend_connects_to_the_validated_ip_not_hostname(monkeypatch):
    async def public_addresses(_host, _port):
        return [(socket.AF_INET, "8.8.8.8")]

    calls = []
    writer = type(
        "Writer",
        (),
        {
            "get_extra_info": lambda _self, _name: None,
        },
    )()

    async def open_connection(**kwargs):
        calls.append(kwargs)
        return asyncio.StreamReader(), writer

    monkeypatch.setattr(reader, "resolve_public_addresses", public_addresses)
    monkeypatch.setattr(asyncio, "open_connection", open_connection)
    stream = asyncio.run(_PublicNetworkBackend().connect_tcp("example.com", 443, timeout=1))
    assert stream is not None
    assert calls[0]["host"] == "8.8.8.8"
    assert calls[0]["family"] == socket.AF_INET


def test_reader_redirect_to_private_address_is_blocked_before_second_request(monkeypatch):
    requests = []

    async def public_addresses(host, _port):
        if host == "example.com":
            return [(socket.AF_INET, "8.8.8.8")]
        return await resolve_public_addresses(host, 80)

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})

    monkeypatch.setattr(reader, "resolve_public_addresses", public_addresses)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
            await _get_with_validated_redirects(
                client,
                "https://example.com/start",
                max_bytes=1024,
                allowed_types=("text/html",),
            )

    with pytest.raises(ReaderError, match="local, private"):
        asyncio.run(run())
    assert len(requests) == 1


def test_reader_request_timeout_is_reported_without_network():
    def handler(_request):
        raise httpx.ReadTimeout("delayed")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await _read_limited_response(
                client,
                "https://example.com/",
                max_bytes=1024,
                allowed_types=("text/html",),
            )

    with pytest.raises(ReaderError) as error:
        asyncio.run(run())
    assert error.value.code == "reader_timeout"


def test_reader_rejects_oversized_content_before_reading_body():
    def handler(_request):
        return httpx.Response(
            200,
            headers={"content-type": "text/html", "content-length": "2048"},
            content=b"x",
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await _read_limited_response(
                client,
                "https://example.com/",
                max_bytes=100,
                allowed_types=("text/html",),
            )

    with pytest.raises(ReaderError) as error:
        asyncio.run(run())
    assert error.value.code == "page_too_large"


def test_reader_rejects_oversized_streamed_body_without_a_length_header():
    def handler(_request):
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            stream=MockBody(b"x" * 101),
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await _read_limited_response(
                client,
                "https://example.com/",
                max_bytes=100,
                allowed_types=("text/html",),
            )

    with pytest.raises(ReaderError) as error:
        asyncio.run(run())
    assert error.value.code == "page_too_large"


def test_reader_extraction_returns_safe_structured_content_and_same_site_images():
    html = """
      <html><head><title>Article title</title>
      <meta property="article:published_time" content="2025-01-02T03:04:05Z">
      <script>window.secret = 'must not run'</script></head>
      <body><nav>Navigation</nav><main><h1>Heading</h1>
      <p onclick="alert(1)">Readable <strong>paragraph</strong></p>
      <ul><li>First</li><li>Second</li></ul>
      <img src="/photo.jpg" alt="Photo">
      <img src="https://other.example/tracker.png">
      <img src="javascript:alert(1)"></main></body></html>
    """
    page = extract_reader_page(html, "https://example.com/article")
    assert page.title == "Article title"
    assert page.published_at == "2025-01-02"
    assert all(block.type != "script" for block in page.blocks)
    assert all("onclick" not in block.text for block in page.blocks)
    assert not any("window.secret" in block.text for block in page.blocks)
    assert [block.items for block in page.blocks if block.type == "list"] == [
        ("First", "Second")
    ]
    images = [block for block in page.blocks if block.type == "image"]
    assert [(image.src, image.alt) for image in images] == [
        ("https://example.com/photo.jpg", "Photo")
    ]


def test_reader_honors_robots_and_uses_mocked_html_only(monkeypatch):
    requested_paths = []

    def handler(request):
        requested_paths.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                stream=MockBody(b"User-agent: *\nDisallow: /private"),
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
                stream=MockBody(b"<article><h1>Allowed</h1><p>Article body</p></article>"),
        )

    async def public_addresses(_host, _port):
        return [(socket.AF_INET, "8.8.8.8")]

    monkeypatch.setattr(reader, "_PinnedTransport", lambda: httpx.MockTransport(handler))
    monkeypatch.setattr(reader, "resolve_public_addresses", public_addresses)

    page = asyncio.run(read_public_page("https://example.com/article"))
    assert page.title == "Allowed"
    assert "/article" in requested_paths

    requested_paths.clear()
    with pytest.raises(ReaderError) as error:
        asyncio.run(read_public_page("https://example.com/private/article"))
    assert error.value.code == "robots_disallowed"
    assert "/private/article" not in requested_paths


def test_redirected_host_robots_policy_is_checked_before_fetching_its_page(monkeypatch):
    requested = []

    def handler(request):
        requested.append((request.url.host, request.url.path))
        if request.url.host == "example.com" and request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "https://redirected.example/blocked"})
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                stream=MockBody(b"User-agent: *\nDisallow: /blocked"),
            )
        return httpx.Response(200, headers={"content-type": "text/html"}, stream=MockBody(b"<p>Never read</p>"))

    async def public_addresses(_host, _port):
        return [(socket.AF_INET, "8.8.8.8")]

    monkeypatch.setattr(reader, "_PinnedTransport", lambda: httpx.MockTransport(handler))
    monkeypatch.setattr(reader, "resolve_public_addresses", public_addresses)
    with pytest.raises(ReaderError) as error:
        asyncio.run(read_public_page("https://example.com/start"))
    assert error.value.code == "robots_disallowed"
    assert ("redirected.example", "/blocked") not in requested


def test_reader_reports_unavailable_when_a_site_has_no_extractable_article(monkeypatch):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            stream=MockBody(b"<html><script>dynamic page</script></html>"),
        )

    async def public_addresses(_host, _port):
        return [(socket.AF_INET, "8.8.8.8")]

    monkeypatch.setattr(reader, "_PinnedTransport", lambda: httpx.MockTransport(handler))
    monkeypatch.setattr(reader, "resolve_public_addresses", public_addresses)
    with pytest.raises(ReaderError) as error:
        asyncio.run(read_public_page("https://example.com/"))
    assert error.value.code == "no_readable_content"


def test_reader_api_validates_input_and_returns_structured_page(client, monkeypatch):
    import backend.api.browser as browser_api

    private = client.post("/api/browser/read", json={"url": "http://127.0.0.1/"})
    assert private.status_code == 403

    page = ReaderPage(
        title="Example",
        site_name="example.com",
        url="https://example.com/",
        published_at=None,
        blocks=(ReaderBlock(type="paragraph", text="Safe article"),),
    )
    async def fake_read(_url):
        return page

    monkeypatch.setattr(browser_api, "read_public_page", fake_read)
    invalid = client.post("/api/browser/read", json={"url": "javascript:alert(1)"})
    assert invalid.status_code == 422
    response = client.post("/api/browser/read", json={"url": "https://example.com/"})
    assert response.status_code == 200
    assert response.json()["blocks"][0]["text"] == "Safe article"
    assert "html" not in response.json()


def test_reader_extraction_does_not_render_untrusted_html():
    page = extract_reader_page(
        "<article><h1>Title</h1><p>Text</p><script>alert(1)</script></article>",
        "https://example.com/",
    )
    assert "script" not in repr(page).lower()
