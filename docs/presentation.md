# Presentation guide

A 15-20 minute walkthrough for the panel, then the code review. Screen:
the repository on GitHub, the IDE, and the app at <http://localhost:8080>.

Before the call: `docker compose up -d --build --wait`, log in once as Ana,
open Swagger in a second tab, have the CI page open.

The login limit (5 per minute per IP) counts every attempt, successful or
not. Switching users and authorizing Swagger already use several, so show
the 429 last, or wait a minute after it.

## 1. User story (1 min)

*As a member of a small team, I want to create tasks, assign them to
teammates and see what is due, so that nothing falls through the cracks.
When I need the list outside the app, I want to export it.*

Two roles per task: the creator (full control) and the assignee (may change
the status). Each user sees only tasks they are part of.

## 2. Demo (5 min)

1. Log in as **Ana**. Point out: overdue tasks in red, badges, "Created by" /
   "Assignee", three pages.
2. Filter: status *In progress*, then a due range. The URL changes (reload
   keeps it).
3. **Export CSV** with the filter on: the job goes to the Celery worker, the
   page polls, **Download**. Open the file.
4. **New task**, assign it to Bruno, due next week. Edit it. Complete it.
5. Log out, log in as **Bruno**: the task is there, but only the status can
   change (no Edit/Delete). Show the 403 in Swagger if he tries a PATCH of
   the title.
6. Delete a task as its creator (confirmation dialog).
7. Resize to phone width (or DevTools): same features, no horizontal scroll.
8. Swagger: **Authorize** with Ana's email and password, run
   `GET /api/v1/tasks`.
9. `docker compose stop redis`, reload: tasks still work, `/api/health`
   says `degraded`. Start it again.
10. Last: repeated wrong logins → 429 with `Retry-After` (the limit counts
    every login attempt in the minute, including the ones above).

## 3. Architecture (4 min)

- Diagram in the [README](../README.md#architecture): nginx → FastAPI →
  PostgreSQL / Redis ← Celery.
- Open `backend/app`: domain → application → infrastructure → api. Show the
  import-linter contracts in `pyproject.toml`; they run in pre-commit and
  CI.
- Walk one request: `routes/tasks.py` `update_task` → `TaskService.update`
  (`application/tasks.py`) → `ensure_can_update` (`domain/permissions.py`)
  → `SqlTaskRepository` (`infrastructure/repositories.py`). Transaction
  committed before the response (`api/dependencies.py`).
- `create_app()` as the composition root: settings validated at startup,
  adapters injected; tests pass their own.
- Export flow: row committed, then queued; idempotent worker; beat
  reconciles lost jobs.
- Frontend: features folder, typed client generated from OpenAPI, TanStack
  Query, filters in the URL.

## 4. Testing (3 min)

- 393 backend tests, 98.5% coverage, run against real PostgreSQL and Redis;
  27 frontend tests. CI: four jobs, all green.
- TDD: show a red/green pair in the history, for example
  `git show 204ef03 9ec17fc --stat` (task entity).
- Show one integration test and one frontend flow test
  (`frontend/tests/app.test.tsx`, "a 401 for an old session...").

## 5. GenAI (4 min)

- Workflow: approved plan → Claude Code implements one step → Codex
  (another vendor's model, read-only) reviews → failing test → fix →
  re-review until no new defects.
- [The prompt I would use](genai/prompts.md#1-the-prompt-i-would-use-for-the-full-implementation):
  constraints, test-first, evidence, checkpoints, failure modes.
- Two concrete corrections ([generated-sample.md](genai/generated-sample.md)):
  the test database guard (could drop a real database) and the frontend
  session race.
- Critical thinking examples: AI tests that passed without the fix (caught
  by reverting the fix), an overstated justification for a library change,
  performance measured with `EXPLAIN ANALYZE` instead of assumed.

## 6. Limitations and next steps (1 min)

Token in sessionStorage (HttpOnly cookie + CSRF for production), no refresh
tokens, offset pagination (keyset next), reconciler instead of outbox,
per-process memory fallback in the rate limiter, local deployment only.

## Likely questions

- **Why sync SQLAlchemy?** Short queries, thread pool in FastAPI, one
  repository for API and worker; async only with a measured need.
- **Why 404 instead of 403 for other users' tasks?** Not revealing that an
  ID exists.
- **Why not SQLite for tests?** The code uses PostgreSQL features SQLite
  lacks or handles differently: `FOR UPDATE SKIP LOCKED`, advisory locks,
  statement and lock timeouts, strict column types. Tests should run on
  what production runs.
- **What if Redis is down?** CRUD works, rate limiting counts in memory for
  30 s at a time, exports return 503, health reports `degraded`.
- **How do you know a job is not lost?** PostgreSQL row first; the beat
  task republishes pending jobs after 2 minutes and fails them after 30.
- **How do you trust `X-Forwarded-For`?** Only from nginx's fixed address on
  the `edge` network; nginx overwrites the header.
- **What did the AI get wrong?** See the review table; the most serious was
  the test database guard.
- **Did you just accept what the AI wrote?** No: tests first, a second
  model's review, each fix proven by a failing test, live checks, and the
  log records where the AI was wrong, including in its explanations.
