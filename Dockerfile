FROM node:22-alpine AS front
WORKDIR /front
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.8 /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev
COPY agents.yaml /app/agents.yaml
COPY --from=front /front/dist /app/static
RUN useradd --system --no-create-home portail
USER portail
ENV PATH="/app/backend/.venv/bin:$PATH" \
    PORTAIL_STATIC_DIR=/app/static \
    PORTAIL_AGENTS_FICHIER=/app/agents.yaml
EXPOSE 8000
CMD ["sh","-c","alembic upgrade head && exec uvicorn --factory portail.api:create_app --host 0.0.0.0 --port 8000"]
