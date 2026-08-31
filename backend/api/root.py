from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

class RootResponse(BaseModel):
    name: str
    subtitle: str
    phase: str
    status: str
    docs_url: str

@router.get("/", response_model=RootResponse, tags=["Meta"])
async def root() -> RootResponse:
    """
    Root endpoint returning general metadata for SEEK backend API.
    """
    return RootResponse(
        name="SEEK Search Engine",
        subtitle="Search Engine for Exploration & Knowledge",
        phase="Phase 1 — Foundation",
        status="Operational",
        docs_url="/docs"
    )
