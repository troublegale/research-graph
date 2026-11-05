FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 UV_LINK_MODE=copy
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-dev
COPY alembic.ini ./
COPY migrations ./migrations
RUN useradd --create-home app && mkdir -p data artifacts && chown app:app /app /app/data /app/artifacts
USER app
EXPOSE 8000
CMD ["sh", "-c", "uv run --no-sync rg migrate && uv run --no-sync rg seed && uv run --no-sync rg serve --host 0.0.0.0"]
