FROM python:3.13-slim
WORKDIR /app
COPY services/ingestor-hevy/pyproject.toml ./
RUN pip install --root-user-action=ignore --no-cache-dir --upgrade pip \
 && pip install --root-user-action=ignore --no-cache-dir -e .
COPY services/ingestor-hevy/app ./app
CMD ["python", "-m", "app.main"]
