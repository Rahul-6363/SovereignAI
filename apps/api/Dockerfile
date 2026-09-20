# Meshcore API (FastAPI) — local build.
#
# Build context is the REPO ROOT (see docker-compose.yml: `context: .`)
# because the app imports `packages/prompts` and `packages/schemas` from
# the monorepo root at runtime (see apps/api/app/config.py).
FROM python:3.12-slim AS base
WORKDIR /app

# System deps for pymupdf / pillow wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python deps first for better layer caching
COPY apps/api/requirements.txt apps/api/requirements.txt
RUN pip install --no-cache-dir -r apps/api/requirements.txt

# Copy the rest of the monorepo (api app + packages it imports from root)
COPY apps/api apps/api
COPY packages packages

WORKDIR /app/apps/api

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
