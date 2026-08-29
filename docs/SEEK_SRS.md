# SEEK – Search Engine
## Software Requirements Specification
**Version 2.0 | Elaborated Technical Specification | August 2026**

---

### Project Metadata
| Item | Details |
|---|---|
| **Project** | SEEK – Search Engine |
| **Type** | AI/ML + Information Retrieval + Full Stack + DevOps |
| **Goal** | Build a genuine, modular search engine with controlled crawling, indexing, retrieval, ranking and optional AI answers. |
| **Development Model** | Phased, Docker-first, zero-cost-first |
| **Core Dependency Rule** | No paid search or LLM API is required for core search. |
| **Target Users** | Students, researchers, developers and general users |

---

### Table of Contents
1. Introduction
2. Problem Statement
3. Vision and Goals
4. Scope and Boundaries
5. Product Overview
6. Actors and Use Cases
7. End-to-End Vision
8. System Architecture
9. Search Sequence Diagram
10. Crawling and Indexing Flow
11. Functional Requirements
12. Non-Functional Requirements
13. Technology Stack
14. Module Design
15. Data Architecture
16. Search and Ranking Design
17. AI/ML and RAG Design
18. API Requirements
19. UI/UX Requirements
20. Docker and Deployment
21. Security and Responsible Crawling
22. Testing Strategy
23. Development Roadmap
24. Acceptance Criteria
25. Risks and Constraints
26. Future Enhancements
27. Conclusion
- Appendix A – Repository Structure
- Appendix B – Design Decisions

---

### 1. Introduction
#### 1.1 Purpose
This SRS defines the requirements, architecture, technology choices, development sequence and acceptance criteria for SEEK. The document is intentionally more detailed than a basic college-project SRS so that it can also act as a development blueprint.

#### 1.2 Project Definition
SEEK is a student-built search engine that owns the major search stages: source discovery, controlled crawling, content extraction, indexing, query processing, retrieval, ranking and result presentation. An optional AI/RAG layer will use retrieved sources to produce a natural-language answer.

#### 1.3 Guiding Principle
SEEK will be built locally first and designed so that the core search experience works with open-source software. Cloud services and external AI APIs are optional accelerators, not mandatory foundations.

---

### 2. Problem Statement
Internet-scale search requires massive infrastructure and is outside the practical scope of a student project. However, the engineering concepts behind search can be implemented on a controlled corpus. SEEK solves this by building a smaller but genuine search system and gradually introducing AI/ML capabilities.
The project should demonstrate the complete pipeline rather than simply sending a query to an existing commercial search API.

---

### 3. Vision and Goals
#### 3.1 Long-Term Vision
The long-term vision is for SEEK to become an AI-assisted research and knowledge-discovery platform. A user should be able to search normally, understand why results were selected, explore multiple sources, and optionally ask SEEK to synthesize information from those sources.

#### 3.2 Project Goals
- Build a real search engine instead of a wrapper around Google/Bing.
- Implement a keyword retrieval baseline using BM25 or equivalent information retrieval.
- Add optional ML-based embedding retrieval.
- Create a hybrid ranking layer combining multiple relevance signals.
- Build a controlled and responsible web crawler.
- Create an optional RAG answer system with source attribution.
- Use Docker to make the system reproducible.
- Keep core functionality usable at zero API cost.
- Make search, ranking, embeddings and AI providers replaceable.

---

### 4. Scope and Boundaries
#### 4.1 Version 1 Scope
- Controlled crawling from configured seed URLs and allowed domains.
- Readable content extraction, cleaning, chunking and metadata storage.
- Keyword index and BM25 search.
- Optional vector index using an open-source embedding model.
- Hybrid result ranking.
- React search interface and FastAPI backend.
- Docker Compose local environment.
- Optional RAG answer generation.
- Automated unit and integration tests.

#### 4.2 Boundaries
- SEEK will not attempt to crawl the entire internet.
- SEEK will not require paid search APIs.
- SEEK will not depend on a paid LLM for ordinary search.
- Cloud deployment is optional and subject to free-tier/educational limits.
- Search quality will be evaluated on a controlled corpus before attempting larger-scale crawling.

---

### 5. Product Overview
- **Data Pipeline**: Seeds → Crawler → robots/domain checks → HTTP retrieval → HTML extraction → cleaning → chunking → metadata → indexes
- **Keyword Search**: Query → normalization → token processing → inverted index/BM25 → candidates
- **ML Search**: Query embedding → vector similarity → semantic candidates
- **Ranking**: Candidate merge → deduplication → relevance/freshness/authority signals → final ordering
- **AI/RAG**: Top source passages → context selection → optional model → answer + source references
- **Presentation**: Structured API response → React UI → results, snippets, sources and optional answer

---

### 6. Actors and Use Cases
| Actor | Use Case | Result |
|---|---|---|
| **General User** | Search | Ranked results and snippets |
| **Student/Researcher** | Research mode | Multiple relevant sources and optional synthesis |
| **Developer** | Code/documentation search | Technical sources prioritized where possible |
| **Developer/Admin** | Configure sources | Crawler receives permitted seeds/domains |
| **Developer/Admin** | Run crawl/index | New documents become searchable |
| **Developer/Admin** | Monitor health | Service/crawler/index failures can be diagnosed |

---

### 7. End-to-End Vision
The complete product is intentionally divided into stages so each stage can be developed and tested independently:
1. Collect permitted source content.
2. Convert web pages into clean searchable documents.
3. Build persistent keyword and optional vector indexes.
4. Receive a user query through the web interface.
5. Understand and normalize the query.
6. Retrieve candidates using available search methods.
7. Merge and rank candidates.
8. Generate snippets and return source metadata.
9. Optionally use top-ranked source passages for an AI/RAG answer.
10. Display the answer and/or results in a clean interface.

---

### 8. System Architecture
| Layer | Responsibility | Primary Technology |
|---|---|---|
| **Presentation** | Search UI, result cards, modes, loading/error states | React + TypeScript + Tailwind |
| **API** | HTTP endpoints, validation, orchestration | FastAPI + Python |
| **Query** | Normalization, optional intent/filter extraction | Python; optional ML |
| **Retrieval** | Keyword and optional vector retrieval | BM25 + FAISS/Chroma |
| **Ranking** | Candidate merge and scoring | Python |
| **Content** | Crawling, extraction, cleaning, chunking | httpx/asyncio + parser |
| **Persistence** | Metadata and application data | PostgreSQL |
| **AI** | Optional RAG answer generation | Open-source model or optional free-tier API |
| **Infrastructure** | Containers, networking, volumes | Docker + Docker Compose |

---

### 9. Search Sequence Diagram
1. User enters a query.
2. Frontend sends a request to the search API.
3. API validates the request and selects the requested search mode.
4. Query processor normalizes the query.
5. Keyword retrieval searches the BM25 index.
6. Optional semantic retrieval searches the vector index.
7. Candidates are merged and duplicates removed.
8. Ranking engine calculates final relevance scores.
9. Top results and snippets are prepared.
10. If AI mode is enabled, selected source passages are passed to RAG.
11. Backend returns JSON containing results and optional answer/source data.
12. Frontend renders the final response.

---

### 10. Crawling and Indexing Flow
1. Developer provides seed URLs.
2. Crawler validates the domain against the allowlist.
3. Crawler checks applicable robots.txt rules.
4. Crawler downloads the page with timeout and retry controls.
5. Content processor extracts title, main text, links and metadata.
6. Navigation, scripts and irrelevant elements are removed.
7. Text is normalized and divided into chunks.
8. URL and content hashes are calculated.
9. Document metadata is stored in PostgreSQL.
10. Keyword index is updated.
11. Optional embeddings are generated and stored in the vector index.
12. Crawl status and errors are logged.

---

### 11. Functional Requirements
- **FR-01 (Search)**: User shall be able to submit text queries.
- **FR-02 (Validation)**: API shall validate query length and parameters.
- **FR-03 (Keyword Retrieval)**: System shall support indexed keyword retrieval.
- **FR-04 (BM25)**: System shall support BM25 or equivalent lexical ranking.
- **FR-05 (Semantic Retrieval)**: System should support optional embedding-based retrieval.
- **FR-06 (Hybrid Search)**: System should merge keyword and semantic candidates.
- **FR-07 (Ranking)**: System shall rank candidates before returning results.
- **FR-08 (Snippets)**: System shall provide readable result snippets.
- **FR-09 (Metadata)**: Results shall include title, URL/domain and score/rank data where appropriate.
- **FR-10 (Pagination)**: System shall support result limits and pagination/incremental loading.
- **FR-11 (Crawler Seeds)**: Developer/admin shall configure seed URLs.
- **FR-12 (Domain Control)**: Crawler shall enforce allowed-domain rules.
- **FR-13 (Robots)**: Crawler shall respect applicable robots.txt instructions.
- **FR-14 (Extraction)**: System shall extract useful textual content from supported pages.
- **FR-15 (Deduplication)**: System shall reduce duplicate/unchanged documents.
- **FR-16 (Index Management)**: Developer/admin shall be able to build/rebuild indexes.
- **FR-17 (Crawl Monitoring)**: System shall expose crawl job status.
- **FR-18 (AI Answer)**: Optional AI mode shall generate answers from retrieved context.
- **FR-19 (Citations)**: AI responses shall expose source references.
- **FR-20 (Fallback)**: Normal search shall work when AI is unavailable.
- **FR-21 (Health)**: System shall provide a health endpoint.
- **FR-22 (API Docs)**: Development API documentation shall be available.
- **FR-23 (Errors)**: Invalid requests and dependency failures shall be handled cleanly.
- **FR-24 (Logging)**: Core components shall create useful logs.

---

### 12. Non-Functional Requirements
- **NFR-01 (Performance)**: Typical local searches should complete within a few seconds on a modest controlled corpus.
- **NFR-02 (Scalability)**: Services should be separable for future scaling.
- **NFR-03 (Reliability)**: Single-page crawler failures must not terminate the whole crawl.
- **NFR-04 (Cost)**: Core search shall not require paid APIs.
- **NFR-05 (Portability)**: Project shall be runnable through Docker.
- **NFR-06 (Maintainability)**: Components shall have clear interfaces and documentation.
- **NFR-07 (Security)**: Secrets shall stay outside source control.
- **NFR-08 (Privacy)**: Only necessary user/session information should be retained.
- **NFR-09 (Usability)**: First-time users should understand the search interface immediately.
- **NFR-10 (Extensibility)**: Embedding, vector and AI providers should be replaceable.
- **NFR-11 (Observability)**: Logs and health checks shall support troubleshooting.
- **NFR-12 (Reproducibility)**: Dependencies and container configuration shall be documented.

---

### 13. Technology Stack
| Layer | Technology | Why It Is Used | Cost |
|---|---|---|---|
| **Frontend** | React + TypeScript | Component-based responsive UI | Free/open source |
| **UI Styling** | Tailwind CSS | Fast consistent styling | Free/open source |
| **Backend** | Python + FastAPI | Simple high-performance API layer | Free/open source |
| **Crawler** | httpx + asyncio | Async HTTP retrieval | Free/open source |
| **Parsing** | BeautifulSoup / Trafilatura | HTML/content extraction | Free/open source |
| **Keyword Search** | BM25 / IR library | Strong inexpensive lexical baseline | Free/open source |
| **ML Embeddings** | Sentence Transformers | Local semantic representation | Free/open source |
| **Vector Search** | FAISS or ChromaDB | Similarity retrieval | Free/open source |
| **Database** | PostgreSQL | Persistent metadata/application data | Free/open source |
| **AI/RAG** | Open-source model / Free API | Optional natural-language answers | Optional |
| **Containers** | Docker + Docker Compose | Reproducible development/deployment | Free |
| **Version Control** | Git + GitHub | Source control | Free tier |

---

### 14. Data Architecture
- **Document**: `id`, `url`, `title`, `content`, `domain`, `hash`, `crawl_time`
- **DocumentChunk**: `chunk_id`, `document_id`, `text`, `position`
- **Embedding**: `chunk_id`, `vector`, `model_name`
- **CrawlJob**: `job_id`, `seed`, `status`, `timestamps`, `counts`
- **CrawlURL**: `url`, `status`, `depth`, `last_seen`, `error`
- **SearchQuery**: `query`, `timestamp`, `mode`
- **SearchResult**: `document_id`, `score`, `rank`, `snippet`

---

### 15. Search and Ranking Design
#### 15.1 Example Scoring Model
$$\text{Final Score} = w_1 \times \text{normalized BM25} + w_2 \times \text{semantic similarity} + w_3 \times \text{freshness} + w_4 \times \text{authority}$$
The weights are configurable and will be tuned experimentally using a small relevance-evaluation dataset.

---

### 16. Development Roadmap
- **Phase 0 – Planning**: Finalize SRS, architecture, scope, zero-cost constraints and repository.
- **Phase 1 – Foundation**: Create React UI, FastAPI service, environment configuration and Docker Compose.
- **Phase 2 – Search MVP**: Create local corpus, PostgreSQL storage, BM25 index and search endpoint.
- **Phase 3 – UI**: Build homepage, results, snippets, pagination and error states.
- **Phase 4 – Crawler**: Implement seeds, queue, domains, robots, extraction, cleaning and deduplication.
- **Phase 5 – Persistent Indexing**: Connect crawler output to database and persistent indexes.
- **Phase 6 – Semantic Search**: Add local embeddings and FAISS/Chroma; compare retrieval quality.
- **Phase 7 – Hybrid Ranking**: Merge lexical and semantic candidates and tune scoring.
- **Phase 8 – AI/RAG**: Add optional source-grounded answer generation and citations.
- **Phase 9 – Search Modes**: Add optional Web, AI, Research and Code modes.
- **Phase 10 – Testing**: Build unit, integration, API, crawler and ranking tests.
- **Phase 11 – Docker Hardening**: Optimize images, volumes, health checks and configuration.
- **Phase 12 – Cloud**: Deploy only after local stability using eligible free resources.
- **Phase 13 – Evaluation**: Measure relevance, latency, crawl throughput and resource usage.
- **Phase 14 – Documentation**: README, setup guide, architecture, API documentation and demonstration.
