# Stage 1: build the React frontend
FROM node:24-alpine AS web
ENV NPM_CONFIG_UPDATE_NOTIFIER=false NPM_CONFIG_FUND=false
WORKDIR /web
COPY services/web/package.json services/web/package-lock.json* ./
RUN npm ci --no-audit
COPY services/web/ ./
RUN npm run build

# Stage 2: Python API + bundled static FE
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
# Install exactly what uv.lock pins, so an unrelated rebuild can't pull a
# breaking release (see services/ingestor-garmin/Dockerfile).
COPY services/api/pyproject.toml services/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
ENV PATH="/app/.venv/bin:$PATH"
COPY services/api/app ./app
COPY --from=web /web/dist ./static
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
