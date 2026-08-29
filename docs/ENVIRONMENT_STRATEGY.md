# SEEK – Environment Configuration & Zero-Cost Strategy

## 1. Environment Configuration Philosophy
SEEK is engineered with a **Docker-first, zero-cost-first** operational strategy. The application must be fully runnable locally on standard student or developer hardware without purchasing cloud resources, subscription APIs, or proprietary search indexes.

---

## 2. Configuration Management

Configuration is loaded through `.env` files using `pydantic-settings` in Python and standard environment injection in Docker containers.

### Key Environment Sections:
1. **Server & Ports**: Host IP bindings, backend port (8000), frontend port (3000).
2. **Database Settings**: PostgreSQL credentials, connection string, container alias.
3. **Crawler Policies**:
   - `CRAWLER_ALLOWED_DOMAINS`: Comma-separated allowlist.
   - `CRAWLER_RESPECT_ROBOTS`: Strict compliance with `robots.txt` (`true`).
   - `CRAWLER_MAX_DEPTH`: Crawl recursion cap (default `2`).
   - `CRAWLER_CONCURRENT_REQUESTS`: Rate limiter to prevent DOSing target servers.
4. **Retrieval Tokens & Embeddings**:
   - `BM25_K1` & `BM25_B`: BM25 hyper-parameters.
   - `EMBEDDING_MODEL`: Local HuggingFace SentenceTransformer model string.
5. **AI / RAG Controls**:
   - `RAG_ENABLED`: Boolean toggle (`false` by default to preserve computational resources).

---

## 3. Zero-Cost Guarantee & Resource Budgeting

| Component | Default Free / Open-Source Tool | Resource Profile |
|---|---|---|
| **Database** | PostgreSQL 16 (Docker) | Low memory footprint (< 100MB RAM idle) |
| **Backend API** | FastAPI + Uvicorn | Lightweight async process (< 150MB RAM) |
| **Lexical Index** | `rank-bm25` (In-memory/File persistent) | Fast CPU retrieval (< 50MB RAM) |
| **Semantic Vectors**| `all-MiniLM-L6-v2` + `FAISS` | CPU execution (~300MB RAM for model) |
| **Frontend UI** | React + Vite + Tailwind CSS | Static asset bundle served via Nginx/Node |

---

## 4. Security, Credentials & Privacy Rules

- **Zero Secret Commits**: No API keys, secret keys, or passwords may be committed into Git repository history. `.env` is listed in `.gitignore`.
- **Untrusted Input Handling**: All external web page HTML fetched by crawler is treated as untrusted text. Scripts are stripped during DOM parsing.
- **Controlled Crawler Scope**: Crawler is strictly locked to allowed domains; outbound connections to arbitrary IP ranges or unverified hosts are prohibited.
