# dbt-duckdb + the project's Python tools. `docker run --rm -v "$PWD/target:/app/target" <image>` runs make dbt-demo.
FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends make git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements-dbt.txt ./
RUN pip install --no-cache-dir -r requirements-dbt.txt

COPY . .
ENV PYTHONPATH=/app/src DBT_PROFILES_DIR=/app
CMD ["make", "dbt-demo"]
