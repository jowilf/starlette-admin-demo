FROM python:3.12-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /uvx /bin/

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1

COPY pyproject.toml uv.lock ./

# GITHUB_TOKEN is needed to fetch the private starlette-admin git dependency;
# passed as a build secret so it never lands in an image layer.
RUN --mount=type=secret,id=github_token,env=GITHUB_TOKEN \
    GIT_CONFIG_COUNT=1 \
    GIT_CONFIG_KEY_0="url.https://x-access-token:${GITHUB_TOKEN}@github.com/.insteadOf" \
    GIT_CONFIG_VALUE_0="https://github.com/" \
    uv sync --frozen --no-dev --no-install-project

COPY . .

RUN uv sync --frozen --no-dev


FROM python:3.12-slim-bookworm

WORKDIR /app

COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:$PATH"

ENV WORKERS=1

CMD ["sh", "-c", "fastapi run src/starlette_admin_demo/app.py --workers ${WORKERS} --port 8000 --forwarded-allow-ips '*'"]
