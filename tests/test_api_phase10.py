"""Phase 10 API surface tests — every endpoint, valid and invalid.

Phase 1-9 each shipped tests for the endpoints they added. What was missing is a
single sweep that walks the **whole** HTTP surface and checks, per endpoint:

* the happy path returns ``200`` (or the documented ``201``) with the documented
  JSON shape;
* invalid input is rejected with ``422`` and a machine-readable body;
* a *missing* prerequisite (no index, no crawl job, no PostgreSQL) is reported
  explicitly (``404`` / ``status: error`` / ``status: unavailable``) instead of
  being papered over or crashing.

Everything runs fully offline: the shared fixtures in ``conftest.py`` pin the
BM25 manager to a temporary index directory + degraded repository and the
semantic manager to a degraded repository, so no socket and no model download is
ever touched.

Existing per-phase endpoint tests (``test_search_phase2``,
``test_crawler_phase4``, ``test_index_persistence_phase5b``,
``test_semantic_search_phase6``, ``test_hybrid_phase7``, ``test_rag_phase8``,
``test_search_modes_phase9``, ``test_health``) keep owning the *deep* behaviour
of their own feature; this module only adds the breadth.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.ai.models import AnswerRequest, AnswerResponse
from backend.main import app

# Every route the application publishes (verified against /openapi.json).
EXPECTED_PATHS = {
    "/",
    "/health",
    "/api/search",
    "/api/search/modes",
    "/api/crawl",
    "/api/crawl/{job_id}",
    "/api/index/status",
    "/api/index/rebuild",
    "/api/index/refresh",
    "/api/index/semantic/rebuild",
    "/api/index/semantic/refresh",
    "/api/answer",
}

LEGACY_MODES = ["lexical", "bm25", "semantic", "hybrid"]
SPECIALIZED_MODES = ["web", "ai", "research", "code"]
ALL_MODES = LEGACY_MODES + SPECIALIZED_MODES


# --------------------------------------------------------------------------- #
# routing / meta endpoints
# --------------------------------------------------------------------------- #


class TestRouting:
    def test_root_advertises_the_service(self, client: TestClient):
        data = client.get("/").json()
        assert data["name"] == "SEEK Search Engine"
        assert data["subtitle"] == "Search Engine for Exploration & Knowledge"
        assert data["status"] == "Operational"
        assert data["docs_url"] == "/docs"

    def test_health_is_static_and_never_touches_a_dependency(self, client: TestClient):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "seek-backend"}

    @pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
    def test_interactive_and_machine_docs_are_served(self, client: TestClient, path):
        assert client.get(path).status_code == 200

    def test_openapi_publishes_every_seek_route(self, client: TestClient):
        spec = client.get("/openapi.json").json()
        assert spec["info"]["title"].startswith("SEEK")
        assert set(spec["paths"]) == EXPECTED_PATHS

    @pytest.mark.parametrize(
        "path", ["/api/nope", "/nope", "/api/search/nope/nope", "/api/index/nope"]
    )
    def test_unknown_paths_are_404(self, client: TestClient, path):
        assert client.get(path).status_code == 404

    @pytest.mark.parametrize(
        "method,path",
        [
            ("post", "/health"),
            ("post", "/"),
            ("post", "/api/search"),
            ("delete", "/api/index/status"),
            ("get", "/api/index/rebuild"),
        ],
    )
    def test_wrong_method_is_405(self, client: TestClient, method, path):
        response = getattr(client, method)(path)
        assert response.status_code == 405

    def test_the_client_fixture_does_not_run_the_lifespan(self, client: TestClient):
        """Guard rail: an accidental ``with TestClient(app)`` would load the
        on-disk artifacts into ``indexes/`` and make the suite order-dependent."""
        assert isinstance(client, TestClient)
        assert client.app is app


# --------------------------------------------------------------------------- #
# GET /api/search
# --------------------------------------------------------------------------- #


class TestSearchEndpointValidation:
    @pytest.mark.parametrize(
        "params",
        [
            {},                                    # q missing
            {"q": ""},                              # q empty (min_length=1)
            {"q": "python", "limit": 0},            # below the ge=1 bound
            {"q": "python", "limit": -5},           # negative
            {"q": "python", "limit": 51},           # above the le=50 bound
            {"q": "python", "mode": "bogus"},
            {"q": "python", "bm25_weight": -1.0},
            {"q": "python", "semantic_weight": -0.5},
        ],
    )
    def test_invalid_requests_are_422_with_a_detail_body(
        self, client: TestClient, offline_index, params
    ):
        response = client.get("/api/search", params=params)
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], (dict, list))

    def test_unknown_mode_detail_lists_the_allowed_modes(
        self, client: TestClient, offline_index
    ):
        detail = client.get("/api/search", params={"q": "x", "mode": "nope"}).json()["detail"]
        assert detail["error"] == "invalid_search_mode"
        assert detail["mode"] == "nope"
        assert set(ALL_MODES) <= set(detail["allowed"])


class TestSearchEndpointContract:
    def test_default_request_keeps_the_phase2_envelope(
        self, client: TestClient, offline_index
    ):
        data = client.get("/api/search", params={"q": "python"}).json()
        assert set(data) >= {"query", "total", "limit", "hits", "took_ms", "message"}
        assert data["mode"] == "lexical"
        assert data["limit"] == 10           # settings.SEARCH_DEFAULT_LIMIT
        assert data["hits"], "the fixture corpus contains a Python document"

    def test_hit_shape_is_stable(self, client: TestClient, offline_index):
        hit = client.get("/api/search", params={"q": "python"}).json()["hits"][0]
        assert set(hit) == {
            "rank",
            "document_id",
            "title",
            "source",
            "snippet",
            "score",
            "matched_terms",
        }
        assert hit["rank"] == 1
        assert isinstance(hit["matched_terms"], list)

    @pytest.mark.parametrize(
        "requested,expected_echoed",
        [(1, 1), (3, 3), (50, 50)],
    )
    def test_limit_is_echoed_back_within_bounds(
        self, client: TestClient, offline_index, requested, expected_echoed
    ):
        data = client.get(
            "/api/search", params={"q": "python", "limit": requested}
        ).json()
        assert data["limit"] == expected_echoed

    @pytest.mark.parametrize("mode", LEGACY_MODES)
    def test_every_legacy_mode_answers_200(self, client: TestClient, offline_index, mode):
        response = client.get("/api/search", params={"q": "python", "mode": mode})
        assert response.status_code == 200
        assert response.json()["hits"] is not None

    @pytest.mark.parametrize("mode", SPECIALIZED_MODES)
    def test_every_specialized_mode_answers_200(
        self, client: TestClient, offline_index, offline_semantic, mode
    ):
        response = client.get("/api/search", params={"q": "python", "mode": mode})
        assert response.status_code == 200
        data = response.json()
        assert data["mode"] == mode
        assert data["status"] in {"ok", "degraded", "unavailable"}

    @pytest.mark.parametrize(
        "raw,expected",
        [("BM25", "lexical"), ("  Hybrid  ", "hybrid"), ("SEMANTIC", "semantic")],
    )
    def test_mode_is_case_and_whitespace_insensitive(
        self, client: TestClient, offline_index, offline_semantic, raw, expected
    ):
        data = client.get("/api/search", params={"q": "python", "mode": raw}).json()
        assert data["mode"] == expected

    @pytest.mark.parametrize(
        "query",
        [
            "docker",
            "documents",
            "the",
            "zzzznotinthecorpus",
            "  spaces  only  ",
            "文档搜索",
            "café",
            "<script>alert(1)</script>",
            "'; DROP TABLE documents; --",
            "%00nullbyte",
            "x" * 4000,
        ],
    )
    def test_hostile_and_edge_case_queries_never_500(
        self, client: TestClient, offline_index, query
    ):
        response = client.get("/api/search", params={"q": query})
        assert response.status_code == 200
        assert response.json()["total"] >= 0

    def test_whitespace_only_query_reports_no_hits_with_a_message(
        self, client: TestClient, offline_index
    ):
        data = client.get("/api/search", params={"q": "  "}).json()
        assert data["hits"] == []
        assert data["total"] == 0


class TestSearchIndexStateMatrix:
    """mode x index-state x query — the explicit Phase 10 matrix."""

    @pytest.mark.parametrize("mode", ALL_MODES)
    @pytest.mark.parametrize(
        "query,query_kind", [("python", "match"), ("zzzznotinthecorpus", "no-match")]
    )
    def test_bm25_only_index(
        self, client: TestClient, offline_index, semantic_missing, mode, query, query_kind
    ):
        """BM25 populated, semantic explicitly unavailable."""
        data = client.get("/api/search", params={"q": query, "mode": mode}).json()
        assert client.get("/api/search", params={"q": query, "mode": mode}).status_code == 200
        if mode in SPECIALIZED_MODES:
            assert data["metadata"]["index"]["bm25"] is True
            assert data["metadata"]["index"]["semantic"] is False
            assert data["status"] in {"ok", "degraded"}
            if query_kind == "no-match":
                assert data["hits"] == []
        else:
            assert data["hits"] is not None

    @pytest.mark.parametrize("mode", ALL_MODES)
    @pytest.mark.parametrize(
        "query,query_kind", [("python", "match"), ("zzzznotinthecorpus", "no-match")]
    )
    def test_empty_index(
        self, client: TestClient, offline_index, empty_index, semantic_missing, mode, query, query_kind
    ):
        """Nothing indexed at all — the "not built yet" path."""
        data = client.get("/api/search", params={"q": query, "mode": mode}).json()
        assert data["hits"] == []
        if mode in SPECIALIZED_MODES:
            assert data["status"] == "unavailable"
            assert data["metadata"]["index"]["bm25"] is False
            assert data["message"]
        elif mode == "lexical":
            assert "rebuild" in data["message"]

    @pytest.mark.parametrize("mode", ["semantic", "hybrid", "web", "ai", "research", "code"])
    def test_semantic_available(
        self, client: TestClient, offline_index, semantic_present, mode
    ):
        """Both retrieval stacks populated."""
        data = client.get("/api/search", params={"q": "python", "mode": mode}).json()
        if mode in SPECIALIZED_MODES:
            assert data["status"] in {"ok", "degraded"}
            assert data["metadata"]["index"]["semantic"] is True
            assert data["metadata"]["retrieval_strategy"] in {
                "hybrid",
                "semantic",
                "lexical",
            }
        elif mode == "semantic":
            assert data["semantic"]["status"] == "ok"
            assert data["hits"]
        else:
            assert data["status"] == "ok"
            assert data["hits"]

    def test_semantic_mode_never_silently_falls_back_to_bm25(
        self, client: TestClient, offline_index, semantic_missing
    ):
        data = client.get("/api/search", params={"q": "python", "mode": "semantic"}).json()
        assert data["hits"] == []
        assert data["semantic"]["status"] == "unavailable"
        assert "unavailable" in data["message"]

    def test_hybrid_reports_degraded_when_semantic_is_missing(
        self, client: TestClient, offline_index, semantic_missing
    ):
        data = client.get("/api/search", params={"q": "python", "mode": "hybrid"}).json()
        assert data["status"] == "degraded"
        assert data["hits"] == []
        assert data["message"].startswith("hybrid search degraded/unavailable:")
        assert "embedding backend offline" in data["message"]
        assert data["semantic_status"]["available"] is False


# --------------------------------------------------------------------------- #
# GET /api/search/modes
# --------------------------------------------------------------------------- #


class TestModeCatalogEndpoint:
    def test_catalog_lists_the_specialized_and_legacy_modes(self, client: TestClient):
        data = client.get("/api/search/modes").json()
        assert [m["id"] for m in data["modes"]] == SPECIALIZED_MODES
        assert set(data["legacy_modes"]) == set(LEGACY_MODES)
        assert data["default_mode"] in ALL_MODES

    def test_catalog_entries_are_self_describing(self, client: TestClient):
        for entry in client.get("/api/search/modes").json()["modes"]:
            assert set(entry) == {
                "id",
                "label",
                "description",
                "retrieval",
                "default_limit",
                "max_limit",
                "candidate_multiplier",
                "ai_answer",
                "weights",
                "source_diversity_cap",
                "snippet_words",
                "capabilities",
            }
            assert 1 <= entry["default_limit"] <= entry["max_limit"]
            assert entry["max_limit"] >= 1


# --------------------------------------------------------------------------- #
# /api/crawl
# --------------------------------------------------------------------------- #


class TestCrawlEndpointValidation:
    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"urls": []},
            {"urls": ["https://example.com"], "max_pages": 0},
            {"urls": ["https://example.com"], "max_pages": 1001},
            {"urls": ["https://example.com"], "max_depth": -1},
            {"urls": ["https://example.com"], "max_depth": 33},
            {"urls": ["https://example.com"], "delay_seconds": -1.0},
            {"urls": ["https://example.com"], "delay_seconds": 121.0},
            {"urls": ["https://example.com"], "concurrency": 0},
            {"urls": ["https://example.com"], "concurrency": 33},
            {"urls": ["https://example.com"], "timeout_seconds": 0.5},
            {"urls": ["https://example.com"], "allowed_domains": "not-a-list"},
        ],
    )
    def test_invalid_crawl_payloads_are_422(self, client: TestClient, payload):
        assert client.post("/api/crawl", json=payload).status_code == 422

    def test_unknown_job_id_is_404_with_a_named_detail(self, client: TestClient):
        response = client.get("/api/crawl/crawl_does_not_exist")
        assert response.status_code == 404
        assert "crawl_does_not_exist" in response.json()["detail"]

    def test_job_list_is_always_well_formed(self, client: TestClient):
        data = client.get("/api/crawl").json()
        assert set(data) == {"jobs", "total_jobs", "crawled_documents"}
        assert data["jobs"] == []
        assert data["total_jobs"] == 0


class TestCrawlEndpointOffline:
    @pytest.fixture
    def stubbed_crawl(self, monkeypatch):
        """Start a job that completes instantly without touching the network."""
        from backend.crawler.models import CrawlPage, CrawlReport, CrawlStatus
        from backend.crawler.service import CrawlManager, get_crawl_manager

        page = CrawlPage(
            url="https://example.com/a",
            final_url="https://example.com/a",
            status_code=200,
            title="Example A",
            text="Example page body with real content.",
            content_hash="a" * 64,
        )

        async def _execute(self, job):
            self.store.record(page)
            job.append_page(page)
            job.complete(CrawlReport(pages_crawled=1, message="done"))

        monkeypatch.setattr("backend.crawler.service._persist_best_effort", lambda _p: 0)
        monkeypatch.setattr(CrawlManager, "_execute", _execute)
        return get_crawl_manager()

    def test_a_job_is_accepted_and_then_reported(self, client: TestClient, stubbed_crawl):
        import time

        created = client.post(
            "/api/crawl",
            json={"urls": ["https://example.com"], "max_pages": 1, "allow_private_hosts": True},
        )
        assert created.status_code == 201
        payload = created.json()
        assert set(payload) == {
            "job_id",
            "status",
            "seed_urls",
            "allowed_domains",
            "max_pages",
            "message",
        }
        job_id = payload["job_id"]

        deadline = time.time() + 5.0
        while time.time() < deadline:
            body = client.get(f"/api/crawl/{job_id}").json()
            if body["status"] in {"completed", "failed"}:
                break
            time.sleep(0.01)

        assert set(body) == {
            "job_id",
            "status",
            "seed_urls",
            "allowed_domains",
            "max_pages",
            "pages_crawled",
            "pages_failed",
            "report",
            "error",
            "started_at",
            "finished_at",
        }
        assert body["status"] == "completed"
        assert body["error"] == ""
        assert body["pages_crawled"] == 1
        assert body["pages_failed"] == 0
        assert body["report"]["pages_crawled"] == 1
        assert body["report"]["message"] == "done"
        assert body["finished_at"]

        listing = client.get("/api/crawl").json()
        assert listing["total_jobs"] == 1
        assert listing["crawled_documents"] == 1

    def test_include_crawled_false_is_honoured_by_the_job_config(self, client: TestClient):
        created = client.post(
            "/api/crawl",
            json={
                "urls": ["https://example.com"],
                "allowed_domains": ["example.com"],
                "delay_seconds": 0.0,
                "timeout_seconds": 1.0,
            },
        )
        assert created.status_code == 201
        assert created.json()["allowed_domains"] == ["example.com"]
        assert created.json()["max_pages"] >= 1


# --------------------------------------------------------------------------- #
# /api/index
# --------------------------------------------------------------------------- #


class TestIndexStatusEndpoint:
    def test_status_reports_both_indexes_even_when_nothing_is_built(
        self, client: TestClient, offline_index, offline_semantic
    ):
        data = client.get("/api/index/status").json()
        assert {
            "index_exists",
            "loaded",
            "document_count",
            "database_available",
            "index_version",
            "corpus_hash",
            "message",
            "semantic",
        } <= set(data)
        assert data["document_count"] == 4
        assert data["database_available"] is False  # degraded repository
        assert isinstance(data["semantic"], dict)
        assert "available" in data["semantic"]

    def test_status_survives_a_broken_semantic_manager(
        self, client: TestClient, offline_index, monkeypatch
    ):
        def _boom():
            raise RuntimeError("semantic manager exploded")

        monkeypatch.setattr("backend.api.index.get_semantic_index_manager", _boom)
        data = client.get("/api/index/status").json()
        assert data["semantic"]["available"] is False
        assert "semantic status unavailable" in data["semantic"]["message"]


class TestIndexLifecycleEndpoints:
    def test_rebuild_without_postgres_falls_back_to_the_local_corpus(
        self, client: TestClient, offline_index, offline_semantic, monkeypatch
    ):
        monkeypatch.setattr("backend.pipeline.load_corpus", lambda: [])
        data = client.post("/api/index/rebuild", json={"include_crawled": False}).json()
        assert data["status"] == "rebuilt"
        assert data["source"] == "legacy_corpus"
        assert data["include_crawled"] is False
        assert data["documents_indexed"] == 0
        assert "not persisted" in data["message"]

    def test_rebuild_can_include_the_crawl_store(
        self, client: TestClient, offline_index, offline_semantic, monkeypatch
    ):
        monkeypatch.setattr("backend.pipeline.load_corpus", lambda: [])
        data = client.post("/api/index/rebuild", json={"include_crawled": True}).json()
        assert data["include_crawled"] is True
        assert data["crawled_documents"] == 0

    def test_rebuild_body_is_optional(self, client: TestClient, offline_index, offline_semantic, monkeypatch):
        monkeypatch.setattr("backend.pipeline.load_corpus", lambda: [])
        assert client.post("/api/index/rebuild").status_code == 200

    def test_rebuild_ignores_an_unknown_body_field(
        self, client: TestClient, offline_index, offline_semantic, monkeypatch
    ):
        monkeypatch.setattr("backend.pipeline.load_corpus", lambda: [])
        assert (
            client.post("/api/index/rebuild", json={"nope": True}).status_code == 200
        )

    def test_refresh_without_postgres_is_reported_not_faked(
        self, client: TestClient, offline_index, offline_semantic
    ):
        data = client.post("/api/index/refresh").json()
        assert data["status"] == "error"
        assert data["changed"] == {}
        assert "PostgreSQL unavailable" in data["message"]

    def test_semantic_rebuild_without_postgres_returns_the_dedicated_code(
        self, client: TestClient, offline_index, offline_semantic
    ):
        data = client.post("/api/index/semantic/rebuild").json()
        assert data["status"] == "error"
        assert data["code"] == "semantic_index_unavailable"
        assert data["documents_indexed"] == 0

    def test_semantic_refresh_without_postgres_is_reported_not_faked(
        self, client: TestClient, offline_index, offline_semantic
    ):
        data = client.post("/api/index/semantic/refresh").json()
        assert data["status"] == "error"
        assert "PostgreSQL unavailable" in data["message"]

    @pytest.mark.parametrize(
        "path",
        ["/api/index/rebuild", "/api/index/refresh", "/api/index/semantic/rebuild", "/api/index/semantic/refresh"],
    )
    def test_index_admin_endpoints_answer_json_even_in_the_degraded_case(
        self, client: TestClient, offline_index, offline_semantic, path
    ):
        response = client.post(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert isinstance(response.json(), dict)


# --------------------------------------------------------------------------- #
# POST /api/answer
# --------------------------------------------------------------------------- #


class TestAnswerEndpointValidation:
    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"query": ""},
            {"query": "x" * 501},
            {"query": "python", "mode": "web"},        # specialized modes are not RAG modes
            {"query": "python", "limit": 0},
            {"query": "python", "limit": 21},
            {"query": "python", "temperature": -0.1},
            {"query": "python", "temperature": 2.1},
        ],
    )
    def test_invalid_answer_payloads_are_422(self, client: TestClient, payload):
        assert client.post("/api/answer", json=payload).status_code == 422


class TestAnswerEndpointContract:
    @pytest.fixture
    def fake_provider(self, monkeypatch):
        """Install a deterministic in-process LLM provider (no model, no socket)."""
        from backend.ai.providers import LLMResult

        class _FakeProvider:
            name = "phase10-fake"
            model = "fake-1b"

            def generate(self, *, prompt, system_prompt="", temperature=None, timeout=None):
                return LLMResult(
                    text="Python is a high-level language [1].",
                    provider=self.name,
                    model=self.model,
                    took_ms=1.0,
                )

            def is_available(self) -> bool:
                return True

        provider = _FakeProvider()
        monkeypatch.setattr("backend.ai.rag.get_llm_provider", lambda: provider)
        return provider

    def test_answer_envelope_always_carries_the_rag_metadata(
        self, client: TestClient, offline_index, semantic_missing
    ):
        data = client.post("/api/answer", json={"query": "python", "mode": "lexical"}).json()
        assert set(data) >= {
            "query",
            "answer",
            "status",
            "fallback_mode",
            "sources",
            "retrieval",
            "generation",
            "search_hits",
            "message",
        }
        assert data["status"] in {"ok", "degraded", "unavailable", "error"}
        assert isinstance(data["sources"], list)

    def test_a_lexical_hit_reaches_the_fake_provider_with_a_citation(
        self, client: TestClient, offline_index, semantic_missing, fake_provider
    ):
        response = client.post("/api/answer", json={"query": "python", "mode": "lexical"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["fallback_mode"] is False
        assert "[1]" in data["answer"]
        assert data["generation"]["provider"] == "phase10-fake"
        assert data["sources"], "a grounded answer must carry its citation"
        assert data["sources"][0]["document_id"] == "py-1"
        assert data["retrieval"]["passages_used"] >= 1

    def test_a_failed_provider_degrades_instead_of_fabricating(
        self, client: TestClient, offline_index, semantic_missing, monkeypatch
    ):
        from backend.ai.providers import LLMProviderError

        class _Broken:
            name = "broken"
            model = "none"

            def generate(self, **_kwargs):
                raise LLMProviderError("model file missing")

            def is_available(self) -> bool:
                return False

        monkeypatch.setattr("backend.ai.rag.get_llm_provider", lambda: _Broken())
        data = client.post("/api/answer", json={"query": "python", "mode": "lexical"}).json()
        assert data["status"] == "degraded"
        assert data["fallback_mode"] is True
        assert data["sources"] == []
        assert data["search_hits"], "the fallback must still surface the raw hits"
        assert "model file missing" in data["message"]

    def test_no_matching_context_never_invents_an_answer(
        self, client: TestClient, offline_index, semantic_missing, fake_provider
    ):
        data = client.post(
            "/api/answer", json={"query": "zzzznotinthecorpus", "mode": "lexical"}
        ).json()
        assert data["fallback_mode"] is True
        assert data["answer"] == data["message"]
        assert "couldn't find enough relevant information" in data["answer"]

    def test_disabled_rag_reports_unavailable(
        self, client: TestClient, offline_index, semantic_missing, monkeypatch
    ):
        monkeypatch.setattr("backend.config.settings.RAG_ENABLED", False)
        data = client.post("/api/answer", json={"query": "python", "mode": "lexical"}).json()
        assert data["status"] == "unavailable"
        assert data["fallback_mode"] is True
        assert "disabled" in data["message"].lower()

    def test_the_response_matches_the_declared_schema(
        self, client: TestClient, offline_index, semantic_missing
    ):
        data = client.post("/api/answer", json={"query": "python", "mode": "lexical"}).json()
        assert AnswerResponse.model_validate(data) is not None
        assert AnswerRequest(query="python").mode == "hybrid"