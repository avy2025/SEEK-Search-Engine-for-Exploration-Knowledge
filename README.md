# SEEK – Search Engine for Exploration & Knowledge

> A Genuine, Modular, Docker-First Search Engine with Controlled Crawling, Lexical & Semantic Retrieval, Hybrid Ranking, and Optional RAG Synthesis.

[![Phase 1: Foundation Ready](https://img.shields.io/badge/Phase%201-Completed-brightgreen.svg)]()
[![Phase 2: Search MVP](https://img.shields.io/badge/Phase%202-Completed-brightgreen.svg)]()
[![Phase 3: UI](https://img.shields.io/badge/Phase%203-Search%20UI-Completed-brightgreen.svg)]()
[![Phase 4: Crawler](https://img.shields.io/badge/Phase%204-Controlled%20Crawler-Completed-brightgreen.svg)]()
[![Phase 5: Persistent Index](https://img.shields.io/badge/Phase%205-Persistent%20Indexing-Completed-brightgreen.svg)]()
[![Phase 6: Semantic Search](https://img.shields.io/badge/Phase%206-Semantic%20Search-Completed-brightgreen.svg)]()
[![Phase 7: Hybrid Ranking](https://img.shields.io/badge/Phase%207-Hybrid%20Ranking-Completed-brightgreen.svg)]()
[![Phase 8: RAG Answers](https://img.shields.io/badge/Phase%208-AI%20Answers-Completed-brightgreen.svg)]()
[![Phase 9: Search Modes](https://img.shields.io/badge/Phase%209-Specialized%20Modes-Completed-brightgreen.svg)]()
[![Phase 10: Test Suite](https://img.shields.io/badge/Phase%2010-Automated%20Testing%20Suite-Completed-brightgreen.svg)]()
[![Phase 11: Docker Hardening](https://img.shields.io/badge/Phase%2011-Docker%20Hardening-Completed-brightgreen.svg)]()
[![Phase 12: Live Internet Search](https://img.shields.io/badge/Phase%2012-Tavily%20Live%20Search-Implemented-brightgreen.svg)]()
[![Stack: FastAPI + React + Docker](https://img.shields.io/badge/Stack-FastAPI%20%7C%20React%20%7C%20Docker-blue.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)]()

---

## 🔍 What is SEEK?

**SEEK** is an open, modular, zero-cost search engine designed to demonstrate the complete lifecycle of information retrieval—from domain-controlled web crawling and HTML parsing to lexical (BM25) and semantic (FAISS) vector retrieval, hybrid candidate ranking, and source-grounded RAG answer generation.

Unlike applications that simply wrap commercial search APIs (e.g. Google or Bing API), SEEK owns its core indexing pipeline and search algorithms. Its local search requires no paid APIs; optional live search uses Tavily's free plan with an application-side monthly budget.

---

## 🚦 Current Project Status

- **Phases 1–11**: **COMPLETED** — Foundation · Search MVP · Search UI · Controlled Crawler · Persistent Indexing · Semantic Search · Hybrid Ranking · RAG Answers · Specialized Modes · Automated Tests · Docker Hardening.
- **Phase 12**: Tavily live internet search is implemented as an optional independent provider; local BM25, FAISS, hybrid retrieval, crawling, PostgreSQL and RAG remain available.
- **Remaining roadmap**: Expanded search evaluation and performance benchmarks, and final documentation polish (Phases 13–14).
- **Operations UI**: The frontend includes a **Manage sources & indexing** panel for submitting crawl jobs, monitoring job counts, viewing index status, and refreshing or rebuilding the lexical index. Crawl-job history is in memory and does not survive backend restarts.
- **Continuous integration**: GitHub Actions runs the backend suite, acceptance probe, frontend tests, typecheck, and production build on pushes and pull requests.
- **Search evaluation**: Run `python scripts/evaluate_search.py` for an offline BM25 baseline against hand-judged queries in `tests/data/search_relevance.json`. The small sample set is a regression aid, not a representative industry benchmark.

---

## ✅ PHASE 1 COMPLETE FEATURES

The current codebase establishes a production-grade full-stack foundation:

1. **FastAPI Backend Core**:
   - Asynchronous Python REST API framework using FastAPI and Uvicorn.
   - Modular application architecture (`backend/main.py`, `backend/config.py`, `backend/api/`).
   - Meta root endpoint (`GET /`) returning application context.
   - Health check endpoint (`GET /health`) returning JSON status.
   - Interactive Swagger API docs available at `/docs` and ReDoc at `/redoc`.
   - Comprehensive automated unit tests (`tests/test_health.py`) using `pytest`.

2. **React + TypeScript + Vite Frontend**:
   - Modern, responsive dark-mode UI built with React 18, TypeScript, and Tailwind CSS.
   - Minimal SEEK homepage interface featuring brand logo, "Search Engine" subtitle, search input field, search button, and Phase 1 development banner.
   - Real-time **Backend Health Status** component querying `GET /health` with dynamic status indicators (`Backend Status: Connected` / `Backend Status: Disconnected`) and graceful fallback.

3. **Docker-First Containerization**:
   - Production Dockerfile for backend (`docker/Dockerfile.backend`) with automated health checks.
   - Multi-stage Dockerfile for frontend (`docker/Dockerfile.frontend`) serving compiled Vite assets via Nginx on port 3000 with API proxy routing.
   - Complete multi-service orchestration manifest (`docker-compose.yml`) linking Frontend, Backend, and PostgreSQL database.

---

## ✅ PHASE 2 COMPLETE FEATURES (Search MVP)

Phase 2 turns the Phase 1 shell into a working **lexical search engine** over a
committed sample corpus. Everything is zero-cost and runs without paid APIs:

1. **Local Sample Corpus** (`data/sample_corpus/`):
   - 10 Markdown documents covering Docker, Python, Machine Learning, NLP, Odoo,
     Databases, Containerization and more (tracked in the repo, deterministic build).

2. **Deterministic Processing Pipeline** (`backend/processing/`):
   - `tokenizer.py` — unicode-normalising tokeniser with a stable stop-word set.
   - `loader.py` — reads the corpus (front-matter aware, fixed file order).
   - `snippets.py` — keyword-aware, deterministic excerpt builder.

3. **In-Memory BM25 Index** (`backend/search/`):
   - `bm25.py` — Okapi-BM25 (k1=1.5, b=0.75) over tokenised documents via `rank-bm25`.
   - `query.py` — query-side normalisation + weighted tokens.
   - `engine.py` — `SearchEngine`: index the corpus once, rank & snippet per query.

4. **Optional Persistence (`backend/db/`)**:
   - SQLAlchemy models/session/repository with graceful degradation when Postgres is down.
   - `pipeline.py` orchestrates corpus → index with best-effort persistence.

5. **Search API (`GET /api/search`)**:
   - Returns `{query, total, limit, hits[], took_ms, message}` — ranked, snipped,
     source-tagged results. Accessible via [http://localhost:8000/api/search?q=docker](http://localhost:8000/api/search?q=docker).

6. **Phase 2 MVP UI** (React frontend, superseded by Phase 3):
   - Live BM25 search against the FastAPI backend with ranked cards, keyword
     excerpts and the health panel.

7. **Tests** — `tests/test_search_phase2.py` (20 tests total incl. Phase 1):
   - Verifies corpus loading, tokenisation, snippets, BM25 ranking, pipeline and the live API.

---

## ✅ PHASE 3 COMPLETE FEATURES (SEEK Search UI)

Phase 3 turns the frontend into a polished, search-engine-focused experience
built on the **existing** FastAPI backend (`GET /api/search`), with no new
backend logic and no future-phase features:

1. **Search Homepage** (`frontend/src/`):
   - Clean, minimal landing: SEEK branding, tagline, prominent search bar with
     keyboard (Enter) + button submission, sample-query shortcuts, visible
     focus states and a responsive layout.

2. **Real Search Results**:
   - Renders the genuine `{hits[]}` response: title, source/domain, snippet,
     relevance score, rank and `matched_terms` chips. Sources are split into
     host + path (or file path for corpus docs) so long URLs never break layout.

3. **Complete Search States**:
   - Initial (landing), loading (spinner + disabled submit), success (ranked
     cards), empty ("No results found" + suggestion — a response counts as
     empty when no hit earned a non-zero BM25 score), and error (user-friendly
     panel + Retry, no stack traces). Empty/whitespace queries are blocked
     client-side.

4. **API Client** (`frontend/src/lib/api.ts`):
   - Single configurable client (`VITE_API_BASE_URL`, default
     `http://localhost:8000`, same-origin proxy fallback) — no duplicated or
     hardcoded endpoints; health polling preserved from Phase 1.

5. **URL Integrations**:
   - Query syncs to `/?q=…` with back/forward (popstate) support and deep-link
     loading on refresh. Fixed the Vite dev proxy prefix rewrite so `/api/*`
     reaches the backend unchanged.

6. **Accessibility**:
   - Semantic HTML (`header/main/footer`, `form role="search"`, `ol` results,
     `<article>` cards), `sr-only` labels, `aria-live`/`role="status"`
     announcements, visible `focus-visible` rings, and accessible buttons.

7. **Verification**:
   - `tsc --noEmit` + production `vite build` pass; real headless-browser runs
     confirmed landing, ranked results (`?q=python` shows title/rank/score),
     empty state, loading spinner and backend-down error panel.

---

## ✅ PHASE 4 COMPLETE FEATURES (Controlled Web Crawler)

Phase 4 adds a **domain-controlled, robots-respecting asynchronous crawler**
(`backend/crawler/`) whose output feeds straight into the existing BM25
pipeline — crawled pages become searchable through the same `/api/search`
endpoint:

1. **Async Crawler** (`backend/crawler/scheduler.py`):
   - BFS frontier crawl with configurable `max_pages`, `max_depth`, per-host
     `delay_seconds` and concurrency, all bounded and safe to run in-process.

2. **Responsible Crawling**:
   - URLs normalized (lowercase scheme/host, default ports dropped, tracking
     params and fragments stripped) and deduplicated by URL **and** content hash.
   - `robots.txt` parsing (`urllib.robotparser`) with per-host caching,
     `Crawl-delay` enforcement, and HTTP 401/403 → block-all semantics.
   - Dangerous URLs rejected (`javascript:`, `data:`, `ftp:`, credentials,
     `localhost`/private IPs by default, binary/PDF paths, `mailto:`, `tel:`).

3. **Extraction & Chunking** (`backend/crawler/extract.py`):
   - BeautifulSoup: main-text extraction (strips `nav`/`script`/`style`/
     `header`/`footer`), title fallback to `h1`/hostname, SHA-256 content hashes,
     non-overlapping text chunks for future RAG.

4. **Crawl Jobs API** (`backend/api/crawl.py`):
   - `POST /api/crawl` — start a job `{urls[], allowed_domains[], max_pages,
     max_depth, delay_seconds, ...}` → `{job_id, status}` (202-style async).
   - `GET /api/crawl` — list jobs; `GET /api/crawl/{job_id}` — poll status
     (`pending/running/completed/failed` + `pages_crawled`, failures, report).

5. **Index Management** (`backend/api/index.py`):
   - `POST /api/index/rebuild` — rebuild the live BM25 engine over corpus
     **+ crawled pages**, hot-swapping the engine so in-flight searches are
     never disturbed.

6. **Dedup & Persistence** (`backend/crawler/service.py`):
   - Thread-safe `CrawlStore` (visited URLs + content hashes) and a background
     `CrawlManager` for job orchestration; crawled docs persisted best-effort
     to Postgres and exposed as `crawl-*` document IDs in search results.

7. **Zero external network per test** — a tiny in-process `http.server` fixture
   serves a deterministic site (robots.txt, PDF, 404, out-of-scope links) so
   the whole suite runs offline. **45 tests total** pass.

---

## ✅ PHASE 5 COMPLETE FEATURES (Persistent Indexing Pipeline)

Phase 5 makes **PostgreSQL the canonical document store** and turns the BM25
index into a versioned, on-disk artifact that survives restarts. The engine is
always reconstructed from the current document set — PostgreSQL is the source
of truth, `indexes/bm25/index.pkl` is a derived artifact:

1. **Canonical persistence** (`backend/db/repository.py`, `backend/pipeline.py`):
   - `list_all()` reads every `documents` row deterministically; `persist_corpus()`
     idempotently seeds the committed corpus into Postgres (never raises).
   - Each document carries a SHA-256 `content_hash`, enabling change detection.

2. **Persistent BM25 artifact** (`backend/search/index_store.py`):
   - `indexes/bm25/index.pkl` + `indexes/bm25/metadata.json` (version, timestamps,
     corpus hash, counts) written **atomically** (same-dir `.tmp` + `os.replace`).
   - `load_index()` never raises; corrupt/absent artifacts degrade gracefully to a
     full rebuild. `INDEX_FORMAT_VERSION = 1`.

3. **Index lifecycle manager** (`backend/search/index_manager.py`):
   - `rebuild()` — full BM25 rebuild from PostgreSQL (falls back to an in-memory
     corpus+crawl build when Postgres is unreachable).
   - `refresh()` — change detection via `document_id -> content_hash` signature
     diff (new / modified / deleted); `unchanged` short-circuits a rewrite.
   - `status()` — `index_exists`, `loaded`, `document_count`, `database_available`,
     `index_version`, `corpus_hash`, `stale`, plus an explainer `message`.

4. **Resilient startup** (`backend/main.py` lifespan):
   - On boot the manager prefers the persisted artifact; if missing/stale/corrupt
     and Postgres is reachable it auto-rebuilds; otherwise serves empty until an
     explicit `POST /api/index/rebuild`.

5. **Index API** (`backend/api/index.py`):
   - `POST /api/index/rebuild` — rebuild (PG-backed or legacy fallback) →
     `{status, documents_indexed, corpus_documents, crawled_documents,
     source, index_version, took_ms}`.
   - `POST /api/index/refresh` — incremental change detection against Postgres.
   - `GET /api/index/status` — persistent-index health for ops/UIs.

6. **Search contract** — `document_id` is now `str(row.document_id)` (the
   Postgres integer primary key, stringified) for PG-sourced documents.

7. **Verification** — `tests/test_index_persistence_phase5b.py` covers rebuild,
   persistence across restart, change detection (new/modified/deleted), resilient
   startup, atomic-write failure recovery and the live API through TestClient.
   **67 backend tests total** pass (`pytest -q`), plus the `scripts/probe_phase2.py`
   import/app probe (18/18 imports).

---

## ✅ PHASE 6 COMPLETE FEATURES (Semantic Search, Local ML Embeddings)

Phase 6 adds a **local semantic retrieval path** on top of the Phase 5
pipeline: documents are embedded with SentenceTransformers, stored in a
persistent FAISS vector index, and searched by cosine similarity — with a
guarantee that the existing BM25 lexical mode keeps working exactly as before:

1. **Local embeddings** (`backend/search/embeddings.py`):
   - `EmbeddingGenerator` wrapping `sentence-transformers/all-MiniLM-L6-v2`
     (384-dim, L2-normalised, batched) with query-side normalisation.
   - **Lazy loading**: the model is never loaded at import time or on server
     boot — only the first real semantic operation pays the load cost
     (singleton + thread lock).
   - `EmbeddingUnavailableError` + fast `is_importable()` guard so a missing ML
     stack degrades cleanly instead of crashing.

2. **Persistent FAISS store** (`backend/search/faiss_store.py`):
   - `indexes/faiss_index.bin` + `indexes/faiss_metadata.json` (format version,
     model, dimension, timestamps, corpus hash, `document_id`/`title`/`source`/
     `content_hash` per vector), written **atomically** (`.tmp` + `os.replace`).
   - `load_faiss_index()` never raises; corrupt/absent artifacts degrade
     gracefully. `FAISS_FORMAT_VERSION = 1`.

3. **Semantic index lifecycle** (`backend/search/semantic.py`):
   - `SemanticIndexManager` singleton: full `rebuild()`, change-detection
     `refresh()` (`document_id -> content_hash` diff: new/modified/deleted),
     `load_on_startup()`, cosine-similarity `search()`, never-raises `status()`.
   - **Persistence across restart**: on boot the manager loads the FAISS
     artifact from disk and reports `source=persistent_faiss_index` without
     reloading the embedding model.

4. **Semantic API** (`backend/api/search.py`, `backend/api/index.py`):
   - `GET /api/search?q=…&mode=semantic` — cosine-score hits, `score_type`
     label, and a full `semantic` status block; `mode=lexical`/`bm25` keeps the
     original BM25 contract unchanged (default).
   - `POST /api/index/semantic/rebuild` and `POST /api/index/semantic/refresh`;
     `GET /api/index/status` now reports both BM25 (`index`/… fields) and
     semantic (`semantic` block) health.
   - **No silent fallback**: when the model or index is unavailable, the API
     returns `hits: []` with `semantic.status = "unavailable"` and an explainer —
     callers can always tell "no semantic result" from "semantic broken".

5. **Verification** — `tests/test_semantic_search_phase6.py` covers three
   tiers: offline deterministic fakes (fake embedder + in-memory repo),
   the live `all-MiniLM-L6-v2` model (laziness, 384-dim determinism, L2
   normalisation), and live PostgreSQL end-to-end (rebuild/search/restart,
   change detection, API flow, missing-model graceful degradation).
   **97 backend tests total** pass (`pytest -q`), probe 18/18.

---

## ✅ PHASE 7 COMPLETE FEATURES (Hybrid Ranking Engine)

Phase 7 merges the lexical (BM25) and vector (FAISS semantic) candidate sets into
a single ranked list, exposed as `GET /api/search?q=…&mode=hybrid`:

1. **Weighted hybrid score** (`backend/search/hybrid.py`): deterministic
   min–max normalisation per candidate component, combined as
   `w_bm25·BM25_norm + w_semantic·Semantic_norm`
   (`HYBRID_BM25_WEIGHT` / `HYBRID_SEMANTIC_WEIGHT`, default 0.5/0.5).
2. **Merge & dedupe**: candidates merged by canonical `document_id`, deduplicated,
   ranked descending, ties broken deterministically by document ID.
3. **Weight validation**: invalid or NaN/Infinity weights are rejected with an
   explicit `status: "error"` payload instead of silently defaulting.
4. **No hidden fallback**: when one index is unavailable the response reports
   `status: "degraded"` / `"unavailable"` and explains which side failed.

---

## ✅ PHASE 8 COMPLETE FEATURES (AI / RAG Answer Generation)

Phase 8 adds source-grounded answer synthesis via `POST /api/answer`:

1. **Passage selector** (`backend/ai/pipeline.py`): top-K context chunks from the
   retrieved hits, deduplicated by document, capped by `RAG_MAX_CONTEXT_CHARS`.
2. **Grounded prompt builder**: strict instructions to answer only from the
   supplied sources, cite them inline as `[1]`, `[2]`, … and declare insufficient
   context otherwise.
3. **Swappable `LLMProvider`s** (`backend/ai/providers.py`): `FakeLLMProvider`
   (deterministic, offline), `OllamaLLMProvider` (local HTTP) and
   `HuggingFaceLLMProvider` (local transformers) — **no paid API**.
4. **Explicit fallback**: RAG disabled, insufficient context (top score below
   `RAG_MIN_SCORE_THRESHOLD`) or provider failure/timeout all yield a structured
   fallback carrying the plain search hits and `fallback_mode: true`.

---

## ✅ PHASE 9 COMPLETE FEATURES (Specialized Search Modes)

Phase 9 turns SEEK into four purpose-built search experiences — **Web Search**,
**AI Answers**, **Research** and **Code Docs** — as a thin **orchestration
layer** over the retrieval and RAG services built in Phases 2–8. No BM25,
semantic, hybrid or RAG logic is duplicated; a mode only chooses which existing
service to call and how to arrange its output.

1. **Mode registry** (`backend/search/modes.py`) — a controlled `SearchMode`
   enum plus a `ModeSpec` per mode (retrieval strategy, ranking weights, result
   limits, candidate widening, RAG toggle, snippet behaviour, source
   diversification, documentation priority). Every knob is read from the
   centralised `MODE_*` / `RESEARCH_*` / `CODE_*` settings in
   `backend/config.py` — no magic numbers in the mode layer.

2. **Orchestrator** (`backend/api/mode_orchestrator.py`) — probes index
   availability, delegates retrieval to the existing `_hybrid_search` /
   `_semantic_search` / `_lexical_search` handlers with the mode's candidate
   width and weights, applies the deterministic post-processing helpers, and for
   the RAG modes hands the *already retrieved* hits to `generate_rag_answer()`
   so retrieval never runs twice.

3. **One explicit envelope.** Every mode returns
   `{query, mode, status, total, limit, hits, took_ms, message, answer, sources, metadata}`:
   - `status` is **`ok`**, **`degraded`** (a preferred capability was missing and
     a fallback was served) or **`unavailable`** (nothing could be served);
   - retrieval health always wins over the RAG outcome;
   - every fallback is spelled out in `message` and `metadata.degraded_reason` —
     **retrieval failures are never hidden**;
   - an installed-but-empty index is reported as `unavailable`, not as an empty
     result set.

4. **Validated mode parameter.** `mode` accepts the legacy retrieval modes
   (`lexical|bm25|semantic|hybrid`) plus `web|ai|research|code`, case-insensitively.
   Anything else returns a clean **HTTP 422** with
   `detail.error = "invalid_search_mode"` and the list of allowed values.
   The legacy contracts are untouched: `GET /api/search?q=python` still returns
   exactly its Phase 2 payload.

5. **Mode behaviour**
   - **`web`** — broad hybrid retrieval, ranked results, no generated answer.
   - **`ai`** — hybrid retrieval plus a Phase 8 grounded answer with citations.
   - **`research`** — wider candidate retrieval
     (`RESEARCH_CANDIDATE_MULTIPLIER`), per-host source diversification,
     richer snippets, and a labelled separation between retrieved evidence
     (`metadata.evidence.kind = "retrieved_evidence"`) and generated synthesis
     (`metadata.synthesis.kind = "generated_synthesis"`).
   - **`code`** — lexical-leaning weights (`CODE_BM25_WEIGHT` 0.7 vs
     `CODE_SEMANTIC_WEIGHT` 0.3), technical identifier expansion
     (`faiss_store.SearchEngine` → also `faiss store search engine`),
     documentation-source **prioritisation** (a preference, never a filter) and
     code excerpts extracted from documents SEEK already indexed. **No external
     crawler and no third-party API** are added.

6. **Honest matching.** The BM25/hybrid pipeline pads its candidate list with
   `0.0`-scored documents; `drop_unmatched_hits()` removes them from the
   specialized-mode envelope so `total` reflects genuine matches
   (`MODE_MATCH_SCORE_FLOOR`). `answer` is `null` whenever RAG falls back —
   SEEK never invents text.

7. **Mode catalog** (`GET /api/search/modes`) — machine-readable description of
   every mode: label, retrieval strategy, limits, weights and capabilities.

8. **Mode-aware UI** (`frontend/`)
   - `src/components/ModeSelector.tsx` — polished, responsive, keyboard
     accessible ARIA `radiogroup` (roving `tabindex`, Arrow/Home/End keys).
   - `src/lib/urlState.ts` — pure `parseSearchState` / `buildSearchPath`, so the
     mode lives in the URL (`/?q=python&mode=research`): shareable, survives a
     refresh, and honours back/forward navigation.
   - `AnswerPanel.tsx` / `SourcesPanel.tsx` / `ResultCard.tsx` — grounded answer
     (or an explicit "no answer could be generated" note), cited sources, code
     excerpts, and a degraded/unavailable banner. Nothing is rendered that the
     backend did not send.

9. **Verification** — `tests/test_search_modes_phase9.py` (108 tests, checklist
   items A–P) plus the frontend suite `npm run test:urlstate`.
   **226 tests pass** (`pytest -q`), probe 18/18, `npm run build` and
   `tsc --noEmit` clean.

Try it live:

```bash
curl -s "http://localhost:8000/api/search/modes" | python -m json.tool
curl -s "http://localhost:8000/api/search?q=python&mode=research" | python -m json.tool
curl -s "http://localhost:8000/api/search?q=SearchEngine&mode=code" | python -m json.tool
curl -s -i "http://localhost:8000/api/search?q=python&mode=bogus"   # 422 invalid_search_mode
```

---

## ✅ PHASE 10 COMPLETE FEATURES (Automated Testing Suite)

Phase 10 turns "the tests we happened to write" into a **documented, cross-phase
automated testing suite** with one entry point and no required infrastructure.
Full coverage matrix: [`docs/TESTING_PHASE10.md`](docs/TESTING_PHASE10.md).

1. **One offline gate** — `python -m pytest -q` runs the whole suite with **no
   PostgreSQL, no embedding-model download and no outbound HTTP**. Repository,
   embedding and semantic-index dependencies are replaced by in-memory doubles
   and deterministic stubs; tests that need real infrastructure read
   `SEEK_TEST_DATABASE_URL` and skip cleanly when it is absent.

2. **Shared fixtures** (`tests/conftest.py`) — sample corpus documents, an
   in-memory `DocumentRepository` with `available` / `fail_with` switches, the
   canonical degraded ("PostgreSQL unreachable") repository, isolated
   `IndexManager` / semantic managers pointed at `tmp_path`, present/unavailable
   semantic doubles, a hermetic `TestClient`, and autouse process-singleton
   isolation so tests never leak state into each other.

3. **Five new suites across 714 tests**:
   - `tests/test_unit_phase10.py` (334) — tokenization, snippets, corpus loading,
     pipeline, query processing, BM25 scoring and vocabulary size, normalisation,
     hybrid weight validation and merge, RAG models/prompt/passage selection/
     providers/orchestrator, crawler URL & robots safety, HTML extraction, fetch,
     crawl store/manager, index and FAISS artifact metadata, settings.
   - `tests/test_api_phase10.py` (138) — every published route, its validation
     and response contract, the mode catalog endpoint, crawl and index endpoints,
     the answer endpoint, and the full **search mode × index-state × query
     matrix** (present / empty / absent index × each mode × matching, non-matching
     and invalid queries).
   - `tests/test_integration_phase10.py` (53) — corpus → index end to end,
     persistence through the repository, the BM25 and FAISS persistence matrices
     (valid, missing, corrupt, stale, metadata-version mismatch, atomic-write
     failure, interrupted write) and failure/resilience combinations.
   - `tests/test_security_phase10.py` (136) — query input is never interpreted as
     code, highlight escaping happens before `<mark>` wrapping, crawl URL/SSRF
     safety including seed validation, no-fabricated-answers guarantees, and
     repository hygiene (no credentials in errors).
   - `tests/test_regression_phase10.py` (53) — the **seams between phases**:
     route inventory stability, the Phase 2 corpus and acceptance probe, the
     crawler → index hop, shared persistence constants, the hybrid weight
     contract through the API, RAG composition, mode catalog parity between
     backend, API and frontend, frontend suites + typecheck + build, documentation
     wiring, and a deliberately non-fragile performance smoke tier.

4. **Frontend coverage through pytest** — reusing the existing `node:test`
   pattern: `frontend/tests/modes.test.mjs` verifies the UI mode catalog against
   the backend contract, and `npm run test:frontend` runs both frontend suites.
   `TestFrontendSuites` drives `npm run test:frontend`, `typecheck` and `build`
   from pytest, skipping cleanly when Node is unavailable.

5. **Defects the suite found and fixed** — no product features were added, but
   writing the tests surfaced eleven real bugs, including a BM25 score/document
   misalignment that returned the **wrong document** whenever a corpus document
   produced no tokens, an inflated vocabulary size, a `NameError` in
   `snippet_tokens()`, a skip-list that indexed `index.md`, undetected metadata
   version mismatches, and two HTTP 500s where structured degradation was
   documented (`mode=semantic` with a failing semantic manager, and a
   blank-seed crawl request).

6. **Honest documentation** — the matrix reports *which behaviour is covered by
   which test* and what is deliberately **not** covered (live PostgreSQL, live
   embedding model, load testing, browser E2E, coverage measurement). It claims
   **no coverage percentage**, and a test enforces that no such number is
   published without an actual measurement run.

Run it:

```bash
python -m pytest -q                  # everything
python -m scripts.probe_phase2       # phase acceptance gate: 18/18 imports + a real query
cd frontend && npm run test:frontend && npm run typecheck && npm run build
```

---

## 🌐 PHASE 12: LIVE INTERNET SEARCH (TAVILY)

The **Live Internet Search** mode calls Tavily directly through a dedicated
backend route. It returns public web search results without crawling or
indexing them. Existing local modes and the crawler are unchanged; Tavily
failures are reported explicitly and never fall back to local search.

- **API**: `POST /api/live-search` accepts a query and optional hostname-only
  `include_domains` / `exclude_domains` lists. `GET /api/live-search/usage`
  reports SEEK's monthly budget.
- **Result details**: Title, original URL, hostname, Tavily snippet, optional
  relevance score and favicon. Results open the original page.
- **Conservative credit guard**: basic search only (documented as 1 credit),
  maximum 5 results, no answer or raw-page content, 900 application credits
  per UTC month, and no retry or paid-provider fallback. Atomic SQLite
  reservations prevent concurrent requests from exceeding that SEEK budget.
  The ledger persists in `indexes/tavily_usage.sqlite3` (the Compose
  `seek_indexes` volume).
- **Cache**: successful identical query/filter combinations are cached for
  10 minutes by default and visibly labelled with the original search time.
  Cache hits do not consume Tavily credits.
- **Account-side limit**: the SEEK budget applies only to SEEK's use of the
  key. Tavily account-wide billing settings are external; stay on the
  Researcher free plan, do not add a payment method or enable paid usage, and
  set any provider-side usage cap offered in the dashboard. Never rely on
  SEEK's 900-credit counter to limit other applications using that key.

### Configure Tavily for local or Docker use

1. Create a key at [Tavily](https://app.tavily.com/) while selecting the free
   Researcher plan. Tavily's published pricing currently advertises 1,000
   monthly credits without requiring a credit card; plan terms can change.
   See the [Search API reference](https://docs.tavily.com/documentation/api-reference/endpoint/search)
   and [current pricing](https://www.tavily.com/pricing).
2. Put the key only in the backend environment: set `TAVILY_API_KEY` in `.env`
   (copied from `.env.example`) or export it for a local backend. Do not put it
   in `VITE_*` variables or frontend code.
3. Keep the free account's usage/billing settings free-only. Do not upgrade,
   enable pay-as-you-go, or attach a payment method. If Tavily offers a
   provider-side monthly limit, configure it at or below the free allowance.
4. Start SEEK as usual. With no key, local search still works and Live Internet
   Search clearly reports that Tavily is not configured.

Example:

```bash
# Start the Docker stack after putting TAVILY_API_KEY in .env
docker compose up --build -d

# Test live search (the key is read from the backend environment)
curl -s -X POST http://localhost:8000/api/live-search \
  -H 'content-type: application/json' \
  -d '{"query":"FastAPI documentation","include_domains":["fastapi.tiangolo.com"]}'

# Read SEEK's application-side remaining credits
curl -s http://localhost:8000/api/live-search/usage
```

The interactive API contracts are published at `/docs` and `/redoc`. Errors
distinguish invalid input, missing/invalid credentials, rate limiting, account
credit exhaustion, timeout, and provider/network unavailability.

---

## ✅ IMPLEMENTED, ADDED, AND STILL TO DO

### Implemented

- **Search and ranking**: BM25 lexical retrieval, local Sentence Transformers embeddings with FAISS, hybrid scoring, and the Web / AI / Research / Code modes.
- **Crawling and indexing**: Domain-scoped crawler with robots.txt support, URL/content deduplication, PostgreSQL document persistence, persisted BM25/FAISS artifacts, and rebuild/refresh/status operations.
- **Grounded answers**: Optional RAG answer generation with interchangeable local/free LLM providers and source citations.
- **Search experience**: Responsive React interface, URL-backed search state, keyboard-accessible mode selection, result/source/answer views, and explicit loading/error/degraded states.
- **Source and index management**: UI for starting crawls, viewing crawl activity and index status, and refreshing or rebuilding the lexical index.
- **Testing and delivery**: Offline backend and frontend suites, an acceptance probe, GitHub Actions checks, and an initial hand-judged BM25 relevance evaluation.
- **Containerization**: Docker Compose stack, persistent volumes, container health checks, restart policies, and production-oriented Docker builds.

### Recently added

- **Operations panel** for crawl submission and crawl/index status using the existing backend routes.
- **BM25 evaluation baseline** at `scripts/evaluate_search.py` with a small query/judgment set under `tests/data/`.
- **GitHub Actions CI** for pytest, the acceptance probe, frontend tests, TypeScript typechecking, and production build.

### Remaining roadmap work

- **Phase 13 — Evaluation and benchmarking**: expand and review relevance judgments; compare lexical, semantic, hybrid, and specialized modes; measure latency and memory at representative corpus sizes.
- **Phase 14 — Documentation and final polish**: complete setup/deployment guidance and publish endpoint/architecture documentation.
- **Operational durability**: persist crawl-job state and support job recovery after backend restarts. Crawl jobs are currently process-local; this is not yet implemented.

User accounts, personalization, multi-node sharding, and learning-to-rank are possible future directions, not currently committed roadmap deliverables.

---

## 🏗️ System Architecture

```text
┌──────────────────────────────────────────────────────────┐
│ React + TypeScript + Vite UI (port 3000 / Nginx)         │
│ Search bar · mode selector · results · answers · sources │
│ Manage sources & indexing · health indicator             │
└──────────────────────────┬───────────────────────────────┘
                           │ HTTP / REST
                           ▼
┌──────────────────────────────────────────────────────────┐
│ FastAPI application (port 8000 / Uvicorn)                 │
│ health · search · answer · crawl jobs · index operations  │
└───────────────┬──────────────────────────┬───────────────┘
                │ search                   │ crawl / index
                ▼                          ▼
┌──────────────────────────────┐  ┌────────────────────────────┐
│ Search mode orchestrator     │  │ Controlled crawler          │
│ web · ai · research · code   │  │ scope · robots · fetch       │
│ legacy lexical/semantic/     │  │ extract · deduplicate        │
│ hybrid retrieval modes       │  │ crawl jobs are in-memory     │
└───────────────┬──────────────┘  └──────────────┬─────────────┘
                │                                │ documents
                ▼                                ▼
┌──────────────────────────────────────────────────────────┐
│ Shared retrieval and answer services                     │
│ BM25 · sentence-transformer embeddings + FAISS · hybrid  │
│ optional RAG synthesis with source citations              │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│ PostgreSQL document store (canonical persisted documents) │
│ Derived artifacts: indexes/bm25 and FAISS semantic index  │
└──────────────────────────────────────────────────────────┘

Build / verification: GitHub Actions → pytest + acceptance probe
                     + frontend tests + typecheck + Vite build
```

### Runtime flow

1. The UI sends a query and selected mode to the FastAPI search route.
2. The mode orchestrator selects behavior and composes the shared lexical,
   semantic, hybrid, or RAG services. Retrieval failures are returned as
   explicit status rather than silently hidden.
3. Results, source citations, and optional grounded answers are rendered by the
   UI. Search parameters remain shareable through the URL.
4. An operator can start a crawl from **Manage sources & indexing**. The
   crawler respects configured scope and robots.txt rules, extracts and
   deduplicates pages, and persists documents best-effort; index operations
   update derived search artifacts.
5. Crawl-job records are currently in process memory. They are lost on backend
   restart; durable job storage/recovery remains future work.

The diagram describes the intended persistent-index path: PostgreSQL is the
canonical document source and BM25/FAISS files are derived artifacts. When
PostgreSQL is unavailable, the lexical index has a documented local-corpus
fallback; semantic rebuild requires the persistent document source.

> **Search modes are an orchestration layer, not a parallel retrieval stack
> (Phase 9).** The `web`, `ai`, `research` and `code` modes reuse exactly the same
> BM25, semantic, hybrid and RAG services as the legacy `bm25`, `semantic` and
> `hybrid` modes. A mode only changes the result limit, candidate widening,
> ranking weights, source prioritisation and post-processing applied on top of
> those shared services. Mode definitions live in `backend/search/modes.py`;
> execution, availability probing and status reporting live in
> `backend/api/mode_orchestrator.py`. No mode ever hides a retrieval failure —
> each response carries an explicit `status` of `ok`, `degraded` or
> `unavailable`.

---

## 🛠️ Technology Stack

| Component | Technology | Purpose |
|---|---|---|
| **Frontend UI** | React 18, TypeScript, Vite, Tailwind CSS | Responsive web search interface |
| **API Backend** | Python 3.11, FastAPI, Uvicorn, Pydantic v2 | High-performance async REST backend |
| **Crawler** | httpx, asyncio, BeautifulSoup4, robotparser | Controlled async crawling + extraction |
| **Embeddings** | sentence-transformers (all-MiniLM-L6-v2) | Local 384-dim semantic embeddings |
| **Vector Search** | faiss-cpu | Persistent FAISS semantic index (`IndexFlatIP`) |
| **Database** | PostgreSQL 16 Alpine | Canonical persisted document store; crawl-job registry is currently in memory |
| **Containerization** | Docker, Docker Compose, Nginx | Reproducible containerized stack |
| **Testing** | Pytest, FastAPI TestClient, Httpx, `node:test` | Automated unit, API, integration, persistence, security and regression suites (Phase 10) |

---

## 🚀 Quick Start & Development Instructions

### Prerequisites
- [Docker & Docker Compose](https://docs.docker.com/get-docker/) installed.
- (Optional for local non-Docker development): Python 3.11+ and Node.js 20+.

---

### Option 1: Docker Compose (Recommended)

1. **Clone Repository & Setup Environment**:
   ```bash
   cp .env.example .env
   ```

2. **Start Complete Stack**:
   ```bash
   docker compose up --build -d
   ```

3. **Verify Containers**:
   ```bash
   docker compose ps
   ```

4. **Access Applications**:
   - **Frontend UI**: [http://localhost:3000](http://localhost:3000)
   - **Backend API Root**: [http://localhost:8000](http://localhost:8000)
   - **Backend Health Check**: [http://localhost:8000/health](http://localhost:8000/health)
   - **Interactive API Documentation (Swagger)**: [http://localhost:8000/docs](http://localhost:8000/docs)
   - **ReDoc API Documentation**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

5. **Stop Stack**:
   ```bash
   docker compose down
   ```

---

### Option 2: Local Development Without Docker

#### Backend Setup
```bash
# Install Python dependencies
pip install -r requirements.txt

# Run the full automated testing suite (offline: no DB, no model download)
python -m pytest -q

# Run the Phase 2 acceptance probe (18/18 imports + a real query)
python -m scripts.probe_phase2

# Run FastAPI backend with Uvicorn
python backend/main.py
```

#### Frontend Setup
```bash
cd frontend

# Install Node dependencies
npm install

# Start Vite dev server
npm run dev
# App will be accessible at http://localhost:3000

# Frontend test suites, typecheck and production build (Phase 10)
npm run test:frontend
npm run typecheck
npm run build
```

The frontend suites use Node's built-in `node:test` runner — no extra test
framework is required. `npm run test:frontend` runs `test:urlstate`,
`test:modes`, and `test:live-search`; the same scripts are invoked from `tests/test_regression_phase10.py`
so `python -m pytest -q` covers the frontend too.

---

## 🧪 Health-Check & Acceptance Verification

To verify that the Phase 1 backend service and health checks are functioning correctly:

1. **cURL Command**:
   ```bash
   curl -i http://localhost:8000/health
   ```

2. **Expected Response (HTTP 200 OK)**:
   ```json
   {
     "status": "ok",
     "service": "seek-backend"
   }
   ```

3. **Frontend Search Smoke Test (Phase 3 UI)**:
   ```bash
   cd frontend && npm install && npm run dev   # serves http://localhost:3000
   ```
   Then open [http://localhost:3000](http://localhost:3000), type `docker container`
   (or press a sample query) and press Enter — ranked results from the real
   `GET /api/search` endpoint render with title, source, snippet and score.
   The query syncs to `/?q=…`, so back/forward and refresh work.

4. **Phase 4 Crawl Smoke Test** (network required — crawls `https://example.com`):
   ```bash
   # Start a crawl job (async)
   curl -s -X POST http://localhost:8000/api/crawl \
     -H "content-type: application/json" \
     -d '{"urls":["https://example.com"], "max_pages": 3, "max_depth": 1}'
   # Poll it
   curl -s http://localhost:8000/api/crawl/<job_id>
   ```
   Expected: the job transitions `running → completed` with `pages_crawled`
   reflecting the page cap, then `robots_blocked`/`out_of_scope` counters.

5. **Rebuild & Search Crawled Content**:
   ```bash
   curl -s -X POST http://localhost:8000/api/index/rebuild
   curl -s "http://localhost:8000/api/search?q=<term>&limit=3" | python -m json.tool
   ```
   Expected: `crawled_documents >= 1` after a successful crawl; search now ranks
   `crawl-*` documents alongside the local corpus.

6. **Phase 6 Semantic Search Smoke Test** (local model + FAISS):
   ```bash
   # Build the semantic index from PostgreSQL (first run downloads the model)
   curl -s -X POST http://localhost:8000/api/index/semantic/rebuild
   # Semantic mode — cosine-similarity hits + a "semantic" status block
   curl -s "http://localhost:8000/api/search?q=docker&mode=semantic" | python -m json.tool
   # Index status now reports both BM25 and semantic state
   curl -s http://localhost:8000/api/index/status | python -m json.tool
   ```
   Expected: `mode=semantic` in the response, hits sorted by cosine similarity,
   `semantic.status=ok`; after restarting the backend the semantic index loads
   from `indexes/faiss_index.bin` (`source=persistent_faiss_index`) without
   re-embedding, and the model loads lazily on first semantic query.

7. **Phase 7 Hybrid Ranking Smoke Test**:
   ```bash
   curl -s "http://localhost:8000/api/search?q=docker&mode=hybrid" | python -m json.tool
   ```
   Expected: `mode=hybrid` with a `metadata.hybrid` block reporting the fusion
   weights used (`HYBRID_BM25_WEIGHT` / `HYBRID_SEMANTIC_WEIGHT`) and per-hit
   score provenance; the legacy
   `/api/search?q=<term>` without `mode` still behaves exactly as before.

8. **Phase 8 AI Answer Smoke Test** (no paid API required):
   ```bash
   curl -s -X POST http://localhost:8000/api/answer \
     -H "content-type: application/json" \
     -d '{"query":"what is a container","top_k":5}' | python -m json.tool
   ```
   Expected: an `answer` string plus `sources` and `passages` when the optional
   LLM provider is configured; otherwise `answer=null` with an explicit
   `rag.status=unavailable` (or `degraded`) reason. Retrieval failures are never
   hidden and an answer is never fabricated.

9. **Phase 9 Specialized Search Modes Smoke Test**:
   ```bash
   # Discover the available modes
   curl -s http://localhost:8000/api/search/modes | python -m json.tool
   # Each specialized mode
   for m in web ai research code; do
     curl -s "http://localhost:8000/api/search?q=python&mode=$m" | python -m json.tool
   done
   # Invalid mode -> HTTP 422
   curl -i "http://localhost:8000/api/search?q=python&mode=nope"
   ```
   Expected: each response echoes `mode`, a `status` of `ok` / `degraded` /
   `unavailable`, and mode-specific payloads (`answer` for `ai`, `sources` for
   `research`, code snippets for `code`). `?q=python&mode=nope` returns
   **HTTP 422** with `detail.code = "invalid_search_mode"`. An unknown mode never
   falls back silently to a different mode.

   Then open [http://localhost:3000](http://localhost:3000) and confirm the mode
   selector switches between **Web / AI / Research / Code**, the address bar keeps
   `?q=python&mode=research`, browser back/forward restores the previous mode, and
   the Research and Code modes render their source / snippet panels.

10. **Phase 10 Test Suite Verification** (no database, model download or network
    required):
    ```bash
    # Backend + API + integration + security + regression
    python -m pytest -q
    # Phase 2 acceptance probe (imports, app build, one real query)
    python -m scripts.probe_phase2
    # Frontend suites, typecheck and production build
    cd frontend && npm run test:frontend && npm run typecheck && npm run build
    ```
    Expected: `pytest -q` reports every test passing with no failures; the probe
    prints `import_ok=18/18`, `app_build=OK` and `search_ok=true`; all frontend
    commands exit `0`. The coverage matrix and the list of deliberate gaps are in
    [`docs/TESTING_PHASE10.md`](docs/TESTING_PHASE10.md).

11. **Search Relevance Baseline** (offline, committed sample corpus):
    ```bash
    python scripts/evaluate_search.py
    ```
    Expected: per-query and macro-average Precision@5, Recall@5, MRR@5 and
    nDCG@5. The relevance judgments are a small, manually curated regression
    set; expand and review them before using scores to make ranking decisions.

---

## 🔮 Next Planned Phase

**Phase 13: Evaluation and Benchmarking** — expand search relevance judgments
and measure latency, memory, and quality across representative datasets.

---

## 📄 License
This project is licensed under the MIT License - see the LICENSE file for details.