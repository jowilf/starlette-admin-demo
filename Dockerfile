ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.11.32


FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv


FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

COPY --from=uv /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    # Cache mounts live outside the layer, so hardlinking into .venv would fail.
    UV_LINK_MODE=copy \
    UV_PYTHON=/usr/local/bin/python3 \
    UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock ./

# Dependencies resolve in their own layer so app-code edits don't reinstall them.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY . .

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python:${PYTHON_VERSION}-slim-bookworm

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UPLOAD_DIR=/app/uploads \
    WORKERS=1

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app

COPY --from=builder --chown=app:app /app /app

# Written to at runtime: uploads by LocalStorage, /app itself by Celery Beat's
# schedule db. WORKDIR created /app as root, so reclaim it here.
RUN install -d -o app -g app /app /app/uploads

USER app

EXPOSE 8000

# Celery services built from this image should override it with
# `healthcheck: {disable: true}` in compose.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=4)"

# `exec` hands PID 1 to the server so SIGTERM reaches it and shutdown stays graceful.
CMD ["sh", "-c", "exec fastapi run src/starlette_admin_demo/app.py --workers ${WORKERS} --port 8000 --forwarded-allow-ips '*'"]
