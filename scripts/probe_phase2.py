import importlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MODULES = [
    "backend.config",
    "backend.db",
    "backend.db.models",
    "backend.db.session",
    "backend.db.repository",
    "backend.processing",
    "backend.processing.models",
    "backend.processing.tokenizer",
    "backend.processing.loader",
    "backend.search",
    "backend.search.models",
    "backend.search.bm25",
    "backend.search.query",
    "backend.search.engine",
    "backend.search.index_store",
    "backend.search.index_manager",
    "backend.pipeline",
    "backend.main",
]

ok = 0
fail = []
for name in MODULES:
    try:
        importlib.import_module(name)
        ok += 1
    except Exception as exc:  # noqa: BLE001
        fail.append(f"{name}: {type(exc).__name__}: {exc}")

print(f"import_ok={ok}/{len(MODULES)}")
for line in fail:
    print("FAIL " + line)

try:
    from backend.main import app
    print("app_build=OK title=" + str(app.title))
except Exception as exc:  # noqa: BLE001
    print("app_build=FAIL " + type(exc).__name__ + " " + str(exc))

# Phase 2's deliverable is a *searchable* index, not a set of importable modules:
# load the committed corpus, index it and run one query end to end. This stays
# offline (in-memory BM25 only) and never touches PostgreSQL or the network.
try:
    from backend.pipeline import build_pipeline

    engine = build_pipeline()
    documents = engine.document_count
    hits = engine.search("search engine", limit=3).hits
    search_ok = documents > 0 and bool(hits)
    print(
        f"search_ok={'true' if search_ok else 'false'} "
        f"documents={documents} hits={len(hits)}"
    )
except Exception as exc:  # noqa: BLE001
    print("search_ok=false " + type(exc).__name__ + " " + str(exc))
