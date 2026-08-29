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

### 3.2 API Layer (`backend/api/`)
- **Framework**: FastAPI (ASGI)
- **Endpoints**:
  - `GET /health`: Service and component status.
  - `GET/POST /api/search`: Primary search handler (supports keyword, semantic, or hybrid).
  - `POST /api/crawl`: Trigger domain-controlled crawl job.
  - `GET /api/crawl/{job_id}`: Poll status of running crawl job.
  - `POST /api/index/rebuild`: Administrative endpoint to rebuild inverted/vector indexes.
  - `POST /api/answer`: Generate RAG answer based on retrieved documents.

### 3.3 Content & Crawler Pipeline (`backend/crawler/`, `backend/processor/`)
- **Tools**: `httpx`, `asyncio`, `BeautifulSoup4`, `trafilatura`
- **Flow**:
  1. Validate target seed domain against configured allowlist.
  2. Parse `robots.txt` and obey crawl-delay / exclusions.
  3. Fetch HTML content asynchronously with timeout/retry handlers.
  4. Extract clean textual content, removing script tags, ads, and navigation clutter.
  5. Chunk text into fine-grained segments for retrieval and store hashes in PostgreSQL.

### 3.4 Retrieval Layer (`backend/search/`)
- **Lexical Baseline**: BM25 algorithm (`rank-bm25`) indexing title, headers, and text chunks.
- **Semantic Engine**: `SentenceTransformers` (`all-MiniLM-L6-v2`) generating text embeddings, indexed in `FAISS` or `ChromaDB`.

### 3.5 Ranking Engine (`backend/ranking/`)
- Combines candidate sets using a weighted hybrid score:
  $$\text{Score} = (w_1 \cdot \text{BM25}_{\text{norm}}) + (w_2 \cdot \text{Semantic}_{\text{sim}}) + (w_3 \cdot \text{Freshness}) + (w_4 \cdot \text{Authority})$$
- Removes duplicate URLs and generates query-matched snippets.

### 3.6 Optional AI / RAG Layer (`backend/ai/`)
- Formulates answers strictly using top-scoring retrieved passages as context.
- Zero-cost architecture: supports local models or optional free-tier LLM API.
- If AI component fails or is disabled, standard search results are returned seamlessly.

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
