"""Phase 9 specialized search modes (web | ai | research | code).

Coverage map (the requirement checklist for this phase):

======  ================================================================
 A      Controlled mode enum + parameter validation
 B      Mode catalog endpoint (``GET /api/search/modes``)
 C      Web Search mode
 D      AI Answers mode (grounded, never fabricated)
 E      Research mode (retrieved evidence vs generated synthesis)
 F      Code Docs mode (indexed corpus only, no external crawler/API)
 G      Invalid mode -> clean HTTP 422
 H      Empty / missing query validation for every mode
 I      Unknown query -> explicit "nothing matched", never invented hits
 J      Index / backend unavailability is reported, never hidden
 K      RAG disabled -> ``unavailable`` with ``answer = null``
 L      Retrieval health wins over the RAG outcome
 M      Backward compatibility of the Phase 2/6/7 contracts + ``/api/answer``
 N      Centralised configuration (no magic numbers in the mode layer)
 O      Frontend URL <-> state round-trip (Node) + static wiring
 P      Orchestration reuses existing services (no duplicated retrieval)
======  ================================================================

Everything here is offline: the BM25 engine is a real
:class:`~backend.search.engine.SearchEngine` over in-memory documents and the
semantic index / RAG provider are deterministic fakes or stubs, so no model,
database or paid API is required.
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.ai.models import (
    AnswerRequest,
    AnswerResponse,
    GenerationMetadata,
    RetrievalMetadata,
    SourceCitation,
)
from backend.config import settings
from backend.db.repository import make_document_repository
from backend.api import mode_orchestrator
from backend.main import app
from backend.processing.models import ProcessedDocument
from backend.search import modes as modes_module
from backend.search.engine import SearchEngine
from backend.search.index_manager import get_index_manager, reset_index_manager
from backend.search.modes import (
    LEGACY_SEARCH_MODES,
    InvalidSearchModeError,
    SearchMode,
    is_documentation_source,
    mode_catalog,
    normalize_mode_param,
    resolve_limit,
    resolve_mode_spec,
    supported_mode_values,
    try_parse_search_mode,
)
from backend.search.models import SearchResponse, SearchResult

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = REPO_ROOT / "frontend"

SPECIALIZED_MODES = ("web", "ai", "research", "code")
ENVELOPE_KEYS = {
    "query",
    "mode",
    "status",
    "total",
    "limit",
    "hits",
    "took_ms",
    "message",
    "answer",
    "sources",
    "metadata",
}


# --------------------------------------------------------------------------- #
# deterministic fixtures
# --------------------------------------------------------------------------- #

_DOC_PY = (
    "Python is a high-level programming language. Use `def greet(name):` to define a "
    "function and then call greet() from your module."
)
_DOC_DOCKER = (
    "Docker packages an application in a container. Run `docker run -it ubuntu` to "
    "start a container image."
)
_DOC_README = (
    "# SearchEngine reference\n\n"
    "The SearchEngine builds a BM25 index. Call create_engine() to load documents.\n\n"
    "```python\n"
    "def create_engine():\n"
    "    return SearchEngine(documents)\n"
    "```\n"
)
_DOC_ML = "Machine learning models learn patterns from training data."


def _doc(document_id: str, title: str, content: str, source: str) -> ProcessedDocument:
    return ProcessedDocument(
        document_id=document_id,
        title=title,
        content=content,
        source=source,
        tokens=tuple(content.lower().split()),
        snippet_tokens=tuple(content.split()),
        content_hash=f"hash-{document_id}",
    )


def _sample_documents() -> list[ProcessedDocument]:
    return [
        _doc("py-1", "Python Guide", _DOC_PY, "https://docs.python.org/tutorial"),
        _doc("dk-1", "Docker Guide", _DOC_DOCKER, "https://docs.docker.com/guide"),
        _doc("rd-1", "SearchEngine reference", _DOC_README, "docs/reference.md"),
        _doc("ml-1", "Machine Learning", _DOC_ML, "https://example.org/ml"),
    ]


class _StubSemanticManager:
    """Minimal stand-in for :class:`SemanticIndexManager`.

    Implements the surface the mode orchestrator uses: the in-memory
    ``document_count``/``loaded`` availability attributes, plus ``status``,
    ``search`` and ``get_document``. No model, no FAISS, no database.
    """

    def __init__(self, documents: list[ProcessedDocument] | None = None) -> None:
        self._docs = {d.document_id: d for d in (documents or [])}
        self.searches: list[tuple[str, int]] = []

    @property
    def loaded(self) -> bool:
        return bool(self._docs)

    @property
    def document_count(self) -> int:
        return len(self._docs)

    def status(self) -> dict[str, Any]:
        loaded = bool(self._docs)
        return {
            "available": True,
            "loaded": loaded,
            "message": "" if loaded else "semantic index not built",
            "documents": len(self._docs),
        }

    def search(self, query: str, limit: int = 10, max_limit: int = 50) -> SearchResponse:
        self.searches.append((query, int(limit)))
        tokens = set(query.lower().split())
        scored = []
        for doc in self._docs.values():
            overlap = len(tokens & set(doc.content.lower().split()))
            # Overlap ratio: an unrelated query scores exactly 0.0, so the fake
            # mirrors the real cosine backend instead of ranking everything.
            score = overlap / max(1, len(tokens))
            scored.append((score, doc))
        scored.sort(key=lambda pair: -pair[0])
        hits = tuple(
            SearchResult(
                rank=index,
                document_id=doc.document_id,
                title=doc.title,
                source=doc.source,
                snippet=doc.content[:80],
                score=round(float(score), 4),
                matched_terms=(),
            )
            for index, (score, doc) in enumerate(scored[: int(limit)], start=1)
        )
        return SearchResponse(
            query=query,
            total=len(hits),
            limit=int(limit),
            hits=hits,
            message="ok",
        )

    def get_document(self, document_id: str) -> ProcessedDocument | None:
        return self._docs.get(str(document_id))


class _UnavailableSemanticManager:
    """Semantic layer that is explicitly unavailable (no silent fallback)."""

    def __init__(self, message: str = "embedding backend offline") -> None:
        self._message = message

    @property
    def loaded(self) -> bool:
        return False

    @property
    def document_count(self) -> int:
        return 0

    def status(self) -> dict[str, Any]:
        return {"available": False, "loaded": False, "message": self._message}

    def search(self, *args: Any, **kwargs: Any) -> SearchResponse:
        raise AssertionError("semantic search must not run when unavailable")

    def get_document(self, document_id: str) -> None:
        return None


@pytest.fixture
def index_env(monkeypatch, tmp_path):
    """Offline BM25 environment shared by the mode fixtures.

    ``IndexManager.status()`` deliberately re-probes PostgreSQL on every call so
    a late-starting database is picked up; without a database every probe costs a
    full connect timeout. The Phase 9 suite is database-free by design, so the
    repository factory is replaced with the degraded no-op repository and the
    persisted index directory is pointed at an empty one. This only removes
    environment probes - the reported availability is unchanged.
    """
    reset_index_manager()
    manager = get_index_manager()
    index_dir = tmp_path / "bm25-index"
    index_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(manager, "_repo_factory", lambda: make_document_repository(None))
    monkeypatch.setattr(manager, "_index_dir", index_dir)
    yield manager
    reset_index_manager()


@pytest.fixture
def bm25_only(index_env, monkeypatch):
    """BM25 index available, semantic index explicitly unavailable."""
    index_env.set_engine(SearchEngine(_sample_documents()))
    monkeypatch.setattr(
        "backend.api.search.get_semantic_index_manager",
        lambda: _UnavailableSemanticManager(),
    )
    return index_env


@pytest.fixture
def full_stack(index_env, monkeypatch):
    """BM25 *and* semantic available so hybrid retrieval really runs."""
    documents = _sample_documents()
    index_env.set_engine(SearchEngine(documents))
    monkeypatch.setattr(
        "backend.api.search.get_semantic_index_manager",
        lambda: _StubSemanticManager(documents),
    )
    return index_env


@pytest.fixture
def empty_index(index_env, monkeypatch):
    """Nothing indexed at all - the worst-case availability scenario."""
    index_env.set_engine(SearchEngine([]))
    monkeypatch.setattr(
        "backend.api.search.get_semantic_index_manager",
        lambda: _UnavailableSemanticManager("no semantic index"),
    )
    return index_env


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _stub_rag(*, answer: str | None, fallback: bool = False, status: str = "ok"):
    """Build a replacement ``generate_rag_answer`` returning a fixed response.

    Deterministic stand-in for the Phase 8 orchestrator: no LLM, no network.
    Citations are derived from the hits the mode layer already retrieved.
    """

    def _fake(request: AnswerRequest, provider=None, retrieval_payload=None) -> AnswerResponse:
        hits = [h for h in ((retrieval_payload or {}).get("hits") or []) if isinstance(h, dict)]
        sources = [
            SourceCitation(
                citation_id=index,
                document_id=str(hit.get("document_id", "")),
                title=str(hit.get("title", "")),
                source=str(hit.get("source", "")),
                rank=int(hit.get("rank", 0) or 0),
                score=float(hit.get("score", 0.0) or 0.0),
            )
            for index, hit in enumerate(hits, start=1)
        ]
        return AnswerResponse(
            query=request.query,
            status=status,
            answer=answer or "",
            fallback_mode=fallback,
            sources=sources,
            retrieval=RetrievalMetadata(
                mode=request.mode,
                passages_considered=len(hits),
                passages_used=len(sources),
                took_ms=1.0,
            ),
            generation=GenerationMetadata(
                provider="fake", model="fake/stub", took_ms=1.0
            ),
            search_hits=hits,
            message="ok",
        )

    return _fake


def _search(client: TestClient, mode: str, query: str = "python", **params: Any):
    return client.get("/api/search", params={"q": query, "mode": mode, **params})


# --------------------------------------------------------------------------- #
# A. controlled mode enum + validation
# --------------------------------------------------------------------------- #


class TestModeDefinitions:
    def test_enum_members_are_the_four_specialized_modes(self):
        assert [mode.value for mode in modes_module.specialized_modes()] == list(
            SPECIALIZED_MODES
        )
        assert SearchMode("web") is SearchMode.WEB
        assert SearchMode("code") is SearchMode.CODE

    def test_normalize_accepts_legacy_and_specialized_modes(self):
        assert normalize_mode_param("bm25") == "lexical"  # legacy alias preserved
        for legacy in LEGACY_SEARCH_MODES:
            assert normalize_mode_param(legacy) in LEGACY_SEARCH_MODES
        for mode in SPECIALIZED_MODES:
            assert normalize_mode_param(mode.upper()) == mode

    def test_normalize_rejects_unknown_values(self):
        for bad in ("bogus", "", "   ", "websearch", "10", None):
            with pytest.raises(InvalidSearchModeError):
                normalize_mode_param(bad)

    def test_try_parse_returns_none_for_legacy_and_invalid(self):
        assert try_parse_search_mode("hybrid") is None
        assert try_parse_search_mode("nope") is None
        assert try_parse_search_mode("research") is SearchMode.RESEARCH

    def test_supported_values_include_legacy_and_phase9(self):
        values = supported_mode_values()
        for legacy in LEGACY_SEARCH_MODES:
            assert legacy in values
        for mode in SPECIALIZED_MODES:
            assert mode in values


# --------------------------------------------------------------------------- #
# B. mode catalog endpoint
# --------------------------------------------------------------------------- #


class TestModeCatalog:
    def test_catalog_endpoint_lists_every_mode(self, client: TestClient):
        res = client.get("/api/search/modes")
        assert res.status_code == 200
        data = res.json()

        assert data["default_mode"] == settings.MODE_DEFAULT
        assert [m["id"] for m in data["modes"]] == list(SPECIALIZED_MODES)
        assert set(data["legacy_modes"]) == set(LEGACY_SEARCH_MODES)

    def test_catalog_entries_describe_strategy_and_capabilities(self, client: TestClient):
        by_id = {m["id"]: m for m in client.get("/api/search/modes").json()["modes"]}

        assert by_id["web"]["ai_answer"] is False
        assert by_id["ai"]["ai_answer"] is True
        assert by_id["research"]["capabilities"]["diversified_sources"] is True
        assert by_id["research"]["capabilities"]["richer_snippets"] is True
        assert by_id["code"]["capabilities"]["code_snippets"] is True
        assert by_id["code"]["capabilities"]["documentation_priority"] is True
        for entry in by_id.values():
            assert entry["label"] and entry["description"]
            assert 0 < entry["default_limit"] <= entry["max_limit"]

    def test_catalog_matches_module_function(self):
        assert mode_catalog() == modes_module.mode_catalog()


# --------------------------------------------------------------------------- #
# C. Web Search mode
# --------------------------------------------------------------------------- #


class TestWebMode:
    def test_returns_shared_envelope(self, full_stack, client: TestClient):
        res = _search(client, "web", "python")
        assert res.status_code == 200
        data = res.json()

        assert ENVELOPE_KEYS <= set(data)
        assert data["mode"] == "web"
        assert data["status"] == "ok"
        assert data["query"] == "python"
        assert data["total"] == len(data["hits"])
        assert isinstance(data["answer"], type(None))
        assert isinstance(data["sources"], list)

    def test_reports_hybrid_strategy_and_never_generates_an_answer(
        self, full_stack, client: TestClient
    ):
        data = _search(client, "web", "python").json()

        assert data["metadata"]["retrieval_strategy"] == "hybrid"
        assert data["answer"] is None, "web mode must not fabricate an answer"
        assert data["metadata"]["capabilities"]["ai_answer"] is False

    def test_sources_mirror_retrieved_hits(self, full_stack, client: TestClient):
        data = _search(client, "web", "docker").json()

        assert data["sources"], "web mode reports its supporting sources"
        for source in data["sources"]:
            assert {"document_id", "title", "source", "domain", "rank", "score"} <= set(source)
        hit_ids = {hit["document_id"] for hit in data["hits"]}
        assert hit_ids == {source["document_id"] for source in data["sources"]}

    def test_falls_back_to_lexical_when_semantic_missing(self, bm25_only, client: TestClient):
        data = _search(client, "web", "python").json()

        assert data["metadata"]["retrieval_strategy"] == "lexical"
        assert data["status"] == "degraded"
        assert data["metadata"]["degraded_reason"]
        assert "semantic" in data["message"]

    def test_uses_configured_default_limit(self, full_stack, client: TestClient):
        data = _search(client, "web", "python").json()
        assert data["limit"] == settings.MODE_WEB_LIMIT
        assert data["metadata"]["limits"]["effective"] == settings.MODE_WEB_LIMIT

    def test_honours_explicit_limit_within_cap(self, full_stack, client: TestClient):
        data = _search(client, "web", "python", limit=2).json()
        assert data["limit"] == 2
        assert len(data["hits"]) <= 2


# --------------------------------------------------------------------------- #
# D. AI Answers mode
# --------------------------------------------------------------------------- #


class TestAiAnswersMode:
    def test_returns_grounded_answer_with_citations(
        self, full_stack, client: TestClient, monkeypatch
    ):
        monkeypatch.setattr(
            "backend.ai.rag.generate_rag_answer",
            _stub_rag(answer="Python is a programming language [1]."),
        )
        data = _search(client, "ai", "python").json()

        assert data["mode"] == "ai"
        assert data["status"] == "ok"
        assert data["answer"] == "Python is a programming language [1]."
        assert data["sources"], "an answer must ship with its citations"
        assert all(source["citation_id"] for source in data["sources"])
        assert data["metadata"]["rag"]["status"] == "ok"
        assert data["metadata"]["rag"]["generated"] is True

    def test_never_fabricates_an_answer_when_context_is_insufficient(
        self, full_stack, client: TestClient, monkeypatch
    ):
        monkeypatch.setattr(
            "backend.ai.rag.generate_rag_answer",
            _stub_rag(answer="", fallback=True, status="ok"),
        )
        data = _search(client, "ai", "python").json()

        assert data["answer"] is None, "a fallback must surface as null, never as text"
        assert data["metadata"]["rag"]["fallback_mode"] is True
        assert data["metadata"]["answer_note"]

    def test_answer_is_never_synthesised_when_the_provider_fails(
        self, full_stack, client: TestClient, monkeypatch
    ):
        def _failing(request: AnswerRequest, provider=None, retrieval_payload=None):
            return _stub_rag(answer="AI answer generation unavailable", fallback=True)(
                request, provider=provider, retrieval_payload=retrieval_payload
            )

        monkeypatch.setattr("backend.ai.rag.generate_rag_answer", _failing)
        data = _search(client, "ai", "python").json()

        assert data["answer"] is None
        assert data["status"] == "ok"  # retrieval itself was healthy
        assert data["metadata"]["rag"]["fallback_mode"] is True

    def test_uses_its_own_configured_limit(self, full_stack, client: TestClient, monkeypatch):
        monkeypatch.setattr("backend.ai.rag.generate_rag_answer", _stub_rag(answer="Answer [1]."))
        data = _search(client, "ai", "python").json()
        assert data["limit"] == settings.MODE_AI_LIMIT

    def test_ai_mode_can_be_disabled_without_affecting_other_modes(
        self, full_stack, client: TestClient, monkeypatch
    ):
        monkeypatch.setattr(settings, "MODE_AI_ENABLED", False)

        ai = _search(client, "ai", "python").json()
        assert ai["metadata"]["capabilities"]["ai_answer"] is False
        assert ai["answer"] is None

        web = _search(client, "web", "python").json()
        assert web["status"] == "ok"


# --------------------------------------------------------------------------- #
# E. Research mode
# --------------------------------------------------------------------------- #


class TestResearchMode:
    def test_separates_retrieved_evidence_from_generated_synthesis(
        self, full_stack, client: TestClient, monkeypatch
    ):
        monkeypatch.setattr(
            "backend.ai.rag.generate_rag_answer",
            _stub_rag(answer="Synthesis across the cited documents [1][2]."),
        )
        data = _search(client, "research", "python").json()

        assert data["mode"] == "research"
        evidence = data["metadata"]["evidence"]
        synthesis = data["metadata"]["synthesis"]

        assert evidence["kind"] == "retrieved_evidence"
        assert evidence["documents_returned"] == len(data["hits"])
        assert synthesis["kind"] == "generated_synthesis"
        assert synthesis["generated"] is True
        assert evidence["documents_returned"] > 0

    def test_evidence_is_available_even_without_synthesis(
        self, full_stack, client: TestClient, monkeypatch
    ):
        monkeypatch.setattr(
            "backend.ai.rag.generate_rag_answer",
            _stub_rag(answer="", fallback=True, status="ok"),
        )
        data = _search(client, "research", "python").json()

        assert data["answer"] is None
        assert data["metadata"]["evidence"]["kind"] == "retrieved_evidence"
        assert data["metadata"]["synthesis"]["generated"] is False

    def test_caps_hits_per_web_host_and_removes_duplicates(
        self, monkeypatch, client: TestClient
    ):
        documents = [
            _doc(
                f"dup-{i}",
                f"Repeated python page {i}",
                "python python python repeated page content",
                "https://docs.python.org/page",
            )
            for i in range(5)
        ] + [_doc("other-1", "Other", "python elsewhere", "https://other.example/x")]
        reset_index_manager()
        get_index_manager().set_engine(SearchEngine(documents))
        monkeypatch.setattr(
            "backend.api.search.get_semantic_index_manager",
            lambda: _StubSemanticManager(documents),
        )
        monkeypatch.setattr(
            "backend.ai.rag.generate_rag_answer", _stub_rag(answer="", fallback=True)
        )

        data = _search(client, "research", "python").json()
        stats = data["metadata"]["diversification"]

        assert data["total"] <= settings.MODE_RESEARCH_LIMIT
        assert stats["distinct_sources"] >= 2
        hosts = [
            source["domain"] for source in data["sources"] if source["domain"]
        ]
        assert len(hosts) <= stats["per_source_cap"] * len(set(hosts))
        reset_index_manager()

    def test_wider_retrieval_than_web_mode(self, full_stack, client: TestClient, monkeypatch):
        monkeypatch.setattr(
            "backend.ai.rag.generate_rag_answer", _stub_rag(answer="", fallback=True)
        )
        research = _search(client, "research", "python").json()
        web = _search(client, "web", "python").json()

        assert research["metadata"]["limits"]["candidates"] > web["metadata"]["limits"][
            "candidates"
        ]
        assert research["metadata"]["snippets"]["words"] == settings.RESEARCH_SNIPPET_WORDS

    def test_synthesis_can_be_disabled_while_evidence_remains(
        self, full_stack, client: TestClient, monkeypatch
    ):
        monkeypatch.setattr(settings, "MODE_RESEARCH_RAG_ENABLED", False)

        data = _search(client, "research", "python").json()
        assert data["metadata"]["capabilities"]["ai_answer"] is False
        assert data["answer"] is None
        assert data["hits"], "disabling synthesis must not suppress retrieved evidence"


# --------------------------------------------------------------------------- #
# F. Code Docs mode
# --------------------------------------------------------------------------- #


class TestCodeDocsMode:
    def test_extracts_code_snippets_from_indexed_content(
        self, full_stack, client: TestClient
    ):
        data = _search(client, "code", "SearchEngine create_engine").json()

        assert data["mode"] == "code"
        snippets = [hit.get("code_snippet") for hit in data["hits"]]
        assert any(snippets), "code mode should surface an excerpt from the corpus"
        for hit in data["hits"]:
            excerpt = hit.get("code_snippet")
            if excerpt:
                assert len(excerpt) <= settings.CODE_SNIPPET_MAX_CHARS

    def test_snippets_are_copied_from_the_index_not_invented(
        self, full_stack, client: TestClient
    ):
        data = _search(client, "code", "SearchEngine").json()
        corpus = " ".join(doc.content for doc in _sample_documents())
        for hit in data["hits"]:
            excerpt = hit.get("code_snippet")
            if not excerpt:
                continue
            first_line = next((line.strip() for line in excerpt.splitlines() if line.strip()), "")
            assert first_line and first_line in corpus

    def test_documents_that_contain_no_code_report_none(
        self, full_stack, client: TestClient
    ):
        data = _search(client, "code", "machine learning training data").json()
        for hit in data["hits"]:
            assert "code_snippet" in hit  # explicit key, never a fabricated excerpt
            assert not hit["code_snippet"] or isinstance(hit["code_snippet"], str)

    def test_prioritises_documentation_sources_without_hiding_others(
        self, full_stack, client: TestClient
    ):
        # Matches both a documentation source (Python tutorial) and a plain page.
        data = _search(client, "code", "python machine").json()
        stats = data["metadata"]["code"]

        doc_ranks = [
            hit["rank"]
            for hit in data["hits"]
            if is_documentation_source(hit["source"], hit["title"])
        ]
        other_ranks = [
            hit["rank"]
            for hit in data["hits"]
            if not is_documentation_source(hit["source"], hit["title"])
        ]

        assert doc_ranks and other_ranks, "fixture query must match both kinds of source"
        assert stats["documentation_priority"] is True
        assert stats["documentation_hits"] == len(doc_ranks)
        assert stats["other_hits"] == len(other_ranks)
        # Documentation first, and every hit is still present (a priority, not a filter).
        assert max(doc_ranks) < min(other_ranks)
        assert sorted(doc_ranks + other_ranks) == list(range(1, len(data["hits"]) + 1))

    def test_expands_technical_identifiers_for_retrieval(
        self, full_stack, client: TestClient
    ):
        data = _search(client, "code", "faiss_store.SearchEngine").json()
        expansion = data["metadata"]["query_expansion"]

        assert expansion["original"] == "faiss_store.SearchEngine"
        assert expansion["technical_terms"] == ["faiss_store.SearchEngine"]
        added = " ".join(expansion["added_terms"])
        # Identifier sub-terms are added for the embedding encoder / BM25 while
        # the original identifier stays in the retrieval query untouched.
        assert "faiss" in added and "store" in added
        assert "search" in added and "engine" in added
        assert expansion["retrieval_query"].startswith("faiss_store.SearchEngine")
        assert data["query"] == "faiss_store.SearchEngine"  # echo stays user-facing

    def test_uses_lexical_leaning_weights(self, full_stack, client: TestClient):
        spec = resolve_mode_spec(SearchMode.CODE)
        assert spec.bm25_weight == settings.CODE_BM25_WEIGHT
        assert spec.semantic_weight == settings.CODE_SEMANTIC_WEIGHT
        assert spec.bm25_weight > spec.semantic_weight
        assert spec.rag_enabled is False, "code mode does not generate answers"

    def test_does_not_call_any_external_service(self, full_stack, client: TestClient, monkeypatch):
        """Code mode must work purely from the local index (no crawler, no API).

        Every outbound fetch entry point of the SEEK crawler is replaced by a
        tripwire, so a request answered at all proves it was served from the
        already indexed corpus.
        """
        from backend.crawler import fetcher

        def _tripwire(*args: Any, **kwargs: Any):
            raise AssertionError("code mode must not fetch anything from the network")

        monkeypatch.setattr(fetcher, "fetch", _tripwire)
        monkeypatch.setattr(fetcher, "httpx", _tripwire)

        res = _search(client, "code", "python")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] > 0
        assert data["metadata"]["retrieval_strategy"] in {"hybrid", "lexical"}
        # Every returned document is one SEEK already indexed.
        indexed = {doc.document_id for doc in _sample_documents()}
        assert {hit["document_id"] for hit in data["hits"]} <= indexed


# --------------------------------------------------------------------------- #
# G. invalid mode -> 422
# --------------------------------------------------------------------------- #


class TestInvalidMode:
    @pytest.mark.parametrize("mode", ["bogus", "web2", "semantic-search", "10", " "])
    def test_unknown_mode_returns_422_with_structured_detail(
        self, full_stack, client: TestClient, mode: str
    ):
        res = client.get("/api/search", params={"q": "python", "mode": mode})
        assert res.status_code == 422

        detail = res.json()["detail"]
        assert detail["error"] == "invalid_search_mode"
        assert detail["mode"] == mode
        assert set(SPECIALIZED_MODES) <= set(detail["allowed"])
        assert "invalid search mode" in detail["message"]
        assert "web" in detail["message"] and "code" in detail["message"]

    def test_invalid_mode_returns_no_results(self, full_stack, client: TestClient):
        res = _search(client, "nope", "python")
        assert res.status_code == 422
        assert "hits" not in res.json()


# --------------------------------------------------------------------------- #
# H. query validation
# --------------------------------------------------------------------------- #


class TestQueryValidation:
    @pytest.mark.parametrize("mode", [*SPECIALIZED_MODES, "lexical", "bm25", "semantic", "hybrid"])
    def test_missing_query_is_rejected(self, full_stack, client: TestClient, mode: str):
        assert client.get("/api/search", params={"mode": mode}).status_code == 422

    @pytest.mark.parametrize("mode", [*SPECIALIZED_MODES, "lexical", "semantic", "hybrid"])
    def test_empty_query_is_rejected(self, full_stack, client: TestClient, mode: str):
        assert client.get("/api/search", params={"q": "", "mode": mode}).status_code == 422

    def test_whitespace_query_is_accepted_and_normalised(
        self, full_stack, client: TestClient
    ):
        data = _search(client, "web", "   python   ").json()
        assert data["query"] == "python"


# --------------------------------------------------------------------------- #
# I. unknown query -> explicit, never invented
# --------------------------------------------------------------------------- #


class TestUnknownQuery:
    """An unmatched query must yield zero results - never padded placeholder hits."""

    UNKNOWN = "zzzqqq nonexistent gibberishtoken"

    @pytest.mark.parametrize("mode", SPECIALIZED_MODES)
    def test_no_match_reports_zero_hits_with_explanation(
        self, full_stack, client: TestClient, mode: str
    ):
        data = _search(client, mode, self.UNKNOWN).json()

        assert data["total"] == 0
        assert data["hits"] == []
        assert data["sources"] == []
        assert data["message"], "an empty result must be explained"
        assert data["status"] == "ok", "an empty result is not a retrieval failure"

    @pytest.mark.parametrize("mode", SPECIALIZED_MODES)
    def test_unmatched_candidates_are_dropped_not_ranked(
        self, full_stack, client: TestClient, mode: str
    ):
        data = _search(client, mode, self.UNKNOWN).json()
        stats = data["metadata"]["matching"]

        assert stats["dropped_unmatched"] > 0, "0.0-scored candidates must not be shown"
        assert stats["returned"] == 0
        assert stats["score_floor"] == settings.MODE_MATCH_SCORE_FLOOR

    def test_matching_documents_are_still_returned(self, full_stack, client: TestClient):
        data = _search(client, "web", "python").json()
        assert data["total"] >= 1
        assert all(hit["score"] > 0 for hit in data["hits"])
        assert [hit["rank"] for hit in data["hits"]] == list(
            range(1, len(data["hits"]) + 1)
        )

    def test_ai_mode_returns_null_answer_for_unknown_query(
        self, full_stack, client: TestClient
    ):
        data = _search(client, "ai", self.UNKNOWN).json()
        assert data["answer"] is None
        assert data["hits"] == []

    def test_unknown_query_on_empty_index_is_unavailable_not_empty(
        self, empty_index, client: TestClient
    ):
        data = _search(client, "web", self.UNKNOWN).json()
        assert data["status"] == "unavailable"
        assert "index" in data["message"]


# --------------------------------------------------------------------------- #
# J. availability reporting
# --------------------------------------------------------------------------- #


class TestAvailabilityReporting:
    @pytest.mark.parametrize("mode", SPECIALIZED_MODES)
    def test_empty_index_is_reported_not_hidden(
        self, empty_index, client: TestClient, mode: str
    ):
        data = _search(client, mode, "python").json()

        assert data["total"] == 0
        assert data["status"] in {"degraded", "unavailable"}
        assert data["message"]
        assert data["metadata"]["index"]["bm25"] is False
        assert data["metadata"]["index"]["semantic"] is False

    @pytest.mark.parametrize("mode", SPECIALIZED_MODES)
    def test_index_health_is_always_published(self, full_stack, client: TestClient, mode: str):
        data = _search(client, mode, "python").json()
        assert data["metadata"]["index"]["bm25"] is True
        assert data["metadata"]["index"]["semantic"] is True

    @pytest.mark.parametrize("mode", SPECIALIZED_MODES)
    def test_degraded_reason_is_machine_readable(self, bm25_only, client: TestClient, mode: str):
        data = _search(client, mode, "python").json()
        assert data["status"] == "degraded"
        assert isinstance(data["metadata"]["degraded_reason"], str)
        assert data["metadata"]["retrieval_strategy"] == "lexical"


# --------------------------------------------------------------------------- #
# K. RAG disabled -> unavailable, answer null
# --------------------------------------------------------------------------- #


class TestRagDisabled:
    @pytest.mark.parametrize("mode", ["ai", "research"])
    def test_disabled_rag_reports_unavailable_with_null_answer(
        self, full_stack, client: TestClient, monkeypatch, mode: str
    ):
        monkeypatch.setattr(settings, "RAG_ENABLED", False)

        data = _search(client, mode, "python").json()

        assert data["answer"] is None, "no answer may be invented when RAG is off"
        assert data["metadata"]["rag"]["enabled"] is False
        assert data["metadata"]["rag"]["status"] == "disabled"
        assert data["metadata"]["rag"]["generated"] is False
        assert data["status"] == "unavailable"
        # Retrieval still worked and its evidence is still returned.
        assert data["hits"]

    def test_non_rag_modes_are_unaffected_by_the_rag_switch(
        self, full_stack, client: TestClient, monkeypatch
    ):
        monkeypatch.setattr(settings, "RAG_ENABLED", False)

        web = _search(client, "web", "python").json()
        code = _search(client, "code", "python").json()

        assert web["status"] == "ok"
        assert "rag" not in web["metadata"]
        assert code["status"] == "ok"
        assert "rag" not in code["metadata"]


# --------------------------------------------------------------------------- #
# L. retrieval health wins over the RAG outcome
# --------------------------------------------------------------------------- #


class TestStatusPrecedence:
    @pytest.mark.parametrize("mode", ["ai", "research"])
    def test_degraded_retrieval_is_not_reported_as_ok_even_with_an_answer(
        self, bm25_only, client: TestClient, monkeypatch, mode: str
    ):
        monkeypatch.setattr(
            "backend.ai.rag.generate_rag_answer", _stub_rag(answer="A grounded answer [1].")
        )

        data = _search(client, mode, "python").json()

        assert data["answer"] == "A grounded answer [1]."
        assert data["status"] == "degraded", "retrieval health outranks the RAG outcome"
        assert data["metadata"]["retrieval_strategy"] == "lexical"

    @pytest.mark.parametrize("mode", ["ai", "research"])
    def test_unavailable_retrieval_skips_synthesis_entirely(
        self, empty_index, client: TestClient, monkeypatch, mode: str
    ):
        def _must_not_run(request, provider=None, retrieval_payload=None):
            raise AssertionError("synthesis must be skipped when retrieval is unavailable")

        monkeypatch.setattr("backend.ai.rag.generate_rag_answer", _must_not_run)

        data = _search(client, mode, "python").json()
        assert data["status"] == "unavailable"
        assert data["answer"] is None
        assert data["metadata"]["rag"]["status"] == "skipped"


# --------------------------------------------------------------------------- #
# M. backward compatibility
# --------------------------------------------------------------------------- #


class TestBackwardCompatibility:
    def test_default_request_keeps_the_legacy_payload(self, full_stack, client: TestClient):
        res = client.get("/api/search", params={"q": "python"})
        assert res.status_code == 200
        data = res.json()

        # Exact Phase 2 contract: no Phase 9 keys leak into the legacy payload.
        assert data["mode"] == "lexical"
        assert set(data) == {
            "query",
            "total",
            "limit",
            "hits",
            "took_ms",
            "message",
            "mode",
            "semantic",
        }
        assert data["limit"] == settings.SEARCH_DEFAULT_LIMIT
        assert set(data["hits"][0]) == {
            "rank",
            "document_id",
            "title",
            "source",
            "snippet",
            "score",
            "matched_terms",
        }

    @pytest.mark.parametrize("legacy", ["lexical", "bm25"])
    def test_bm25_modes_still_alias_the_lexical_handler(
        self, full_stack, client: TestClient, legacy: str
    ):
        data = _search(client, legacy, "python").json()
        assert data["mode"] == "lexical"
        assert "answer" not in data
        assert "sources" not in data

    def test_semantic_mode_contract_is_unchanged(self, full_stack, client: TestClient):
        data = _search(client, "semantic", "python").json()
        assert data["mode"] == "semantic"
        assert data["semantic"]["status"] in {"ok", "not_built", "unavailable"}
        assert "score_type" in data
        assert "answer" not in data

    def test_hybrid_mode_contract_is_unchanged(self, full_stack, client: TestClient):
        data = _search(client, "hybrid", "python").json()
        assert data["mode"] == "hybrid"
        assert set(data["weights"]) == {"bm25", "semantic"}
        assert "answer" not in data

    def test_legacy_limit_bounds_are_preserved(self, full_stack, client: TestClient):
        assert _search(client, "lexical", "python", limit=50).status_code == 200
        assert _search(client, "lexical", "python", limit=0).status_code == 422
        assert _search(client, "lexical", "python", limit=51).status_code == 422

    def test_phase8_answer_endpoint_still_works(self, full_stack, client: TestClient):
        res = client.post(
            "/api/answer",
            json={"query": "python programming", "mode": "hybrid", "limit": 3},
        )
        assert res.status_code == 200
        data = res.json()
        assert {"query", "status", "answer", "sources", "retrieval", "generation"} <= set(data)

    def test_mode_query_does_not_change_legacy_handlers(self, full_stack, client: TestClient):
        with_mode = _search(client, "web", "python").json()
        without_mode = client.get("/api/search", params={"q": "python"}).json()
        assert with_mode["query"] == without_mode["query"]
        assert without_mode["mode"] == "lexical"


# --------------------------------------------------------------------------- #
# N. centralised configuration
# --------------------------------------------------------------------------- #


class TestCentralisedConfiguration:
    def test_every_mode_has_a_settings_backed_spec(self):
        for mode in SPECIALIZED_MODES:
            spec = resolve_mode_spec(mode)
            assert spec.default_limit >= 1
            assert spec.max_limit == settings.MODE_MAX_LIMIT
            assert spec.candidate_limit(spec.default_limit) <= settings.MODE_MAX_CANDIDATES

    def test_patching_settings_changes_mode_behaviour(self, monkeypatch):
        monkeypatch.setattr(settings, "MODE_WEB_LIMIT", 3)
        assert resolve_limit(resolve_mode_spec(SearchMode.WEB), None) == 3

        monkeypatch.setattr(settings, "MODE_MAX_LIMIT", 4)
        assert resolve_limit(resolve_mode_spec(SearchMode.WEB), None) == 3

    def test_limits_are_clamped_to_the_configured_maximum(self):
        spec = resolve_mode_spec(SearchMode.WEB)
        assert resolve_limit(spec, 10_000) == settings.MODE_MAX_LIMIT
        assert resolve_limit(spec, 0) == 1

    def test_candidate_width_uses_the_configured_multipliers(self):
        research = resolve_mode_spec(SearchMode.RESEARCH)
        code = resolve_mode_spec(SearchMode.CODE)
        web = resolve_mode_spec(SearchMode.WEB)

        assert research.candidate_multiplier == settings.RESEARCH_CANDIDATE_MULTIPLIER
        assert code.candidate_multiplier == settings.CODE_CANDIDATE_MULTIPLIER
        assert web.candidate_multiplier == 1
        assert research.candidate_limit(2) > web.candidate_limit(2)

    def test_mode_layer_contains_no_hard_coded_limits(self):
        """Mode behaviour must read settings, not literals sprinkled in code."""
        source = Path(modes_module.__file__).read_text(encoding="utf-8")
        for literal in ("MODE_WEB_LIMIT", "MODE_AI_LIMIT", "MODE_RESEARCH_LIMIT", "MODE_CODE_LIMIT"):
            assert literal in source

    def test_api_documents_the_mode_parameter(self, client: TestClient):
        schema = client.get("/openapi.json").json()
        modes = schema["paths"]["/api/search"]["get"]["parameters"]
        mode_param = next(p for p in modes if p["name"] == "mode")
        assert "web" in mode_param["description"] and "research" in mode_param["description"]


# --------------------------------------------------------------------------- #
# Q. availability is read without a database round-trip, never hidden
# --------------------------------------------------------------------------- #


class TestAvailabilityProbeCost:
    """The mode envelope needs BM25 / semantic availability on every request.

    ``IndexManager.status()`` re-probes PostgreSQL on every call, which costs a
    full connect timeout when the database is unreachable. The orchestrator
    therefore reads the managers' in-memory state instead. These tests pin the two
    properties that matter: no extra database probe on the hot path, and no way
    for a probe failure to be hidden.
    """

    def test_availability_does_not_call_index_manager_status(
        self, bm25_only, monkeypatch
    ):
        calls = {"n": 0}
        manager = get_index_manager()
        real_status = manager.status

        def counting_status():
            calls["n"] += 1
            return real_status()

        monkeypatch.setattr(manager, "status", counting_status)
        mode_orchestrator._index_availability()
        assert calls["n"] == 0, "availability must be read from memory, not from status()"

    def test_availability_reflects_live_engine_state(self, bm25_only):
        state = mode_orchestrator._index_availability()
        assert state["bm25_documents"] == bm25_only.engine.document_count
        assert state["bm25"] is True

    def test_availability_tracks_a_hot_swapped_engine(self, bm25_only, client: TestClient):
        """Swapping the live engine is reflected immediately - nothing is cached."""
        assert mode_orchestrator._index_availability()["bm25"] is True
        assert mode_orchestrator._index_availability()["bm25_documents"] > 0

        bm25_only.set_engine(SearchEngine([]))
        state = mode_orchestrator._index_availability()
        assert state["bm25_documents"] == 0
        # The index is still *loaded* (so it is available), but with zero documents
        # and no hits the envelope must escalate to unavailable rather than
        # reporting a healthy empty result set.
        data = client.get("/api/search", params={"q": "python", "mode": "web"}).json()
        assert data["status"] == "unavailable"
        assert data["metadata"]["index"]["bm25_documents"] == 0

    def test_empty_index_reports_unavailable(self, empty_index, client: TestClient):
        data = client.get("/api/search", params={"q": "python", "mode": "web"}).json()
        assert data["status"] == "unavailable"
        assert data["metadata"]["index"]["bm25"] is False
        assert data["metadata"]["index"]["bm25_documents"] == 0

    def test_unavailable_index_explains_itself(self, empty_index, client: TestClient):
        data = client.get("/api/search", params={"q": "python", "mode": "web"}).json()
        assert data["message"]
        assert "index" in data["message"].lower()

    def test_semantic_manager_failure_is_reported_not_swallowed(
        self, bm25_only, client: TestClient, monkeypatch
    ):
        def broken():
            raise RuntimeError("semantic index is corrupt")

        monkeypatch.setattr("backend.api.search.get_semantic_index_manager", broken)
        response = client.get("/api/search", params={"q": "python", "mode": "web"})
        assert response.status_code == 200
        data = response.json()
        assert data["metadata"]["index"]["semantic"] is False
        assert data["metadata"]["degraded_reason"]

    @pytest.mark.parametrize("mode", SPECIALIZED_MODES)
    def test_mode_request_makes_no_extra_database_probe(
        self, bm25_only, client: TestClient, mode: str, monkeypatch
    ):
        """The mode path must not add database round-trips of its own."""
        calls = {"n": 0}
        manager = get_index_manager()
        real_status = manager.status

        def counting_status():
            calls["n"] += 1
            return real_status()

        monkeypatch.setattr(manager, "status", counting_status)
        before = calls["n"]
        assert client.get("/api/search", params={"q": "python", "mode": mode}).status_code == 200
        # The legacy retrieval handler probes once on its own; the orchestrator
        # must not add a second probe of its own.
        assert calls["n"] - before <= 1


# --------------------------------------------------------------------------- #
# O. frontend URL state + wiring
# --------------------------------------------------------------------------- #


def _node_available() -> bool:
    return shutil.which("node") is not None


@pytest.mark.skipif(not _node_available(), reason="node is required for the URL-state test")
class TestFrontendUrlState:
    def test_url_state_round_trip_suite_passes(self):
        """Runs ``npm run test:urlstate`` (the real frontend test suite)."""
        result = subprocess.run(
            ["npm", "run", "--silent", "test:urlstate"],
            cwd=FRONTEND_DIR,
            capture_output=True,
            text=True,
            timeout=300,
            shell=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "# fail 0" in result.stdout

    def test_app_wires_the_url_state_helpers(self):
        app_source = (FRONTEND_DIR / "src" / "App.tsx").read_text(encoding="utf-8")
        assert "parseSearchState" in app_source
        assert "buildSearchPath" in app_source
        assert "pushState" in app_source, "searches must be recorded in history"
        assert "popstate" in app_source, "back/forward navigation must be honoured"
        assert "ModeSelector" in app_source

    def test_mode_selector_is_keyboard_accessible(self):
        selector = (FRONTEND_DIR / "src" / "components" / "ModeSelector.tsx").read_text(
            encoding="utf-8"
        )
        assert 'role="radiogroup"' in selector
        assert 'role="radio"' in selector
        assert "aria-checked" in selector
        for key in ("ArrowRight", "ArrowLeft", "Home", "End"):
            assert key in selector
        assert "tabIndex" in selector, "single tab stop (roving tabindex)"

    def test_frontend_mode_ids_match_the_backend_enum(self):
        modes_source = (FRONTEND_DIR / "src" / "lib" / "modes.ts").read_text(encoding="utf-8")
        match = re.search(r"SEARCH_MODES:[^=]*=\s*\[([^\]]*)\]", modes_source)
        assert match, "SEARCH_MODES must stay an explicit literal for auditing"
        frontend_modes = re.findall(r"'([a-z]+)'", match.group(1))
        assert tuple(frontend_modes) == SPECIALIZED_MODES

    def test_npm_script_is_declared(self):
        scripts = json.loads((FRONTEND_DIR / "package.json").read_text(encoding="utf-8"))
        assert "test:urlstate" in scripts["scripts"]

    def test_ui_renders_answer_and_sources_panels(self):
        results = (FRONTEND_DIR / "src" / "components" / "SearchResults.tsx").read_text(
            encoding="utf-8"
        )
        assert "AnswerPanel" in results
        assert "SourcesPanel" in results
        assert "modeResponse" in results
        # Degraded / unavailable must be surfaced, not hidden.
        assert "degraded" in results and "unavailable" in results


# --------------------------------------------------------------------------- #
# P. no duplicated retrieval
# --------------------------------------------------------------------------- #


class TestReusesExistingServices:
    def test_orchestrator_delegates_to_the_existing_handlers(self, full_stack, monkeypatch):
        calls: list[str] = []
        import backend.api.search as search_api

        for handler in ("_hybrid_search", "_lexical_search", "_semantic_search"):
            original = getattr(search_api, handler)

            def _spy(*args, _name=handler, _fn=original, **kwargs):
                calls.append(_name)
                return _fn(*args, **kwargs)

            monkeypatch.setattr(search_api, handler, _spy)

        from backend.api.mode_orchestrator import execute_search_mode

        execute_search_mode(query="python", mode=SearchMode.WEB)
        assert calls == ["_hybrid_search"], "web mode must delegate to the hybrid handler"

    def test_orchestrator_reuses_retrieved_hits_for_rag(self, full_stack, monkeypatch):
        """The mode layer must not run retrieval twice."""
        seen: list[int] = []

        def _counting(*args, provider=None, retrieval_payload=None):
            seen.append(len((retrieval_payload or {}).get("hits") or []))
            return _stub_rag(answer="Answer [1].")(args[0], provider=provider,
                                                  retrieval_payload=retrieval_payload)

        monkeypatch.setattr("backend.ai.rag.generate_rag_answer", _counting)

        from backend.api.mode_orchestrator import execute_search_mode

        response = execute_search_mode(query="python", mode=SearchMode.AI)
        assert seen and seen[0] > 0, "RAG must receive the already-retrieved hits"
        assert response["answer"] == "Answer [1]."

    def test_get_document_lookups_are_read_only(self, full_stack):
        engine = get_index_manager().engine
        before = engine.document_count
        doc = engine.get_document("rd-1")
        assert doc is not None
        assert "create_engine" in doc.content
        assert engine.get_document("does-not-exist") is None
        assert engine.document_count == before

    def test_modes_module_has_no_index_or_network_dependencies(self):
        """The mode layer must not import a retrieval or network stack of its own."""
        tree = ast.parse(Path(modes_module.__file__).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

        for forbidden in ("httpx", "requests", "aiohttp", "faiss", "socket"):
            assert forbidden not in imported, f"{forbidden} must not be imported by the mode layer"
        assert "urllib.parse" in {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }, "only urllib.parse (host parsing) may be imported - never urllib.request"

    def test_modes_module_does_not_import_a_retrieval_implementation(self):
        tree = ast.parse(Path(modes_module.__file__).read_text(encoding="utf-8"))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
            elif isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)

        for forbidden in ("backend.search.bm25", "backend.search.hybrid", "backend.search.semantic",
                          "backend.search.embeddings", "backend.ai.rag", "backend.search.faiss_store"):
            assert forbidden not in modules, f"{forbidden} must be reached via the API layer"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))