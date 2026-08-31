from fastapi import APIRouter
from backend.api.health import router as health_router
from backend.api.root import router as root_router

api_router = APIRouter()

api_router.include_router(root_router)
api_router.include_router(health_router)
