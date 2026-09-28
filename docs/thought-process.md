# Thought process

How the work was approached, in the order it happened. The decisions
themselves, with alternatives, are in [decisions.md](decisions.md); the
dated record of what each AI tool did is in [ai-log.md](ai-log.md).

## 1. Read the brief for what is evaluated, not only what is required

The requirements list is long (CRUD, JWT, pagination, filters, PostgreSQL,
80% coverage, Docker, Swagger, rate limiting, Celery, React, seed data), but
the evaluation criteria are few: Clean Architecture, testing (TDD
preferred), code quality, working functionality with a clean browser
console, a clear presentation, and critical use of GenAI. Every requirement
was planned so that it also produces evidence for one of those criteria:

| Criterion | Evidence planned for it |
| --- | --- |
| Clean Architecture | Layers enforced by import-linter; use cases tested with fakes |
| Testing / TDD | Red/green commit pairs; integration tests on real PostgreSQL and Redis; coverage gate in CI |
| Code quality | mypy strict, Ruff, ESLint, TypeScript strict, pre-commit = CI |
| Functionality | Seeded demo, one-command start, checks in a real browser at two widths |
| GenAI | Every change reviewed by a second model; findings, rejections and corrections logged |

## 2. Plan before code

Before writing code, a 16-step plan was written and approved by the author
(tooling, Compose, domain, persistence, auth, CRUD, seed, rate limiting,
exports, CI, frontend, coverage, docs, clean-clone check, code study,
submission). Each step had to end in a working, committed state, and each
step started only on the author's instruction. This kept every step small
enough to review.

## 3. Rules first, frameworks last

The domain and use cases were written first, test-first, with no database or
web framework. That forced the business questions early:

- Who can see a task? Its creator and its assignee.
- Who can change what? The creator changes everything and deletes; the
  assignee may only change the status.
- What does "completed" mean? `completed_at` is set when a task becomes
  completed and cleared when it is reopened; the database enforces it too.
- What happens to a task when its assignee is deleted? It becomes unassigned
  (`SET NULL`); a creator cannot be deleted while they own tasks
  (`RESTRICT`).

Only then came SQLAlchemy, FastAPI, Celery and React, each as an adapter
around rules that were already tested.

## 4. Treat AI output as a proposal

Claude Code wrote most of the code. It was never accepted on its own word:

- Tests were written before the code and, for most steps, committed and run
  red first; for review fixes, a test had to be seen failing without the
  fix. Several times the AI's own test turned out
  to pass without the fix (for example, race tests that paused at the wrong
  moment) and had to be rewritten until it did fail.
- A different model, OpenAI Codex (`gpt-6-astra`), reviewed every change in a
  read-only sandbox, repeatedly, until it reported no new defects. It found
  real problems the first model missed, including a way the test fixture
  could drop the real database and several race conditions.
- Behavior was also checked live: over HTTP through the running stack, with
  Redis or PostgreSQL stopped, in Chromium at desktop and phone widths.
- When the AI's justification for a decision was overstated (slowapi), the
  log says so.

Details and examples: [genai/](genai/README.md).

## 5. Failure modes as features

Much of the design is about what happens when something breaks, because that
is where simple implementations go wrong:

- Redis down: CRUD keeps working, health says `degraded`, rate limiting
  falls back to memory, exports return 503 instead of hanging.
- PostgreSQL slow or down: connection, statement and lock timeouts; health
  returns 503.
- A job lost between API and worker: reconciled every minute.
- A commit that fails: the client gets a 500, never a 200 for unsaved data.
- A token rejected mid-session: the frontend returns to the login page; a
  late rejection from an old session does not end a new one.

## 6. What was left out on purpose

- Registration, password reset and user administration: not asked for; the
  seed provides users.
- Refresh tokens and revocation: the token lifetime and the check that the
  user is still active cover the demo.
- Cloud deployment and TLS: the exercise asks for local Docker.
- Automated end-to-end browser tests in CI: the frontend has component
  and flow tests with a faked network, and the full stack was checked by
  hand in Chromium; a Playwright suite would be the next step.
- Keyset pagination and a transactional outbox: measured or reasoned to be
  unnecessary at this size, and documented as the next step.
