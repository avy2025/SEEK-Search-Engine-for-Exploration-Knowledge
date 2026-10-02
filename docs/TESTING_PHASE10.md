# Phase 10 — Automated Testing Suite

Phase 10 adds a **cross-phase** automated testing suite for SEEK: one documented
coverage matrix, shared offline fixtures, and a single pytest entry point that
exercises every Phase 0–9 seam without a database, a network or an embedding
model download.

This document is the coverage matrix. It records **which behaviour is covered by
which test**, not a coverage percentage — see
[Why there is no coverage number](#why-there-is-no-coverage-number).

---

## Contents

- [Goals and non-goals](#goals-and-non-goals)
- [How to run the suite](#how-to-run-the-suite)
- [Test layout](#test-layout)
- [Coverage matrix](#coverage-matrix)
  - [1. Processing — tokenizer, loader, snippets](#1-processing--tokenizer-loader-snippets)
  - [2. BM25 and the search engine](#2-bm25-and-the-search-engine)
  - [3. Query processing](#3-query-processing)
  - [4. Semantic search (offline)](#4-semantic-search-offline)
  - [5. Hybrid ranking](#5-hybrid-ranking)
  - [6. RAG answer generation](#6-rag-answer-generation)
  - [7. Specialized search modes](#7-specialized-search-modes)
  - [8. HTTP API surface](#8-http-api-surface)
  - [9. Search mode × index-state × query matrix](#9-search-mode--index-state--query-matrix)
  - [10. Controlled crawler](#10-controlled-crawler)
  - [11. PostgreSQL repository](#11-postgresql-repository)
  - [12. Persistence and restart](#12-persistence-and-restart)
  - [13. Frontend](#13-frontend)
  - [14. Security and input validation](#14-security-and-input-validation)
  - [15. Failure and resilience combinations](#15-failure-and-resilience-combinations)
  - [16. Performance smoke](#16-performance-smoke)
  - [17. Cross-phase regression](#17-cross-phase-regression)
  - [18. Documentation wiring](#18-documentation-wiring)
- [Fixture catalogue](#fixture-catalogue)
- [Offline and skip conventions](#offline-and-skip-conventions)
- [Defects found and fixed by this suite](#defects-found-and-fixed-by-this-suite)
- [Why there is no coverage number](#why-there-is-no-coverage-number)
- [Known gaps and deliberate non-goals](#known-gaps-and-deliberate-non-goals)

---

## Goals and non-goals

**Goals**

1. One command (`python -m pytest -q`) that covers processing, retrieval,
   ranking, RAG, the HTTP surface, persistence, the crawler, security and the
   frontend wiring.
2. Every tier runs **offline**: no PostgreSQL, no `sentence-transformers`
   download, no outbound HTTP. Real infrastructure is exercised only when a
   developer explicitly opts in.
3. Cross-phase **seam** coverage — the promises a later phase makes to an
   earlier one — which per-phase suites structurally cannot see.
4. A documented matrix so a reviewer can tell what is covered, by what, and
   what is deliberately not.

**Non-goals**

* No new product features. Phase 10 added no retrieval capability, no endpoint
  and no setting. Where a test exposed a real defect, the defect was fixed (see
  [Defects found and fixed](#defects-found-and-fixed-by-this-suite)); nothing
  was added to make a test convenient.
* No CI service definition. The suite is a local/CLI gate that any CI runner can
  invoke; no workflow file is added here.
* No load or soak testing. The performance tier is a smoke check only.

---

## How to run the suite

```bash
# Everything (the single gate)
python -m pytest -q

# One tier at a time
python -m pytest tests/test_unit_phase10.py -q
python -m pytest tests/test_api_phase10.py -q
python -m pytest tests/test_integration_phase10.py -q
python -m pytest tests/test_security_phase10.py -q
python -m pytest tests/test_regression_phase10.py -q

# Pre-existing per-phase suites (unchanged)
python -m pytest tests/test_search_phase2.py tests/test_index_persistence_phase5b.py -q

# Phase 2 acceptance probe (imports + app build + one real query)
python scripts/probe_phase2.py

# Frontend suites, typecheck and production build
cd frontend
npm run test:frontend     # runs test:urlstate then test:modes
npm run typecheck
npm run build
```

Running from the repository root matters: the test modules import `backend.*`
directly and `from conftest import ...`, so no packaging step or install is
required.

---

## Test layout

| File | Phase 10 tests | Scope |
|---|---:|---|
| `tests/conftest.py` | — | Shared offline fixtures and process-singleton isolation |
| `tests/test_unit_phase10.py` | 334 | Processing, BM25, query, hybrid, RAG, crawler helpers, artifact metadata, settings |
| `tests/test_api_phase10.py` | 138 | Every HTTP endpoint: routing, validation, contracts, state matrix |
| `tests/test_integration_phase10.py` | 53 | Corpus → index, persistence matrices, failure combinations |
| `tests/test_security_phase10.py` | 136 | Injection, escaping, URL safety, no-fabrication, repo hygiene |
| `tests/test_regression_phase10.py` | 53 | Cross-phase seams, frontend wiring, docs, performance smoke |
| `frontend/tests/modes.test.mjs` | 6 | Frontend mode catalog parity (`node:test`) |

Pre-existing suites, retained as-is:

| File | Tests | Phase |
|---|---:|---|
| `tests/test_health.py` | 2 | 1 |
| `tests/test_search_phase2.py` | 18 | 2 |
| `tests/test_crawler_phase4.py` | 25 | 4 |
| `tests/test_persistence_phase5a.py` | 7 | 5A |
| `tests/test_index_persistence_phase5b.py` | 15 | 5B |
| `tests/test_semantic_search_phase6.py` | 30 | 6 |
| `tests/test_hybrid_phase7.py` | 7 | 7 |
| `tests/test_rag_phase8.py` | 14 | 8 |
| `tests/test_search_modes_phase9.py` | 118 | 9 |
| `frontend/tests/urlState.test.mjs` | 11 | 9 |

---

## Coverage matrix

Legend for the **Existing** column: `pre` = pre-existing per-phase suite,
`p10` = added by Phase 10, `—` = no pre-existing coverage.

### 1. Processing — tokenizer, loader, snippets

| Feature | Existing | Missing before Phase 10 | Phase 10 tests |
|---|---|---|---|
| `tokenize()` core behaviour | pre `test_search_phase2.py::TestTokenizerSnippet` | — | — |
| Unicode folding, case folding, accents | pre | — | `TestTokenizerEdges` |
| CJK / no-space scripts | p10 | **no** | `TestTokenizerEdges` |
| Emoji and symbol-only input | p10 | **no** | `TestTokenizerEdges` |
| Empty / whitespace / `None`-like input | p10 | **no** | `TestTokenizerEdges` |
| `keep_stopwords` toggle (query vs document side) | p10 | **partial** — only the default path | `TestTokenizerEdges` |
| `snippet_tokens()` | p10 | **no** (raised `NameError`) | `TestSnippetEdges` |
| `make_snippet()` selection, bounds, truncation | pre | **partial** | `TestSnippetEdges` |
| Snippet with no matching token | p10 | **no** | `TestSnippetEdges` |
| Corpus loader: file order, front matter | pre | — | — |
| Corpus loader: skip-list | p10 | **broken** (`index.md` was indexed) | `TestCorpusLoaderEdges` |
| Corpus loader: missing corpus dir, unreadable file, empty file, nested dirs, non-`.md` files | p10 | **no** | `TestCorpusLoaderEdges` |
| Corpus loader: `content_hash` stability | p10 | **no** | `TestCorpusLoaderEdges` |
| Pipeline: `build_pipeline`, `run_pipeline`, `persist_corpus` best-effort | pre | — | `TestPipelineEdges` |

### 2. BM25 and the search engine

| Feature | Existing | Missing before Phase 10 | Phase 10 tests |
|---|---|---|---|
| Okapi scoring, `k1` / `b` / `epsilon` | pre `test_search_phase2.py::TestSearchEngine` | — | — |
| `score()` alignment with the document list | p10 | **wrong document returned** when a doc had no tokens | `TestBm25IndexEdges` |
| `vocabulary_size()` | p10 | **counted documents, not terms** | `TestBm25IndexEdges` |
| Empty index / empty query / no match | p10 | **partial** | `TestBm25IndexEdges` |
| Duplicate documents, identical tokens, very long documents | p10 | **no** | `TestBm25IndexEdges` |
| Unicode-only tokens, single-document corpus | p10 | **no** | `TestBm25IndexEdges` |
| Engine: limit clamping, `max_limit`, rank renumbering | p10 | **partial** | `TestSearchEngineEdges` |
| Engine: `index_documents` re-index / swap semantics | p10 | **no** | `TestSearchEngineEdges` |
| Engine: snippet generation and `matched_terms` | pre | — | `TestSearchEngineEdges` |
| Determinism: same index + query ⇒ same response | p10 | **no** | `TestSearchEngineEdges`, `TestPersistenceSmoke` |

### 3. Query processing

| Feature | Existing | Missing before Phase 10 | Phase 10 tests |
|---|---|---|---|
| Normalisation, stop-word removal, weighting | pre | — | — |
| Empty query → validation error | p10 | **partial** | `TestQueryProcessing` |
| Whitespace-only, very long, unicode query | p10 | **no** | `TestQueryProcessing` |
| Punctuation-only query | p10 | **no** | `TestQueryProcessing` |
| Query echo normalisation (documented lowercasing) | p10 | **no** | `TestQueryProcessing`, `TestSearchEndpointContract` |

### 4. Semantic search (offline)

The semantic stack is tested with **fakes and stubs only** — no model download,
no `faiss` import at module scope. `backend.main` must stay importable without
the ML stack, so the suite never imports `sentence_transformers` directly.

| Feature | Existing | Missing before Phase 10 | Phase 10 tests |
|---|---|---|---|
| `EmbeddingGenerator` laziness, dimension, L2 norm | pre `test_semantic_search_phase6.py` | — | — |
| FAISS store round-trip, atomic write | pre | — | `TestFaissMetadata` |
| FAISS metadata: version, model, dimension, corpus hash | pre | — | `TestFaissMetadata` |
| FAISS metadata: **non-mapping** `documents` entries | p10 | **raised** | `TestFaissMetadata` |
| `load_faiss_index` document loop on malformed entries | p10 | **raised** | `TestFaissMetadata` |
| `SemanticIndexManager` rebuild / refresh / status | pre | — | `TestIndexMetadata`, `TestFaissMetadata` |
| `mode=semantic` unavailable path (structured, not 500) | p10 | **HTTP 500** | `TestSearchIndexStateMatrix`, `TestFailureCombinations` |
| Embedding failure mid-search | pre (Phase 6) | — | `TestFailureCombinations` |
| Missing semantic artifact → degrade, never crash | p10 | **partial** | `TestFaissPersistenceMatrix` |

### 5. Hybrid ranking

| Feature | Existing | Missing before Phase 10 | Phase 10 tests |
|---|---|---|---|
| Min-max normalisation incl. all-equal / NaN / inf | pre | — | `TestScoreNormalisation` |
| Weight normalisation and validation | pre | — | `TestWeightValidation`, `TestHybridWeightContract` |
| Rejection: negative, both zero, zero total | p10 | **partial** | `TestWeightValidation`, `TestHybridWeightContract` |
| Merge + dedupe by `document_id` | pre | — | `TestHybridMerge`, `TestHybridWeightContract` |
| Deterministic tie-breaking | p10 | **no** | `TestHybridMerge` |
| Snippet highlighter: escaping before wrapping | pre | — | `TestHighlighting` |
| Highlighter: no matches, regex-special terms, case | p10 | **no** | `TestHighlighting` |
| API echoes normalised weights | p10 | **no** | `TestHybridWeightContract` |
| API structured error for zero weight pair | p10 | **no** | `TestHybridWeightContract` |
| API 422 for negative weight (`ge=0.0`) | p10 | **no** | `TestHybridWeightContract` |
| Hybrid unavailable / degraded status | pre | — | `TestSearchIndexStateMatrix` |

### 6. RAG answer generation

| Feature | Existing | Missing before Phase 10 | Phase 10 tests |
|---|---|---|---|
| Passage selection, char caps, dedupe | pre `test_rag_phase8.py` | — | `TestPassageSelection` |
| Grounded prompt builder | pre | — | `TestGroundedPrompt` |
| Answer models, validation | pre | — | `TestAnswerModels` |
| `FakeLLMProvider` determinism | pre | — | `TestFakeProvider` |
| `OllamaLLMProvider` against a stub HTTP client | pre | — | `TestOllamaProvider` |
| Provider factory resolution + failure | pre | — | `TestProviderFactory` |
| RAG orchestrator: disabled, insufficient context, provider failure | pre | — | `TestRagOrchestrator` |
| Citation filtering / numbering | pre | — | `TestCitationFiltering` |
| Mode layer hands its hits to RAG (no re-retrieval) | p10 | **no** | `TestRagComposition` |
| `/api/answer` and `mode=ai` share one contract | p10 | **no** | `TestRagComposition` |

### 7. Specialized search modes

| Feature | Existing | Missing before Phase 10 | Phase 10 tests |
|---|---|---|---|
| Mode enum, validation, 422 on unknown | pre `test_search_modes_phase9.py` | — | — |
| `ModeSpec` resolution, limits, weights | pre | — | `TestModeCatalogParity` |
| Per-mode behaviour (web / ai / research / code) | pre | — | — |
| Status precedence (`ok` / `degraded` / `unavailable`) | pre | — | `TestSearchIndexStateMatrix` |
| Backward compatibility of legacy modes | pre | — | `TestEndpointInventory`, `TestModeCatalogParity` |
| Shared response envelope across every mode | p10 | **no** | `TestModeCatalogParity` |
| Backend catalog order == API catalog order | p10 | **no** | `TestModeCatalogParity` |
| Backend enum == frontend `SEARCH_MODES` literal | p10 | **no** | `TestModeCatalogParity` |
| Backend legacy list == frontend `LegacySearchMode` | p10 | **no** | `TestModeCatalogParity` |
| Frontend sends only modes the backend serves | p10 | **no** | `TestModeCatalogParity` |
| Catalog stability across calls | p10 | **no** | `TestModeCatalogParity` |

### 8. HTTP API surface

The complete published surface is asserted as an exact set — adding or removing
an endpoint without updating `EXPECTED_ROUTES` fails the suite.

| Route | Methods | Existing | Missing before Phase 10 | Phase 10 tests |
|---|---|---|---|---|
| `GET /` | GET | pre | — | `TestEndpointInventory`, `TestRouting` |
| `GET /health` | GET | pre | — | `TestRouting` |
| `GET /api/search` | GET | pre | — | `TestSearchEndpointContract`, `TestRouting` |
| `GET /api/search/modes` | GET | pre | — | `TestModeCatalogEndpoint`, `TestModeCatalogParity` |
| `POST /api/answer` | POST | pre | — | `TestAnswerEndpointContract` |
| `GET /api/crawl` | GET | pre | — | `TestCrawlEndpointOffline` |
| `POST /api/crawl` | POST | pre | — | `TestCrawlEndpointValidation`, `TestCrawlEndpointOffline` |
| `GET /api/crawl/{job_id}` | GET | pre | — | `TestCrawlEndpointOffline` |
| `GET /api/index/status` | GET | pre | — | `TestIndexStatusEndpoint` |
| `POST /api/index/rebuild` | POST | pre | — | `TestIndexLifecycleEndpoints` |
| `POST /api/index/refresh` | POST | pre | — | `TestIndexLifecycleEndpoints` |
| `POST /api/index/semantic/rebuild` | POST | pre | — | `TestIndexLifecycleEndpoints` |
| `POST /api/index/semantic/refresh` | POST | pre | — | `TestIndexLifecycleEndpoints` |

Cross-cutting API guarantees:

| Guarantee | Existing | Missing before Phase 10 | Phase 10 tests |
|---|---|---|---|
| Route inventory is exactly the documented set | p10 | **no** | `TestEndpointInventory` |
| Every route answers without a 5xx | p10 | **no** | `TestEndpointInventory` |
| Every router is mounted on the app (no orphan) | p10 | **no** | `TestEndpointInventory` |
| OpenAPI operation ids are present and unique | p10 | **no** | `TestEndpointInventory` |
| Unsupported method → 405, unknown path → 404 | p10 | **no** | `TestRouting` |
| JSON content type on every response | p10 | **no** | `TestEndpointInventory` |
| Missing/blank/invalid required params → 4xx | pre | — | `TestSearchEndpointValidation`, `TestCrawlEndpointValidation`, `TestAnswerEndpointValidation` |
| Unknown query params are ignored, not fatal | p10 | **no** | `TestSearchEndpointValidation` |

### 9. Search mode × index-state × query matrix

Every combination of `mode` × index state is asserted. Three index states are
used: `offline_index` (sample documents present), `empty_index` (installed but
zero documents), and no index at all.

| Mode | Documents present | Index empty | Semantic unavailable | Query: normal | Query: no match | Query: invalid |
|---|---|---|---|---|---|---|
| `lexical` (default) | p10 | p10 | p10 | p10 | p10 | p10 (422) |
| `bm25` (alias) | p10 | p10 | p10 | p10 | p10 | p10 (422) |
| `semantic` | p10 | p10 | p10 (structured) | p10 | p10 | p10 (422) |
| `hybrid` | p10 | p10 | p10 (degraded) | p10 | p10 | p10 (422) |
| `web` | p10 | p10 | p10 | p10 | p10 | p10 (422) |
| `ai` | p10 | p10 | p10 | p10 | p10 | p10 (422) |
| `research` | p10 | p10 | p10 | p10 | p10 | p10 (422) |
| `code` | p10 | p10 | p10 | p10 | p10 | p10 (422) |

Pinned invariants:

* An installed-but-empty index is reported `unavailable`, never as an empty
  result set.
* A non-matching query returns zero hits rather than zero-scored filler.
* `answer` is `null` whenever RAG falls back — nothing is fabricated.
* Retrieval health wins over RAG outcome in `status`.

Covered by `TestSearchIndexStateMatrix` (`tests/test_api_phase10.py`) and
`TestSearchIndexStateMatrix` assertions reused by
`TestFailureCombinations` (`tests/test_integration_phase10.py`).

### 10. Controlled crawler

All crawler tests run against **in-process fixtures** — no outbound HTTP. The
pre-existing Phase 4 suite drives an `http.server` fixture that serves a
deterministic site.

| Feature | Existing | Missing before Phase 10 | Phase 10 tests |
|---|---|---|---|
| URL normalisation (case, default ports, tracking params, fragments) | pre | — | `TestUrlNormalisation` |
| `normalize_url` dot-segment behaviour | p10 | **no** | `TestUrlNormalisation` (pinned) |
| Dangerous URL rejection (`javascript:`, `data:`, `ftp:`, credentials, `mailto:`, `tel:`) | pre | — | `TestUrlSafety` |
| Private/loopback host detection | pre | **literal only** (pinned) | `TestUrlSafety` |
| Binary / PDF extension rejection | pre | — | `TestUrlSafety` |
| Seed URLs validated like discovered links | p10 | **not enforced** | `TestUrlSafety`, `TestCrawlUrlSafety` |
| Blank-seed list → 422, not 500 | p10 | **HTTP 500** | `TestCrawlEndpointValidation`, `TestCrawlUrlSafety` |
| `robots.txt` parsing, `Crawl-delay`, 401/403 block-all | pre | — | `TestRobotsPolicy` |
| Robots cache and per-host isolation | pre | — | `TestRobotsPolicy` |
| HTML extraction, title fallback, chunking, hashes | pre | — | `TestExtraction` |
| Link extraction (relative → absolute, fragment/in-page) | pre | — | `TestLinkExtraction` |
| Fetcher: timeouts, status codes, content type | pre | — | `TestFetcher` |
| Crawl config sanitisation / domain matching | pre | — | `TestCrawlModels` |
| `CrawlStore` dedupe (URL and content hash), thread safety | pre | — | `TestCrawlStore` |
| `CrawlManager` job lifecycle | pre | — | `TestCrawlManager` |
| Crawl job API contract | pre | — | `TestCrawlEndpointOffline` |
| Crawled page survives the hop into the BM25 index | p10 | **no** | `TestCrawlerToIndexSeam` |
| `include_crawled` false drops only `http(s)`-sourced rows | p10 | **no** | `TestCrawlerToIndexSeam` |

### 11. PostgreSQL repository

| Feature | Existing | Missing before Phase 10 | Phase 10 tests |
|---|---|---|---|
| `is_available()` when the engine cannot connect | pre `test_persistence_phase5a.py` | — | `TestRepositoryDegradation` |
| Every repository method degrades instead of raising | pre | **partial** | `TestRepositoryDegradation` |
| Repository factory with an invalid URL | pre | — | `TestRepositoryFactory` |
| Factory with a null URL (degraded path) | p10 | **no** | `TestRepositoryFactory` |
| In-memory double behaves like the real surface | p10 | **no** | `TestFakeRepositoryDouble` |
| No SQL/credentials leak into responses or logs | p10 | **no** | `TestRepositoryHygiene` |
| Live PostgreSQL tier (`SEEK_TEST_DATABASE_URL`) | pre | — | skipped when unavailable |

### 12. Persistence and restart

| Scenario | Existing | Missing before Phase 10 | Phase 10 tests |
|---|---|---|---|
| Rebuild → persist → **restart** → identical results | pre `test_index_persistence_phase5b.py` | — | `TestBm25PersistenceMatrix` |
| Valid artifact loads on startup | pre | — | `TestBm25PersistenceMatrix` |
| **Missing** artifact → graceful rebuild / empty | pre | — | `TestBm25PersistenceMatrix` |
| **Corrupt** artifact → rebuild, never raise | pre | — | `TestBm25PersistenceMatrix` |
| **Stale** artifact (content hashes differ) → `stale: true`, refresh path | pre | — | `TestBm25PersistenceMatrix` |
| **Metadata / artifact version mismatch** → clean error | p10 | **not detected** | `TestIndexMetadata`, `TestBm25PersistenceMatrix` |
| Non-mapping `documents` entries in metadata | p10 | **raised** | `TestIndexMetadata` |
| **Atomic-write failure** (write raises) → previous artifact intact | pre | — | `TestIndexArtifactLifecycle` |
| **Interrupted write** (partial `.tmp`) → previous artifact intact | pre | — | `TestIndexArtifactLifecycle` |
| Corpus hash changes on content change | pre | — | `TestBm25PersistenceMatrix` |
| Document serialisation round-trips through both stores | p10 | **no** | `TestPersistenceConstantsAgree` |
| FAISS persistence matrix (same 7 scenarios) | p10 | **partial** | `TestFaissPersistenceMatrix` |
| Configured artifact names == store constants | p10 | **no** | `TestPersistenceConstantsAgree` |
| Both stores declare format version 1 | p10 | **no** | `TestPersistenceConstantsAgree` |
| Status endpoint reports the persisted version | p10 | **no** | `TestPersistenceConstantsAgree` |

### 13. Frontend

Frontend suites follow the existing `npm run test:urlstate` pattern
(`node:test` + `--experimental-strip-types`, no test framework dependency) and
are driven from pytest so one command covers the whole stack.

| Area | Existing | Missing before Phase 10 | Phase 10 tests |
|---|---|---|---|
| URL state parse/build/back-forward | pre `frontend/tests/urlState.test.mjs` | — | `TestFrontendSuites` |
| Mode catalog parity with the backend enum | p10 `frontend/tests/modes.test.mjs` | **no** | `TestFrontendSuites`, `TestModeCatalogParity` |
| `isSearchMode` / `modeLabel` / `modeHint` fallbacks | p10 | **no** | `frontend/tests/modes.test.mjs` |
| `App.tsx` owns the URL-state contract | p10 | **no** | `TestFrontendWiring` |
| Mode selector is keyboard operable (radiogroup, arrows, Home/End) | p10 | **no** | `TestFrontendWiring` |
| Degraded/unavailable states are rendered, not hidden | p10 | **no** | `TestFrontendWiring` |
| API client tolerates a failed request | p10 | **no** | `TestFrontendWiring` |
| `tsc --noEmit` typechecks | p10 | **no** | `TestFrontendSuites` |
| Production `vite build` succeeds | p10 | **no** | `TestFrontendSuites` |
| All npm scripts declared | p10 | **no** | `TestFrontendSuites` |

### 14. Security and input validation

| Area | Existing | Missing before Phase 10 | Phase 10 tests |
|---|---|---|---|
| SQL-ish input in `q` is inert, never executed | pre | — | `TestSearchInputIsNeverInterpreted` |
| HTML/JS in a query is escaped, not rendered | pre | — | `TestSearchInputIsNeverInterpreted` |
| `<mark>` wrapping happens **after** escaping | pre | — | `TestHighlightEscapesBeforeWrapping` |
| Path traversal in `document_id` / source paths | p10 | **no** | `TestCrawlUrlSafety` |
| Overlong query, huge `limit`, absurd `max_pages` / `max_depth` | p10 | **no** | `TestSearchInputIsNeverInterpreted`, `TestCrawlEndpointValidation` |
| Unicode / RTL / null-byte / control characters | p10 | **no** | `TestSearchInputIsNeverInterpreted` |
| Malformed JSON body → 4xx, never 500 | p10 | **no** | `TestAnswerEndpointValidation`, `TestCrawlEndpointValidation` |
| Unexpected content type → 4xx | p10 | **no** | `TestAnswerEndpointValidation` |
| SSRF-ish seed and link targets rejected | pre | — | `TestCrawlUrlSafety` |
| `answer` is never fabricated when RAG is unavailable | pre | — | `TestNoFabricatedAnswers` |
| Sources/citations never reference un-retrieved documents | pre | — | `TestNoFabricatedAnswers` |
| No credential or connection string in an error body | p10 | **no** | `TestRepositoryHygiene` |

### 15. Failure and resilience combinations

| Combination | Existing | Missing before Phase 10 | Phase 10 tests |
|---|---|---|---|
| PostgreSQL down + index present | pre | — | `TestFailureCombinations` |
| PostgreSQL down + index missing | pre | — | `TestFailureCombinations` |
| PostgreSQL down + index corrupt | p10 | **no** | `TestFailureCombinations` |
| PostgreSQL down + semantic stack missing | p10 | **HTTP 500** | `TestFailureCombinations` |
| PostgreSQL down + semantic manager raising on status | pre | — | `TestFailureCombinations` |
| Embedding failure during semantic search | pre | — | `TestFailureCombinations` |
| LLM provider failure / timeout during RAG | pre | — | `TestFailureCombinations` |
| Repository method raising mid-lifecycle | p10 | **no** | `TestFailureCombinations` |
| Atomic write raising mid-rebuild | pre | — | `TestIndexArtifactLifecycle` |
| Build raising after a successful previous build | pre | — | `TestBm25PersistenceMatrix` |
| Every failing path returns a structured status, never a 5xx | p10 | **500s present** | `TestFailureCombinations`, `TestEndpointInventory` |

### 16. Performance smoke

Deliberately order-of-magnitude only. No assertion in this tier is tight enough
to be timing-fragile: bounds are loose multiples of the measured cost, so the
tier catches a **complexity** regression, not a slow machine.

| Scenario | Existing | Missing before Phase 10 | Phase 10 tests |
|---|---|---|---|
| 500-document index build | p10 | **no** | `TestPerformanceSmoke` (regression), `TestPerformanceSmoke` (unit) |
| Query latency on a 500-doc index | p10 | **no** | `TestPerformanceSmoke` |
| `limit` growth must not blow up cost | p10 | **no** | `TestPerformanceSmoke` |
| Artifact round-trip scaling | p10 | **no** | `TestPerformanceSmoke` (unit) |
| Snippet generation cost | p10 | **no** | `TestPerformanceSmoke` (unit) |

### 17. Cross-phase regression

The seams a per-phase suite structurally cannot see, because each one only
inspects its own side of the contract.

| Seam | Existing | Missing before Phase 10 | Phase 10 tests |
|---|---|---|---|
| Phase 0–2: committed corpus loads, tokenises, indexes | p10 | **no** | `TestPhase2ChainIsIntact` |
| Phase 0–2: probe imports 18/18 modules and builds the app | p10 | **no** | `TestPhase2ChainIsIntact` |
| Phase 0–2: probe actually answers a query (`search_ok=true`) | p10 | **no** | `TestPhase2ChainIsIntact` |
| Phase 0–2: skip-list files stay out of the index | p10 | **no** | `TestPhase2ChainIsIntact` |
| Phase 4 → 5/6: crawled page reaches the BM25 index | p10 | **no** | `TestCrawlerToIndexSeam` |
| Phase 5B/6: artifact constants shared by engine, stores, status | p10 | **no** | `TestPersistenceConstantsAgree` |
| Phase 7: weight contract holds through the API | p10 | **no** | `TestHybridWeightContract` |
| Phase 8 → 9: RAG is orchestration, not a second retrieval stack | p10 | **no** | `TestRagComposition` |
| Phase 9: mode envelope carries the RAG detail block | p10 | **no** | `TestRagComposition` |
| Phase 9: catalog parity backend ↔ API ↔ frontend | p10 | **no** | `TestModeCatalogParity` |
| Phase 0–9: route inventory stability | p10 | **no** | `TestEndpointInventory` |

### 18. Documentation wiring

Documentation that can silently rot is itself tested.

| Check | Existing | Missing before Phase 10 | Phase 10 tests |
|---|---|---|---|
| `README.md` documents every published route | p10 | **no** | `TestDocumentationIsPresent` |
| This document exists and names every coverage area | p10 | **no** | `TestDocumentationIsPresent` |
| `docs/ROADMAP_TODO.md` marks Phase 10 COMPLETED | p10 | **no** | `TestDocumentationIsPresent` |
| This document claims **no** coverage percentage | p10 | **no** | `TestDocumentationIsPresent` |

---

## Fixture catalogue

All shared fixtures live in `tests/conftest.py`; no test module builds its own
infrastructure.

| Fixture | Scope | What it provides |
|---|---|---|
| `REPO_ROOT`, `FRONTEND_DIR` | module | Repository paths, so tests never hardcode `..` |
| `_isolate_process_singletons` | function, autouse | Resets the index / semantic / crawl singletons between tests |
| `_reset_crawl_manager` | function, autouse | Clears crawl jobs so job-list assertions are deterministic |
| `make_document()` | helper | Builds a `ProcessedDocument` with sane defaults |
| `doc` | function | One sample document |
| `sample_documents` | function | Four documents, three of them `https://`-sourced |
| `FakeRepository` | class | In-memory `DocumentRepository` with `available` / `fail_with` switches |
| `degraded_repository` | function | The canonical "PostgreSQL unreachable" repository |
| `fake_repository` | function | An available in-memory repository, ready for rows |
| `offline_index` | function | Live `IndexManager` with the sample corpus, isolated dir, degraded repo |
| `empty_index` | function | Same, but zero documents — the "index not built yet" state |
| `offline_semantic` | function | The *real* semantic manager with a degraded repo and isolated dir |
| `StubSemanticManager` | class | Deterministic semantic double with hits |
| `UnavailableSemanticManager` | class | Semantic double that always reports unavailable |
| `semantic_present` | function | Installs `StubSemanticManager` |
| `semantic_missing` | function | Installs `UnavailableSemanticManager` |
| `client` | function | `TestClient(app)` **without** a `with` block, so the lifespan does not run |

`client` deliberately does not enter the context manager: running the FastAPI
lifespan would call `load_on_startup()`, probe PostgreSQL and write into the
repository's `indexes/` tree. Tests that need a specific index state pin it with
`offline_index` / `empty_index` instead.

---

## Offline and skip conventions

* **No model downloads.** The semantic stack is exercised with fakes. Tests that
  would need a real model are not part of the default gate.
* **No PostgreSQL required.** Tests needing a live database read
  `SEEK_TEST_DATABASE_URL` (default
  `postgresql+psycopg2://seek:seek@localhost:5432/seek`) and `skip` when the
  database is unreachable. The suite is fully green without one.
* **No outbound HTTP.** The crawler suite uses an in-process `http.server`
  fixture; everything else uses repository doubles.
* **No network for node.** `TestFrontendSuites` skips cleanly when `node` or
  `npm` is absent, so a Python-only environment still passes.
* **No `pytest-asyncio`.** Async paths are driven with `asyncio.run(...)`.

---

## Defects found and fixed by this suite

Phase 10 added no product features. It did surface real defects, which were
fixed because the tests had to be able to assert correct behaviour. Each fix is
small, local, and directly justified by a failing test.

| Component | Defect | Fix |
|---|---|---|
| `backend/processing/tokenizer.py` | `snippet_tokens()` raised `NameError` on the undefined name `keep_stopwords`. | Iterate with `keep_stopwords=True` and clamp the word budget with `max(0, int(words))`. |
| `backend/processing/loader.py` | The skip-list was matched against `path.stem`, so `index.md` was indexed as a searchable document. | Match against `path.name`. |
| `backend/search/bm25.py` | `score()` returned a numpy array and mis-aligned `score[i]` to `documents[i]` whenever a document had no tokens — returning the **wrong document**. | Build a `list[float]` through a new `_corpus_slots` mapping. |
| `backend/search/bm25.py` | `vocabulary_size()` counted documents, because `rank_bm25`'s `doc_freqs` is a per-document list. | Return `len(self._bm25.idf)`. |
| `backend/search/index_store.py` | `read_metadata()` raised on non-mapping `documents` entries instead of reporting unreadable. | Broadened the except tuple. |
| `backend/search/index_store.py` | `load_index()` validated only the **artifact's** version, not the metadata's. | Reject `metadata.format_version != INDEX_FORMAT_VERSION` with a clear message. |
| `backend/search/faiss_store.py` | Same two gaps as the BM25 store. | Broadened except tuples; metadata version now validated. |
| `backend/api/search.py` | A raising `get_semantic_index_manager()` made `mode=semantic` and `mode=hybrid` return **HTTP 500** instead of the documented structured unavailability. | Added `_semantic_status()`, used by `_hybrid_search`, `_semantic_search` and `_lexical_search`. |
| `backend/api/crawl.py` | A blank-seed list reached `CrawlManager.start_job` and raised `ValueError` → **HTTP 500**. | Sanitize the config and return HTTP 422 when no non-blank seed survives. |
| `backend/crawler/scheduler.py` | Seed URLs were validated with `is_dangerous_url` only, so a private/loopback or binary-extension seed was accepted even though the same URL would be rejected as a discovered link. | Apply `is_crawlable_url(..., allow_private_hosts=...)` to seeds too; drop the now-unused import. |
| `scripts/probe_phase2.py` | The phase acceptance gate only proved the modules *import*, not that the index *searches*. | The probe now also builds the pipeline and runs one query, printing `search_ok` and `documents`. |

---

## Why there is no coverage number

This document deliberately reports **no coverage percentage**. A percentage would
have to come from an actual `coverage run` over the measured statement set, and
that measurement has not been performed here. Publishing an unmeasured number
would misrepresent untested behaviour as tested — the exact failure mode this
suite exists to prevent.

`TestDocumentationIsPresent::test_the_testing_document_does_not_fabricate_a_coverage_percentage`
enforces this: the document is checked for a `NN% coverage` style claim, and the
test fails if one appears. If a coverage run is added later, the number belongs
in the CI report that produced it, and this guard should be updated deliberately
rather than silently.

What this document does report instead: **which behaviour is covered, by which
test, and what is deliberately not covered**. That is the part a reviewer can
check.

---

## Known gaps and deliberate non-goals

| Gap | Why it is not covered | How to cover it |
|---|---|---|
| Live PostgreSQL end-to-end | Requires a running server; the default gate must be green without one | Set `SEEK_TEST_DATABASE_URL` — the Phase 5A/5B/6 suites then run their live tiers |
| Live embedding model | Would download ~90 MB on first run; the default gate must be offline | `tests/test_semantic_search_phase6.py::TestLiveEmbeddingModel` runs it when the stack is installed |
| Load / soak / concurrency testing | Out of scope for Phase 10; the performance tier is a smoke check | A dedicated benchmark harness (Phase 13) |
| Browser end-to-end UI testing | Needs a headless browser and a served frontend; Phase 3/9 verified manually | Playwright against a running stack |
| Statement/branch coverage measurement | Not measured, therefore not claimed — see above | `coverage run -m pytest` + `coverage report` in CI |
| `backend/main.py` lifespan behaviour under a real boot | `TestClient` deliberately skips the lifespan so `indexes/` stays clean | Exercised manually via `python backend/main.py`; the startup branches are covered at the manager level |

Each row is a decision, not an oversight.