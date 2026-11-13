"""Safe, read-only article reader endpoint."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.browser.reader import ReaderError, read_public_page, validate_reader_url

router = APIRouter(prefix="/api/browser", tags=["browser"])


class ReaderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., min_length=1, max_length=2048)


class ReaderBlockResponse(BaseModel):
    type: Literal["heading", "paragraph", "list", "image"]
    text: str = ""
    level: int | None = None
    ordered: bool = False
    items: list[str] = Field(default_factory=list)
    src: str = ""
    alt: str = ""


class ReaderPageResponse(BaseModel):
    title: str
    site_name: str
    url: str
    published_at: str | None
    blocks: list[ReaderBlockResponse]


@router.post(
    "/read",
    name="read_public_webpage",
    summary="Read a public webpage as sanitized article content",
    response_model=ReaderPageResponse,
)
async def read_webpage(request: ReaderRequest) -> ReaderPageResponse:
    try:
        validate_reader_url(request.url)
        page = await read_public_page(request.url)
    except ReaderError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return ReaderPageResponse(
        title=page.title,
        site_name=page.site_name,
        url=page.url,
        published_at=page.published_at,
        blocks=[
            ReaderBlockResponse(
                type=block.type,
                text=block.text,
                level=block.level,
                ordered=block.ordered,
                items=list(block.items),
                src=block.src,
                alt=block.alt,
            )
            for block in page.blocks
        ],
    )


__all__ = ["ReaderRequest", "ReaderPageResponse", "read_webpage", "router"]
