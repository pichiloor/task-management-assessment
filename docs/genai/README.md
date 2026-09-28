# Generative AI: evidence

The exercise asks four things about the use of a GenAI coding tool. Each is
answered in its own file, with real prompts, real code and real results.

| The exercise asks | Where it is answered |
| --- | --- |
| The prompt you would use to generate the scaffold or the full implementation | [prompts.md §1](prompts.md#1-the-prompt-i-would-use-for-the-full-implementation), plus the prompts actually used in §2 |
| The output code, or a representative sample | [generated-sample.md](generated-sample.md): code kept as generated, and two corrections shown before and after |
| How you validated the AI's suggestions | [validation.md](validation.md#layers-of-validation) |
| How you corrected or improved the output | [review-and-corrections.md](review-and-corrections.md) |
| How you handled edge cases, authentication and validation | [validation.md](validation.md#edge-cases-authentication-and-validation) |
| How you assessed performance and idiomatic quality | [validation.md](validation.md#performance) (with `EXPLAIN ANALYZE` results) and [idiomatic quality](validation.md#idiomatic-quality) |

The dated, step-by-step log of what each tool did is
[docs/ai-log.md](../ai-log.md).

## Tools and roles

| Tool | Role |
| --- | --- |
| Claude Code (Claude Opus 5.5) | Wrote the plan with the author, then the code, tests and documentation, one approved step at a time |
| OpenAI Codex (`gpt-6-astra`), read-only | Built the step 1 scaffold; afterwards reviewed every change by Claude Code, round after round, until it found no new defects |
| The author | Approved the plan and each step, chose libraries, accepted or rejected each finding, decided every push |

Using two models from different vendors was deliberate: a reviewer that
does not share the author model's habits catches different mistakes. In this
project the reviewer found, among others, a way the test suite could drop a
real database, several race conditions and a denial-of-service lever; the
full table is in [review-and-corrections.md](review-and-corrections.md).
