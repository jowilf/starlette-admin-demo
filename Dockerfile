FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.5.2 /uv /uvx /bin/

WORKDIR /app

COPY . .

RUN uv sync --frozen --no-dev

CMD ["uv", "run", "--", "uvicorn", "app.main:app", "--workers", "8", "--forwarded-allow-ips", "*", "--proxy-headers"]
