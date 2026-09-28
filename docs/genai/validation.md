# Validation

How AI-generated code was checked before it was accepted. Every result
below was produced by running the command; the dated details are in the
[AI log](../ai-log.md).

## Layers of validation

| Check | What it catches | When |
| --- | --- | --- |
| Tests written first | Code that does not do what was asked | Every step from 3 on. Red run executed and committed separately for domain, use cases, auth, endpoints, seed and rate limiting; for repositories and the export worker the tests were written first but committed with the code, and for repositories no separate red run was executed |
| "Fails without the fix" | Tests that pass for the wrong reason | Every review fix: the fix is reverted or the test run before it |
| mypy strict, Ruff, ESLint, `tsc` (TypeScript strict) | Type errors, dead code, unsafe patterns | Every commit (pre-commit) and CI |
| import-linter | Layer violations (e.g. a use case importing SQLAlchemy) | Every commit and CI |
| Integration tests on real PostgreSQL and Redis | Behavior SQLite or mocks would not reproduce: row and advisory locks, timeouts, PostgreSQL types, Redis failover, a real Celery worker | Docker and CI |
| Review by a second model | Design flaws, races, security issues the first model did not see | After every change, repeated until "no new defects" |
| Live checks on the running stack | Wiring, configuration, real failure modes | Every step |
| Real browser | Layout, accessibility, console errors | Frontend |

## Tests that passed for the wrong reason

Running each new test against the code *without* the fix caught several
AI-written tests that proved nothing:

- A race test for the rate limiter paused after the key was removed, not
  between the expiry check and the removal, so it passed without the lock.
  Rewritten until it failed 3 out of 3 runs without the fix and passed 3 out
  of 3 with it.
- A probe-revalidation test's fake clock never reached the probe; it passed
  without the fix.
- The first seed date test passed even if `today` was ignored; it now pins
  exact offsets for three different dates.
- A scripted edit to a test silently did not apply (Ruff had reformatted the
  file), and the suite passed with the old test. Since then every scripted
  edit asserts that the text it replaces exists.

## Edge cases, authentication and validation

What was designed and tested explicitly, beyond the happy path:

- **Authentication.** Only HS256 accepted (no `alg: none`, no algorithm
  confusion); `exp` and `sub` required; `sub` limited to 10 digits and the
  PostgreSQL integer range (a 4301-digit subject made `int()` raise); an
  inactive user's token stops working; one error for unknown email, wrong
  password and inactive user; the secret must be 32+ characters and is never
  echoed in error messages; the app does not start without it.
- **Authorization.** Visibility and field-level permissions per role, 404
  for invisible tasks, requester-only exports; tested for creator, assignee
  and outsider on every operation.
- **Input validation.** Title required and trimmed, length limits in
  Pydantic, the domain and the database; PATCH distinguishes omitted from
  null; `due_date` cannot be combined with `due_from`/`due_to`; an inverted
  range is rejected (and the frontend does not send it); `page_size` ≤ 100;
  unknown fields rejected (`extra="forbid"`).
- **Consistency.** Every domain mutator validates before changing anything;
  a PATCH that fails after a valid change persists nothing; the database
  rejects inconsistent rows (tested by inserting them).
- **Failure modes.** Redis down (CRUD works, health `degraded`, rate limit in
  memory, export 503), PostgreSQL down or slow (timeouts, 503), a failed
  commit (500, not 200), a lost Celery job (republished), a worker crash
  (`acks_late`, idempotent worker), a client disconnecting during a
  download (file closed), concurrent seed runs (advisory lock), a recreated
  API container (nginx re-resolves it).
- **Frontend.** Rejected token → login; a late 401 from an old session is
  ignored; a save finishing after its dialog closed is ignored; a failed
  status poll does not stop the export; focus stays inside dialogs.

## Performance

Measured, not assumed. A separate database was loaded with 20,026 tasks
(the demo plus `seed --bulk 20000`), 9,921 of them visible to one user, and
the listing queries were run with `EXPLAIN ANALYZE` on PostgreSQL 16.15:

| Query | Plan | Execution time |
| --- | --- | --- |
| Page 1, no filters | Seq scan + top-N heapsort | 2.08 ms |
| `count(*)` for the same filter | Seq scan | 2.09 ms |
| Page 1, `status=pending` and a 30-day due range | Index scan on `ix_tasks_status_due_date` + incremental sort | 0.09 ms |
| Page 500 (`OFFSET 9980`) | Seq scan + full sort | 6.00 ms |

Reading of the results: with three users, one user sees half the table, so
a sequential scan is the right plan and the per-user indexes are not used;
with many users those indexes would be selected. Filtered queries use the
composite index. Deep offsets grow linearly; keyset pagination would fix
that and is documented as a limitation rather than implemented.

Other performance decisions checked in review: the Argon2 dummy hash (for
timing equalization) was being computed on every request, about 64 MiB of
work each, and is now computed once at startup; exports stream rows from a
server-side cursor in batches of 500 instead of loading them; export cleanup
queries use batches of 1000 IDs to stay under the PostgreSQL protocol's
65,535-parameter limit.

## Idiomatic quality

- mypy `--strict` over the application code (`backend/app`; tests,
  migrations and scripts are not type-checked), TypeScript `strict` over the
  frontend, zero ESLint warnings allowed.
- SQLAlchemy 2 style (`select()`, `Mapped[]`), Pydantic v2 models, FastAPI
  dependencies with `Annotated`; no deprecated APIs (the backend suite runs
  with `-W error::DeprecationWarning`).
- React hooks lint rules enforced (one AI fix was rejected by them and
  redone); server state in TanStack Query, not in hand-written effects.
- Reviewed for readability: names over comments, comments only where the
  reason is not obvious (why, not what).

## Latest results

| Check | Result |
| --- | --- |
| Backend suite in Docker (`pytest --cov=app -W error::DeprecationWarning`) | 393 passed, 98.51% line and branch coverage |
| Frontend (`vitest run`) | 27 passed |
| `tsc --noEmit`, ESLint | Clean |
| pre-commit, all hooks | Passed |
| Full stack through nginx | Login, CRUD, filters, export and download, health, Swagger, security headers |
| Rate limit behind nginx | 6th login in a minute → 429; keyed by the real client address; a forged `X-Forwarded-For` has no effect |
| Chromium (Playwright), 1280 px and 390 px | Whole flow works; no console errors; no horizontal scroll |

## Step 1 scaffold (Codex)

Recorded at the time (2026-09-26): `uv sync --locked` and `npm ci`
succeeded; `pre-commit run --all-files` passed all 14 hooks; npm reported
zero vulnerabilities. These validated configuration only; no application
code existed yet.
