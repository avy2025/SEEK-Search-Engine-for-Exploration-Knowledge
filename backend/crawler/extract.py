"""Main-text extraction from HTML pages (Phase 4).

A deliberately conservative extractor built on BeautifulSoup — no external ML
or paid service. It removes navigation chrome (script/style/nav/header/footer/
aside/form/noscript/svg), collapses whitespace and returns the visible paragraph
text plus a usable ``<title>`` fallback chain.

``chunk_text`` splits long pages into fixed-size non-overlapping segments with a
small tail guard, which future semantic-search stages can index independently.
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional

from bs4 import BeautifulSoup

STRIP_TAGS = frozenset(
    {
        "script", "style", "noscript", "svg", "nav", "header", "footer",
        "aside", "form", "button", "iframe", "canvas", "audio", "video",
        "object", "embed", "template",
    }
)

_WS_RE = re.compile(r"[ \t\r\f\v]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")


def extract_title(soup: BeautifulSoup, url: str) -> str:
    raw = soup.title.get_text(" ", strip=True) if soup.title else ""
    if raw:
        return raw.strip()
    h1 = soup.h1
    if h1:
        raw = h1.get_text(" ", strip=True)
        if raw:
            return raw.strip()
    from backend.crawler.url import hostname_of
    return hostname_of(url)


def extract_text(html: str, url: str = "", *, max_chars: int = 200_000) -> tuple[str, str]:
    """Return ``(title, main_text)`` extracted from *html*.

    *title* prefers <title>, falls back to <h1>, then the URL's hostname.
    *main_text* is the visible text of the non-chrome region, whitespace-fixed,
    hard-truncated to *max_chars* characters.
    """
    soup = BeautifulSoup(html, "html.parser")
    title = extract_title(soup, url)
    for tag in list(soup.find_all(True)):
        if tag.name in STRIP_TAGS:
            tag.decompose()

    text = soup.get_text("\n")
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            lines.append(_WS_RE.sub(" ", line))
    cleaned = _MULTI_NL_RE.sub("\n\n", "\n".join(lines)).strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]
    return title, cleaned


def hash_text(text: str) -> str:
    """Deterministic content hash (dedup key for crawled documents)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_text(text: str, *, size: int = 1500) -> tuple[str, ...]:
    """Split *text* into fixed-size non-overlapping chunks (last may be short)."""
    if not text:
        return ()
    size = max(64, int(size))
    return tuple(text[start : start + size] for start in range(0, len(text), size))


__all__ = ["extract_text", "extract_title", "hash_text", "chunk_text", "STRIP_TAGS"]