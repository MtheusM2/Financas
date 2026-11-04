# Trixie traz o cliente PostgreSQL 17, a mesma versao do banco: o backup depende disso.
FROM python:3.12-slim-trixie
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home app && mkdir -p /backups && chown app /backups
USER app
