# Decisions

Each entry: what was decided, the alternatives, and why. "Author" is the
person submitting this exercise; AI proposals are attributed in
[ai-log.md](ai-log.md).

## Backend

**FastAPI + Pydantic v2.** Chosen over Django REST Framework and Flask: typed
request/response models, OpenAPI and Swagger generated from the code (which
the frontend's types are generated from in turn), and dependency injection
that fits a composition root.

**Synchronous SQLAlchemy 2.** Async SQLAlchemy was considered. The endpoints
are short queries; FastAPI runs sync endpoints in a thread pool, and the
Celery worker is synchronous anyway. Sync keeps one repository
implementation for both. Revisit only with a measured need.

**Clean Architecture with enforced contracts.** Four packages (domain,
application, infrastructure, api) and import-linter contracts in pre-commit
and CI. The alternative, a conventional FastAPI layout (routers calling ORM
models), is shorter but couples business rules to the web and database
frameworks, which is exactly what the panel evaluates.

**Repositories return detached domain objects and never commit.** The
request (or the worker job) owns the transaction. A use case that fails
halfway leaves nothing saved; a test checks that a PATCH failing after a
valid change persists nothing.

**Permissions as domain functions, 404 for invisible tasks.** Returning 403
for a task the user cannot see would reveal that it exists. Single-task
operations go through these functions; lists are filtered by one SQL
visibility predicate (`_conditions` in `repositories.py`) that the task
listing and the CSV export share, so the file never contains a task the user
cannot see in the list.

**PATCH applies only the fields sent.** `model_fields_set` distinguishes
"omitted" from "null"; `assignee_id` and `due_date` accept null to clear,
the other fields reject it. PUT was not implemented: partial updates are what
the UI needs, and the assignee may only change the status.

**Offset pagination with `total` and `pages`.** Simple for a UI with page
numbers. Keyset pagination was considered; measured cost at 20,000 tasks is
2 ms for page 1 and 6 ms for page 500, so it was not needed (see
[genai/validation.md](genai/validation.md#performance)).

**Invariants in the database as well.** CHECK constraints and a lowercase
email constraint duplicate domain rules on purpose: a bug or a manual SQL
change cannot store an inconsistent row.

**Hand-written Alembic migrations with a drift test.** Autogenerate misses
CHECK constraints and some defaults; a test compares the migrated schema with
the models, and another tests the constraints by behavior.

## Authentication

**JWT HS256 with PyJWT, Argon2 with argon2-cffi.** Only HS256 is accepted
when decoding (rules out `alg: none` and algorithm confusion); `exp` and
`sub` are required; the secret must be at least 32 characters and the app
refuses to start without it. Login failures give one message for unknown
email, wrong password and inactive user, and an unknown email still runs one
hash verification to reduce the timing difference.

**No refresh tokens or revocation list.** Out of scope for the exercise;
tokens last 60 minutes and stop working when the user is deactivated.

## Rate limiting

**`limits` directly instead of slowapi.** Author's decision. slowapi wraps
`limits`; its decorator and middleware model was awkward to combine with
settings built per app in `create_app`. slowapi does support callable limits
and exemptions, so this is a preference, not a limitation (the first
justification given by the AI overstated it; see the AI log).

**Redis counters with a 30-second in-memory fallback.** Failing open would
disable protection during a Redis outage; failing closed would take the API
down with Redis. The fallback keeps both working, at the cost of per-process
counting during the outage.

**Per user after login, per IP before.** Requests with a missing or invalid
token are keyed by IP, so junk tokens do not get fresh counters.

## Background processing

**Celery + Redis, with PostgreSQL as the source of truth.** The export row is
committed before the job is published. Jobs can be lost (Redis restart,
publish failure, worker crash); a beat task reconciles every minute. A
transactional outbox would be the stronger design; the reconciler gives the
same end result with less machinery, at the cost of a 2 to 3 minute delay for
a lost job.

**Files on a shared volume, downloaded through the API.** The API checks the
requester before streaming the file; there is no public URL to guess.

## Frontend

**React + TypeScript + Vite, TanStack Query, React Router.** Query handles
caching, polling and invalidation, so there is no global store; filters live
in the URL.

**Types generated from OpenAPI (`openapi-typescript`).** No hand-written API
types to drift. CI regenerates them and fails on a diff.

**Plain CSS with custom properties.** No UI library: the app is small, and a
component library would add weight and styling to override. Light and dark
mode follow the system setting.

**Token in `sessionStorage`.** Survives a reload but not closing the tab, and
is not sent automatically, so there is no CSRF surface. The trade-off is
exposure to XSS, reduced by a strict Content-Security-Policy. HttpOnly
cookies with CSRF tokens are the production alternative.

**Same origin through nginx.** No CORS configuration to get wrong, and the
browser never talks to the API container directly.

## Tooling

**uv, Ruff, mypy strict, import-linter, pre-commit, detect-secrets.** CI runs
`pre-commit run --all-files`, so local hooks and CI are the same checks.
Docker images and GitHub Actions are pinned (actions by commit SHA).

**Tests against real PostgreSQL and Redis.** SQLite would hide PostgreSQL
behavior (CHECK constraints, `FOR UPDATE SKIP LOCKED`, advisory locks,
`NULLS LAST`). The test database is dropped and rebuilt on each run and must
be named exactly `<POSTGRES_DB>_test`, so the real database cannot be
dropped by mistake.
