# Architecture

## Layers

```text
            ┌──────────────────────────────────────────────┐
            │ api            FastAPI routes, schemas,      │
            │                error mapping, rate limits    │
            │   ┌──────────────────────────────────────┐   │
            │   │ application  use cases + ports       │   │
            │   │   ┌──────────────────────────────┐   │   │
            │   │   │ domain  entities, rules,     │   │   │
            │   │   │         permissions, errors  │   │   │
            │   │   └──────────────────────────────┘   │   │
            │   └──────────────────────────────────────┘   │
            └──────────────────────────────────────────────┘
 infrastructure: SQLAlchemy, Alembic, JWT, Argon2, Redis, Celery, CSV files
 (implements the ports; wired in create_app and worker_main)
```

- **Domain** (`app/domain`) is plain Python: dataclasses for `Task`, `User`
  and `Export`, their invariants (a title is required, timestamps must be
  timezone-aware and are stored in UTC, `completed_at` follows the status),
  the permission rules and the error types. Every mutator validates before it
  changes anything, so a rejected call leaves the entity untouched.
- **Application** (`app/application`) holds the use cases (`TaskService`,
  `AuthService`, `ExportService`) and the ports they need: repositories, a
  password hasher, a token service, an export queue, an export file store and
  a clock. The use cases own the business flow; they never see HTTP, SQL or
  Celery.
- **Infrastructure** (`app/infrastructure`) implements the ports.
  Repositories flush but never commit and always return domain objects,
  never ORM rows, so the caller cannot change the database by accident.
- **API** (`app/api`) translates HTTP to use-case calls and back: Pydantic
  schemas, authentication dependency, error mapping to
  `{"detail", "code"}`, rate-limit dependencies.

import-linter checks three contracts on every commit and in CI: domain and
application may not import FastAPI, SQLAlchemy, Celery or infrastructure;
domain may not import application or API; application may not import API.

### Composition

`create_app()` in `app/api/app.py` is the composition root for the API. It
reads and validates every setting at startup, creates the engine, Redis
client, Celery client, token service and Argon2 hasher, and stores them on
`app.state`. Tests call `create_app()` with their own session factory,
Redis client and fake queue instead of overriding dependencies, so the real
wiring is what gets tested. The worker has its own composition root in
`app/infrastructure/worker_main.py`.

### Request lifecycle

1. nginx receives the request and forwards `/api/...` unchanged, replacing
   `X-Forwarded-For` with the peer address.
2. The rate-limit dependency counts the request (per IP for login, per user
   for the rest) in Redis.
3. The auth dependency decodes the JWT (HS256 only, `exp` and `sub`
   required) and loads the user; an inactive user is rejected.
4. A session is opened for the request; the use case runs; the transaction
   is committed **before** the response is sent (`scope="function"`), so a
   failed commit becomes a 500 instead of a 200 for data that was not saved.
5. Domain errors become JSON with a stable `code` (`task_not_found`,
   `forbidden_field`, `rate_limited`, ...).

## Data model

```text
users                          tasks                               exports
─────                          ─────                               ───────
id          PK                 id           PK                     id             PK
email       unique, lowercase  title        ≤ 200                  requester_id   FK users (cascade)
name                           description  ≤ 2000                 status         pending|completed|failed
password_hash (Argon2)         status       pending|in_progress|   task_status    filter
is_active                                   completed              due_from       filter
created_at                     creator_id   FK users (restrict)    due_to         filter
                               assignee_id  FK users (set null)    row_count, error_code
                               due_date                            created_at, dispatched_at,
                               completed_at                        finished_at, expires_at
                               created_at, updated_at
```

- CHECK constraints: valid task and export statuses; lowercase email;
  `completed_at` set exactly when a task is completed; export fields
  consistent with the export status.
- Indexes: `tasks(creator_id)`, `tasks(assignee_id)` for visibility,
  `tasks(status, due_date)` for filtered listings, plus one partial index on
  pending exports for the maintenance task.
- Migrations are written by hand; a test compares tables, columns, types,
  indexes and server defaults with the models, and another checks the CHECK
  constraints by inserting rows that must be rejected.

## Background export

```text
POST /api/v1/exports ──► insert export (pending), COMMIT ──► publish id to Redis (db 1)
                                                               │
                        worker: lock row FOR UPDATE ◄──────────┘
                                skip if not pending (idempotent)
                                stream visible tasks (500 per batch)
                                write CSV to temp file, os.replace ──► exports volume
                                mark completed (row_count, expires_at)

beat, every minute (maintenance queue):
  republish exports pending > 2 min since last dispatch
  fail exports pending > 30 min (export_timed_out)
  delete files of expired or failed exports, and stale temp files

GET /api/v1/exports/{id}            status (requester only)
GET /api/v1/exports/{id}/download   409 pending/failed · 410 expired or missing · CSV
```

- The row is committed before publishing, so a job never points to a row
  that does not exist. If publishing fails, the export is marked failed and
  the API returns 503 `queue_unavailable`.
- The worker applies the same visibility rules as the listing, at the time
  it runs.
- CSV cells starting with `=`, `+`, `-`, `@`, tab or carriage return are
  prefixed with `'` to prevent formula injection in spreadsheets; the file is
  UTF-8 with BOM so Excel reads accents correctly.
- `acks_late` plus the idempotent worker make redelivery safe.

## Rate limiting

`limits` with a Redis fixed-window counter (database 0). If Redis fails, the
limiter switches to its own in-memory counter for 30 seconds, then one
request probes Redis again. State changes carry a generation number so a
slow request cannot overwrite a newer state. Health and docs are not
limited. The API trusts `X-Forwarded-For` only from nginx's fixed address
on the `edge` network.

## Frontend

```text
src/
  api/          http.ts (fetch + error translation), endpoints.ts (typed calls),
                generated/schema.ts (from openapi.json)
  features/
    auth/       AuthProvider (token state, 401 → login), LoginPage, RequireAuth
    tasks/      TasksPage, TaskCard, TaskFormDialog, FilterBar, filter/URL hooks
    exports/    ExportPanel (request, poll, authenticated download)
  components/   Modal, ConfirmDialog, Field, Pagination
```

- Server state lives in TanStack Query; every change invalidates the task
  lists, so pages and totals always match the server. UI state (open dialog)
  is local; filters and page are in the URL.
- The UI hides actions the backend would refuse, but the backend decides.
- Only the changed fields are sent in a PATCH.
- nginx serves the build with a Content-Security-Policy and long-lived
  caching for hashed assets; client routes fall back to `index.html`.

## Deployment (local)

Compose has two networks. `default` connects everything except nginx;
`edge` (`172.31.240.0/28`) connects only nginx and the API, and gives nginx a
fixed address the API can trust. Only nginx publishes a host port.
PostgreSQL, Redis (AOF) and the export files use named volumes. `migrate`
runs once before the API, worker and beat start.
