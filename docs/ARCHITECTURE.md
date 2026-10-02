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
> (`VITE_API_BASE_URL`), and health polling.

> **Implemented (Phase 9)**: the specialized search modes are wired end to end.
> `src/lib/modes.ts` mirrors the backend enum, `src/lib/urlState.ts` holds the
> pure `parseSearchState` / `buildSearchPath` pair that keeps `?q=…&mode=…` in
> the URL (deep links, refresh and back/forward), and
> `src/components/ModeSelector.tsx` renders the four modes as an ARIA
> `radiogroup` with roving `tabindex` and Arrow/Home/End keys.
> `SearchResults.tsx` composes the mode-specific view: an explicit
> degraded/unavailable banner, `AnswerPanel` (grounded AI answer / research
> synthesis, or an explicit "no answer could be generated" note),
> `SourcesPanel` (cited sources), and `ResultCard`s that render the code excerpt
> supplied by Code Docs. The UI never invents data: every field is taken from the
> backend envelope.

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
  - `GET /api/search/modes`: Machine-readable catalog of the specialized search modes.
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
> `tests/test_semantic_search_phase6.py`, plus the cross-phase Phase 10 suite
> described in §3.8).
> `POST /api/answer` (RAG) remains roadmap backlog.

> **Implemented (Phases 7–9)**: `GET /api/search` additionally accepts
> `mode=hybrid` (Phase 7) and the specialized modes `web|ai|research|code`
> (Phase 9), `GET /api/search/modes` serves the mode catalog, and `POST
> /api/answer` (Phase 8 RAG) is live. `backend/api/search.py` keeps the legacy
> handlers (`_lexical_search`, `_semantic_search`, `_hybrid_search`) untouched
> and validates the `mode` parameter through the controlled enum in
> `backend/search/modes.py`; an unknown mode is rejected with HTTP 422
> (`detail.error = "invalid_search_mode"`). Mode execution is delegated to
> `backend/api/mode_orchestrator.py`, which composes the existing handlers and
> the Phase 8 RAG pipeline rather than re-implementing retrieval.

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

### 3.7 Specialized Search Modes (`backend/search/modes.py`, `backend/api/mode_orchestrator.py`)

Phase 9 adds four user-facing search modes as a thin **orchestration layer** over
the retrieval and RAG components above. No scoring, indexing or embedding logic
is duplicated: modes only choose *which* existing service to call and *how* to
arrange its output.

- **Mode Registry (`backend/search/modes.py`)**: a controlled `SearchMode` enum
  (`web`, `ai`, `research`, `code`) plus a `ModeSpec` describing, per mode, the
  retrieval strategy, ranking weights, result limits, candidate widening, RAG
  toggle, snippet behaviour, source diversification and documentation/code
  handling. Every knob is read from the centralised `MODE_*` / `RESEARCH_*` /
  `CODE_*` settings, so deployments retune modes without code changes.
  `normalize_mode_param()` also accepts the legacy retrieval modes and raises
  `InvalidSearchModeError` for anything else.
- **Orchestrator (`backend/api/mode_orchestrator.py`)**: `execute_search_mode()`
  probes index availability, delegates retrieval to `_hybrid_search` /
  `_semantic_search` / `_lexical_search` (with the mode's candidate width and
  weights), applies the deterministic post-processing helpers, and — for the RAG
  modes — hands the *already retrieved* hits to `generate_rag_answer()` so
  retrieval never runs twice.
- **Response envelope**: every mode returns
  `{query, mode, status, total, limit, hits, took_ms, message, answer, sources, metadata}`.
  `status` is `ok`, `degraded` (a preferred capability was missing and a fallback
  was served) or `unavailable` (nothing could be served). Retrieval health always
  wins over the RAG outcome, and every fallback is spelled out in `message` and
  `metadata.degraded_reason` — retrieval failures are never hidden.
- **Honest matching**: the BM25/hybrid pipeline pads its candidate list with
  `0.0`-scored documents. `drop_unmatched_hits()` removes them from the
  specialized-mode envelope (`MODE_MATCH_SCORE_FLOOR`), so `total` reflects real
  matches instead of ranking padding. The legacy retrieval modes keep their
  original behaviour.
- **Mode behaviour**:
  - `web` — hybrid retrieval, ranked results, no generated answer.
  - `ai` — hybrid retrieval plus a Phase 8 grounded answer with citations.
  - `research` — wider candidate retrieval (`RESEARCH_CANDIDATE_MULTIPLIER`),
    per-host source diversification, richer snippets, and a labelled distinction
    between `metadata.evidence` (`retrieved_evidence`) and `metadata.synthesis`
    (`generated_synthesis`).
  - `code` — lexical-leaning weights (`CODE_BM25_WEIGHT` > `CODE_SEMANTIC_WEIGHT`),
    technical identifier expansion, documentation-source *prioritisation* (a
    preference, never a filter) and code excerpts extracted from documents SEEK
    already indexed. It adds no crawler and calls no external API.
- **No fabrication**: `answer` is `null` whenever the RAG pipeline falls back,
  and snippets/code excerpts are re-rendered from indexed document content only.

### 3.8 Test Architecture (`tests/`, `frontend/tests/`)

Phase 10 turns testing into an architectural concern rather than a collection of
per-phase scripts. The suite is organised by **what it protects** rather than by
which phase wrote the code, because the contracts most likely to rot are the
ones that span a phase boundary.

- **Layered suites** (`tests/`):
  | Layer | Module | Protects |
  |---|---|---|
  | Unit | `test_unit_phase10.py` | Processing, BM25, query, hybrid, RAG, crawler helpers, artifact metadata, settings |
  | API | `test_api_phase10.py` | Every published route: routing, validation, contracts, mode × index-state × query matrix |
  | Integration | `test_integration_phase10.py` | Corpus → index, persistence matrices (valid/missing/corrupt/stale/metadata-mismatch/atomic-write-failure/interrupted-write), failure combinations |
  | Security | `test_security_phase10.py` | Input never interpreted, escaping order, URL/SSRF safety, no-fabricated-answers, repository hygiene |
  | Regression | `test_regression_phase10.py` | Cross-phase seams, frontend wiring, documentation wiring, performance smoke |

  The original per-phase modules (`test_search_phase2.py`,
  `test_crawler_phase4.py`, `test_index_persistence_phase5b.py`,
  `test_semantic_search_phase6.py`, `test_hybrid_phase7.py`,
  `test_rag_phase8.py`, `test_search_modes_phase9.py`) are retained unchanged so
  phase history stays auditable.

- **Shared fixtures** (`tests/conftest.py`): in-memory document corpora, a
  `FakeRepository` implementing the full `DocumentRepository` surface with
  `available` / `fail_with` switches, the canonical degraded repository,
  `IndexManager` / `SemanticIndexManager` instances redirected to `tmp_path`,
  present/unavailable semantic doubles, and a hermetic `TestClient`. An autouse
  fixture resets the index, semantic and crawl singletons between tests, so no
  test can observe state left by another.

- **Hermetic by construction**: the default gate needs no PostgreSQL, no
  embedding-model download and no outbound HTTP. Tests requiring real
  infrastructure read `SEEK_TEST_DATABASE_URL` and skip cleanly when it is
  absent; `sentence_transformers` is never imported at module scope, so
  `backend.main` stays importable without the ML stack.

- **Frontend as a first-class test citizen**: frontend logic lives in pure
  modules (`urlState.ts`, `modes.ts`) testable with Node's built-in `node:test`
  runner — no test-framework dependency. `npm run test:frontend` runs both
  suites, and `TestFrontendSuites` drives `test:frontend`, `typecheck` and
  `build` from pytest so a single command verifies the whole stack.

- **Contract documentation as a test**: `docs/TESTING_PHASE10.md` holds the
  coverage matrix, and `TestDocumentationIsPresent` asserts that the README
  documents every published route, that the roadmap marks Phase 10 complete, and
  that the matrix publishes **no coverage percentage** without a real measurement
  run.

> **Implemented (Phase 10)**: `python -m pytest -q` is the single gate covering
> Phases 0–9; `python scripts/probe_phase2.py` verifies the Phase 2 acceptance
> criteria (18/18 imports, app build, and one real end-to-end query).

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
