# Project conventions

## Scope and language

Steps 1 (tooling), 2 (PostgreSQL and Redis in Compose), 3 (domain rules and
use cases, TDD), 4 (SQLAlchemy repositories, Alembic) and 5 (JWT login,
Argon2, auth endpoints) and 6 (task CRUD endpoints, `/api/health`, `api`
Compose service), 7 (demo seed), 8 (rate limiting) and 9 (Celery worker and
CSV export), 10 (CI on GitHub Actions) and 11 (React frontend behind nginx)
are done, and the documentation (README, `docs/`, GenAI evidence in
`docs/genai/`) is written. Next: clean-clone check and submission.

Frontend (`frontend/`): Vite + React + TypeScript strict, TanStack Query,
React Router. Types come from the OpenAPI document: after changing an
endpoint or schema run `./scripts/gen-api-types.sh` and commit
`frontend/openapi.json` and `src/api/generated/`. Tests: `npm --prefix
frontend test` (Vitest + Testing Library, `fetch` faked in
`tests/support/fake-api.ts`). nginx (`frontend/nginx.conf`) serves the build
and proxies `/api` unchanged; it is the only service with a host port
(`WEB_PORT`, default 8080) and has a fixed address on the `edge` network,
which is what `RATE_LIMIT_TRUSTED_PROXIES` trusts.

CSV export (`app/application/exports.py`, `app/infrastructure/worker.py`,
`worker_main.py`, `export_files.py`, `app/api/routes/exports.py`):
`POST /api/v1/exports` commits the row, then publishes its ID (503 +
`queue_unavailable` if the broker is down). The worker locks the row and is
idempotent. PostgreSQL is the source of truth: Celery beat runs
`exports.maintain` every minute on the `maintenance` queue (republish
exports pending 2 min since their last dispatch, fail them after 30 min,
delete files of expired/failed/missing exports and stale temp files).
Broker: Redis database 1 (`CELERY_BROKER_URL`), AOF on. Files live in the
`exports` volume at `/data/exports` (`EXPORT_DIR`, `EXPORT_TTL_HOURS`).
Tests that build their own app pass `export_queue=FakeExportQueue()`.

Rate limiting (`app/infrastructure/rate_limiter.py`, `app/api/rate_limits.py`)
uses the `limits` library directly (slowapi was dropped with the author's
approval: integrating its decorator/middleware model with per-app settings
built in `create_app` was awkward; slowapi does support callable limits and
`exempt`, so this is a preference, not a hard limitation). Limits must be a
single positive expression such as `5/minute`. In-memory counting is
serialized with a lock (limits' MemoryStorage is not safe under threads). Login: `RATE_LIMIT_LOGIN` per client IP; everything under
`/api/v1`: `RATE_LIMIT_API` per user (IP for missing/invalid tokens). Counters
in Redis, falling back to process memory for 30 s when Redis fails. The client
IP comes from X-Forwarded-For only for `RATE_LIMIT_TRUSTED_PROXIES`.

Demo data: `migrate` runs `python -m app.infrastructure.seed` after the
migrations, with `SEED_DEMO_DATA=true` (the seed refuses to run without it).
It is idempotent and serialized by an advisory lock, recreates missing demo
tasks, stops if a demo user was deactivated or its password changed (fix with
`--reset-demo-users`), and `--bulk N` adds N random tasks for measurements. Demo users `ana@`, `bruno@`, `carla@example.com`, password
`demo-password-2026` (public on purpose, local use only).

API layout: `app/api/app.py` (`create_app` reads and validates settings at
startup and keeps the session factory, token service and hasher on
`app.state`; tests pass `auth=`, `session_factory=` and `redis=` instead of
overriding dependencies), `dependencies.py` (one transaction per request, closed with
`scope="function"` before the response is sent),
`errors.py` (business errors → `{"detail", "code"}`, 401 adds
`WWW-Authenticate: Bearer`), `routes/`. Swagger at `/api/docs`.
Unit tests use the in-memory fakes in `backend/tests/fakes.py`. The author authorized running
pytest, coverage and frontend tests while implementing this repository.
Keep code, comments and repository documents in English. Do not add libraries
outside the approved stack without consulting the author.

## Architecture

- `backend/app/domain`: pure rules and entities.
- `backend/app/application`: use cases and repository interfaces.
- `backend/app/infrastructure`: SQLAlchemy, JWT, hashing and queue adapters.
- `backend/app/api`: HTTP validation, authentication and response mapping.
- Dependencies point inward; wire concrete implementations at startup.
- Domain/application cannot import FastAPI, SQLAlchemy, Celery or infrastructure.
  Domain cannot import application/API; application cannot import API.
- Use synchronous SQLAlchemy 2 sessions, Pydantic v2 and timezone-aware UTC.
- All backend public endpoints belong under `/api`; nginx preserves that prefix.
- Frontend uses React/TypeScript, Vite, TanStack Query and React Router.
  Generate client types from OpenAPI when the API exists.

## Local setup and quality commands

Run from the repository root with Python 3.12, uv, pre-commit, Node 24.14.1
and npm 11 installed. Keep tool writes inside the repository:

```sh
export PATH="$HOME/.local/bin:$PATH"
export UV_CACHE_DIR="$PWD/.cache/uv"
export PRE_COMMIT_HOME="$PWD/.cache/pre-commit"
export npm_config_cache="$PWD/.cache/npm"
export XDG_CACHE_HOME="$PWD/.cache"
export TMPDIR="$PWD/.tmp"
export UV_PYTHON_DOWNLOADS=never
mkdir -p "$TMPDIR"
uv sync --project backend --locked
npm --prefix frontend ci
pre-commit install
pre-commit run --all-files
(cd backend && uv run --locked mypy)
(cd backend && uv run --locked lint-imports)
npm --prefix frontend run lint
```

Commit both lockfiles. Ruff handles lint and formatting; mypy is strict.
import-linter checks the architecture; ESLint checks frontend code and config.
Secret detection and basic file hygiene must pass. TypeScript is strict
(`npm --prefix frontend run typecheck`).

## Later implementation and tests

Use TDD for critical authorization and validation rules when that work is in
scope. Backend coverage must reach at least 80%; meaningful integration tests
use PostgreSQL and Redis. PostgreSQL has no host port, so the full suite runs
in Docker against a separate `<POSTGRES_DB>_test` database that is dropped and
rebuilt each run (`tests/support/database.py` refuses any name that is not a
plain identifier ending in `_test` within 63 bytes); on the host, integration
tests are skipped:

```sh
docker compose run --rm --build backend-tests            # full suite + coverage
cd backend && uv run --locked pytest                     # unit tests only
```

Migrations: `docker compose run --rm migrate` applies them. Write each revision
by hand under `backend/migrations/versions/`, wrapping full constraint names in
`op.f()`. `test_migrations.py` compares tables, columns, types, indexes and
server defaults with the models; Alembic does not compare CHECK constraints,
so `test_schema_constraints.py` checks their names and behavior.
CI (`.github/workflows/ci.yml`, on push to `main`, pull requests and manual
runs) has four jobs: `quality` runs `pre-commit run --all-files`, which includes ESLint and
`tsc` (so CI and
local hooks are the same checks); `backend-tests` runs the full suite on the
runner with PostgreSQL and Redis as `services` (same image versions as
Compose, `TEST_POSTGRES_DB` set so integration tests run, coverage under 80%
fails); `docker-build` builds the `runtime` and `test` images. Actions are
pinned by commit SHA and checkout does not keep the token. `frontend` regenerates the API types and fails on
a diff, then runs `tsc`, Vitest and the production build; `docker-build`
also builds the frontend image.

Do not claim tests passed, coverage, performance or platform compatibility
without executing the corresponding checks and recording real results.

## Security, runtime and evidence

Never commit secrets or use default JWT secrets. `.env.example` contains blank
secret fields. Later setup must generate a local secret, and Compose/application
startup must reject missing secrets. Demo credentials will be public and local.
Do not expose PostgreSQL or Redis host ports. Use Docker Engine within WSL;
use `sg docker -c "docker ..."` if needed, never Docker Desktop.
Compose runs `db` (PostgreSQL 16.15) and `redis` (Redis 7.4.11) with
healthchecks and a named volume for data, plus `migrate` (one-shot Alembic
and demo seed),
`api` (uvicorn factory on port 8000, reachable only through nginx;
healthcheck on `/api/health`), `web` (nginx, port 8080), `worker` (Celery, queues `maintenance,celery`), `beat`
(exactly one) and `backend-tests` (profile `test`). The backend Dockerfile has `runtime` and
`test` targets and runs as a non-root user. The frontend Dockerfile builds with Node
24.14.1 and serves with nginx 1.30.1.

```sh
./scripts/setup-env.sh              # once: creates .env with random secrets
docker compose up -d --wait         # start db and redis, wait until healthy
docker compose down                 # stop, keep data
docker compose down -v              # stop and delete the database volume
```

Record each AI session and actual corrections in `docs/ai-log.md`; record the
exact tool/model only when verified. Save prompts, generated samples, review
findings and actual validation under `docs/genai/`. Attribute proposals honestly.
Do not invent tests, results, human review, decisions or application evidence.
