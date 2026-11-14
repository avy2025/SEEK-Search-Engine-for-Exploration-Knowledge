"""Anonymous browser-session bootstrap for session-owned search history."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from backend.config import settings
from backend.db.history import (
    HistoryStoreUnavailable,
    SearchHistoryRepository,
    get_history_repository,
)
from backend.db.models import BrowserSession

SESSION_COOKIE_NAME = "seek_browser_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 30
router = APIRouter(prefix="/api", tags=["browser-session"])


class SessionBootstrapResponse(BaseModel):
    ready: bool


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def require_allowed_browser_origin(request: Request) -> None:
    """Reject cross-site writes; wildcard CORS is not an origin allowlist."""
    origin = request.headers.get("origin")
    if not origin or origin == "null":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A trusted browser origin is required.",
        )

    allowed_origins = {
        configured.rstrip("/")
        for configured in settings.cors_origins_list
        if configured != "*"
    }
    if origin.rstrip("/") in allowed_origins:
        return

    origin_parts = urlsplit(origin)
    request_origin = f"{request.url.scheme}://{request.url.netloc}"
    if (
        origin_parts.scheme
        and origin_parts.netloc
        and f"{origin_parts.scheme}://{origin_parts.netloc}" == request_origin
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="The browser origin is not allowed to modify search history.",
    )


def require_browser_session(request: Request) -> BrowserSession:
    token = request.cookies.get(SESSION_COOKIE_NAME, "")
    if not token or len(token) > 128:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid browser session is required.",
        )
    try:
        browser_session = get_history_repository().get_browser_session(
            _token_hash(token),
            now=datetime.now(timezone.utc),
        )
    except HistoryStoreUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Search history is temporarily unavailable.",
        ) from exc
    if browser_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid browser session is required.",
        )
    return browser_session


@router.post("/session", response_model=SessionBootstrapResponse)
def bootstrap_browser_session(
    request: Request,
    response: Response,
) -> SessionBootstrapResponse:
    require_allowed_browser_origin(request)
    now = datetime.now(timezone.utc)
    try:
        repository: SearchHistoryRepository = get_history_repository()
        existing_token = request.cookies.get(SESSION_COOKIE_NAME, "")
        existing_session = (
            repository.get_browser_session(_token_hash(existing_token), now=now)
            if existing_token and len(existing_token) <= 128
            else None
        )
        if existing_session is None:
            token = secrets.token_urlsafe(32)
            repository.create_browser_session(
                _token_hash(token),
                now + timedelta(seconds=SESSION_TTL_SECONDS),
            )
            response.set_cookie(
                key=SESSION_COOKIE_NAME,
                value=token,
                max_age=SESSION_TTL_SECONDS,
                httponly=True,
                secure=settings.APP_ENV.lower() not in {"development", "testing"},
                samesite="lax",
                path="/api",
            )
    except HistoryStoreUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Search history is temporarily unavailable.",
        ) from exc
    return SessionBootstrapResponse(ready=True)
