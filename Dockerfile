FROM node:22-alpine@sha256:1314fb30ec37592d5845e5a160d522c0e680972aa534549940b8d73bde88481a AS front
WORKDIR /front
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9.8@sha256:08f409e1d53e77dfb5b65c788491f8ca70fe1d2d459f41c89afa2fcbef998abe /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev
COPY agents.yaml /app/agents.yaml
COPY --from=front /front/dist /app/static
RUN useradd -u 1000 --system --no-create-home portail \
    && mkdir /donnees /espaces && chown 1000:1000 /donnees /espaces
USER portail
ENV PATH="/app/backend/.venv/bin:$PATH" \
    PORTAIL_STATIC_DIR=/app/static \
    PORTAIL_AGENTS_FICHIER=/app/agents.yaml
EXPOSE 8000
CMD ["sh","-c","alembic upgrade head && exec uvicorn --factory portail.api:create_app --host 0.0.0.0 --port 8000 --no-proxy-headers --log-config journal.json --no-access-log"]
