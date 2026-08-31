from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

class HealthCheckResponse(BaseModel):
    status: str
    service: str

@router.get("/health", response_model=HealthCheckResponse, tags=["Health"])
async def health_check() -> HealthCheckResponse:
    """
    Service health check endpoint for SEEK backend.
    """
    return HealthCheckResponse(
        status="ok",
        service="seek-backend"
    )
