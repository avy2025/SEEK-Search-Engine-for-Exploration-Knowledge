# SEEK – Search Engine for Exploration & Knowledge

> A Genuine, Modular, Docker-First Search Engine with Controlled Crawling, Lexical & Semantic Retrieval, Hybrid Ranking, and Optional RAG Synthesis.

[![Phase 1: Foundation Ready](https://img.shields.io/badge/Phase%201-Completed-brightgreen.svg)]()
[![Phase 2: Search MVP](https://img.shields.io/badge/Phase%202-Completed-brightgreen.svg)]()
[![Phase 3: UI](https://img.shields.io/badge/Phase%203-Search%20UI-Completed-brightgreen.svg)]()
[![Phase 4: Crawler](https://img.shields.io/badge/Phase%204-Controlled%20Crawler-Completed-brightgreen.svg)]()
[![Phase 5: Persistent Index](https://img.shields.io/badge/Phase%205-Persistent%20Indexing-Completed-brightgreen.svg)]()
[![Phase 6: Semantic Search](https://img.shields.io/badge/Phase%206-Semantic%20Search-Completed-brightgreen.svg)]()
[![Stack: FastAPI + React + Docker](https://img.shields.io/badge/Stack-FastAPI%20%7C%20React%20%7C%20Docker-blue.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)]()

---

## 🔍 What is SEEK?

**SEEK** is an open, modular, zero-cost search engine designed to demonstrate the complete lifecycle of information retrieval—from domain-controlled web crawling and HTML parsing to lexical (BM25) and semantic (FAISS) vector retrieval, hybrid candidate ranking, and source-grounded RAG answer generation.

Unlike applications that simply wrap commercial search APIs (e.g. Google or Bing API), SEEK owns its core indexing pipeline and search algorithms. It operates under a strict **zero-cost constraint**, requiring no paid APIs or external dependencies.

---

## 🚦 Current Project Status

- **Phases 1–6**: **COMPLETED** — Foundation · Search MVP (BM25) · Search UI · Controlled Web Crawler · Persistent Indexing Pipeline · Semantic Search (Local ML Embeddings)
- **Next Phase**: **Phase 7 — Hybrid Ranking Engine** `[UPCOMING]`

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

## ❌ NOT YET IMPLEMENTED

To keep the development scope clean and strictly phase-aligned, the following components are **NOT** yet implemented:

- ❌ Multi-Signal Hybrid Ranker (Phase 7)
- ❌ AI / RAG Answer Generation (Phase 8)

---

## 🏗️ System Architecture

```
                                   +---------------------------------------+
                                   |         React + Vite UI (Phase 3)     |
                                   |      Search box + ranked results      |
                                   |      (Port 3000 / Nginx Container)    |
                                   +-------------------+-------------------+
                                                        |
                                                        |  HTTP / REST
                                                        v
                                   +---------------------------------------+
                                   |          FastAPI Gateway              |
                                   |     (Port 8000 / Uvicorn Container)   |
                                   +---------+-----------------+-----------+
                                             |                 |
                                             v                 v
                                    +----------------+ +------------------+
                                    |  GET /health   | |  GET /           |
                                    | (Health Check) | | (System Meta)    |
                                    +----------------+ +------------------+
                                             |
                                             v
+--------------------------------------------+
|  /api/search (lexical | semantic)           |
                            |  /api/crawl (jobs)                          |
                            |  /api/index/rebuild | refresh | status       |
                            |  /api/index/semantic/rebuild | refresh        |
                            +-------------------+------------------------+
                                                |
                            +-------------------+------------------------+
                            |                                          |
                            v                                          v
           +---------------------------------+             +-----------------------+
           |  Crawler pipeline (Phase 4)     |------\     |  BM25 engine (Phase 5)|
           |  seeds -> robots -> fetch ->    |       \    |  canonical: PostgreSQL|
           |  extract -> chunk -> dedup      |        \   |  artifact: indexes/    |
           +---------------------------------+         \  |  bm25/index.pkl        |
                                                        \ +-----------------------+
                                                         \
                                                          \  +-----------------------+
                                                           \ |  Semantic engine (6)  |
                                                            \|  FAISS IndexFlatIP    |
                                                             |  artifact: indexes/   |
                                                             |  faiss_index.bin      |
                                                             +-----------------------+
```

---

## 🛠️ Technology Stack

| Component | Technology | Purpose |
|---|---|---|
| **Frontend UI** | React 18, TypeScript, Vite, Tailwind CSS | Responsive web search interface |
| **API Backend** | Python 3.11, FastAPI, Uvicorn, Pydantic v2 | High-performance async REST backend |
| **Crawler** | httpx, asyncio, BeautifulSoup4, robotparser | Controlled async crawling + extraction |
| **Embeddings** | sentence-transformers (all-MiniLM-L6-v2) | Local 384-dim semantic embeddings |
| **Vector Search** | faiss-cpu | Persistent FAISS semantic index (`IndexFlatIP`) |
| **Database** | PostgreSQL 16 Alpine | Persistent metadata and crawl queue storage |
| **Containerization** | Docker, Docker Compose, Nginx | Reproducible containerized stack |
| **Testing** | Pytest, TestClient, Httpx | Automated integration and unit testing |

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

# Run pytest test suite
python -m pytest -q

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
```

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

---

## 🔮 Next Planned Phase

**Phase 7: Hybrid Ranking Engine** (merge BM25 lexical and FAISS semantic
candidates into a single weighted ranking)

---

## 📄 License
This project is licensed under the MIT License - see the LICENSE file for details.