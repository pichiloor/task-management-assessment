# Project conventions

## Scope and language

Steps 1 (tooling), 2 (PostgreSQL and Redis in Compose) and 3 (domain rules and
use cases, TDD) are done. Next: SQLAlchemy models and Alembic migrations.
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
Secret detection and basic file hygiene must pass. TypeScript is strict;
its compiler check will be connected when source files exist.

## Later implementation and tests

Use TDD for critical authorization and validation rules when that work is in
scope. Backend coverage must reach at least 80%; meaningful integration tests
use PostgreSQL and Redis. Command:
`cd backend && uv run --locked pytest --cov=app --cov-report=term-missing`.
Do not claim tests passed, coverage, performance or platform compatibility
without executing the corresponding checks and recording real results.

## Security, runtime and evidence

Never commit secrets or use default JWT secrets. `.env.example` contains blank
secret fields. Later setup must generate a local secret, and Compose/application
startup must reject missing secrets. Demo credentials will be public and local.
Do not expose PostgreSQL or Redis host ports. Use Docker Engine within WSL;
use `sg docker -c "docker ..."` if needed, never Docker Desktop.
Compose runs `db` (PostgreSQL 16.15) and `redis` (Redis 7.4.11) with
healthchecks and a named volume for data. Backend/frontend Dockerfiles, nginx
and application CI are still placeholders.

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
