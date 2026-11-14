# Image des conteneurs de commande du portail : Python, Node, uv, git, rien d'autre.
FROM python:3.12-slim-bookworm
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9.8 /uv /usr/local/bin/uv
RUN groupadd -g 1000 agent \
    && useradd -u 1000 -g 1000 -m -d /home/agent agent
ENV HOME=/home/agent
USER agent
WORKDIR /travail
