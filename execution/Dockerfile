# Image des conteneurs de commande du portail : Python, Node, uv, git, rien d'autre.
FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
COPY --from=node:22-bookworm-slim@sha256:e9f565d32859f0cbfb52125eafe8be39390f24dac302dc3cdf566e8ba3ab21ee /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim@sha256:e9f565d32859f0cbfb52125eafe8be39390f24dac302dc3cdf566e8ba3ab21ee /usr/local/lib/node_modules /usr/local/lib/node_modules
# npm 10 (livré avec Node 22) garde des dépendances vulnérables sans correctif : npm 11 épinglé.
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && npm install -g npm@11.21.2 && npm cache clean --force \
    && apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9.8@sha256:08f409e1d53e77dfb5b65c788491f8ca70fe1d2d459f41c89afa2fcbef998abe /uv /usr/local/bin/uv
RUN groupadd -g 1000 agent \
    && useradd -u 1000 -g 1000 -m -d /home/agent agent
ENV HOME=/home/agent
USER agent
WORKDIR /travail
