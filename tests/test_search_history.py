from __future__ import annotations

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import secrets
from time import sleep
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy import inspect as inspect_database

from backend.api.session import SESSION_COOKIE_NAME
from backend.api import history as history_api
from backend.api import session as session_api
from backend.config import settings
from backend.db.history import (
    HistoryStoreUnavailable,
    SearchHistoryRepository,
)
from backend.db.models import Base, BrowserSession, SearchHistory
from backend.db.session import make_database_engine
from backend.main import app
from backend import main as main_module

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_records_each_supported_mode_and_normalizes_query(client):
    for mode in ("web", "live", "ai", "research", "code"):
        response = client.post(
            "/api/history",
            json={
                "query": f"  {mode} query  ",
                "mode": mode,
                "request_id": str(uuid4()),
            },
        )
        assert response.status_code == 201
        entry = response.json()
        assert entry["query"] == f"{mode} query"
        assert entry["mode"] == mode
        assert entry["status"] == "completed"
        UUID(entry["id"])
        assert entry["created_at"]


def test_history_is_newest_first_and_supports_mode_filter_and_pagination(client):
    for query, mode in (
        ("first web", "web"),
        ("second live", "live"),
        ("third web", "web"),
    ):
        response = client.post(
            "/api/history",
            json={"query": query, "mode": mode, "request_id": str(uuid4())},
        )
        assert response.status_code == 201
        sleep(0.002)

    page = client.get("/api/history", params={"limit": 2, "offset": 0}).json()
    assert [entry["query"] for entry in page["items"]] == [
        "third web",
        "second live",
    ]
    assert page["total"] == 3

    filtered = client.get("/api/history", params={"mode": "web"}).json()
    assert [entry["query"] for entry in filtered["items"]] == [
        "third web",
        "first web",
    ]
    assert filtered["total"] == 2

    later_page = client.get(
        "/api/history", params={"limit": 1, "offset": 1, "mode": "web"}
    ).json()
    assert [entry["query"] for entry in later_page["items"]] == ["first web"]


def test_get_delete_individual_and_clear_history(client):
    created = client.post(
        "/api/history",
        json={"query": "delete me", "mode": "web", "request_id": str(uuid4())},
    ).json()
    entry_id = created["id"]

    assert client.get(f"/api/history/{entry_id}").json()["query"] == "delete me"
    assert client.delete(f"/api/history/{entry_id}").status_code == 204
    assert client.get(f"/api/history/{entry_id}").status_code == 404
    assert client.delete(f"/api/history/{entry_id}").status_code == 404
    assert client.get("/api/history").json()["items"] == []

    client.post(
        "/api/history",
        json={"query": "one", "mode": "ai", "request_id": str(uuid4())},
    )
    client.post(
        "/api/history",
        json={"query": "two", "mode": "live", "request_id": str(uuid4())},
    )
    cleared = client.delete("/api/history")
    assert cleared.status_code == 200
    assert cleared.json() == {"deleted_count": 2}
    assert client.get("/api/history").json()["total"] == 0


def test_rejects_invalid_queries_modes_ids_and_pagination(client):
    for payload in (
        {"query": "   ", "mode": "web", "request_id": str(uuid4())},
        {"query": "x" * 501, "mode": "web", "request_id": str(uuid4())},
        {"query": "valid", "mode": "unknown", "request_id": str(uuid4())},
    ):
        assert client.post("/api/history", json=payload).status_code == 422

    assert client.get("/api/history/not-a-uuid").status_code == 422
    assert client.delete("/api/history/not-a-uuid").status_code == 422
    assert client.get("/api/history", params={"limit": 101}).status_code == 422
    assert client.get("/api/history", params={"offset": 1_000_001}).status_code == 422


def test_history_request_cannot_choose_its_owner(client):
    response = client.post(
        "/api/history",
        json={
            "query": "owned by my session",
            "mode": "web",
            "request_id": str(uuid4()),
            "owner_session_id": str(uuid4()),
        },
    )
    assert response.status_code == 422


def test_browser_sessions_are_http_only_and_origin_checked():
    client = TestClient(app, headers={"Origin": "http://localhost:3000"})
    response = client.post("/api/session")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert ("secure" in cookie) == (
        settings.APP_ENV.lower() not in {"development", "testing"}
    )

    hostile = TestClient(app, headers={"Origin": "https://attacker.example"})
    assert hostile.post("/api/session").status_code == 403
    hostile.cookies.update(client.cookies)
    assert hostile.post(
        "/api/history",
        json={"query": "blocked", "mode": "web", "request_id": str(uuid4())},
    ).status_code == 403


def test_missing_and_expired_browser_sessions_do_not_read_history(client, _isolated_search_history):
    anonymous = TestClient(app, headers={"Origin": "http://localhost:3000"})
    assert anonymous.get("/api/history").status_code == 401

    raw_token = secrets.token_urlsafe(32)
    expired = _isolated_search_history.create_browser_session(
        hashlib.sha256(raw_token.encode()).hexdigest(),
        datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    assert expired.id
    anonymous.cookies.set(
        SESSION_COOKIE_NAME,
        raw_token,
        domain="testserver",
        path="/api",
    )
    assert anonymous.get("/api/history").status_code == 401
    renewed = anonymous.post("/api/session")
    assert renewed.status_code == 200
    assert anonymous.get("/api/history").json()["total"] == 0


def test_two_browser_sessions_cannot_read_or_delete_each_others_history(
    client, _isolated_search_history
):
    client_b = TestClient(app, headers={"Origin": "http://localhost:3000"})
    assert client_b.post("/api/session").status_code == 200
    entry_a = client.post(
        "/api/history",
        json={"query": "private A", "mode": "web", "request_id": str(uuid4())},
    ).json()
    entry_b = client_b.post(
        "/api/history",
        json={"query": "private B", "mode": "ai", "request_id": str(uuid4())},
    ).json()

    assert [item["query"] for item in client.get("/api/history").json()["items"]] == [
        "private A"
    ]
    assert [item["query"] for item in client_b.get("/api/history").json()["items"]] == [
        "private B"
    ]
    assert client_b.get(f"/api/history/{entry_a['id']}").status_code == 404
    assert client_b.delete(f"/api/history/{entry_a['id']}").status_code == 404
    assert client.delete(f"/api/history/{entry_b['id']}").status_code == 404
    assert client_b.delete("/api/history").json() == {"deleted_count": 1}
    assert client_b.get("/api/history").json()["total"] == 0
    assert client.get(f"/api/history/{entry_a['id']}").status_code == 200


def test_history_database_failures_are_reported_without_internal_details(
    client, monkeypatch
):
    def unavailable_repository():
        raise HistoryStoreUnavailable

    monkeypatch.setattr(history_api, "get_history_repository", unavailable_repository)
    response = client.get("/api/history")
    assert response.status_code == 503
    assert response.json() == {
        "detail": "Search history is temporarily unavailable."
    }


def test_recording_is_idempotent_and_rejects_key_reuse_for_other_search(client):
    request_id = str(uuid4())
    payload = {"query": "one search", "mode": "web", "request_id": request_id}
    first = client.post("/api/history", json=payload)
    retry = client.post("/api/history", json=payload)
    assert first.status_code == retry.status_code == 201
    assert first.json()["id"] == retry.json()["id"]
    assert client.get("/api/history").json()["total"] == 1

    conflict = client.post(
        "/api/history",
        json={"query": "different query", "mode": "web", "request_id": request_id},
    )
    assert conflict.status_code == 409
    assert client.get("/api/history").json()["total"] == 1


def test_history_migration_is_idempotent_and_handles_startup_created_table(
    tmp_path, monkeypatch
):
    config = Config(str(REPO_ROOT / "alembic.ini"))
    migration_url = f"sqlite:///{tmp_path / 'migration.sqlite3'}"
    monkeypatch.setattr(settings, "DATABASE_URL", migration_url)

    command.upgrade(config, "head")
    command.upgrade(config, "head")

    engine = create_engine(migration_url)
    inspector = inspect_database(engine)
    assert inspector.has_table("search_history")
    assert {
        "ix_search_history_created_at",
        "ix_search_history_mode_created_at",
        "ix_search_history_owner_created_at",
    }.issubset({index["name"] for index in inspector.get_indexes("search_history")})
    assert inspector.has_table("browser_sessions")
    engine.dispose()

    startup_url = f"sqlite:///{tmp_path / 'startup-created.sqlite3'}"
    startup_engine = create_engine(startup_url)
    Base.metadata.create_all(
        startup_engine,
        tables=[BrowserSession.__table__, SearchHistory.__table__],
    )
    startup_engine.dispose()
    monkeypatch.setattr(settings, "DATABASE_URL", startup_url)

    command.upgrade(config, "head")
    startup_engine = create_engine(startup_url)
    assert inspect_database(startup_engine).has_table("search_history")
    startup_engine.dispose()


def test_migration_quarantines_legacy_history_from_new_sessions(tmp_path, monkeypatch):
    config = Config(str(REPO_ROOT / "alembic.ini"))
    database_url = f"sqlite:///{tmp_path / 'legacy-history.sqlite3'}"
    monkeypatch.setattr(settings, "DATABASE_URL", database_url)
    command.upgrade(config, "20261114_01")

    legacy_id = str(uuid4())
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            SearchHistory.__table__.insert().values(
                id=legacy_id,
                query="legacy private search",
                mode="web",
            )
        )
    engine.dispose()
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    with engine.connect() as connection:
        owner_id = connection.execute(
            text("SELECT owner_session_id FROM search_history WHERE id = :id"),
            {"id": legacy_id},
        ).scalar_one()
        expires_at = connection.execute(
            text("SELECT expires_at FROM browser_sessions WHERE id = :id"),
            {"id": owner_id},
        ).scalar_one()
    assert owner_id
    assert datetime.fromisoformat(str(expires_at)).replace(
        tzinfo=timezone.utc
    ) < datetime.now(timezone.utc)
    engine.dispose()

    repository = SearchHistoryRepository(engine=create_engine(database_url))
    legacy_entry = repository.get(legacy_id, owner_session_id="untrusted")
    assert legacy_entry is None

    monkeypatch.setattr(history_api, "get_history_repository", lambda: repository)
    monkeypatch.setattr(session_api, "get_history_repository", lambda: repository)
    new_client = TestClient(app, headers={"Origin": "http://localhost:3000"})
    assert new_client.post("/api/session").status_code == 200
    assert new_client.get("/api/history").json()["total"] == 0
    repository.engine.dispose()


def test_application_startup_runs_additive_database_migrations(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'startup-migrations.sqlite3'}"
    monkeypatch.setattr(settings, "DATABASE_URL", database_url)

    main_module._run_database_migrations()

    engine = create_engine(database_url)
    inspector = inspect_database(engine)
    assert inspector.has_table("browser_sessions")
    assert inspector.has_table("search_history")
    assert "owner_session_id" in {
        column["name"] for column in inspector.get_columns("search_history")
    }
    engine.dispose()


def test_downgrade_does_not_expose_session_owned_rows(tmp_path, monkeypatch):
    config = Config(str(REPO_ROOT / "alembic.ini"))
    database_url = f"sqlite:///{tmp_path / 'downgrade.sqlite3'}"
    monkeypatch.setattr(settings, "DATABASE_URL", database_url)
    command.upgrade(config, "head")

    repository = SearchHistoryRepository(engine=create_engine(database_url))
    owner = repository.create_browser_session(
        secrets.token_hex(32),
        datetime.now(timezone.utc) + timedelta(days=1),
    )
    repository.create("private before rollback", "web", str(uuid4()), owner_session_id=owner.id)
    repository.engine.dispose()

    command.downgrade(config, "20261114_01")
    engine = create_engine(database_url)
    inspector = inspect_database(engine)
    assert "owner_session_id" not in {
        column["name"] for column in inspector.get_columns("search_history")
    }
    assert not inspector.has_table("browser_sessions")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM search_history")).scalar_one() == 0
    engine.dispose()


def test_history_persists_when_repository_is_recreated(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'persistent-history.sqlite3'}"
    first_engine = create_engine(database_url)
    first = SearchHistoryRepository(engine=first_engine)
    owner = first.create_browser_session(
        secrets.token_hex(32),
        datetime.now(timezone.utc) + timedelta(days=1),
    )
    created = first.create(
        "persists", "ai", str(uuid4()), owner_session_id=owner.id
    )
    entry_id = created.id
    first_engine.dispose()

    second_engine = create_engine(database_url)
    second = SearchHistoryRepository(engine=second_engine)
    entries, total = second.list(owner.id, limit=10, offset=0)
    assert total == 1
    assert entries[0].id == entry_id
    assert entries[0].query == "persists"
    second_engine.dispose()


def test_configured_sqlite_history_repository_uses_sqlite_connection_options(
    tmp_path, monkeypatch
):
    database_url = f"sqlite:///{tmp_path / 'configured-sqlite.sqlite3'}"
    monkeypatch.setattr(settings, "DATABASE_URL", database_url)

    repository = SearchHistoryRepository()
    owner = repository.create_browser_session(
        secrets.token_hex(32),
        datetime.now(timezone.utc) + timedelta(days=1),
    )
    entry = repository.create(
        "SQLite runtime query",
        "web",
        str(uuid4()),
        owner_session_id=owner.id,
    )

    assert repository.get(entry.id, owner_session_id=owner.id) is not None
    repository.engine.dispose()

    memory_engine = make_database_engine("sqlite:///:memory:")
    with memory_engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1
    memory_engine.dispose()


def test_concurrent_history_writes_keep_every_entry(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'concurrent-history.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    repository = SearchHistoryRepository(engine=engine)
    owner = repository.create_browser_session(
        secrets.token_hex(32),
        datetime.now(timezone.utc) + timedelta(days=1),
    )
    queries = [f"query-{index}" for index in range(24)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        entries = list(
            pool.map(
                lambda query: repository.create(
                    query, "web", str(uuid4()), owner_session_id=owner.id
                ),
                queries,
            )
        )

    saved, total = repository.list(owner.id, limit=100, offset=0)
    assert total == len(queries)
    assert len({entry.id for entry in entries}) == len(queries)
    assert {entry.query for entry in saved} == set(queries)
    engine.dispose()
