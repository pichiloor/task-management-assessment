# Review and corrections

Record actual findings and corrections during this session. No application code exists yet.

## Frontend dependency compatibility

Codex's first install requested unversioned current development tools. npm
returned ERESOLVE: TypeScript 7.0.2 conflicted with typescript-eslint (below 6.1)
and openapi-typescript (5.x). The corrected install selects TypeScript 5.9.3,
ESLint 9 and Node 24 declarations and retains peer-dependency validation.
This is an actual tooling correction, not an application-code review.

## ESLint maintenance correction

The compatible retry installed successfully, but npm marked ESLint 9 unsupported.
Codex inspected typescript-eslint, eslint-plugin-react-hooks and
eslint-plugin-react-refresh peer requirements; all accept ESLint 10. The final
choice is ESLint 10 with @eslint/js 10, while retaining TypeScript 5.9.3.
