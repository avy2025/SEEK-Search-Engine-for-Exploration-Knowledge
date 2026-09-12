# SEEK – Search Engine for Exploration & Knowledge

> A Genuine, Modular, Docker-First Search Engine with Controlled Crawling, Lexical & Semantic Retrieval, Hybrid Ranking, and Optional RAG Synthesis.

[![Phase 1: Foundation Ready](https://img.shields.io/badge/Phase%201-Completed-brightgreen.svg)]()
[![Phase 2: Search MVP](https://img.shields.io/badge/Phase%202-Completed-brightgreen.svg)]()
[![Stack: FastAPI + React + Docker](https://img.shields.io/badge/Stack-FastAPI%20%7C%20React%20%7C%20Docker-blue.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)]()

---

## 🔍 What is SEEK?

**SEEK** is an open, modular, zero-cost search engine designed to demonstrate the complete lifecycle of information retrieval—from domain-controlled web crawling and HTML parsing to lexical (BM25) and semantic (FAISS) vector retrieval, hybrid candidate ranking, and source-grounded RAG answer generation.

Unlike applications that simply wrap commercial search APIs (e.g. Google or Bing API), SEEK owns its core indexing pipeline and search algorithms. It operates under a strict **zero-cost constraint**, requiring no paid APIs or external dependencies.

---

## 🚦 Current Project Status

- **Current Phase**: **Phase 2 — Search MVP (Local Corpus + BM25)** `[COMPLETED]`
- **Next Phase**: **Phase 3 — Controlled Crawling & Document Ingestion** `[UPCOMING]`

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

6. **Real Search UI** (React frontend):
   - Live BM25 search against the FastAPI backend with loading / empty / error states,
     ranked cards with keyword excerpts, matched-term chips, and the existing health panel.

7. **Tests** — `tests/test_search_phase2.py` (20 tests total incl. Phase 1):
   - Verifies corpus loading, tokenisation, snippets, BM25 ranking, pipeline and the live API.

---

## ❌ NOT YET IMPLEMENTED

To keep the development scope clean and strictly phase-aligned, the following components are **NOT** yet implemented:

- ❌ Web Crawler (Async crawling, domain allowlisting, and `robots.txt` parsing - Phase 3/4)
- ❌ Document Extractor & Text Chunking (Phase 4)
- ❌ FAISS Vector Indexing & Local Embeddings (Phase 6)
- ❌ Multi-Signal Hybrid Ranker (Phase 7)
- ❌ AI / RAG Answer Generation (Phase 8)

---

## 🏗️ System Architecture

```
                                   +---------------------------------------+
                                   |         React + Vite UI (Phase 2)     |
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
                                   +-----------------------------------------+
                                   |   GET /api/search  (Phase 2: BM25)      |
                                   |   engine.search -> rank + snippets      |
                                   +-------------------+---------------------+
                                                       |
                                       in-memory Okapi-BM25 index
                                       + optional best-effort Postgres
```

---

## 🛠️ Technology Stack

| Component | Technology | Purpose |
|---|---|---|
| **Frontend UI** | React 18, TypeScript, Vite, Tailwind CSS | Responsive web search interface |
| **API Backend** | Python 3.11, FastAPI, Uvicorn, Pydantic v2 | High-performance async REST backend |
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
python -m pytest tests/

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

3. **Phase 2 Search Smoke Test**:
   ```bash
   curl -s "http://localhost:8000/api/search?q=docker&limit=3" | python -m json.tool
   ```
   Expected: a `200` with `hits[]` — each hit holding `rank`, `title`, `source`,
   `snippet`, `score`, and `matched_terms` (ranked BM25 results from the corpus).

---

## 🔮 Next Planned Phase

**Phase 3: Controlled Crawling & Document Ingestion**
- Async crawler with domain allowlisting and `robots.txt` parsing.
- Document extractor (HTML parsing, metadata) and text chunking.
- Extend the persisted document store + index beyond the sample corpus.

---

## 📄 License
This project is licensed under the MIT License - see the LICENSE file for details.