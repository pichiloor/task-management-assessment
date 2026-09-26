# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.12.19 AS uv

FROM python:3.12.14-slim AS base
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock ./

# Runtime image: production dependencies only, non-root user.
FROM base AS runtime
RUN uv sync --locked --no-dev --no-install-project
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
RUN useradd --system --uid 10001 app
USER app

# Test image: adds the dev group and the test suite.
FROM base AS test
RUN uv sync --locked --no-install-project
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY tests ./tests
ENV COVERAGE_FILE=/tmp/.coverage
RUN useradd --system --uid 10001 app
USER app
CMD ["pytest", "-p", "no:cacheprovider", "--cov=app", "--cov-report=term-missing"]
