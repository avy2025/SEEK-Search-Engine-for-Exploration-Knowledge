from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.config import settings
from backend.api.router import api_router
from backend.search.index_manager import get_index_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load persistent indexes at startup (never blocks boot).

    BM25 (Phase 5B):
    * a valid persisted index is loaded immediately (PostgreSQL not required);
    * a missing/corrupt index is (re)built from PostgreSQL when reachable;
    * otherwise the app starts with an empty search index that reports its
      state via ``GET /api/index/status`` and rebuilds on demand.

    Semantic FAISS (Phase 6):
    * a valid persisted FAISS artifact is loaded immediately — this only reads
      ``indexes/faiss_index.bin``; the embedding model is **not** loaded here
      (it materialises lazily on the first semantic search/rebuild);
    * a missing/corrupt semantic index merely leaves semantic search
      unbuilt/unavailable; it never blocks boot and BM25 is unaffected.
    """
    from backend.search.index_manager import reset_index_manager
    from backend.search.semantic import (
        get_semantic_index_manager,
        reset_semantic_index_manager,
    )

    reset_index_manager()
    manager = get_index_manager()
    state = manager.load_on_startup()
    print(
        f"[startup] index: source={state.get('source')} "
        f"documents={state.get('document_count')} "
        f"loaded={state.get('loaded')}"
    )

    reset_semantic_index_manager()
    sem_manager = get_semantic_index_manager()
    sem_state = sem_manager.load_on_startup()
    print(
        f"[startup] semantic: source={sem_state.get('source')} "
        f"documents={sem_state.get('document_count')} "
        f"loaded={sem_state.get('loaded')}"
    )
    try:
        yield
    finally:
        manager.close()
        sem_manager.close()


app = FastAPI(
    title=settings.APP_NAME,
    description="SEEK - Search Engine for Exploration & Knowledge API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Configure CORS
origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()]
if "*" not in origins:
    origins.extend(["http://localhost:3000", "http://127.0.0.1:3000"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=settings.BACKEND_HOST,
        port=settings.BACKEND_PORT,
        reload=True
    )
