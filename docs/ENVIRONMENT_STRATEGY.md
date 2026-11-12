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
   - `RAG_ENABLED`: Boolean toggle (enabled by default).
   - `RAG_LLM_PROVIDER`: `fake` (offline default), `ollama`, or `transformers`.
   - `RAG_OLLAMA_HOST` / `RAG_OLLAMA_MODEL`: Local Ollama endpoint and model.
   - `RAG_TRANSFORMERS_MODEL`: Local Hugging Face model identifier.
6. **Optional Live Internet Search**:
   - `TAVILY_API_KEY`: backend-only Tavily credential; empty by default.
   - `TAVILY_CONNECT_TIMEOUT_SECONDS` / `TAVILY_READ_TIMEOUT_SECONDS`: provider timeouts.
   - `TAVILY_CACHE_TTL_SECONDS`: successful-result cache duration (default 600).
   - `TAVILY_USAGE_DB_PATH`: SQLite monthly usage ledger (default
     `./indexes/tavily_usage.sqlite3`); Docker stores it on the persistent
     `seek_indexes` volume.
7. **Optional Gemini AI Answers**:
   - `GEMINI_API_KEY`: backend-only Google AI Studio key; empty by default.
   - `GEMINI_MODEL`: model identifier (default `gemini-3.5-flash-lite`); the
     backend rejects models outside its verified free-tier allowlist.
   - `GEMINI_CONNECT_TIMEOUT_SECONDS` / `GEMINI_READ_TIMEOUT_SECONDS`: API timeouts.
   - `GEMINI_DAILY_REQUEST_LIMIT`: maximum 30 requests per UTC day.
   - `GEMINI_MAX_SOURCES` / `GEMINI_MAX_CONTEXT_CHARS`: caps of 5 sources and
     12,000 research characters.
   - `GEMINI_CACHE_TTL_SECONDS`: successful answer cache duration (default 600).
   - `GEMINI_USAGE_DB_PATH`: persistent SQLite daily usage ledger; Docker stores
     it on the `seek_indexes` volume.

### Tavily free-plan safeguards (Phase 12)

- Live search is opt-in and uses only `search_depth=basic`, `max_results <= 5`,
  `include_answer=false`, and `include_raw_content=false`. The API key is sent
  only from the backend to Tavily and never returned to the frontend.
- Tavily documents basic search as 1 API credit. SEEK reserves that credit in
  an atomic SQLite transaction before each provider request and uses returned
  credit usage if the response provides it.
- Reference: [Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search),
  [Tavily pricing](https://www.tavily.com/pricing), and
  [Tavily dashboard](https://app.tavily.com/).
- The application has a fixed 900-credit monthly budget, leaving at least 100
  of the published 1,000 free-plan credits unused. It does not configure or
  enable paid usage.
- This counter applies only to this SEEK installation. Use the provider
  dashboard for an account-wide cap where available, and stay on the free
  Researcher plan without adding a payment method, upgrading, or enabling
  pay-as-you-go. Provider plan terms may change.
- Do not share one key with other applications if you need SEEK's displayed
  remaining count to match all account activity; external use is not visible to
  SEEK.

### Gemini free-tier safeguards (Phase 13)

- Current official [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing)
  lists `gemini-3.5-flash-lite` as free tier and `gemini-3.8-flash` as not
  available on the free tier. SEEK defaults to the former and rejects any model
  not explicitly allowlisted in backend code. The provider also verifies that
  the model supports `generateContent` before its first generation.
- The AI Answers path has no Google Search grounding, retries, paid model
  fallback, or alternate provider. SEEK accepts at most 30 requests per day,
  five sources and 12,000 context characters, and stores daily usage in SQLite.
- Create the API key in [Google AI Studio](https://aistudio.google.com/apikey)
  using a project with Cloud billing disabled and no paid billing account.
  Google quota and billing configuration remain external; the app cannot
  guarantee account-wide charges will not occur if billing is later enabled.
- Both keys remain backend-only, are sent in request headers/bodies only as
  required, and are never placed in Vite build variables or API responses.

---

## 3. Zero-Cost Guarantee & Resource Budgeting

| Component | Default Free / Open-Source Tool | Resource Profile |
|---|---|---|
| **Database** | PostgreSQL 16 (Docker) | Low memory footprint (< 100MB RAM idle) |
| **Backend API** | FastAPI + Uvicorn | Lightweight async process (< 150MB RAM) |
| **Lexical Index** | `rank-bm25` (In-memory/File persistent) | Fast CPU retrieval (< 50MB RAM) |
| **Semantic Vectors**| `all-MiniLM-L6-v2` + `FAISS` | CPU execution (~300MB RAM for model) |
| **Frontend UI** | React + Vite + Tailwind CSS | Static asset bundle served via Nginx/Node |
| **Live search** | Tavily Search REST API (optional, free-plan only) | Basic web search; local 900-credit monthly guard |
| **AI Answers** | Tavily research + Gemini free-tier API (optional) | 30 requests/day; max 5 sources / 12,000 chars; no paid fallback |

---

## 4. Security, Credentials & Privacy Rules

- **Zero Secret Commits**: No API keys, secret keys, or passwords may be committed into Git repository history. `.env` is listed in `.gitignore`.
- **Tavily Key**: `TAVILY_API_KEY` is injected into the backend only; never use a frontend `VITE_*` variable or expose credentials in a response/log.
- **Gemini Key**: `GEMINI_API_KEY` is injected into the backend only. Keep the Google AI Studio project billing disabled; the runtime only allows the currently verified free-tier Gemini model.
- **Untrusted Input Handling**: All external web page HTML fetched by crawler is treated as untrusted text. Scripts are stripped during DOM parsing.
- **Controlled Crawler Scope**: Crawler is strictly locked to allowed domains; outbound connections to arbitrary IP ranges or unverified hosts are prohibited.
