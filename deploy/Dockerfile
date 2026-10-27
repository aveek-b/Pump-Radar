FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY api ./api
RUN python -m pip install --no-cache-dir .

ENV PUMPRADAR_DB=/state/alerts.sqlite3
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
