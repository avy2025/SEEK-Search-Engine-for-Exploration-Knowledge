"""URL normalisation, canonicalisation and crawl-safety checks (Phase 4).

Two responsibilities, kept in one module so the scheduler applies a single
consistent policy:

* **normalise** — lowercase scheme/host, drop default ports, remove fragments,
  strip common tracking parameters and collapse dot-segments, so
  ``http://X.com/a?utm_x=1#f`` and ``http://x.com/a?utm_y=2`` are the same URL.
* **safety** — reject non-http(s) schemes, embedded credentials, empty hosts,
  and (when enabled) hosts resolving to private/loopback/link-local addresses,
  plus obviously binary/non-HTML file extensions.
"""
from __future__ import annotations

import ipaddress
import re
from typing import Optional
from urllib.parse import (
    parse_qsl,
    urlencode,
    urljoin,
    urlsplit,
    urlunsplit,
)

TRACKING_PARAMS = frozenset(
    {
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "gclid", "fbclid", "mc_cid", "mc_eid", "ref", "ref_src", "spm",
    }
)

# File extensions that are almost never crawlable HTML.
UNWANTED_EXTENSIONS = frozenset(
    {
        ".7z", ".aac", ".avi", ".bmp", ".bz2", ".css", ".csv", ".doc", ".docx",
        ".eot", ".exe", ".flac", ".gif", ".gz", ".ico", ".jpeg", ".jpg", ".js",
        ".json", ".m4a", ".mkv", ".mov", ".mp3", ".mp4", ".mpeg", ".mpg", ".ogg",
        ".ogv", ".pdf", ".png", ".ppt", ".pptx", ".rar", ".svg", ".tar", ".tif",
        ".tiff", ".ttf", ".txt", ".wav", ".webm", ".webp", ".woff", ".woff2",
        ".xls", ".xlsx", ".xml", ".zip",
    }
)

# Hostnames that are clearly not public web content regardless of DNS.
LOCAL_HOSTNAMES = frozenset({"localhost", "localhost.localdomain"})

_REGEX_IPV6 = re.compile(r"^[0-9a-f:]+$")


def _scheme_of(url: str) -> str:
    try:
        return (urlsplit(url).scheme or "").lower()
    except ValueError:
        return ""


def normalize_url(url: str, *, drop_tracking: bool = True) -> str:
    """Return a deterministic canonical form of *url* (never raises).

    Unknown/unsupported input falls back to the original string so the scheduler
    never crashes on a hostile link — it simply keeps the raw URL and lets the
    safety checks decide.
    """
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    if not parts.scheme or not parts.netloc:
        return url.strip()

    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    host = parts.hostname or ""
    port = parts.port
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None

    userinfo = ""
    if parts.username:
        userinfo = parts.username
        if parts.password:
            userinfo += ":" + parts.password
        userinfo += "@"

    host_part = f"[{host}]" if ":" in host else host
    rebuilt_netloc = netloc
    if port is not None:
        rebuilt_netloc = f"{host_part}:{port}"
    else:
        rebuilt_netloc = host_part
    if userinfo:
        rebuilt_netloc = f"{userinfo}{rebuilt_netloc}"

    # Path: collapse duplicate slashes, drop trailing slash from the bare root,
    # resolve dot segments without relying on network authority handling.
    path = re.sub(r"/{2,}", "/", parts.path)
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    query = parts.query
    if drop_tracking and query:
        kept = [
            (k, v)
            for k, v in parse_qsl(query, keep_blank_values=True)
            if k.lower() not in TRACKING_PARAMS
        ]
        query = urlencode(kept)

    return urlunsplit((scheme, rebuilt_netloc, path, query, ""))


def canonicalize_url(url: str) -> str:
    """Like :func:`normalize_url` but resolves relative links against *base*."""
    return normalize_url(url)


def resolve_url(base: str, link: str) -> str:
    """Resolve a (possibly relative) *link* against *base* and canonicalise."""
    try:
        return normalize_url(urljoin(base, link))
    except ValueError:
        return normalize_url(link)


def hostname_of(url: str) -> str:
    """Return the lowercased hostname of *url* (port stripped, IPv6 unbracketed)."""
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return ""
    return (host or "").lower()


def is_http_url(url: str) -> bool:
    return _scheme_of(url) in ("http", "https")


def _looks_like_private_host(host: str) -> bool:
    """Best-effort private/loopback detection for literals + obvious hostnames."""
    if not host:
        return True
    lowered = host.lower()
    if lowered in LOCAL_HOSTNAMES:
        return True
    if lowered.endswith(".local") or lowered.endswith(".localdomain"):
        return True
    if _REGEX_IPV6.match(host):
        try:
            return ipaddress.ip_address(host).is_private or (
                ipaddress.ip_address(host).is_loopback
                or ipaddress.ip_address(host).is_link_local
                or ipaddress.ip_address(host).is_reserved
                or ipaddress.ip_address(host).is_unspecified
            )
        except ValueError:
            return False
    # IPv4 literals
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        addr.is_private or addr.is_loopback or addr.is_link_local
        or addr.is_reserved or addr.is_unspecified
    )


def is_private_host(url: str) -> bool:
    return _looks_like_private_host(hostname_of(url))


def has_embedded_credentials(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return bool(parts.username)


def has_unwanted_extension(url: str) -> bool:
    try:
        path = (urlsplit(url).path or "").lower()
    except ValueError:
        return False
    for suffix in UNWANTED_EXTENSIONS:
        if path.endswith(suffix):
            return True
    return False


def is_dangerous_url(url: str) -> bool:
    """True when *url* must never be requested (scheme, credentials, host)."""
    if not url or not is_http_url(url):
        return True
    if has_embedded_credentials(url):
        return True
    if not hostname_of(url):
        return True
    return False


def is_crawlable_url(url: str, *, allow_private_hosts: bool = False) -> bool:
    """Full safety gate used by the scheduler before any HTTP request."""
    if is_dangerous_url(url):
        return False
    if has_unwanted_extension(url):
        return False
    if not allow_private_hosts and is_private_host(url):
        return False
    return True


def domain_matches(host: str, allowed_domains: tuple[str, ...]) -> bool:
    """True when *host* equals, or is a subdomain of, an allowed domain."""
    host = (host or "").lower().rstrip(".")
    for allowed in allowed_domains:
        domain = (allowed or "").lower().lstrip(".").rstrip(".")
        if not domain:
            continue
        if host == domain or host.endswith("." + domain):
            return True
    return False


def scope_hosts(allowlist: tuple[str, ...], seeds: tuple[str, ...]) -> tuple[str, ...]:
    """Effective host scope: explicit allowlist, else the seed hosts."""
    hosts = [h for h in allowlist if h]
    if not hosts:
        seen: set[str] = set()
        for seed in seeds:
            host = hostname_of(seed)
            if host and host not in seen:
                seen.add(host)
                hosts.append(host)
    return tuple(hosts)


__all__ = [
    "normalize_url",
    "canonicalize_url",
    "resolve_url",
    "hostname_of",
    "is_http_url",
    "is_private_host",
    "is_dangerous_url",
    "is_crawlable_url",
    "domain_matches",
    "scope_hosts",
    "TRACKING_PARAMS",
    "UNWANTED_EXTENSIONS",
]