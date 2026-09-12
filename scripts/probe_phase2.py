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
