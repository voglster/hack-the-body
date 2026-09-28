FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
# Install exactly what uv.lock pins, so an unrelated rebuild can't pull a
# breaking release (see services/ingestor-garmin/Dockerfile).
COPY services/treadmill-tracker/pyproject.toml services/treadmill-tracker/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
ENV PATH="/app/.venv/bin:$PATH"
COPY services/treadmill-tracker/app ./app
CMD ["python", "-m", "app.main"]
