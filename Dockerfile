FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.5.2 /uv /uvx /bin/

WORKDIR /app

COPY . .

RUN uv sync --frozen --no-dev

CMD ["uv", "run", "--", "gunicorn", "app.main:app", "-w", "8", "-k", "uvicorn_worker.UvicornWorker", "-b", "0.0.0.0:8000", "--forwarded-allow-ips", "*"]
