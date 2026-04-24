# Stage 1: build the React frontend
FROM node:20-alpine AS web
WORKDIR /web
COPY services/web/package.json services/web/package-lock.json* ./
RUN npm install
COPY services/web/ ./
RUN npm run build

# Stage 2: Python API + bundled static FE
FROM python:3.12-slim
WORKDIR /app
COPY services/api/pyproject.toml ./
RUN pip install --no-cache-dir -e .
COPY services/api/app ./app
COPY --from=web /web/dist ./static
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
