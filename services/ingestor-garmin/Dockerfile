FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
# Install exactly what uv.lock pins. A bare `pip install -e .` re-resolved on
# every build and silently pulled garminconnect 0.3.16, which broke every fetch.
COPY services/ingestor-garmin/pyproject.toml services/ingestor-garmin/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
ENV PATH="/app/.venv/bin:$PATH"
COPY services/ingestor-garmin/app ./app
CMD ["python", "-m", "app.main", "run"]
