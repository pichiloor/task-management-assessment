# Architecture

Approved direction: domain rules, application use cases and repository contracts,
infrastructure adapters, and HTTP handlers in separate packages. Composition of
concrete adapters belongs at application startup. The inner packages must not
import FastAPI, SQLAlchemy, Celery, or infrastructure; import-linter checks this.
Domain also cannot import application or API; application cannot import API.

Use synchronous SQLAlchemy sessions. Later, nginx will serve React and proxy
`/api/` unchanged to FastAPI. PostgreSQL persists data; Redis backs rate limiting
and the Celery export worker. Implementation is pending.
