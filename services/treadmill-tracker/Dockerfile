FROM python:3.13-slim
WORKDIR /app
COPY services/treadmill-tracker/pyproject.toml ./
RUN pip install --root-user-action=ignore --no-cache-dir --upgrade pip \
 && pip install --root-user-action=ignore --no-cache-dir -e .
COPY services/treadmill-tracker/app ./app
CMD ["python", "-m", "app.main"]
