from functools import lru_cache
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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
