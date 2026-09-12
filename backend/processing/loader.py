"""Corpus loader for the SEEK Phase 2 sample corpus.

Reads every ``*.md`` file under :data:`backend.config.settings.SAMPLE_CORPUS_DIR`
in **deterministic filename-sorted order**, parses the small YAML-ish front-matter
(``title:`` / optional ``tags:`` handled as plain text lines — we deliberately do
**not** pull in PyYAML just for this), normalises the body with
:func:`backend.processing.tokenizer.normalize` and emits
:class:`~backend.processing.models.ProcessedDocument` values.

Determinism contract
--------------------
* Files are enumerated with ``sorted()`` on their ``Path`` so a fixed seed set of
  files always yields the identical index, independent of filesystem order.
* ``content_hash`` is SHA-256 over the *normalised* content — used for
  deduplication against the database (``unique=True`` on ``content_hash``).
* Only ``data/sample_corpus/**`` (committed, project-owned) is scanned — never the
  potentially huge user areas.
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from backend.config import settings
from backend.processing.models import ProcessedDocument
from backend.processing.tokenizer import STOPWORDS, normalize, tokenize

logger = logging.getLogger("seek.processing.loader")

# Line-based YAML-ish front-matter (no external dependency).
FRONTMATTER_RE = re.compile(r"^---\s*$")
KEY_VALUE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$")

MARKDOWN_SHORTCUTS = ("#", "##", "###", ">")

_skip = {"index.md", "readme.md", "manifest.md"}
SKIP_FILENAMES = frozenset(_skip)


@dataclass(frozen=True)
class DocumentSource:
    """A corpus location that was successfully parsed into a document."""

    document_id: str
    title: str
    source: str  # absolute path (for API `source` field)
    raw_heading: str = ""  # first markdown heading, used by snippet logic


def _read_meta(path: Path) -> DocumentSource:
    """Extract title + document_id from *path*'s front-matter / filename."""
    raw = path.read_text(encoding="utf-8")
    title = ""
    in_front = False
    for line in raw.splitlines():
        if FRONTMATTER_RE.match(line):
            in_front = not in_front
            continue
        if in_front:
            m = KEY_VALUE_RE.match(line)
            if m and m.group(1).lower() == "title":
                title = m.group(2).strip().strip("'\"")
                break
    if not title:
        title = path.stem.replace("_", " ").title()
    document_id = path.stem
    return DocumentSource(
        document_id=document_id,
        title=title,
        source=str(path.resolve()),
        raw_heading=(raw.splitlines() or [""])[0].lstrip("# ").strip(),
    )


def _strip_frontmatter(raw: str) -> str:
    """Return *raw* with its leading ``---...---`` block removed."""
    lines = raw.splitlines()
    if lines and FRONTMATTER_RE.match(lines[0]):
        end = None
        for idx in range(1, len(lines)):
            if FRONTMATTER_RE.match(lines[idx]):
                end = idx
                break
        if end is not None:
            return "\n".join(lines[end + 1 :])
    return raw


def load_corpus(
    corpus_dir: str | Path | None = None,
    *,
    dedupe: bool = True,
) -> list[ProcessedDocument]:
    """Load, normalise and tokenise the whole corpus.

    Returns a deterministic list of :class:`ProcessedDocument` sorted by
    ``document_id``. Files whose content is empty after stripping stop-words are
    skipped. When ``dedupe`` is true, identical ``content_hash`` values collapse
    to the first occurrence (filename-sorted), keeping the index lean.
    """
    root = Path(corpus_dir or settings.SAMPLE_CORPUS_DIR).resolve()
    documents: list[ProcessedDocument] = []
    seen_hashes: set[str] = set()

    if not root.is_dir():
        logger.warning("Corpus directory not found: %s", root)
        return documents

    # Deterministic: *all* .md files sorted by relative path.
    files = sorted(root.rglob("*.md"), key=lambda p: p.relative_to(root).as_posix())
    for path in files:
        if path.stem.lower() in SKIP_FILENAMES:
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            logger.warning("Could not read corpus file: %s", path)
            continue
        meta = _read_meta(path)
        content = _strip_frontmatter(raw).strip()
        if not content:
            continue
        norm = normalize(content)
        content_hash = hashlib.sha256(norm.encode("utf-8")).hexdigest()
        if dedupe and content_hash in seen_hashes:
            continue
        seen_hashes.add(content_hash)
        tokens = tokenize(content)
        if not tokens:
            continue
        documents.append(
            ProcessedDocument(
                document_id=meta.document_id,
                title=meta.title,
                content=content,
                source=meta.source,
                tokens=tuple(tokens),
                content_hash=content_hash,
            )
        )

    logger.info("Loaded %d documents from %s", len(documents), root)
    return documents
