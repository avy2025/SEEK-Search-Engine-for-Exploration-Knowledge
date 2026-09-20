from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "SEEK Search Engine"
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- Phase 1 Persistence (PostgreSQL) ---
    DATABASE_URL: str = "postgresql+psycopg2://seek:seek@db:5432/seek"

    # --- Phase 2 Search MVP ---
    SAMPLE_CORPUS_DIR: str = "data/sample_corpus"
    BM25_K1: float = 1.5
    BM25_B: float = 0.75
    SEARCH_DEFAULT_LIMIT: int = 10
    SEARCH_MAX_LIMIT: int = 50
    SNIPPET_SURROUNDING_WORDS: int = 12
    CACHE_ONLY: bool = True

    # --- Phase 5 Persistent Index ---
    STORAGE_INDEX_PATH: str = "indexes"
    INDEX_SUBDIR: str = "bm25"

    # --- Phase 6 Semantic Search (Local ML Embeddings) ---
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    EMBEDDING_BATCH_SIZE: int = 32
    # Persistent FAISS artifact location (the directory holds the two files
    # below, next to the Phase 5B ``bm25/`` subdir).
    SEMANTIC_INDEX_PATH: str = "indexes"
    FAISS_INDEX_FILE: str = "faiss_index.bin"
    FAISS_METADATA_FILE: str = "faiss_metadata.json"

    # --- Phase 7 Hybrid Ranking Engine ---
    HYBRID_BM25_WEIGHT: float = 0.5
    HYBRID_SEMANTIC_WEIGHT: float = 0.5
    HYBRID_BM25_CANDIDATES: int = 50
    HYBRID_SEMANTIC_CANDIDATES: int = 50

    # --- Phase 8 AI / RAG Answer Generation ---
    RAG_ENABLED: bool = True
    RAG_LLM_PROVIDER: str = "fake"  # options: "fake", "ollama", "transformers"
    RAG_OLLAMA_HOST: str = "http://localhost:11434"
    RAG_OLLAMA_MODEL: str = "qwen2.5:0.5b"
    RAG_TRANSFORMERS_MODEL: str = "Qwen/Qwen2.5-0.5B-Instruct"
    RAG_MAX_PASSAGES: int = 5
    RAG_MAX_CONTEXT_CHARS: int = 3000
    RAG_MIN_SCORE_THRESHOLD: float = 0.15
    RAG_LLM_TIMEOUT_SECONDS: float = 10.0
    RAG_TEMPERATURE: float = 0.2

    # --- Phase 4 Controlled Web Crawler ---
    CRAWLER_ALLOWED_DOMAINS: str = ""
    CRAWLER_MAX_DEPTH: int = 2
    CRAWLER_MAX_PAGES: int = 25
    CRAWLER_CONCURRENT_REQUESTS: int = 1
    CRAWLER_DELAY_SECONDS: float = 1.0
    CRAWLER_TIMEOUT_SECONDS: float = 10.0
    CRAWLER_MAX_REDIRECTS: int = 5
    CRAWLER_MAX_CONTENT_CHARS: int = 200_000
    CRAWLER_USER_AGENT: str = "SEEK-Crawler/1.0 (+http://localhost:3000/bot-info)"
    CRAWLER_RESPECT_ROBOTS: bool = True
    CRAWLER_BLOCK_PRIVATE_HOSTS: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def index_dir(self) -> str:
        """Directory where the persistent BM25 artifact is stored."""
        return str(Path(self.STORAGE_INDEX_PATH) / self.INDEX_SUBDIR)

    @property
    def semantic_index_dir(self) -> str:
        """Directory where the persistent FAISS artifact is stored."""
        return str(Path(self.SEMANTIC_INDEX_PATH))

    @property
    def faiss_index_path(self) -> str:
        return str(Path(self.semantic_index_dir) / self.FAISS_INDEX_FILE)

    @property
    def faiss_metadata_path(self) -> str:
        return str(Path(self.semantic_index_dir) / self.FAISS_METADATA_FILE)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
