# syntax=docker/dockerfile:1

ARG OPENCODE_VERSION=latest

FROM debian:bookworm-slim

ARG OPENCODE_VERSION

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
     && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        jq \
     && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 opencode \
     && mkdir -p /work /tmp/opencode \
     && chown opencode:opencode /work /tmp/opencode

USER opencode
WORKDIR /work

RUN curl -fsSL "https://opencode.ai/install?version=${OPENCODE_VERSION}" | bash

ENV PATH="/home/opencode/.opencode/bin:${PATH}"

EXPOSE 4096

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:4096/global/health || exit 1

CMD ["opencode", "serve", "--hostname", "0.0.0.0", "--port", "4096"]
