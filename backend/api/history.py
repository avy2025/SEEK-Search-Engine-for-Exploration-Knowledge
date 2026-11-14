"""Search history API for recording and managing completed searches."""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Literal, Optional, TypeVar
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.db.history import (
    HistoryIdempotencyConflict,
    HistoryStoreUnavailable,
    SearchHistoryRepository,
    get_history_repository,
)
from backend.db.models import SearchHistory

HistoryMode = Literal["web", "ai", "research", "code", "live"]
T = TypeVar("T")

router = APIRouter(prefix="/api/history", tags=["history"])


class SearchHistoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    mode: HistoryMode
    request_id: UUID

    @field_validator("query", mode="before")
    @classmethod
    def normalize_query(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class SearchHistoryEntry(BaseModel):
    id: UUID
    query: str
    mode: HistoryMode
    status: Literal["completed"]
    created_at: datetime

    @classmethod
    def from_model(cls, entry: SearchHistory) -> "SearchHistoryEntry":
        return cls.model_validate(
            {
                "id": entry.id,
                "query": entry.query,
                "mode": entry.mode,
                "status": entry.status,
                "created_at": entry.created_at,
            }
        )


class SearchHistoryPage(BaseModel):
    items: list[SearchHistoryEntry]
    total: int
    limit: int
    offset: int


class SearchHistoryClearResult(BaseModel):
    deleted_count: int


def _run(operation: Callable[[SearchHistoryRepository], T]) -> T:
    try:
        return operation(get_history_repository())
    except HistoryStoreUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Search history is temporarily unavailable.",
        ) from exc


@router.post("", response_model=SearchHistoryEntry, status_code=status.HTTP_201_CREATED)
def record_search(request: SearchHistoryCreate) -> SearchHistoryEntry:
    try:
        entry = _run(
            lambda repository: repository.create(
                request.query, request.mode, str(request.request_id)
            )
        )
    except HistoryIdempotencyConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The history request ID was already used for a different search.",
        ) from exc
    return SearchHistoryEntry.from_model(entry)


@router.get("", response_model=SearchHistoryPage)
def list_search_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    mode: Optional[HistoryMode] = Query(default=None),
) -> SearchHistoryPage:
    entries, total = _run(
        lambda repository: repository.list(limit=limit, offset=offset, mode=mode)
    )
    return SearchHistoryPage(
        items=[SearchHistoryEntry.from_model(entry) for entry in entries],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{id}", response_model=SearchHistoryEntry)
def get_search_history(id: UUID) -> SearchHistoryEntry:
    entry = _run(lambda repository: repository.get(str(id)))
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="History entry not found.",
        )
    return SearchHistoryEntry.from_model(entry)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_search_history(id: UUID) -> None:
    deleted = _run(lambda repository: repository.delete(str(id)))
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="History entry not found.",
        )


@router.delete("", response_model=SearchHistoryClearResult)
def clear_search_history() -> SearchHistoryClearResult:
    return SearchHistoryClearResult(
        deleted_count=_run(lambda repository: repository.clear())
    )
