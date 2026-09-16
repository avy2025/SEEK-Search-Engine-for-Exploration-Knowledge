# SEEK – 14-Phase Implementation Roadmap & TODO Tracker

> **Current Phase**: Phase 5 (Persistent Indexing Pipeline) - **COMPLETED**  
> **Next Recommended Phase**: Phase 6 (Semantic Search, Local ML Embeddings)

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

### [ ] Phase 6: Semantic Search (Local ML Embeddings)
- [ ] Integrate `SentenceTransformers` (`all-MiniLM-L6-v2`) in `backend/search/`.
- [ ] Build vector embedding generator for document chunks.
- [ ] Implement FAISS vector index store in `indexes/faiss_index.bin`.
- [ ] Expose semantic similarity search mode in backend API.

---

### [ ] Phase 7: Hybrid Ranking Engine
- [ ] Implement candidate merging algorithm combining BM25 lexical and semantic vector candidates.
- [ ] Implement weighted hybrid scoring formula ($\text{BM25} + \text{Semantic} + \text{Freshness} + \text{Authority}$).
- [ ] Implement result deduplication and snippet highlighter.

---

### [ ] Phase 8: AI / RAG Answer Generation
- [ ] Implement passage selector to pick top $K$ relevant context chunks.
- [ ] Implement local/free LLM context prompt builder.
- [ ] Expose `/api/answer` endpoint for AI synthesized answers with source citations.
- [ ] Ensure full fallback to standard search if RAG is disabled or fails.

---

### [ ] Phase 9: Specialized Search Modes
- [ ] Add mode filter UI toggles (Web Search, AI Answers, Research Mode, Code Docs).
- [ ] Implement backend mode-specific scoring weights and query intent handlers.

---

### [ ] Phase 10: Automated Testing Suite
- [ ] Write unit tests for query normalization, BM25 scoring, and chunking logic.
- [ ] Write integration tests for API endpoints (`/health`, `/api/search`, `/api/crawl`).
- [ ] Write crawler allowlist and robots parser test suite.

---

### [ ] Phase 11: Docker Hardening & Optimization
- [ ] Optimize multi-stage Docker build files for fast container builds.
- [ ] Setup volume persistence for PostgreSQL data and vector index directories.
- [ ] Add container health checks and restart policies.

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
