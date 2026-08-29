# SEEK – Search Engine for Exploration & Knowledge

> A Genuine, Modular, Docker-First Search Engine with Controlled Crawling, Lexical & Semantic Retrieval, Hybrid Ranking, and Optional RAG Synthesis.

[![Phase 0: Architecture Ready](https://img.shields.io/badge/Phase%200-Completed-brightgreen.svg)]()
[![Stack: FastAPI + React + Docker](https://img.shields.io/badge/Stack-FastAPI%20%7C%20React%20%7C%20Docker-blue.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)]()

---

## 🔍 Overview
**SEEK** is an end-to-end search engine designed to demonstrate the complete lifecycle of information retrieval—from source discovery and controlled crawling to HTML content parsing, lexical/semantic indexing, hybrid candidate ranking, and source-grounded AI answer generation.

Unlike applications that simply wrap proprietary commercial search APIs (e.g. Google or Bing API), SEEK owns its core data pipeline and search indexes. It is built locally first under a **zero-cost constraint**, requiring no paid APIs or cloud dependencies for core functionality.

---

## 📁 Repository Structure
```
SEEK/
├── docs/                      # Architectural specifications & roadmap documentation
│   ├── ARCHITECTURE.md        # System design, data flow, schema, and ranking formulas
│   ├── ENVIRONMENT_STRATEGY.md# Environment variables & zero-cost rules
│   ├── ROADMAP_TODO.md        # 14-Phase step-by-step development tracker
│   └── SEEK_SRS.md            # Software Requirements Specification (Version 2.0)
├── frontend/                  # React + TypeScript + Tailwind CSS UI (Phase 1+)
├── backend/                   # FastAPI Backend Services
│   ├── api/                   # REST API routes and endpoint controllers
│   ├── crawler/               # Async domain-controlled web crawler
│   ├── processor/             # HTML clean text extractor & chunking
│   ├── search/                # Lexical (BM25) and Semantic (FAISS) retrievers
│   ├── ranking/               # Multi-signal hybrid ranker & deduplicator
│   ├── ai/                    # Optional RAG answer synthesis module
│   └── models/                # Pydantic & SQLAlchemy data schemas
├── data/                      # Local document corpus and raw seed files
├── indexes/                   # Persistent BM25 inverted index & vector stores
├── tests/                     # Automated unit, integration, and API test suites
├── docker/                    # Dockerfiles for backend and frontend
├── docker-compose.yml         # Container orchestration manifest
├── .env.example               # Environment configuration template
├── requirements.txt           # Python dependency specification
└── README.md                  # Main repository README
```

---

## 🛠️ Technology Stack

| Component | Technology | Purpose |
|---|---|---|
| **Frontend UI** | React, TypeScript, Tailwind CSS | Modern responsive search interface |
| **API Gateway** | Python, FastAPI, Uvicorn | High-performance async REST backend |
| **Database** | PostgreSQL | Persistent document metadata and crawl queue |
| **Crawler** | `httpx`, `asyncio`, `trafilatura` | Domain-controlled async web crawler |
| **Lexical Search**| BM25 (`rank-bm25`) | Inexpensive, high-precision keyword baseline |
| **Semantic Search**| SentenceTransformers (`all-MiniLM-L6-v2`), FAISS | Local embedding vector similarity search |
| **Infrastructure**| Docker, Docker Compose | Reproducible local development & deployment |

---

## 🚦 Phased Development Roadmap

- **Phase 0: Planning & Architecture Setup** `[COMPLETED]`
  - SRS analysis, directory structure creation, system design, roadmap authoring, environment strategy.
- **Phase 1: Foundation & Docker Setup** `[NEXT RECOMMENDED PHASE]`
  - Setup basic FastAPI health endpoint, React project shell, and Docker Compose local environment.
- **Phase 2: Search MVP (Local Corpus)**
- **Phase 3: Search UI & Snippet Display**
- **Phase 4: Controlled Web Crawler**
- **Phase 5: Persistent Indexing Pipeline**
- **Phase 6: Local Semantic Vector Search**
- **Phase 7: Hybrid Ranking Engine**
- **Phase 8: AI / RAG Synthesis Layer**
- **Phase 9-14: Testing, Hardening & Evaluation**

---

## 🛠️ Quick Start (Phase 0 Setup Verification)

1. **Clone & Environment Setup**:
   ```bash
   cp .env.example .env
   ```
2. **Review Documentation**:
   - Technical Architecture: [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md)
   - Environment Strategy: [`docs/ENVIRONMENT_STRATEGY.md`](./docs/ENVIRONMENT_STRATEGY.md)
   - Roadmap & TODOs: [`docs/ROADMAP_TODO.md`](./docs/ROADMAP_TODO.md)
   - Full SRS Document: [`docs/SEEK_SRS.md`](./docs/SEEK_SRS.md)

---

## 📄 License
This project is licensed under the MIT License - see the LICENSE file for details.