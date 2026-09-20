from fastapi import APIRouter
from backend.api.health import router as health_router
from backend.api.root import router as root_router
from backend.api.search import router as search_router
from backend.api.crawl import router as crawl_router
from backend.api.index import router as index_router
from backend.api.answer import router as answer_router

api_router = APIRouter()

api_router.include_router(root_router)
api_router.include_router(health_router)
api_router.include_router(search_router)
api_router.include_router(crawl_router)
api_router.include_router(index_router)
api_router.include_router(answer_router)
