FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /uvx /bin/

WORKDIR /app

COPY . .

RUN uv sync --frozen --no-dev

CMD ["uv", "run", "--", "fastapi", "run", "--workers", "8", "--port", "8000", "--forwarded-allow-ips", "*"]
