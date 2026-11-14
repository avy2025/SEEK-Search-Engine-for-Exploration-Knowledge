from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_postgres_compose_credentials_are_required_and_not_host_published():
    compose = (REPOSITORY_ROOT / "docker-compose.yml").read_text()
    postgres = compose.split("  postgres:", 1)[1].split("  backend:", 1)[0]
    backend = compose.split("  backend:", 1)[1].split("  frontend:", 1)[0]

    for variable in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        assert re.search(rf'\$\{{{variable}:\?', postgres)
        assert re.search(rf'\$\{{{variable}:\?', backend)
        assert f"${{{variable}:-" not in postgres + backend
    assert not re.search(r"^\s+ports:", postgres, re.MULTILINE)


def test_example_environment_has_no_known_weak_database_credentials():
    example = (REPOSITORY_ROOT / ".env.example").read_text()
    config = (REPOSITORY_ROOT / "backend" / "config.py").read_text()
    assert re.search(r"^POSTGRES_USER=\s*$", example, re.MULTILINE)
    assert re.search(r"^POSTGRES_PASSWORD=\s*$", example, re.MULTILINE)
    assert "seek_dev_password" not in example
    assert "seek:seek@" not in config
