# Review and corrections

Workflow: Claude Code implements a step and commits it; Codex (`gpt-6-astra`,
read-only sandbox) reviews the commit; each finding is accepted or rejected
by the author; accepted findings get a test that fails first, then the fix;
the fix goes back to Codex, until it reports no new defects. The complete,
dated list is in the [AI log](../ai-log.md). The most significant findings:

| Step | Severity | Finding | Correction |
| --- | --- | --- | --- |
| 3 | Medium | Domain mutators changed a field before validating their input, leaving half-applied changes on error | Validate first in every mutator |
| 4 | High | Test fixture could `DROP DATABASE` a real database (63-byte truncation, and later `production_test`) | Name must be exactly `POSTGRES_DB + "_test"`, a plain identifier within 63 bytes ([sample](generated-sample.md#2-correction-the-test-database-guard-found-by-the-reviewer-high-severity)) |
| 4 | Medium | Test URL built by string interpolation broke with `@`, `/`, `%` in the password | `URL.create()` from components |
| 5 | Medium | Transaction committed after the response: a failed commit could follow a 200 | Commit before the response (`scope="function"`) |
| 5 | Medium | A dummy Argon2 hash (~64 MiB) computed on every request: denial-of-service lever | Computed once at startup |
| 5 | Medium | Rejected secrets echoed in validation errors (could reach logs) | `hide_input_in_errors` |
| 6 | Medium | A PostgreSQL server that stops answering could hang requests indefinitely | Connect, statement and lock timeouts; 2 s in the health check |
| 7 | Medium | Two concurrent seed runs could insert the demo twice | PostgreSQL advisory lock, tested with SQLSTATE `55P03` |
| 8 | Medium | `limits`' in-memory storage could admit extra requests under concurrency (expiry checked outside its lock, cleanup on a timer thread) | Own in-memory fixed-window counter under one lock |
| 8 | Medium | A slow request could overwrite a newer Redis health state | Generation number on every state change |
| 9 | High | A lost or unpublishable job left an export pending forever; Redis had no persistence | Beat reconciler, `dispatched_at`, Redis AOF |
| 9 | Medium | A file deleted between the check and the download gave a 500; a client disconnecting early leaked the open file | Open first (410 if gone); close in `finally` around the ASGI call |
| 11 | Medium | nginx resolved the API once; a recreated container meant 502s | Docker DNS resolver with a 10 s validity |
| 11 | Medium | An export whose first status poll failed stopped polling for good | Seed the query with the accepted job |
| 11 | Medium | Tab focus escaped modal dialogs | Focus wraps inside the dialog |
| 11 | Medium | A late 401 from an old session logged out the new one | Conditional logout ([sample](generated-sample.md#3-correction-a-race-in-the-frontend-session-found-by-the-reviewer)) |
| 11 | Medium | Under React StrictMode, the dialog thought it was closed after mounting | Reset the flag on effect setup; tests now render in StrictMode |

## Corrections to the AI's reasoning, not only its code

- **Overstated justification.** Claude said slowapi "binds limits at import
  time" and "needs private attributes" to exempt routes. Codex checked
  slowapi 0.1.10: both claims were wrong. The switch to `limits` was kept as
  the author's preference, and the documentation says so.
- **Overstated claims in the log.** Codex caught log entries that described
  a test change that had never been applied, a cleanup that "flushes" Redis
  when it only deletes its own keys, and a timing protection described more
  strongly than the test proved. All were corrected.
- **Findings not adopted.** Codex noted that the in-memory limiter prunes
  expired keys in O(n) every 1000 hits and that some tests reach private
  attributes. Both were judged acceptable for a per-process fallback and
  left as documented limitations.

## Tooling corrections during scaffolding (Codex, step 1)

- npm rejected TypeScript 7.0.2 (outside the supported range of
  typescript-eslint and openapi-typescript); TypeScript 5.9.3 was selected
  without bypassing peer checks.
- ESLint 9 was reported unsupported; after checking every plugin's peer
  range, ESLint 10 was used.
