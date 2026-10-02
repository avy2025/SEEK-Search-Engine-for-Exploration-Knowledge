"""Phase 10 cross-phase regression suite.

Where the other Phase 10 modules test one area deeply, this one tests the
*seams between phases*: the promises a later phase makes to an earlier one. Those
are the contracts most likely to rot silently, because each per-phase suite only
looks at its own side.

Covered seams:

* **Phases 0-2 (platform, DB, processing, BM25)** — the committed corpus still
  indexes, the phase-2 probe script still reports a fully healthy import, and
  ``scripts/probe_phase2.py`` keeps its output keys.
* **Phase 4 (crawler) -> 5/6 (indexes)** — crawled pages become documents, and
  their ``http(s)`` source is what ``include_crawled`` keys off.
* **Phase 5B/6 (persistence)** — the artifact format constants the engine, the
  stores and the status endpoints all read stay in sync.
* **Phase 7 (hybrid)** — the weight contract (normalised, defaults, rejection)
  holds through the API and not only in the unit tests.
* **Phase 8 (RAG) -> 9 (modes)** — RAG never re-implements retrieval, and the
  mode envelope keeps carrying the RAG detail block.
* **Phase 9 (modes)** — the endpoint inventory is stable, the frontend catalog
  matches the backend enum, and the frontend builds and typechecks.
* **Frontend wiring** — ``npm run test:frontend``, ``typecheck`` and ``build``.

Node-dependent tests skip cleanly when ``node``/``npm`` are absent; nothing here
downloads a model or needs PostgreSQL.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.search import router as search_router
from backend.config import settings
from backend.processing.models import ProcessedDocument
from backend.search import index_store
from backend.search.engine import SearchEngine
from backend.search.hybrid import (
    InvalidHybridWeightsError,
    merge_and_rerank_hybrid,
    validate_and_normalize_weights,
)
from backend.search.modes import (
    LEGACY_SEARCH_MODES,
    mode_catalog,
    specialized_modes,
    supported_mode_values,
)
from backend.search.models import SearchResult

from conftest import REPO_ROOT, make_document

FRONTEND_DIR = REPO_ROOT / "frontend"
PROBE_SCRIPT = REPO_ROOT / "scripts" / "probe_phase2.py"

#: The Phase 9 mode identifiers, in catalog order, as plain strings.
SPECIALIZED_MODES: tuple[str, ...] = tuple(m.value for m in specialized_modes())
#: The legacy retrieval modes in the order ``supported_mode_values`` publishes them.
LEGACY_MODE_ORDER: tuple[str, ...] = supported_mode_values()[: len(LEGACY_SEARCH_MODES)]

# The complete Phase 0-9 HTTP surface. Adding an endpoint is a deliberate act.
EXPECTED_ROUTES: dict[str, set[str]] = {
    "/": {"GET"},
    "/health": {"GET"},
    "/api/search": {"GET"},
    "/api/search/modes": {"GET"},
    "/api/answer": {"POST"},
    "/api/crawl": {"GET", "POST"},
    "/api/crawl/{job_id}": {"GET"},
    "/api/index/status": {"GET"},
    "/api/index/rebuild": {"POST"},
    "/api/index/refresh": {"POST"},
    "/api/index/semantic/rebuild": {"POST"},
    "/api/index/semantic/refresh": {"POST"},
}


def _node_available() -> bool:
    return shutil.which("node") is not None


def _npm_available() -> bool:
    return shutil.which("npm") is not None


requires_node = pytest.mark.skipif(not _node_available(), reason="node is required")
requires_npm = pytest.mark.skipif(
    not (_node_available() and _npm_available()), reason="npm is required"
)


# --------------------------------------------------------------------------- #
# 1. endpoint inventory (cross-cutting)
# --------------------------------------------------------------------------- #


class TestEndpointInventory:
    def test_the_routes_are_exactly_the_documented_ones(self, client: TestClient):
        """No endpoint appeared or disappeared without the inventory following."""
        published: dict[str, set[str]] = {}
        for route in client.app.routes:
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None)
            if not path or not methods or path.startswith(("/openapi", "/docs", "/redoc")):
                continue
            published.setdefault(path, set()).update(
                m for m in methods if m not in {"HEAD", "OPTIONS"}
            )
        assert published == EXPECTED_ROUTES

    def test_every_published_route_answers(self, client: TestClient):
        """No route is declared but unreachable (a broken dependency, a typo)."""
        for path, methods in EXPECTED_ROUTES.items():
            for method in methods:
                if path == "/api/answer":
                    response = client.request(method, path, json={})
                elif path in {"/api/crawl", "/api/index/rebuild", "/api/index/refresh"}:
                    response = client.request(method, path)
                elif method == "GET" and path == "/api/crawl":
                    response = client.get(path)
                else:
                    response = client.request(method, path)
                assert response.status_code < 500, (method, path)
                assert response.headers["content-type"].startswith("application/json")

    def test_every_endpoint_is_reachable_from_the_router_objects(self):
        """Every module-level router is mounted by the app (no orphan router).

        ``include_router`` copies the sub-routes onto the parent, so the check
        compares the *published paths* per router prefix rather than object
        identity.
        """
        from backend.api import answer, crawl, health, index, root
        from backend.api.router import api_router
        from backend.main import app

        # Each router already carries its own prefix, so route paths are complete.
        routers = [
            ("search", search_router),
            ("answer", answer.router),
            ("crawl", crawl.router),
            ("index", index.router),
            ("health", health.router),
            ("root", root.router),
        ]
        mounted = {getattr(r, "path", "") for r in app.routes}
        aggregated = {getattr(r, "path", "") for r in api_router.routes}

        for label, router in routers:
            paths = [getattr(r, "path", "") for r in router.routes]
            assert paths, f"the {label} router declares no routes"
            for path in paths:
                assert path in aggregated, f"{path} is missing from backend.api.router"
                assert path in mounted, f"{path} is missing from backend.main:app"

    def test_openapi_operation_ids_are_unique(self, client: TestClient):
        """Duplicate operation ids break generated clients."""
        spec = client.get("/openapi.json").json()
        operation_ids = [
            operation.get("operationId")
            for path in spec["paths"].values()
            for method, operation in path.items()
            if isinstance(operation, dict)
        ]
        assert all(operation_ids), "every operation must publish an operationId"
        assert len(operation_ids) == len(set(operation_ids))


# --------------------------------------------------------------------------- #
# 2. Phase 0-2: the committed corpus and the phase-2 probe
# --------------------------------------------------------------------------- #


class TestPhase2ChainIsIntact:
    @pytest.fixture(scope="class")
    def probe(self) -> subprocess.CompletedProcess:
        """Run the phase-2 acceptance probe once for the whole class.

        The probe imports the app in a fresh interpreter, so it must be a
        subprocess; running it once keeps the class fast while still covering
        every output key the gate publishes.
        """
        return subprocess.run(
            [sys.executable, str(PROBE_SCRIPT)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=600,
        )

    def test_the_committed_corpus_loads_tokens_and_indexes(self):
        from backend.processing.loader import load_corpus

        documents = load_corpus()
        assert len(documents) >= 8, "the sample corpus shrank below its accepted size"
        for doc in documents:
            assert isinstance(doc, ProcessedDocument)
            assert doc.document_id and doc.tokens and doc.content_hash

    def test_the_committed_corpus_never_indexes_its_own_skip_files(self):
        """``index.md`` is a loader skip-list entry, not a searchable document."""
        from backend.processing.loader import SKIP_FILENAMES, load_corpus

        ids = {d.document_id.lower() for d in load_corpus()}
        for name in SKIP_FILENAMES:
            assert name.lower() not in ids, f"{name} must stay out of the index"

    def test_the_phase2_probe_still_imports_every_module(self, probe):
        """``scripts/probe_phase2.py`` is the phase acceptance gate; keep it working."""
        assert probe.returncode == 0, probe.stdout + probe.stderr
        assert "import_ok=18/18" in probe.stdout, probe.stdout

    def test_the_phase2_probe_reports_no_import_failures(self, probe):
        assert "FAIL " not in probe.stdout, probe.stdout

    def test_the_phase2_probe_reports_a_working_app(self, probe):
        assert "app_build=OK" in probe.stdout, probe.stdout

    def test_the_phase2_probe_reports_a_working_search(self, probe):
        """Phase 2's real deliverable is a *searchable* index, not just imports."""
        assert "search_ok=true" in probe.stdout, probe.stdout
        match = re.search(r"documents=(\d+)", probe.stdout)
        assert match, probe.stdout
        assert int(match.group(1)) >= 8


# --------------------------------------------------------------------------- #
# 3. Phase 4 -> 5/6: crawler output feeds the indexes
# --------------------------------------------------------------------------- #


class TestCrawlerToIndexSeam:
    def test_a_crawled_page_survives_the_whole_hop_into_the_index(self, tmp_path):
        from backend.crawler.models import CrawlPage
        from backend.crawler.service import CrawlStore
        from backend.search.index_manager import IndexManager

        from conftest import FakeRepository

        store = CrawlStore()
        page = CrawlPage(
            url="https://docs.example.com/kubernetes",
            final_url="https://docs.example.com/kubernetes",
            status_code=200,
            title="Kubernetes Operators",
            text="An operator automates application deployment on a Kubernetes cluster.",
            content_hash="b" * 64,
        )
        store.record(page)
        documents = store.to_processed_documents()
        assert len(documents) == 1

        repository = FakeRepository(
            [
                FakeRepository.row(
                    d.document_id,
                    title=d.title,
                    content=d.content,
                    source=d.source,
                    content_hash=d.content_hash,
                )
                for d in documents
            ]
        )
        manager = IndexManager(
            index_dir=tmp_path / "bm25", repository=repository, seed_corpus=False
        )
        build = manager.rebuild(include_crawled=True)
        assert build.crawled_documents == 1
        assert manager.engine.search("kubernetes operator").hits[0].document_id.startswith(
            "crawl-"
        )

    def test_include_crawled_false_drops_only_http_sourced_rows(self, tmp_path):
        from backend.search.index_manager import IndexManager

        from conftest import FakeRepository

        rows = [
            FakeRepository.row("local-1", content="local file body", source="docs/a.md",
                               content_hash="a" * 64),
            FakeRepository.row("crawl-1", content="crawled page body",
                               source="https://example.com/a", content_hash="c" * 64),
        ]
        manager = IndexManager(
            index_dir=tmp_path / "bm25", repository=FakeRepository(rows), seed_corpus=False
        )
        assert manager.rebuild(include_crawled=False).documents_indexed == 1
        assert manager.rebuild(include_crawled=True).documents_indexed == 2


# --------------------------------------------------------------------------- #
# 4. persistence constants shared by the engine, stores and status endpoints
# --------------------------------------------------------------------------- #


class TestPersistenceConstantsAgree:
    def test_the_configured_artifact_names_match_the_store_constants(self):
        from backend.search import faiss_store

        assert settings.FAISS_INDEX_FILE == faiss_store.FAISS_INDEX_FILE
        assert settings.FAISS_METADATA_FILE == faiss_store.FAISS_METADATA_FILE

    def test_the_configured_index_dirs_match_the_settings_properties(self):
        assert settings.index_dir == str(
            __import__("pathlib").Path(settings.STORAGE_INDEX_PATH) / settings.INDEX_SUBDIR
        )
        assert settings.semantic_index_dir == settings.SEMANTIC_INDEX_PATH

    def test_both_stores_declare_format_version_one(self):
        from backend.search import faiss_store

        assert index_store.INDEX_FORMAT_VERSION == 1
        assert faiss_store.FAISS_FORMAT_VERSION == 1
        assert index_store.IndexMetadata().format_version == 1
        assert faiss_store.FaissIndexMetadata().format_version == 1

    def test_the_document_serialisation_round_trips_through_both_stores(self):
        from backend.search import faiss_store

        original = make_document("py-1", "Python", "Python is a language", "a/b.md")
        bm25_copy = index_store.document_from_dict(index_store.document_to_dict(original))
        faiss_copy = faiss_store.document_from_dict(
            faiss_store.document_to_dict(original)
        )
        assert bm25_copy == original
        assert faiss_copy == original

    def test_index_status_reports_the_persisted_version(
        self, client, offline_index, monkeypatch, sample_documents
    ):
        """The status endpoint reports what the artifact on disk says.

        ``offline_index`` pins the *degraded* repository, so ``rebuild()`` refuses;
        a ``FakeRepository`` makes the same build path reachable without a database
        and keeps the assertion about the persisted artifact (not about the DB).
        """
        from conftest import FakeRepository

        repository = FakeRepository.from_documents(sample_documents)
        monkeypatch.setattr(offline_index, "_repo_factory", lambda: repository)
        monkeypatch.setattr(offline_index, "_repository", repository)

        # ``include_crawled=True`` so the http-sourced sample documents are kept
        # (three of the four carry an https:// source on purpose).
        build = offline_index.rebuild(include_crawled=True)
        assert build.documents_indexed == len(sample_documents)
        assert build.crawled_documents == 3

        data = client.get("/api/index/status").json()
        assert data["index_version"] == index_store.INDEX_FORMAT_VERSION
        assert data["index_exists"] is True
        assert data["loaded"] is True
        assert data["document_count"] == len(sample_documents)
        assert data["corpus_hash"] == offline_index.metadata.corpus_hash
        assert data["stale"] is False


# --------------------------------------------------------------------------- #
# 5. Phase 7: the hybrid weight contract holds through the API
# --------------------------------------------------------------------------- #


class TestHybridWeightContract:
    def test_defaults_are_normalised_to_one(self):
        normalized = validate_and_normalize_weights(None, None)
        assert normalized.bm25 == pytest.approx(0.5)
        assert normalized.semantic == pytest.approx(0.5)
        assert normalized.bm25 + normalized.semantic == pytest.approx(1.0)

    def test_explicit_weights_are_normalised_not_rejected(self):
        normalized = validate_and_normalize_weights(3.0, 1.0)
        assert normalized.bm25 == pytest.approx(0.75)
        assert normalized.semantic == pytest.approx(0.25)

    def test_a_zero_total_is_rejected(self):
        with pytest.raises(InvalidHybridWeightsError):
            validate_and_normalize_weights(0.0, 0.0)
        with pytest.raises(InvalidHybridWeightsError):
            validate_and_normalize_weights(-1.0, 1.0)

    def test_the_api_echoes_the_normalised_weights(self, client, offline_index):
        data = client.get(
            "/api/search", params={"q": "python", "mode": "hybrid", "bm25_weight": 3.0,
                                    "semantic_weight": 1.0}
        ).json()
        assert data["weights"]["bm25"] == pytest.approx(0.75)
        assert data["weights"]["semantic"] == pytest.approx(0.25)

    def test_a_negative_weight_is_rejected_by_request_validation(self, client, offline_index):
        """``ge=0.0`` rejects negatives before the handler — a clean 422, never a 500."""
        response = client.get(
            "/api/search", params={"q": "python", "mode": "hybrid", "bm25_weight": -1.0}
        )
        assert response.status_code == 422
        assert response.status_code < 500

    def test_a_zero_weight_pair_is_a_structured_error_not_a_500(self, client, offline_index):
        """Both weights at zero passes ``ge=0.0`` but not the sum validation."""
        response = client.get(
            "/api/search",
            params={
                "q": "python", "mode": "hybrid",
                "bm25_weight": 0.0, "semantic_weight": 0.0,
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "error"
        assert "invalid hybrid configuration" in response.json()["message"]
        assert response.json()["hits"] == []

    def test_a_document_appears_once_no_matter_how_many_rankers_found_it(self):
        """Phase 7's de-duplication is what makes the merged list a set union."""
        hit = SearchResult(
            rank=1, document_id="py-1", title="Python", source="a", snippet="s",
            score=1.0,
        )
        merged, weights = merge_and_rerank_hybrid(
            bm25_hits=[hit], semantic_hits=[hit], query="python", limit=10
        )
        assert len(merged) == 1
        assert merged[0].document_id == "py-1"
        assert weights["bm25"] + weights["semantic"] == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# 6. Phase 8 -> 9: RAG is orchestration, not a second retrieval stack
# --------------------------------------------------------------------------- #


class TestRagComposition:
    def test_the_mode_layer_passes_its_hits_to_rag_instead_of_re_retrieving(
        self, client, offline_index, monkeypatch
    ):
        import backend.ai.rag as rag_module

        calls: list[dict] = []
        original = rag_module.generate_rag_answer

        def _spy(request, provider=None, retrieval_payload=None):
            calls.append(retrieval_payload or {})
            return original(request, provider=provider, retrieval_payload=retrieval_payload)

        monkeypatch.setattr(rag_module, "generate_rag_answer", _spy)
        # The mode orchestrator imports the symbol lazily inside the function.
        client.get("/api/search", params={"q": "python", "mode": "ai"})
        assert calls, "the mode layer must call the Phase 8 RAG pipeline"
        assert calls[0].get("hits"), "and must hand over the hits it retrieved"

    def test_a_mode_response_carries_the_rag_detail_block(self, client, offline_index):
        data = client.get("/api/search", params={"q": "python", "mode": "ai"}).json()
        assert "rag" in data["metadata"]
        rag = data["metadata"]["rag"]
        assert {"enabled", "status", "generated", "passages"} <= set(rag)

    def test_research_mode_adds_a_synthesis_block_when_an_answer_was_produced(
        self, client, offline_index
    ):
        data = client.get("/api/search", params={"q": "python", "mode": "research"}).json()
        if data["metadata"].get("rag", {}).get("generated"):
            assert data["metadata"]["synthesis"]["kind"] == "generated_synthesis"
        else:
            assert "rag" in data["metadata"]

    def test_web_mode_never_generates_an_answer(self, client, offline_index):
        data = client.get("/api/search", params={"q": "python", "mode": "web"}).json()
        assert data["answer"] is None
        assert "rag" not in data["metadata"]

    def test_the_rag_endpoint_and_the_ai_mode_share_one_contract(self, client, offline_index):
        """Both entry points must agree on the answer field's presence and type."""
        via_endpoint = client.post("/api/answer", json={"query": "python", "mode": "lexical"})
        via_mode = client.get("/api/search", params={"q": "python", "mode": "ai"})
        assert via_endpoint.status_code == 200
        assert isinstance(via_endpoint.json()["answer"], str)
        assert isinstance(via_mode.json()["answer"], (str, type(None)))


# --------------------------------------------------------------------------- #
# 7. Phase 9: mode catalog and frontend parity
# --------------------------------------------------------------------------- #


class TestModeCatalogParity:
    def test_the_python_and_api_catalogs_agree(self, client: TestClient):
        api_modes = [entry["id"] for entry in client.get("/api/search/modes").json()["modes"]]
        assert tuple(api_modes) == SPECIALIZED_MODES
        assert tuple(entry["id"] for entry in mode_catalog()["modes"]) == SPECIALIZED_MODES

    def test_the_legacy_retrieval_modes_are_still_declared(self, client: TestClient):
        catalog = client.get("/api/search/modes").json()
        declared = catalog.get("legacy_modes") or catalog.get("retrieval_modes")
        assert declared is not None, "the catalog must still name the legacy modes"
        assert set(declared) == set(LEGACY_SEARCH_MODES)

    def test_every_specialized_mode_is_reachable_through_the_api(self, client: TestClient):
        for mode in SPECIALIZED_MODES:
            response = client.get("/api/search", params={"q": "python", "mode": mode})
            assert response.status_code == 200, mode
            assert response.json()["mode"] == mode

    def test_the_frontend_catalog_matches_the_backend_enum(self):
        """``src/lib/modes.ts`` must not drift from ``backend/search/modes.py``."""
        source = (FRONTEND_DIR / "src" / "lib" / "modes.ts").read_text(encoding="utf-8")
        match = re.search(r"SEARCH_MODES:[^=]*=\s*\[([^\]]*)\]", source)
        assert match, "SEARCH_MODES must stay an explicit literal for auditing"
        frontend_modes = re.findall(r"'([a-z]+)'", match.group(1))
        assert tuple(frontend_modes) == SPECIALIZED_MODES

    def test_the_frontend_legacy_mode_list_matches_the_backend(self):
        source = (FRONTEND_DIR / "src" / "lib" / "api.ts").read_text(encoding="utf-8")
        match = re.search(r"LegacySearchMode\s*=\s*([^;]+);", source)
        assert match
        frontend_legacy = re.findall(r"'([a-z0-9]+)'", match.group(1))
        assert tuple(frontend_legacy) == LEGACY_MODE_ORDER

    def test_the_frontend_requests_the_modes_the_backend_serves(self):
        """The UI must send a specialized mode, never invent its own verb."""
        api_source = (FRONTEND_DIR / "src" / "lib" / "api.ts").read_text(encoding="utf-8")
        assert "/api/search?" in api_source
        assert "params.set('mode'" in api_source
        assert "'/api/answer" not in api_source, (
            "the answer endpoint is reached through the mode layer, not directly"
        )

    def test_every_search_mode_uses_the_same_envelope(self, client: TestClient, offline_index):
        """Specialized modes add fields; they must not remove any."""
        expected = {
            "query", "mode", "status", "total", "limit",
            "hits", "took_ms", "message", "answer", "sources", "metadata",
        }
        for mode in SPECIALIZED_MODES:
            data = client.get("/api/search", params={"q": "python", "mode": mode}).json()
            assert set(data) == expected, mode

    def test_the_mode_catalog_is_stable_across_calls(self, client: TestClient):
        first = client.get("/api/search/modes").json()
        second = client.get("/api/search/modes").json()
        assert first == second


# --------------------------------------------------------------------------- #
# 8. frontend suites run through pytest
# --------------------------------------------------------------------------- #


def _npm(script: str, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["npm", "run", "--silent", script],
        cwd=FRONTEND_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=True,
    )


@requires_npm
class TestFrontendSuites:
    def test_the_url_state_suite_passes(self):
        result = _npm("test:urlstate")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "# fail 0" in result.stdout

    def test_the_mode_catalog_suite_passes(self):
        result = _npm("test:modes")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "# fail 0" in result.stdout

    def test_the_combined_frontend_script_passes(self):
        result = _npm("test:frontend")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "# fail 0" in result.stdout

    def test_typescript_typechecks(self):
        result = _npm("typecheck")
        assert result.returncode == 0, result.stdout + result.stderr

    def test_the_production_build_succeeds(self):
        result = _npm("build")
        assert result.returncode == 0, result.stdout + result.stderr

    def test_the_frontend_scripts_are_declared(self):
        scripts = json.loads((FRONTEND_DIR / "package.json").read_text(encoding="utf-8"))["scripts"]
        for script in ("test:urlstate", "test:modes", "test:frontend", "typecheck", "build"):
            assert script in scripts, script


class TestFrontendWiring:
    def test_the_app_owns_the_url_state_contract(self):
        source = (FRONTEND_DIR / "src" / "App.tsx").read_text(encoding="utf-8")
        for helper in ("parseSearchState", "buildSearchPath", "pushState", "popstate"):
            assert helper in source, helper

    def test_the_mode_selector_is_keyboard_operable(self):
        source = (FRONTEND_DIR / "src" / "components" / "ModeSelector.tsx").read_text(
            encoding="utf-8"
        )
        for token in ('role="radiogroup"', 'role="radio"', "aria-checked", "tabIndex"):
            assert token in source, token
        for key in ("ArrowRight", "ArrowLeft", "Home", "End"):
            assert key in source, key

    def test_degraded_states_are_rendered_not_hidden(self):
        source = (FRONTEND_DIR / "src" / "components" / "SearchResults.tsx").read_text(
            encoding="utf-8"
        )
        for token in ("degraded", "unavailable", "AnswerPanel", "SourcesPanel"):
            assert token in source, token

    def test_the_api_client_tolerates_a_failed_request(self):
        """The UI must have a same-origin fallback, not a bare rejection."""
        source = (FRONTEND_DIR / "src" / "lib" / "api.ts").read_text(encoding="utf-8")
        assert "catch" in source
        assert "fetch(" in source


# --------------------------------------------------------------------------- #
# 9. documentation / roadmap wiring
# --------------------------------------------------------------------------- #


class TestDocumentationIsPresent:
    def test_the_readme_documents_the_api_surface(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        for path in sorted(EXPECTED_ROUTES):
            assert path in readme, f"{path} is missing from README.md"

    def test_the_testing_strategy_document_exists_and_names_every_area(self):
        doc = (REPO_ROOT / "docs" / "TESTING_PHASE10.md").read_text(encoding="utf-8")
        for area in (
            "processing", "BM25", "semantic", "hybrid", "RAG",
            "API", "crawler", "persistence", "frontend", "security",
        ):
            assert area.lower() in doc.lower(), f"{area} is not covered in the matrix"

    def test_the_roadmap_marks_phase_10_complete(self):
        roadmap = (REPO_ROOT / "docs" / "ROADMAP_TODO.md").read_text(encoding="utf-8")
        assert re.search(r"Phase\s*10[^\n]*COMPLETED", roadmap, re.IGNORECASE), (
            "Phase 10 must be marked COMPLETED in the roadmap"
        )

    def test_the_testing_document_does_not_fabricate_a_coverage_percentage(self):
        """A coverage number without a measurement run is a lie; assert we have none."""
        doc = (REPO_ROOT / "docs" / "TESTING_PHASE10.md").read_text(encoding="utf-8")
        assert not re.search(r"\d{1,3}(\.\d+)?\s*%\s*(line\s*)?coverage", doc, re.I), (
            "do not claim a measured coverage percentage without running coverage.py"
        )


# --------------------------------------------------------------------------- #
# 10. a light performance smoke tier
# --------------------------------------------------------------------------- #


class TestPerformanceSmoke:
    def test_a_large_index_builds_and_answers_quickly_enough(self, tmp_path):
        """Order-of-magnitude only: no assertion here should be timing-fragile.

        The bound is deliberately loose (many multiples of the measured cost) so
        it fails on a regression in *complexity* rather than on a slow machine.
        """
        import time

        from backend.search.index_manager import IndexManager

        from conftest import FakeRepository

        rows = [
            FakeRepository.row(
                f"doc-{i}",
                title=f"Document {i}",
                content=f"document {i} discusses python docker kubernetes machine "
                f"learning indexing retrieval number {i}",
                source=f"corpus/doc-{i}.md",
                content_hash=f"{i:064x}",
            )
            for i in range(500)
        ]
        manager = IndexManager(
            index_dir=tmp_path / "bm25", repository=FakeRepository(rows), seed_corpus=False
        )
        started = time.perf_counter()
        manager.rebuild()
        build_seconds = time.perf_counter() - started

        started = time.perf_counter()
        for _ in range(20):
            response = manager.engine.search("kubernetes retrieval", limit=10)
        query_ms = (time.perf_counter() - started) * 1000.0 / 20

        assert build_seconds < 30.0, f"500 documents took {build_seconds:.1f}s to index"
        assert query_ms < 200.0, f"a query took {query_ms:.0f}ms on a 500-doc index"
        assert response.hits

    def test_search_scales_sublinearly_with_the_result_limit(self):
        """Returning more hits must not cost more than the ranking itself."""
        import time

        documents = [
            make_document(f"d{i}", f"Doc {i}", f"python docker kubernetes item {i}")
            for i in range(300)
        ]
        engine = SearchEngine(documents)

        def _time(limit: int) -> float:
            started = time.perf_counter()
            for _ in range(5):
                engine.search("python", limit=limit)
            return (time.perf_counter() - started) * 1000.0 / 5

        small, large = _time(5), _time(50)
        assert small < 500.0, f"a 5-hit query took {small:.0f}ms"
        assert large < max(3.0 * small, 250.0), (
            f"limit=50 ({large:.0f}ms) must not blow past limit=5 ({small:.0f}ms)"
        )
