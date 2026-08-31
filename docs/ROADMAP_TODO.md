# SEEK – 14-Phase Implementation Roadmap & TODO Tracker

> **Current Phase**: Phase 1 (Foundation & Docker Environment) - **COMPLETED**  
> **Next Recommended Phase**: Phase 2 (Search MVP & Local Corpus)

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

### [ ] Phase 2: Search MVP (Local Corpus) (Next Phase)
- [ ] Create initial local text document corpus in `data/sample_corpus/`.
- [ ] Setup PostgreSQL database models using SQLAlchemy/Alembic.
- [ ] Implement initial BM25 lexical index builder in `backend/search/`.
- [ ] Implement `/api/search` endpoint returning preliminary JSON search results.

---

### [ ] Phase 3: UI Implementation
- [ ] Build clean SEEK homepage search component.
- [ ] Build search results page (displaying titles, domain badges, snippets, relevance scores).
- [ ] Implement query loading states, error boundaries, and empty result handling.
- [ ] Connect React UI to FastAPI `/api/search` endpoint.

---

### [ ] Phase 4: Controlled Web Crawler
- [ ] Build async crawler module (`backend/crawler/`) using `httpx` and `asyncio`.
- [ ] Implement domain allowlist validator and `robots.txt` rule parser.
- [ ] Implement HTML content parser (`trafilatura` / `BeautifulSoup`) to extract main text body.
- [ ] Implement text chunking and document hash deduplication.

---

### [ ] Phase 5: Persistent Indexing Pipeline
- [ ] Wire crawler output directly to PostgreSQL document storage.
- [ ] Create incremental and full index rebuild routines (`/api/index/rebuild`).
- [ ] Persist BM25 index to `indexes/` directory.

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
