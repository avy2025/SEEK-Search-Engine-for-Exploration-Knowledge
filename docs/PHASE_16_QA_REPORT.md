# Phase 16 — QA, Security and Performance Report

**Review date:** 2026-11-14
**Repository baseline:** `28510a8` (`main`)
**Disposition:** Audit fixes and local verification completed. This report is not a production-readiness certification.

## Scope reviewed

Reviewed the FastAPI app and startup path; React/TypeScript search UI; BM25,
FAISS and hybrid retrieval; Tavily and Gemini service boundaries and free-tier
controls; browser Reader Mode and crawler URL/fetch paths; database models,
history API and Alembic migrations; CORS/session handling; environment
configuration; Dockerfiles and Compose; Git history; and existing backend and
frontend tests.

## Verification

| Check | Result |
|---|---|
| Complete backend and integrated pytest suite | **1021 passed, 29 skipped, 18 warnings** |
| Frontend tests | **31 passed** |
| TypeScript check | Passed (`npm run typecheck`) |
| Frontend production build | Passed with Vite 8.3.8 |
| Full npm dependency audit | **0 known vulnerabilities** |
| Python dependency audit | **0 known vulnerabilities** (`pip-audit`) |
| Python dependency consistency | Passed (`pip check`) |
| Compose YAML and credential/port policy | Parsed and checked successfully |
| Local Uvicorn smoke test | Passed against temporary SQLite: health, sample-index rebuild and search, session bootstrap, history listing |
| Docker image / Compose runtime | **Not run:** Docker and Docker Compose CLIs are unavailable |
| PostgreSQL integration / restart persistence | **Not run:** no PostgreSQL client or test server is available |

The skipped tests include PostgreSQL-dependent integration checks. The warnings
are existing test/dependency deprecations, including pytest-asyncio fixture-scope,
Starlette/httpx, FastAPI status constants, and Alembic path-separator notices.
No tests were removed or weakened to obtain the passing count.

The local HTTP smoke test launched a real Uvicorn process with an isolated
temporary SQLite database and index directories. Tavily and Gemini keys were
explicitly empty; no paid or external provider calls were made. This verifies
local API behavior, not PostgreSQL or container deployment behavior.

## Findings and remediation

Line references below identify the affected code in the pre-audit baseline
`28510a8`; each item is fixed in the reviewed worktree.

| # | Severity | File | Lines | Vulnerability | Confidence |
|---|----------|------|-------|---------------|------------|
| 1 | 🟠 HIGH | `backend/crawler/fetcher.py` | 72-79 | Crawler requests followed redirects without per-hop public-address validation or DNS pinning, creating an SSRF path. Fixed with public-IP validation and pinned connections for each request and redirect. | 9/10 |
| 2 | 🟠 HIGH | `docker-compose.yml` | 10-14 | Compose supplied fallback database credentials and published PostgreSQL on a host port. Credentials are now required from environment configuration and PostgreSQL has no host port mapping. | 10/10 |
| 3 | 🟠 HIGH | `frontend/package.json` | 27, 32 | The Vite 5 development toolchain matched npm advisories, including a high-severity Vite issue and vulnerable esbuild versions. Upgraded to Vite 8.3.8 and `@vitejs/plugin-react` 6.3.0; the full npm audit is clean. | 9/10 |
| 4 | 🟠 HIGH | `requirements.txt` | 15 | The unbounded transitive SoupSieve dependency resolved to 3.0.4, affected by CVE-2026-126190 (polynomial-time denial of service on attacker-influenced nested HTML). Added `soupsieve>=4.0.0`; verified installed version 4.1.1 and a clean Python audit. | 9/10 |
| 5 | 🟡 MEDIUM | `backend/api/history.py` | 79-85, 95-136 | History operations were not associated with a browser owner, allowing visitors of a shared instance to read or alter one another's queries. Added opaque anonymous browser sessions, server-side ownership checks and legacy-row quarantine. | 9/10 |

### Security controls added or verified

- Crawler and Reader Mode accept only safe public HTTP(S) destinations, reject
  private/loopback/link-local/reserved addresses and credentials, validate
  redirects, pin requests to validated public addresses, disable environment
  proxies, and bound request time, content size, content types and redirects.
  The crawler no longer accepts the private-host bypass flag.
- Reader Mode checks robots policy, extracts structured text rather than
  returning executable source HTML, and sanitizes output. Tests mock DNS and
  HTTP; no external site is fetched by the automated suite.
- History uses a random HTTP-only browser cookie; only its hash and server-side
  expiry are stored. CRUD queries are scoped to that server-resolved session,
  writes require a trusted Origin, and history/session responses are not cached.
  Pre-existing unowned history is assigned to an expired quarantine session.
  Downgrading the ownership migration deletes history before reverting to an
  unscoped schema rather than exposing it.
- Compose requires explicit PostgreSQL credentials and keeps its service on the
  private Compose network. Provider credentials remain backend-only; a source
  scan found no credential-shaped Tavily or Gemini literals.
- The database engine now selects SQLite-compatible connection options for
  local SQLite URLs instead of passing PostgreSQL-only `connect_timeout`.
- A cold-import cycle between Reader Mode and the crawler package was fixed by
  lazily loading crawler service exports; a clean-process regression test covers
  the import order.

## Performance measurements

This is a deterministic component-level microbenchmark, not a production load
test. It ran on macOS 26.6 arm64, Python 3.11.18, 10 logical CPUs and FAISS
1.15.1. Each cell reports **p50 / p95 latency in ms / requests per second**;
each concurrency level ran 100 calls. All workloads reported zero errors.

- BM25 used a synthetic 1,000-document corpus.
- FAISS used 1,000 64-dimensional vectors and the real FAISS index, with a
  deterministic embedding stub (model inference is not included).
- Hybrid search ran BM25, FAISS and the production merge/rerank function.
- Live Search used the real service/ledger path with a mocked Tavily provider.
- AI Answers used the real orchestration/ledger path with mocked research and
  Gemini providers. Neither workload consumed API credits.
- Reader Mode used `read_public_page` with mocked public DNS and HTTP responses,
  including a mocked robots response, then exercised the extraction path.
- History listing queried a temporary SQLite database seeded with 2,000 rows.
  SQLite timings are not PostgreSQL timings.

| Workload | 1 concurrent | 5 concurrent | 10 concurrent | 25 concurrent |
|---|---:|---:|---:|---:|
| BM25 | 0.675 / 0.760 / 1422.94 | 3.845 / 6.955 / 1230.97 | 7.416 / 14.840 / 1208.63 | 17.828 / 33.495 / 1187.31 |
| FAISS + deterministic embedding stub | 0.343 / 0.395 / 2640.21 | 1.719 / 5.075 / 2864.45 | 3.395 / 6.778 / 2864.64 | 5.796 / 21.663 / 2803.40 |
| Hybrid BM25 + FAISS | 2.466 / 2.647 / 400.60 | 12.946 / 24.091 / 379.07 | 26.349 / 43.458 / 356.29 | 58.946 / 99.172 / 373.09 |
| Live Search, mocked Tavily | 0.760 / 1.004 / 1232.46 | 0.822 / 20.604 / 1090.61 | 1.993 / 42.027 / 726.82 | 4.191 / 145.852 / 497.48 |
| AI Answers, mocked Tavily/Gemini | 0.813 / 1.228 / 1133.54 | 1.960 / 23.619 / 1009.74 | 2.024 / 61.327 / 1075.82 | 4.490 / 156.056 / 477.70 |
| Reader Mode, mocked HTTP + extraction | 1.686 / 2.157 / 440.22 | 8.405 / 12.101 / 585.35 | 17.249 / 35.610 / 533.03 | 42.884 / 62.456 / 581.90 |
| SQLite history listing, 2,000 rows | 0.227 / 0.312 / 3767.03 | 1.809 / 3.052 / 2656.32 | 9.252 / 11.252 / 1077.00 | 15.669 / 98.784 / 972.29 |

The timed calls used 3.835 seconds of process CPU over 3.558 seconds wall time;
the Python process reached 147.9 MiB peak RSS, including setup. These are
aggregate harness values (including Python, NumPy, FAISS and SQLite), not
per-request, container or production resource measurements. The single-run
figures are environment-sensitive. Mocked provider
and webpage latencies exclude real network delays, and the synthetic corpus
does not represent a production index. The results do not justify speculative
optimization; hybrid reranking and concurrent local SQLite queries show the
largest local costs.

## Deployment and persistence

Compose YAML and the credential/port policy were checked with a YAML parser.
The actual Compose config command, Docker builds, container health checks, named
volume recreation, and PostgreSQL persistence could not be exercised because
Docker, `docker-compose`, `psql` and `pg_isready` are absent in this environment.
The SQLite runtime smoke test does not substitute for PostgreSQL verification.

To run the documented stack on a machine with Docker:

```bash
cp .env.example .env
# Set POSTGRES_USER, POSTGRES_DB and a unique POSTGRES_PASSWORD in .env.
docker compose up --build -d
docker compose ps
```

For local development without PostgreSQL, SEEK can use a SQLite URL for its
database-backed history path and fall back to the committed sample corpus for
local search:

```bash
export APP_ENV=development
export DATABASE_URL=sqlite:////tmp/seek-local.sqlite3
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000

# In a second terminal:
cd frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 3000
```

Use PostgreSQL to verify canonical document persistence and the skipped
PostgreSQL integration cases. The frontend Vite 8 toolchain requires Node
20.19+ or 22.12+.

## Remaining limitations

- PostgreSQL behavior, persistent-volume restart behavior, Docker builds and
  deployed health checks remain unverified in this environment.
- Real Tavily, Gemini, Reader Mode network latency, API quotas and the actual
  Sentence Transformers inference time were intentionally not exercised.
- No production-scale corpus or sustained HTTP server load test was run.
- The application has no accounts; history is isolated per anonymous browser
  session, not synchronized across devices or users.
- Passing automated checks does not establish production readiness. A deployment
  review, PostgreSQL-backed verification, real-container checks and production
  traffic measurements remain necessary.
