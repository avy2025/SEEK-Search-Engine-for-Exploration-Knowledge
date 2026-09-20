# SEEK – System Architecture & Module Specification

## 1. Executive Summary
SEEK (Search Engine for Exploration & Knowledge) is designed as a genuine, modular, open-source search engine. The project implements all core phases of information retrieval: web crawling, content processing, indexing, query parsing, lexical/semantic candidate retrieval, hybrid ranking, and an optional RAG (Retrieval-Augmented Generation) answer layer.

## 2. High-Level Architecture Diagram

```
+-----------------------------------------------------------------------+
|                            USER INTERFACE                             |
|              React + TypeScript + Tailwind CSS (Port 3000)            |
+-----------------------------------------------------------------------+
                                   |
                                   v  (REST / HTTP)
+-----------------------------------------------------------------------+
|                          FASTAPI BACKEND GATEWAY                      |
|                         (Python / Async - Port 8000)                  |
+-----------------------------------------------------------------------+
       |                           |                          |
       v                           v                          v
+--------------+          +------------------+       +------------------+
| QUERY ENGINE |          | CRAWLER PIPELINE |       | AI / RAG ENGINE  |
| - Parse      |          - Allowlist check  |       - Context select   |
| - Tokenize   |          - Robots.txt check |       - Source reference |
| - Normalize  |          - HTTP Fetcher     |       - Local/Free LLM   |
+--------------+          - Text Extractor   |       +------------------+
       |                  +------------------+
       v                           |
+------------------+               |
| RETRIEVAL LAYER  |<--------------+
| - BM25 Index     |  (Populates / Updates Indexes)
| - FAISS Embeddings
+------------------+
       |
       v
+------------------+
| HYBRID RANKER    |
| - Score Merging  |
| - Deduplication  |
| - Snippet Gen    |
+------------------+
       |
       v
+-----------------------------------------------------------------------+
|                          PERSISTENCE LAYER                            |
|             PostgreSQL Database (Document Metadata & Queue)           |
+-----------------------------------------------------------------------+
```

---

## 3. Layer & Module Breakdown

### 3.1 Presentation Layer (`frontend/`)
- **Framework**: React + TypeScript + Tailwind CSS
- **Responsibilities**:
  - Render clean search bar with mode selectors (Web, Research, Code, AI).
  - Present ranked result cards with titles, source URLs, domains, snippets, and scores.
  - Display visually separated AI synthesized answers with clickable source citations.
  - Handle loading skeletons, error states, and pagination.

> **Implemented (Phase 3)**: the SEEK search UI is live — a minimal search-driven
> homepage with a prominent search bar, sample queries, real ranked results
> (title/source/snippet/score/rank/matched terms), full loading / empty / error
> states, URL-query sync (`/?q=…`), a configurable API base URL
> (`VITE_API_BASE_URL`), and health polling. Mode selectors and AI answers are
> roadmap backlog (Phases 7–9).

### 3.2 API Layer (`backend/api/`)
- **Framework**: FastAPI (ASGI)
- **Endpoints**:
  - `GET /health`: Service and component status.
  - `GET/POST /api/search`: Primary search handler (supports keyword, semantic, or hybrid).
  - `POST /api/crawl`: Trigger domain-controlled crawl job.
  - `GET /api/crawl/{job_id}`: Poll status of running crawl job.
  - `POST /api/index/rebuild`: Rebuild indexes (PostgreSQL-backed, with legacy in-memory fallback).
  - `POST /api/index/refresh`: Incremental change detection (new/modified/deleted) against PostgreSQL.
  - `POST /api/index/semantic/rebuild`: Rebuild the FAISS semantic index from PostgreSQL.
  - `POST /api/index/semantic/refresh`: Incremental change detection for the FAISS semantic index.
  - `GET /api/index/status`: Persistent-index health and staleness status (BM25 + semantic).
  - `POST /api/answer`: Generate RAG answer based on retrieved documents.

> **Implemented (Phases 4–6)**: `GET /health`, `GET /` (service meta),
> `GET /api/search` (with `mode=lexical|bm25|semantic`), `POST /api/crawl`,
> `GET /api/crawl`, `GET /api/crawl/{job_id}`, `POST /api/index/rebuild`,
> `POST /api/index/refresh`, `POST /api/index/semantic/rebuild`,
> `POST /api/index/semantic/refresh` and `GET /api/index/status` are live,
> consumed by the Phase 3 React UI (`frontend/`) and exercised end-to-end by the
> acceptance probe (`scripts/probe_phase2.py`) and the test suites
> (`tests/test_search_phase2.py`, `tests/test_crawler_phase4.py`,
> `tests/test_index_persistence_phase5b.py`,
> `tests/test_semantic_search_phase6.py`).
> `POST /api/answer` (RAG) remains roadmap backlog.

### 3.3 Content & Crawler Pipeline (`backend/crawler/`, `backend/processing/`)
- **Tools**: `httpx`, `asyncio`, `BeautifulSoup4`, `urllib.robotparser`
- **Flow**:
  1. Normalize/validate each seed URL against the configured allowlist and
     reject dangerous URLs (non-http schemes, credentials, private hosts,
     binary/PDF paths).
  2. Parse `robots.txt` (per-host cache) and obey crawl-delay / exclusions;
     HTTP 401/403 robots responses block broadly.
  3. Fetch HTML content asynchronously with timeout, redirect and size caps.
  4. Extract clean textual content with BeautifulSoup, removing scripts, ads,
     navigation and header/footer clutter.
  5. Chunk text into fine-grained segments, compute SHA-256 content hashes,
     dedupe by URL and content, and fold results into the BM25 index via
     `POST /api/index/rebuild`.

> **Implemented (Phase 4)**: the crawler (`backend/crawler/`) is live via the
> `backend/api/crawl.py` router (async jobs, `CrawlManager` background threads,
> `CrawlStore` in-process dedup) plus `backend/api/index.py` to rebuild the
> search engine over corpus + crawled pages. Trafilatura remains an optional
> upgrade; BeautifulSoup is the active extractor.

### 3.4 Retrieval Layer (`backend/search/`)
- **Lexical Baseline**: BM25 algorithm (`rank-bm25`) indexing title, headers, and text chunks.
- **Semantic Engine**: `SentenceTransformers` (`all-MiniLM-L6-v2`) generating text embeddings, indexed in `FAISS` or `ChromaDB`.

> **Implemented (Phases 2, 5 & 6)**: lexical retrieval is live via
> `backend/processing/` (tokenizer, loader, snippets) -> `backend/pipeline.py`
> (corpus + crawled pages -> `backend/search/engine.py`) -> `GET /api/search`.
> Phase 5 adds a persistent index lifecycle: `backend/search/index_store.py`
> (atomic `indexes/bm25/index.pkl` + `metadata.json` artifact, versioned) and
> `backend/search/index_manager.py` (`IndexManager` singleton — full `rebuild`,
> incremental `refresh` via `document_id -> content_hash` change detection,
> `status`, resilient startup loading). PostgreSQL is the canonical source of
> truth; the on-disk artifact is a derived, rebuildable cache.
>
> Phase 6 adds semantic retrieval: `backend/search/embeddings.py` wraps
> `SentenceTransformers` (`all-MiniLM-L6-v2` → 384-dim, L2-normalised batch
> encoding; the model is loaded lazily on first use, never at import/boot),
> `backend/search/faiss_store.py` persists the FAISS `IndexFlatIP` artifact
> + metadata to `indexes/faiss_index.bin` / `faiss_metadata.json` (atomic
> writes, `FAISS_FORMAT_VERSION = 1`), and `backend/search/semantic.py` hosts
> the `SemanticIndexManager` singleton (`rebuild`, change-detection `refresh`,
> `load_on_startup`, cosine-similarity `search`, `status`). `GET /api/search` now
> accepts `mode=lexical|bm25|semantic|hybrid`; when the embedding stack or index is
> unavailable the API returns structured status blocks (`unavailable`/`degraded`)
> and never silently falls back to BM25 while claiming `mode=hybrid`.

### 3.5 Ranking Engine (`backend/search/hybrid.py`)
- Combines lexical (BM25) and vector (Semantic FAISS) candidate sets using a weighted hybrid score:
  $$\text{Score}_{\text{hybrid}} = (w_{\text{BM25}} \cdot \text{BM25}_{\text{norm}}) + (w_{\text{semantic}} \cdot \text{Semantic}_{\text{norm}})$$
- **Score Normalization Strategy**: Scores are scaled using deterministic Min-Max normalization ($s_{\text{norm}} = \frac{s - s_{\text{min}}}{s_{\text{max}} - s_{\text{min}}}$) per candidate component set. Equal score or single candidate sets map to 1.0 (or 0.0 if score <= 0.0). NaN/Infinity inputs are sanitized to 0.0.
- **Candidate Merging & Deduplication**: Candidates from BM25 and Semantic indices are retrieved up to candidate limits (`HYBRID_BM25_CANDIDATES`, `HYBRID_SEMANTIC_CANDIDATES`), merged by canonical `document_id`, deduplicated, and ranked descending by hybrid score. Ties are broken deterministically by document ID.
- **Query Term Highlighting**: Snippets preserve plain text safety and wrap matched terms case-insensitively in `<mark>...</mark>` tags while escaping raw HTML to prevent XSS.

### 3.6 Optional AI / RAG Layer (`backend/ai/`)
- **Passage Selector (`backend/ai/pipeline.py`)**: Extracts top-K context chunks from candidate retrieval hits (hybrid/lexical/semantic), enforces character caps (`RAG_MAX_CONTEXT_CHARS=3000`), strips snippet markup tags, and deduplicates source documents.
- **Grounded Prompt Builder**: Formulates strict instruction prompts compelling the model to answer *only* using supplied sources, cite inline source IDs (`[1]`, `[2]`), and state insufficient context when information is missing.
- **LLM Provider Abstraction (`backend/ai/providers.py`)**: Modular `LLMProvider` interface supporting:
  - `FakeLLMProvider`: Deterministic mock provider for offline tests and zero-dependency CI runs.
  - `OllamaLLMProvider`: Local Ollama HTTP API endpoint (`http://localhost:11434`).
  - `HuggingFaceLLMProvider`: Local CPU/GPU PyTorch transformers pipeline (`Qwen/Qwen2.5-0.5B-Instruct`).
- **Endpoint & Fallback (`POST /api/answer`)**: Synthesizes grounded answers with source citations. If RAG is disabled, context is insufficient (top score < 0.15 or zero hits), or the LLM provider fails/times out, the endpoint returns a structured fallback envelope containing standard search hits.

---

## 4. Data Model Schema (PostgreSQL)

```sql
-- Main indexed documents metadata
CREATE TABLE documents (
    id SERIAL PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    domain VARCHAR(255) NOT NULL,
    title TEXT,
    content TEXT NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    crawled_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Granular document chunks for fine-grained retrieval & RAG
CREATE TABLE document_chunks (
    chunk_id SERIAL PRIMARY KEY,
    document_id INT REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    text_content TEXT NOT NULL,
    char_length INT NOT NULL
);

-- Crawl tracking & job history
CREATE TABLE crawl_jobs (
    job_id VARCHAR(64) PRIMARY KEY,
    seed_url TEXT NOT NULL,
    status VARCHAR(32) NOT NULL, -- PENDING, RUNNING, COMPLETED, FAILED
    pages_crawled INT DEFAULT 0,
    started_at TIMESTAMP WITH TIME ZONE,
    finished_at TIMESTAMP WITH TIME ZONE
);
```
