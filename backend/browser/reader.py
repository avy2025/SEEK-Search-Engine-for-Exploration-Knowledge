"""Bounded public-web retrieval and structured article extraction."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl
from collections.abc import Iterable
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpcore
import httpx
from bs4 import BeautifulSoup

from backend.crawler.extract import STRIP_TAGS, extract_title

MAX_PAGE_BYTES = 1_000_000
MAX_ROBOTS_BYTES = 256_000
MAX_READER_CHARS = 100_000
MAX_REDIRECTS = 5
REQUEST_TIMEOUT_SECONDS = 8.0
USER_AGENT = "SEEK-Reader/1.0"
_ALLOWED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif")


class ReaderError(Exception):
    """Expected reader failure with a safe user-facing message."""

    def __init__(self, code: str, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ReaderBlock:
    type: str
    text: str = ""
    level: int | None = None
    ordered: bool = False
    items: tuple[str, ...] = ()
    src: str = ""
    alt: str = ""


@dataclass(frozen=True)
class ReaderPage:
    title: str
    site_name: str
    url: str
    published_at: str | None
    blocks: tuple[ReaderBlock, ...]


def validate_reader_url(url: str) -> str:
    """Normalize a destination and reject unsafe URL forms before resolution."""
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise ReaderError("invalid_url", "Enter a valid public HTTP or HTTPS URL.", 422)
    try:
        parts = urlsplit(url.strip())
        port = parts.port
        host = parts.hostname
    except ValueError as exc:
        raise ReaderError("invalid_url", "Enter a valid public HTTP or HTTPS URL.", 422) from exc

    scheme = parts.scheme.lower()
    if (
        scheme not in {"http", "https"}
        or not host
        or parts.username is not None
        or parts.password is not None
        or (scheme == "http" and port not in (None, 80))
        or (scheme == "https" and port not in (None, 443))
        or any(ord(char) < 32 or ord(char) == 127 for char in url)
    ):
        raise ReaderError("invalid_url", "Only public HTTP and HTTPS pages can be read.", 422)

    host = host.rstrip(".").lower()
    if not host or host in {"metadata", "metadata.google.internal"}:
        raise ReaderError("blocked_destination", "This destination is not available in Reader Mode.", 422)
    normalized_netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        normalized_netloc = f"{normalized_netloc}:{port}"
    return urlunsplit((scheme, normalized_netloc, parts.path or "/", parts.query, ""))


async def resolve_public_addresses(host: str, port: int) -> list[tuple[int, str]]:
    """Resolve every candidate and refuse mixed or non-public DNS answers."""
    try:
        literal = ipaddress.ip_address(host)
        addresses = [(socket.AF_INET6 if literal.version == 6 else socket.AF_INET, str(literal))]
    except ValueError:
        try:
            loop = asyncio.get_running_loop()
            records = await asyncio.wait_for(
                loop.getaddrinfo(host, port, type=socket.SOCK_STREAM),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except (OSError, TimeoutError, UnicodeError) as exc:
            raise ReaderError("destination_unavailable", "The website could not be reached.") from exc
        addresses = []
        for family, _socktype, _proto, _canonname, sockaddr in records:
            if family in (socket.AF_INET, socket.AF_INET6):
                addresses.append((family, sockaddr[0]))

    if not addresses:
        raise ReaderError("destination_unavailable", "The website could not be reached.")

    for _family, address in addresses:
        try:
            public = ipaddress.ip_address(address).is_global
        except ValueError:
            public = False
        if not public:
            raise ReaderError(
                "blocked_destination",
                "Reader Mode cannot access local, private, or reserved network addresses.",
                403,
            )
    return addresses


class _PinnedStream(httpcore.AsyncNetworkStream):
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        operation = self._reader.read(max_bytes)
        try:
            return await asyncio.wait_for(operation, timeout) if timeout is not None else await operation
        except TimeoutError as exc:
            raise httpcore.ReadTimeout("Read timed out.") from exc

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self._writer.write(buffer)
        operation = self._writer.drain()
        try:
            if timeout is not None:
                await asyncio.wait_for(operation, timeout)
            else:
                await operation
        except TimeoutError as exc:
            raise httpcore.WriteTimeout("Write timed out.") from exc

    async def aclose(self) -> None:
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except OSError:
            pass

    async def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> _PinnedStream:
        operation = self._writer.start_tls(
            ssl_context,
            server_hostname=server_hostname,
            ssl_handshake_timeout=timeout,
        )
        try:
            if timeout is not None:
                await asyncio.wait_for(operation, timeout)
            else:
                await operation
        except TimeoutError as exc:
            raise httpcore.ConnectTimeout("TLS handshake timed out.") from exc
        return self

    def get_extra_info(self, info: str) -> object:
        if info == "ssl_object":
            return self._writer.get_extra_info("ssl_object")
        if info == "client_addr":
            return self._writer.get_extra_info("sockname")
        if info == "server_addr":
            return self._writer.get_extra_info("peername")
        if info == "socket":
            return self._writer.get_extra_info("socket")
        return None


class _PublicNetworkBackend(httpcore.AsyncNetworkBackend):
    """Connect only to the same resolved public IPs that were validated."""

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[tuple[int, int, int | bytes]] | None = None,
    ) -> _PinnedStream:
        addresses = await resolve_public_addresses(host, port)
        last_error: OSError | None = None
        for family, address in addresses:
            try:
                operation = asyncio.open_connection(
                    host=address,
                    port=port,
                    family=family,
                    local_addr=(local_address, 0) if local_address else None,
                )
                try:
                    reader, writer = (
                        await asyncio.wait_for(operation, timeout)
                        if timeout is not None
                        else await operation
                    )
                except TimeoutError as exc:
                    raise httpcore.ConnectTimeout("Connection timed out.") from exc
                raw_socket = writer.get_extra_info("socket")
                if raw_socket is not None and socket_options:
                    for level, option, value in socket_options:
                        raw_socket.setsockopt(level, option, value)
                return _PinnedStream(reader, writer)
            except OSError as exc:
                last_error = exc
        raise httpcore.ConnectError("Unable to connect to the validated public address.") from last_error

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[tuple[int, int, int | bytes]] | None = None,
    ) -> _PinnedStream:
        raise httpcore.ConnectError("Unix sockets are not supported by Reader Mode.")

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class _PinnedTransport(httpx.AsyncBaseTransport):
    """HTTPX adapter backed by a DNS-pinning HTTP Core connection pool."""

    def __init__(self) -> None:
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            max_connections=4,
            max_keepalive_connections=0,
            http2=False,
            network_backend=_PublicNetworkBackend(),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        core_response = await self._pool.handle_async_request(core_request)

        class ResponseStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                async for chunk in core_response.stream:
                    yield chunk

            async def aclose(self) -> None:
                await core_response.stream.aclose()

        return httpx.Response(
            status_code=core_response.status,
            headers=core_response.headers,
            stream=ResponseStream(),
            extensions=core_response.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


async def _read_limited_response(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_bytes: int,
    allowed_types: tuple[str, ...],
) -> tuple[int, str, bytes, str]:
    try:
        async with client.stream("GET", url) as response:
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if response.status_code in {301, 302, 303, 307, 308}:
                return response.status_code, content_type, b"", response.headers.get("location", "")
            if response.status_code >= 400:
                return response.status_code, content_type, b"", ""
            if not any(content_type == allowed or content_type.endswith("+html") for allowed in allowed_types):
                raise ReaderError("unsupported_content", "This website did not return a readable HTML page.")
            if response.headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
                raise ReaderError("unsupported_content", "This website returned an unsupported encoded page.")
            content_length = response.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        raise ReaderError("page_too_large", "This page is too large to open in Reader Mode.")
                except ValueError:
                    pass
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_raw():
                total += len(chunk)
                if total > max_bytes:
                    raise ReaderError("page_too_large", "This page is too large to open in Reader Mode.")
                chunks.append(chunk)
            return response.status_code, content_type, b"".join(chunks), ""
    except (httpx.TimeoutException, httpcore.TimeoutException) as exc:
        raise ReaderError("reader_timeout", "The website took too long to respond.", 504) from exc
    except ReaderError:
        raise
    except (
        httpx.HTTPError,
        httpcore.NetworkError,
        httpcore.ProtocolError,
        httpcore.LocalProtocolError,
        OSError,
        TimeoutError,
    ) as exc:
        raise ReaderError("reader_unavailable", "The website could not be loaded in Reader Mode.") from exc


async def _get_with_validated_redirects(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_bytes: int,
    allowed_types: tuple[str, ...],
    before_request: Callable[[str], Awaitable[None]] | None = None,
) -> tuple[str, str, bytes, int]:
    current = validate_reader_url(url)
    for redirect_count in range(MAX_REDIRECTS + 1):
        if before_request is not None:
            await before_request(current)
        parts = urlsplit(current)
        await resolve_public_addresses(parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80))
        status_code, content_type, body, location = await _read_limited_response(
            client,
            current,
            max_bytes=max_bytes,
            allowed_types=allowed_types,
        )
        if status_code in {301, 302, 303, 307, 308}:
            if redirect_count == MAX_REDIRECTS or not location:
                raise ReaderError("too_many_redirects", "The website redirected too many times.")
            current = validate_reader_url(urljoin(current, location))
            continue
        if status_code in {401, 403}:
            return current, content_type, body, status_code
        if status_code >= 400:
            raise ReaderError("reader_unavailable", "The website could not be loaded in Reader Mode.")
        return current, content_type, body, status_code
    raise ReaderError("too_many_redirects", "The website redirected too many times.")


def _published_date(soup: BeautifulSoup) -> str | None:
    for selector, attribute in (
        ('meta[property="article:published_time"]', "content"),
        ('meta[property="og:published_time"]', "content"),
        ('meta[name="date"]', "content"),
        ('meta[name="pubdate"]', "content"),
        ('meta[itemprop="datePublished"]', "content"),
        ("time[datetime]", "datetime"),
    ):
        node = soup.select_one(selector)
        raw = node.get(attribute, "").strip() if node else ""
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed.date().isoformat()
        except ValueError:
            continue
    return None


def extract_reader_page(html: str, url: str) -> ReaderPage:
    """Extract safe text and image references; never return source HTML."""
    soup = BeautifulSoup(html, "html.parser")
    title = extract_title(soup, url)
    published_at = _published_date(soup)
    root = soup.find("article") or soup.find("main") or soup.body or soup
    for tag in root.find_all(list(STRIP_TAGS)):
        tag.decompose()

    final_host = (urlsplit(url).hostname or "").lower()
    blocks: list[ReaderBlock] = []
    character_count = 0
    for node in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "img"]):
        if node.name in {"ul", "ol"}:
            items = tuple(
                " ".join(item.stripped_strings)[:2000]
                for item in node.find_all("li", recursive=False)
                if " ".join(item.stripped_strings)
            )
            text = "\n".join(items)
            if items:
                blocks.append(ReaderBlock(type="list", ordered=node.name == "ol", items=items))
                character_count += len(text)
        elif node.name == "img":
            raw_src = node.get("src") or node.get("data-src") or ""
            image_url = urljoin(url, raw_src)
            try:
                image_parts = urlsplit(image_url)
            except ValueError:
                continue
            extension = image_parts.path.lower().rsplit(".", 1)
            same_site = (image_parts.hostname or "").lower() == final_host
            page_parts = urlsplit(url)
            try:
                image_port = image_parts.port or (443 if image_parts.scheme == "https" else 80)
                page_port = page_parts.port or (443 if page_parts.scheme == "https" else 80)
            except ValueError:
                continue
            if (
                same_site
                and image_parts.scheme == page_parts.scheme
                and image_port == page_port
                and image_parts.username is None
                and image_parts.password is None
                and len(extension) == 2
                and f".{extension[-1]}" in _ALLOWED_IMAGE_EXTENSIONS
            ):
                blocks.append(
                    ReaderBlock(type="image", src=image_url, alt=(node.get("alt") or "")[:300])
                )
        else:
            text = " ".join(node.stripped_strings).strip()
            if not text:
                continue
            text = text[:4000]
            character_count += len(text)
            if node.name.startswith("h"):
                blocks.append(ReaderBlock(type="heading", text=text, level=int(node.name[1])))
            else:
                blocks.append(ReaderBlock(type="paragraph", text=text))
        if character_count >= MAX_READER_CHARS:
            break

    return ReaderPage(
        title=title[:300],
        site_name=final_host,
        url=url,
        published_at=published_at,
        blocks=tuple(blocks),
    )


async def read_public_page(url: str) -> ReaderPage:
    """Fetch one public page with robots checks and bounded, pinned requests."""
    normalized = validate_reader_url(url)
    timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS, connect=3.0)
    async with httpx.AsyncClient(
        transport=_PinnedTransport(),
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity",
        },
    ) as client:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS * 2 + 2):
                checked_origins: set[tuple[str, str]] = set()

                async def ensure_robots_allowed(destination: str) -> None:
                    parts = urlsplit(destination)
                    origin = (parts.scheme, parts.netloc.lower())
                    if origin in checked_origins:
                        return
                    robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
                    try:
                        _robots_final, _robots_type, robots_body, robots_status = (
                            await _get_with_validated_redirects(
                                client,
                                robots_url,
                                max_bytes=MAX_ROBOTS_BYTES,
                                allowed_types=("", "text/plain", "text/html"),
                            )
                        )
                    except ReaderError as exc:
                        if exc.code in {"blocked_destination", "invalid_url"}:
                            raise
                        if exc.code in {"page_too_large", "unsupported_content", "too_many_redirects"}:
                            raise ReaderError(
                                "robots_unavailable",
                                "SEEK could not safely read this website’s robots.txt policy.",
                                403,
                            ) from exc
                        robots_body, robots_status = b"", 0
                    if robots_status in {401, 403}:
                        raise ReaderError(
                            "robots_disallowed",
                            "The website’s robots.txt does not allow Reader Mode access.",
                            403,
                        )
                    if robots_body:
                        policy = RobotFileParser()
                        policy.set_url(robots_url)
                        policy.parse(robots_body.decode("utf-8", errors="replace").splitlines())
                        if not policy.can_fetch(USER_AGENT, destination):
                            raise ReaderError(
                                "robots_disallowed",
                                "The website’s robots.txt does not allow Reader Mode access.",
                                403,
                            )
                    checked_origins.add(origin)

                await ensure_robots_allowed(normalized)
                final_url, _content_type, body, status_code = await _get_with_validated_redirects(
                    client,
                    normalized,
                    max_bytes=MAX_PAGE_BYTES,
                    allowed_types=("text/html", "application/xhtml+xml"),
                    before_request=ensure_robots_allowed,
                )
                if status_code in {401, 403}:
                    raise ReaderError(
                        "access_restricted",
                        "The website does not allow SEEK Reader Mode to access this page.",
                        403,
                    )
        except TimeoutError as exc:
            raise ReaderError("reader_timeout", "The website took too long to respond.", 504) from exc

    page = extract_reader_page(body.decode("utf-8", errors="replace"), final_url)
    if not page.blocks:
        raise ReaderError("no_readable_content", "No readable article content was found on this page.")
    return page


__all__ = [
    "ReaderBlock",
    "ReaderError",
    "ReaderPage",
    "extract_reader_page",
    "read_public_page",
    "resolve_public_addresses",
    "validate_reader_url",
]
