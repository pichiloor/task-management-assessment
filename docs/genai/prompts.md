# Prompts

The exercise asks for "the prompt you would use to generate the API scaffold
or full implementation". Section 1 is that prompt, written after doing the
work, so it includes what turned out to matter. Section 2 shows the prompts
that were actually used, verbatim, and section 3 explains the choices.

## 1. The prompt I would use for the full implementation

Tool: Claude Code (agentic, runs commands in the repository). The prompt is
meant to be sent once, with the agent stopping at each checkpoint for the
author's approval.

````text
You are implementing a take-home exercise that will be reviewed line by line
by senior engineers. Correctness and evidence matter more than speed.

## Product
A task manager. Users log in with email and password. A user sees the tasks
they created or are assigned to. A task has title (1-200 chars), description
(≤2000), status (pending | in_progress | completed), optional assignee and
optional due date. The creator edits every field and deletes; the assignee
may only change the status. `completed_at` is set when a task becomes
completed and cleared when it is reopened. Tasks the user cannot see return
404, never 403.

## Stack (do not add libraries without asking me)
Backend: Python 3.12, FastAPI, Pydantic v2, synchronous SQLAlchemy 2,
Alembic, PostgreSQL 16, PyJWT (HS256) + argon2-cffi, Redis, Celery, uv.
Frontend: React + TypeScript (strict) + Vite, TanStack Query, React Router,
types generated from the backend's OpenAPI with openapi-typescript.
Quality: Ruff, mypy --strict, import-linter, ESLint, pre-commit,
detect-secrets. Tests: pytest + pytest-cov (≥80%, branch coverage), Vitest +
Testing Library. Everything runs with docker compose; pin every image and
dependency version.

## Architecture (enforced, not suggested)
backend/app/{domain,application,infrastructure,api}. Domain: dataclasses,
invariants, permission functions, error types, no framework imports.
Application: use cases and ports (Protocols) for repositories, hasher, token
service, queue, clock. Infrastructure implements the ports. API maps HTTP to
use cases. Add import-linter contracts that fail if domain/application import
FastAPI, SQLAlchemy, Celery or infrastructure. One composition root,
`create_app(...)`, that validates settings at startup and accepts test
doubles as arguments. One transaction per request, committed before the
response is sent. Repositories flush, never commit, and return domain
objects.

## API
/api/v1/auth/token (OAuth2 password form), /api/v1/users/me, /api/v1/users
(id and name only), /api/v1/tasks CRUD with PATCH applying only the fields
sent (null clears assignee_id and due_date, and is rejected elsewhere),
listing filters status, due_date, due_from/due_to, pagination page/page_size
(≤100) returning items/total/page/page_size/pages, ordered by due date
(nulls last) then id. /api/health checks PostgreSQL and Redis. Errors are
{"detail", "code"}. Swagger at /api/docs.

## Cross-cutting
- Rate limiting: login 5/min per IP, API 120/min per user; Redis-backed;
  decide and document what happens when Redis is down. Trust
  X-Forwarded-For only from the reverse proxy.
- CSV export as a Celery job: commit the row before publishing; the worker
  must be idempotent; lost jobs must be recovered; files expire; only the
  requester can download; guard against CSV formula injection.
- Demo seed: 3 users with a published demo password, tasks covering every
  status, overdue/today/future/none, cross-assigned, enough for 2+ pages;
  idempotent and safe to run concurrently.
- Frontend: login, list with filters in the URL, pagination, create/edit
  dialog, delete with confirmation, complete, export with polling and an
  authenticated download. Responsive (390 px and 1280 px), keyboard
  accessible, no console errors. nginx serves it and proxies /api unchanged.
- Security: no secrets in the repo; a script generates .env; the app refuses
  to start with a missing or short JWT secret; accept only HS256.

## How to work
1. Before any code, write a numbered plan with checkpoints and wait for my
   approval. Work one checkpoint at a time; stop after each one.
2. Test first. Commit the failing tests, show me the red run, then
   implement. For every bug fix, write a test that fails without the fix and
   show that it does.
3. Integration tests run against real PostgreSQL and Redis in Docker, never
   SQLite. The test fixture drops and recreates its database: make it
   impossible to point at a non-test database.
4. After each checkpoint run: ruff, mypy --strict, lint-imports, the full
   test suite with coverage, and a live check over HTTP against the running
   stack. Report the actual command output. Never claim a result you did not
   run.
5. Think about failure: Redis down, PostgreSQL slow, a job lost, a commit
   that fails, concurrent requests, a client that disconnects. Test the ones
   that matter.
6. Keep a log in docs/ai-log.md: what you generated, what was wrong, what was
   corrected, with commit hashes.
7. Do not push, and do not add dependencies, without asking.
````

## 2. Prompts actually used

The work followed a 16-step plan written in a planning conversation with
Claude and approved by the author before any code (the plan itself is not
part of this repository). After that, implementation prompts were short
instructions in Spanish, because the plan and the repository's `CLAUDE.md`
carried the detail.

### Step 1, sent to Codex (verbatim)

The only step implemented by Codex: environment, repository and quality
tooling, with no application logic.

```text
Tarea: ejecutar SOLO el paso 1 (entorno, repositorio y herramientas de calidad) de una prueba técnica. No implementes lógica de la aplicación; eso viene en pasos posteriores.

Contexto: el plan completo y aprobado está en /home/pichiloor/plan-prueba-tecnica-bla.md. Lee al menos las secciones 3 (Preparación del entorno), 4 (Stack), 5 (Arquitectura), 12 (Evidencia GenAI) y 13 (Estructura del repositorio) antes de empezar, y respeta lo que dicen.

Decisiones ya tomadas por el usuario:
- Nombre del repo: task-management-assessment, PÚBLICO, en la cuenta de GitHub pichiloor (gh CLI ya autenticado). Directorio local: /home/pichiloor/task-management-assessment
- Identidad de git: usar el correo noreply de GitHub de la cuenta (obtén el ID con `gh api user --jq .id` y arma `<id>+pichiloor@users.noreply.github.com`). Configúralo SOLO a nivel del repo (git config local), no global. Nombre: el que devuelva `gh api user --jq .name` (o pichiloor si viene vacío).
- Herramientas ya instaladas: uv 0.12.19 y pre-commit en ~/.local/bin, Python 3.12, Node v24. Docker está en WSL; si tu shell no tiene acceso al socket usa `sg docker -c "..."`. No uses Docker Desktop.

Qué debe quedar hecho:
1. Repo creado en GitHub (público) y enlazado en el directorio local, rama main.
2. Esqueleto de carpetas según la sección 13 del plan (backend/, frontend/, docs/, etc.), con archivos mínimos (__init__.py, .gitkeep) donde haga falta para que la estructura exista. Sin código de negocio.
3. backend/pyproject.toml gestionado con uv (Python 3.12), dependencias del stack del plan y grupo dev (pytest, pytest-cov, ruff, mypy, import-linter, etc.). Genera uv.lock. Configuración de Ruff, mypy y los contratos de import-linter que describe la arquitectura del plan.
4. .pre-commit-config.yaml con Ruff (lint + format), mypy y chequeos básicos (trailing whitespace, end-of-file, detección de secretos/archivos grandes). Instala los hooks (`pre-commit install`) y verifica que `pre-commit run --all-files` pase.
5. .gitignore y .editorconfig adecuados (Python, Node, .env, coverage, etc.). Un .env.example si el plan lo contempla. Nada de secretos reales en el repo.
6. CLAUDE.md en la raíz con las convenciones del proyecto (arquitectura, comandos, reglas de calidad) según el plan.
7. docs/ai-log.md (bitácora GenAI: abrir con la primera entrada real de esta sesión, indicando qué herramienta generó qué) y docs/thought-process.md (encabezado y secciones iniciales, con las decisiones ya tomadas del plan). No inventes contenido que no haya ocurrido.
8. README.md mínimo (título, descripción de una línea, "en construcción"); el README completo va al final.
9. Primer commit con mensaje claro y push a origin main.

No corras pytest ni suites de prueba (todavía no hay código). No modifiques nada fuera de /home/pichiloor/task-management-assessment salvo lo que requiera crear el repo en GitHub.

Al terminar, repórtame: URL del repo, hash del commit, árbol de archivos creado, salida resumida de `pre-commit run --all-files`, y cualquier decisión que hayas tomado por tu cuenta o desviación del plan.
```

### Steps 2-16, sent to Claude Code

Each step started with a one-line instruction from the author, for example
"adelante con el paso 10" ("go ahead with step 10") or "continua del 11 al
16" ("continue from 11 to 16"). The agent read the plan section and
`CLAUDE.md`, proposed or asked about anything not decided (for example,
replacing slowapi, or adding `httpx2`), implemented, and stopped.

### Review prompt, sent to Codex after each change (verbatim)

The author's rule: every change made by Claude Code is reviewed by Codex,
model `gpt-6-astra`, in a read-only sandbox, before it is considered done.
This is the review of the frontend commit:

```text
Review the latest commit (git show 6c076c5) in this repository: a React +
TypeScript frontend (frontend/src, frontend/tests), nginx config
(frontend/nginx.conf, security-headers.conf, Dockerfile), docker-compose
changes (web service, edge network, RATE_LIMIT_TRUSTED_PROXIES), a script
that exports the backend OpenAPI document (backend/scripts/export_openapi.py,
scripts/gen-api-types.sh) and a new CI job (.github/workflows/ci.yml). The
backend API is in backend/app/api (read it to check the frontend matches the
contract and permissions: creator edits/deletes, assignee may only change
status).

You are read-only: do not edit files. Report only concrete defects
(correctness, security, broken behavior, CI that would fail or pass wrongly,
accessibility problems that break use), each with file:line, a concrete
failure scenario, and severity (high/medium/low). Skip style preferences. Be
precise; if you are unsure, say so. This is a technical assessment due
tonight, so prioritize what matters.
```

Follow-up, after fixing its findings (verbatim):

```text
All three accepted and fixed in commit f6980a4 (git show f6980a4): nginx now
uses resolver 127.0.0.11 with a variable upstream; ExportPanel seeds the
query with the accepted job; Modal wraps Tab/Shift+Tab. Review that commit
for correctness (for instance, does proxy_pass with a variable still pass
the /api prefix and query string unchanged?), and report any remaining
concrete defects in the frontend/nginx/CI changes from 6c076c5 you did not
mention before. Same rules: read-only, file:line, failure scenario,
severity; say "no new defects" if none.
```

The loop repeated until the answer was "no new defects". For the frontend
that took four rounds (3, 2, 1 and 0 findings).

## 3. Why the prompts are written this way

- **Constraints over wishes.** "Do not add libraries without asking",
  "never SQLite", "HS256 only" remove whole classes of plausible but wrong
  output. Without them, agents tend to add convenient dependencies and test
  against SQLite, which hides PostgreSQL behavior.
- **Evidence is part of the task.** Asking for the red run, the actual
  command output and a test that fails without each fix makes claims
  checkable. It also caught the AI's own weak tests several times.
- **Checkpoints.** One step at a time keeps each diff reviewable and lets the
  author decide at each point (library choices, scope, when to push).
- **A second model as reviewer, read-only.** A different model does not
  share the first one's blind spots, and read-only access keeps the
  reviewer from "fixing" things without an explanation. Asking for
  file:line, a failure scenario and a severity filters out vague or
  stylistic comments; "say no new defects if none" gives it a way to stop
  instead of inventing findings.
- **The failure modes are named in the prompt.** Models implement the happy
  path by default; listing Redis down, lost jobs, concurrency and client
  disconnects is what got those cases designed and tested.
