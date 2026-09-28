"""Writes the API's OpenAPI document to stdout, sorted and stable.

The frontend generates its TypeScript types from this file, and CI checks
that the committed copy matches the code:

    uv run python scripts/export_openapi.py > ../frontend/openapi.json

Building the app only reads settings; nothing connects to PostgreSQL or
Redis, so placeholder values are enough.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PLACEHOLDERS = {
    "POSTGRES_USER": "openapi",
    "POSTGRES_PASSWORD": "openapi",  # pragma: allowlist secret
    "POSTGRES_DB": "openapi",
    "JWT_SECRET": "openapi-export-placeholder-secret-0000",  # pragma: allowlist secret
    "REDIS_URL": "redis://localhost:6379/0",
}


def main() -> None:
    for name, value in PLACEHOLDERS.items():
        os.environ.setdefault(name, value)
    from app.api.app import create_app

    schema = create_app().openapi()
    json.dump(schema, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
