FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv
WORKDIR /app
RUN useradd --create-home --uid 10001 app && mkdir -p /app/data/photos /app/models && chown -R app:app /app/data /app/models
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --python /usr/local/bin/python
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY --chown=app:app models/*LICENSE models/README.md ./models/
USER app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 APP_STORAGE_DIR=/app/data/photos APP_MODEL_DIR=/app/models
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
