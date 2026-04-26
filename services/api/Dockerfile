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
WORKDIR /app
COPY services/api/pyproject.toml ./
RUN pip install --root-user-action=ignore --no-cache-dir --upgrade pip \
 && pip install --root-user-action=ignore --no-cache-dir -e .
COPY services/api/app ./app
COPY --from=web /web/dist ./static
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
