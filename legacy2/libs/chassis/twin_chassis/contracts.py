"""Write the service's requests into contracts/openapi/<service>.v1.json.

    cd services/<service> && uv run python -m twin_chassis.contracts <service>

Run after changing the requests on purpose; the diff of the file is the change
of the contract, reviewed like any other. The tests fail while they differ.
"""
from __future__ import annotations

import importlib
import sys

from .settings import find_contracts
from .testing import openapi_text

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    service = sys.argv[1]
    app = importlib.import_module("app.main").build()
    path = find_contracts() / "openapi" / f"{service}.v1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(openapi_text(app), encoding="utf-8")
    print(f"written: {path}")
