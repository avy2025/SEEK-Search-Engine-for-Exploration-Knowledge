# SEEK – Search Engine for Exploration & Knowledge

> A Genuine, Modular, Docker-First Search Engine with Controlled Crawling, Lexical & Semantic Retrieval, Hybrid Ranking, and Optional RAG Synthesis.

[![Phase 1: Foundation Ready](https://img.shields.io/badge/Phase%201-Completed-brightgreen.svg)]()
[![Phase 2: Search MVP](https://img.shields.io/badge/Phase%202-Completed-brightgreen.svg)]()
[![Phase 3: UI](https://img.shields.io/badge/Phase%203-Search%20UI-Completed-brightgreen.svg)]()
[![Phase 4: Crawler](https://img.shields.io/badge/Phase%204-Controlled%20Crawler-Completed-brightgreen.svg)]()
[![Stack: FastAPI + React + Docker](https://img.shields.io/badge/Stack-FastAPI%20%7C%20React%20%7C%20Docker-blue.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)]()

---

## 🔍 What is SEEK?

**SEEK** is an open, modular, zero-cost search engine designed to demonstrate the complete lifecycle of information retrieval—from domain-controlled web crawling and HTML parsing to lexical (BM25) and semantic (FAISS) vector retrieval, hybrid candidate ranking, and source-grounded RAG answer generation.

Unlike applications that simply wrap commercial search APIs (e.g. Google or Bing API), SEEK owns its core indexing pipeline and search algorithms. It operates under a strict **zero-cost constraint**, requiring no paid APIs or external dependencies.

---

## 🚦 Current Project Status

- **Phases 1–4**: **COMPLETED** — Foundation · Search MVP (BM25) · Search UI · Controlled Web Crawler
- **Next Phase**: **Phase 5 — Persistent Indexing Pipeline** `[UPCOMING]`

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

## ❌ NOT YET IMPLEMENTED

To keep the development scope clean and strictly phase-aligned, the following components are **NOT** yet implemented:

- ❌ FAISS Vector Indexing & Local Embeddings (Phase 6)
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
                          |  /api/search  (BM25)  /api/crawl (jobs)   |
                          |  /api/index/rebuild (corpus + crawled)    |
                          +-------------------+------------------------+
                                              |
                          +-------------------+--------------------+
                          |                                          |
                          v                                          v
          +---------------------------------+             +-----------------------+
          |  Crawler pipeline (Phase 4)     |------\     |  In-memory BM25 index |
          |  seeds -> robots -> fetch ->    |       \    |  corpus + crawl-* docs |
          |  extract -> chunk -> dedup      |        \   |  + best-effort Postgres|
          +---------------------------------+         \  +-----------------------+
```

---

## 🛠️ Technology Stack

| Component | Technology | Purpose |
|---|---|---|
| **Frontend UI** | React 18, TypeScript, Vite, Tailwind CSS | Responsive web search interface |
| **API Backend** | Python 3.11, FastAPI, Uvicorn, Pydantic v2 | High-performance async REST backend |
| **Crawler** | httpx, asyncio, BeautifulSoup4, robotparser | Controlled async crawling + extraction |
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

---

## 🔮 Next Planned Phase

**Phase 5: Persistent Indexing Pipeline** (persist crawled output to PostgreSQL,
incremental rebuilds, index-on-disk)

---

## 📄 License
This project is licensed under the MIT License - see the LICENSE file for details.