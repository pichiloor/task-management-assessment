#!/usr/bin/env sh
# Regenerates the frontend's API contract from the backend code:
#   frontend/openapi.json               (the OpenAPI document)
#   frontend/src/api/generated/schema.ts (TypeScript types for the client)
# Run after changing an endpoint or schema; CI fails if they are stale.
set -eu
cd "$(dirname "$0")/.."
(cd backend && uv run --locked python scripts/export_openapi.py) > frontend/openapi.json
npm --prefix frontend run --silent gen:api
