# SEEK – 14-Phase Implementation Roadmap & TODO Tracker

> **Current Phase**: Phase 10 (Automated Testing Suite) - **COMPLETED**  
> **Next Recommended Phase**: Phase 11 (Docker Hardening & Optimization)

---

## Phase Breakdown & Status

### [x] Phase 0: Planning & Repository Architecture
- [x] Analyze SEEK SRS completely and document functional/non-functional requirements.
- [x] Define module boundaries, data flow, and DB schema.
- [x] Initialize repository directory structure (`frontend/`, `backend/`, `data/`, `indexes/`, `docs/`, `docker/`).
- [x] Establish environment strategy (`.env.example`) and dependency manifests (`requirements.txt`).
- [x] Author TODO roadmap and architectural specification.

---

### [x] Phase 1: Foundation Setup & Docker Stack (COMPLETED)
- [x] Initialize FastAPI backend skeleton with health check (`GET /health`) & meta (`GET /`) endpoints.
- [x] Initialize React + TypeScript + Vite + Tailwind CSS project in `frontend/`.
- [x] Implement backend health indicator in UI (Connected / Disconnected) with graceful error handling.
- [x] Create Dockerfile for backend (`docker/Dockerfile.backend`) and frontend (`docker/Dockerfile.frontend`).
- [x] Validate Docker Compose local service orchestration (`docker-compose.yml`).

---

### [x] Phase 2: Search MVP (Local Corpus) (COMPLETED)
- [x] Create initial local text document corpus in `data/sample_corpus/`.
- [x] Setup PostgreSQL database models using SQLAlchemy/Alembic.
- [x] Implement initial BM25 lexical index builder in `backend/search/`.
- [x] Implement `/api/search` endpoint returning preliminary JSON search results.

---

### [x] Phase 3: UI Implementation (COMPLETED)
- [x] Build clean SEEK homepage search component.
- [x] Build search results page (displaying titles, domain badges, snippets, relevance scores).
- [x] Implement query loading states, error boundaries, and empty result handling.
- [x] Connect React UI to FastAPI `/api/search` endpoint.
- [x] Configurable API base URL (`VITE_API_BASE_URL`) + single frontend API client.
- [x] URL-query sync (`/?q=…`) with back/forward support; browser-level sanity checks.

---

### [x] Phase 4: Controlled Web Crawler (COMPLETED)
- [x] Build async crawler module (`backend/crawler/`) using `httpx` and `asyncio`.
- [x] Implement URL normalization/scoping and dedup (URL + content hash).
- [x] Implement domain allowlist validator and `robots.txt` rule parser.
- [x] Implement HTML content parser (`BeautifulSoup`) to extract main text body.
- [x] Implement text chunking and document hash deduplication.
- [x] Expose crawl job API (`POST /api/crawl`, `GET /api/crawl`, `GET /api/crawl/{job_id}`).
- [x] Fold crawled pages into the BM25 index (`POST /api/index/rebuild`).
- [x] Crawler test suite (offline fixture) — 45 tests total across all phases.

---

### [x] Phase 5: Persistent Indexing Pipeline (COMPLETED)
- [x] Make PostgreSQL the canonical document source (repository `list_all`, idempotent `persist_corpus`, per-document SHA-256 `content_hash`).
- [x] Persist BM25 index to `indexes/bm25/` — `index.pkl` + `metadata.json`, atomic writes, `INDEX_FORMAT_VERSION = 1`.
- [x] Build `IndexManager` lifecycle: full `rebuild()`, incremental `refresh()` (new/modified/deleted change detection), `status()`.
- [x] Resilient startup loading (persisted artifact → auto-rebuild from PG → empty) wired into the FastAPI `lifespan`.
- [x] Add `POST /api/index/refresh` and `GET /api/index/status`; keep legacy in-memory rebuild fallback when Postgres is down.
- [x] Phase 5B regression suite (`tests/test_index_persistence_phase5b.py`) — 67 backend tests total pass.

---

### [x] Phase 6: Semantic Search (Local ML Embeddings) (COMPLETED)
- [x] Integrate `SentenceTransformers` (`all-MiniLM-L6-v2`) in `backend/search/` (`backend/search/embeddings.py` — lazy, thread-safe `EmbeddingGenerator`).
- [x] Build vector embedding generator for document chunks (L2-normalised, batch encoded).
- [x] Implement FAISS vector index store in `indexes/faiss_index.bin` (`backend/search/faiss_store.py` — atomic writes, `FAISS_FORMAT_VERSION = 1`).
- [x] Persist FAISS + metadata (`faiss_metadata.json`) and build the `SemanticIndexManager` lifecycle (full `rebuild`, change-detection `refresh`, `load_on_startup`, `status`) in `backend/search/semantic.py`.
- [x] Expose semantic similarity search mode in backend API (`GET /api/search?mode=semantic`, structured `semantic` status block; `POST /api/index/semantic/rebuild` / `/refresh`); graceful degradation when the ML stack is unavailable (never silently falls back to BM25).
- [x] Keep BM25 lexical mode fully working (default `mode=lexical`).
- [x] Phase 6 regression suite (`tests/test_semantic_search_phase6.py` — offline fakes + live model + live PostgreSQL tiers) — **97 backend tests total pass**.

---

### [x] Phase 7: Hybrid Ranking Engine (COMPLETED)
- [x] Implement candidate merging algorithm combining BM25 lexical and semantic vector candidates.
- [x] Implement weighted hybrid scoring formula ($\text{Hybrid Score} = w_{\text{BM25}} \cdot \text{BM25}_{\text{norm}} + w_{\text{semantic}} \cdot \text{Semantic}_{\text{norm}}$) with deterministic Min-Max normalization.
- [x] Implement document deduplication by canonical `document_id` and safe case-insensitive snippet term highlighter (`<mark>...</mark>`).
- [x] Expose `mode=hybrid` endpoint (`GET /api/search?mode=hybrid&bm25_weight=...&semantic_weight=...`) with structured weights, explicit degraded/unavailable status reporting, and candidate limits.
- [x] Phase 7 test suite (`tests/test_hybrid_phase7.py`) — **104 backend tests total pass**.

---

### [x] Phase 8: AI / RAG Answer Generation (COMPLETED)
- [x] Implement passage selector to pick top $K$ relevant context chunks with character caps.
- [x] Implement local/free LLM context prompt builder and swappable `LLMProvider` abstraction (`FakeLLMProvider`, `OllamaLLMProvider`, `HuggingFaceLLMProvider`).
- [x] Expose `POST /api/answer` endpoint for AI synthesized answers with source citations.
- [x] Ensure full fallback to standard search hits if RAG is disabled, context is insufficient, or LLM fails/times out.
- [x] Phase 8 test suite (`tests/test_rag_phase8.py`) — **118 backend tests total pass**.

---

### [x] Phase 9: Specialized Search Modes (COMPLETED)
- [x] Define the controlled mode enum + `ModeSpec` registry in `backend/search/modes.py` (`web`, `ai`, `research`, `code`) with case-insensitive validation and a clean HTTP 422 for unknown values.
- [x] Add the orchestration layer `backend/api/mode_orchestrator.py` that delegates to the existing BM25/semantic/hybrid handlers and the Phase 8 RAG pipeline — no duplicated retrieval or scoring.
- [x] Expose the modes on `GET /api/search` through one explicit envelope (`{query, mode, status, total, limit, hits, took_ms, message, answer, sources, metadata}`) with `ok` / `degraded` / `unavailable` status.
- [x] Implement backend mode-specific ranking behaviour: candidate widening, lexical-leaning Code Docs weights, documentation-source priority, technical identifier expansion, source diversification and richer snippets — all reading centralised `MODE_*` / `RESEARCH_*` / `CODE_*` settings.
- [x] Publish the machine-readable mode catalog at `GET /api/search/modes`.
- [x] Add the polished, responsive, keyboard-accessible mode selector to the React UI, with the mode persisted in the URL (`?q=python&mode=research`) and back/forward navigation honoured.
- [x] Add mode-specific result rendering: grounded answer panel, cited sources panel, code excerpts, and explicit degraded/unavailable banners (nothing fabricated).
- [x] Phase 9 test suite (`tests/test_search_modes_phase9.py`, 108 tests covering items A–P) plus the frontend URL-state suite (`npm run test:urlstate`) — **226 tests pass**.

---

### [x] Phase 10: Automated Testing Suite (COMPLETED)
- [x] Documented cross-phase coverage matrix (`docs/TESTING_PHASE10.md`) mapping feature → existing tests → missing coverage → Phase 10 tests, with **no** fabricated coverage percentage.
- [x] Shared offline fixtures in `tests/conftest.py` (corpus docs, `FakeRepository`, degraded repository, isolated `IndexManager`/semantic managers, semantic doubles, hermetic `TestClient`) plus process-singleton isolation.
- [x] `tests/test_unit_phase10.py` — unit coverage for tokenization, snippets, corpus loading, pipeline, query processing, BM25 scoring/alignment, normalisation, weight validation, highlighting, hybrid merge, RAG models/prompt/passages/providers/orchestrator, crawler URL/robots/extract/fetch/store/manager, index+FAISS artifact metadata and settings.
- [x] `tests/test_api_phase10.py` — every published route: routing, validation, response contracts, mode catalog endpoint, crawl endpoint, index status/lifecycle, answer endpoint, plus the full **mode × index-state × query matrix**.
- [x] `tests/test_integration_phase10.py` — corpus → index end to end, persistence through the repository, the BM25 and FAISS persistence matrices (valid / missing / corrupt / stale / metadata mismatch / atomic-write failure / interrupted write) and failure combinations.
- [x] `tests/test_security_phase10.py` — query input is never interpreted, highlight escaping order, crawl URL/SSRF safety and seed validation, no-fabricated-answers guarantees, repository hygiene.
- [x] `tests/test_regression_phase10.py` — cross-phase seams (Phase 2 chain + `scripts/probe_phase2.py` gate, crawler → index hop, persistence constants, hybrid weight contract, RAG composition, mode catalog/frontend parity), frontend suites driven through pytest, documentation wiring and a non-fragile performance smoke tier.
- [x] Frontend coverage reusing the existing `node:test` pattern — `frontend/tests/modes.test.mjs` (mode catalog parity) plus a combined `npm run test:frontend` script, both driven from pytest.
- [x] Documented deliberate gaps (live PostgreSQL via `SEEK_TEST_DATABASE_URL`, live embedding model, load testing, browser E2E, coverage measurement) instead of hiding them.
- [x] Fix the defects the new tests exposed (BM25 score/document misalignment and vocabulary count, tokenizer `snippet_tokens` `NameError`, loader skip-list matching, artifact metadata version validation, structured semantic/crawl degradation instead of HTTP 500, crawl seed URL validation) — no product features added.
- [x] Verification gate: `python -m pytest -q`, `python scripts/probe_phase2.py`, `npm run test:frontend`, `npm run typecheck`, `npm run build` all pass.

---

### [x] Phase 11: Docker Hardening & Optimization
- [x] Optimize multi-stage Docker build files for fast container builds.
- [x] Setup volume persistence for PostgreSQL data and vector index directories.
- [x] Add container health checks and restart policies.

---

### [ ] Phase 12: Cloud Deployment Preparation (Optional)
- [ ] Document free-tier cloud deployment steps (Render / Railway / Fly.io / Educational Cloud).
- [ ] Configure production CORS and environment variable overrides.

---

### [ ] Phase 13: Evaluation & Benchmarking
- [ ] Benchmark query latency and memory consumption.
- [ ] Evaluate search relevance using sample test query sets.

---

### [ ] Phase 14: Documentation & Final Polish
- [ ] Finalize `README.md` setup instructions.
- [ ] Create system architecture diagrams and API endpoint documentation.
