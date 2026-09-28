FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
# Install exactly what uv.lock pins, so an unrelated rebuild can't pull a
# breaking release (see services/ingestor-garmin/Dockerfile).
COPY services/ingestor-hevy/pyproject.toml services/ingestor-hevy/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
ENV PATH="/app/.venv/bin:$PATH"
COPY services/ingestor-hevy/app ./app
CMD ["python", "-m", "app.main"]
