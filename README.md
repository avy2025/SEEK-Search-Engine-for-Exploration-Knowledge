# SEEK – Search Engine for Exploration & Knowledge

> A Genuine, Modular, Docker-First Search Engine with Controlled Crawling, Lexical & Semantic Retrieval, Hybrid Ranking, and Optional RAG Synthesis.

[![Phase 1: Foundation Ready](https://img.shields.io/badge/Phase%201-Completed-brightgreen.svg)]()
[![Stack: FastAPI + React + Docker](https://img.shields.io/badge/Stack-FastAPI%20%7C%20React%20%7C%20Docker-blue.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)]()

---

## 🔍 What is SEEK?

**SEEK** is an open, modular, zero-cost search engine designed to demonstrate the complete lifecycle of information retrieval—from domain-controlled web crawling and HTML parsing to lexical (BM25) and semantic (FAISS) vector retrieval, hybrid candidate ranking, and source-grounded RAG answer generation.

Unlike applications that simply wrap commercial search APIs (e.g. Google or Bing API), SEEK owns its core indexing pipeline and search algorithms. It operates under a strict **zero-cost constraint**, requiring no paid APIs or external dependencies.

---

## 🚦 Current Project Status

- **Current Phase**: **Phase 1 — Foundation & Docker Infrastructure** `[COMPLETED]`
- **Next Phase**: **Phase 2 — Search MVP (Local Corpus)** `[UPCOMING]`

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

## ❌ NOT YET IMPLEMENTED

To keep the development scope clean and strictly phase-aligned, the following components are **NOT** yet implemented:

- ❌ Web Crawler (Async crawling, domain allowlisting, and `robots.txt` parsing - Phase 4)
- ❌ Document Extractor & Text Chunking (Phase 4)
- ❌ BM25 Lexical Inverted Index (Phase 2 & Phase 5)
- ❌ FAISS Vector Indexing & Local Embeddings (Phase 6)
- ❌ Multi-Signal Hybrid Ranker (Phase 7)
- ❌ AI / RAG Answer Generation (Phase 8)
- ❌ Real Search Query Processing (Search button currently displays Phase 1 status notice - Phase 2+)

---

## 🏗️ System Architecture

```
                                  +---------------------------------------+
                                  |         React + Vite UI               |
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
                                   |  GET /health   | |      GET /       |
                                   | (Health Check) | | (System Meta)    |
                                   +----------------+ +------------------+
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

---

## 🔮 Next Planned Phase

**Phase 2: Search MVP (Local Corpus)**
- Populate local sample document collection in `data/sample_corpus/`.
- Setup SQLAlchemy models and database migrations.
- Implement initial BM25 keyword indexer.
- Expose `/api/search` endpoint returning JSON candidate results.

---

## 📄 License
This project is licensed under the MIT License - see the LICENSE file for details.