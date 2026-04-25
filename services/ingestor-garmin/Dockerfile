FROM python:3.12-slim
WORKDIR /app
COPY services/ingestor-garmin/pyproject.toml ./
RUN pip install --no-cache-dir -e .
COPY services/ingestor-garmin/app ./app
CMD ["python", "-m", "app.main", "run"]
