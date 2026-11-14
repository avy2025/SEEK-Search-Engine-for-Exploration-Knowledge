from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import sleep
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy import inspect as inspect_database

from backend.api import history as history_api
from backend.config import settings
from backend.db.history import (
    HistoryStoreUnavailable,
    SearchHistoryRepository,
)
from backend.db.models import Base, SearchHistory

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
    }.issubset({index["name"] for index in inspector.get_indexes("search_history")})
    engine.dispose()

    startup_url = f"sqlite:///{tmp_path / 'startup-created.sqlite3'}"
    startup_engine = create_engine(startup_url)
    Base.metadata.create_all(startup_engine, tables=[SearchHistory.__table__])
    startup_engine.dispose()
    monkeypatch.setattr(settings, "DATABASE_URL", startup_url)

    command.upgrade(config, "head")
    startup_engine = create_engine(startup_url)
    assert inspect_database(startup_engine).has_table("search_history")
    startup_engine.dispose()


def test_history_persists_when_repository_is_recreated(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'persistent-history.sqlite3'}"
    first_engine = create_engine(database_url)
    first = SearchHistoryRepository(engine=first_engine)
    created = first.create("persists", "ai", str(uuid4()))
    entry_id = created.id
    first_engine.dispose()

    second_engine = create_engine(database_url)
    second = SearchHistoryRepository(engine=second_engine)
    entries, total = second.list(limit=10, offset=0)
    assert total == 1
    assert entries[0].id == entry_id
    assert entries[0].query == "persists"
    second_engine.dispose()


def test_concurrent_history_writes_keep_every_entry(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'concurrent-history.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    repository = SearchHistoryRepository(engine=engine)
    queries = [f"query-{index}" for index in range(24)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        entries = list(
            pool.map(
                lambda query: repository.create(query, "web", str(uuid4())),
                queries,
            )
        )

    saved, total = repository.list(limit=100, offset=0)
    assert total == len(queries)
    assert len({entry.id for entry in entries}) == len(queries)
    assert {entry.query for entry in saved} == set(queries)
    engine.dispose()
