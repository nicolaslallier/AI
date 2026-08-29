# syntax=docker/dockerfile:1

# Pin the opencode release for reproducible builds.
# Override via: docker build --build-arg OPENCODE_VERSION=1.x.y ...
ARG OPENCODE_VERSION=1.18.25

FROM debian:bookworm-slim

# Re-declare for the stage scope.
ARG OPENCODE_VERSION

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
      && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        tar \
      && rm -rf /var/lib/apt/lists/*

# The state/config dirs are created here so that named volumes mounted over
# them inherit the opencode ownership instead of being created root-owned.
RUN useradd --create-home --uid 10001 opencode \
      && mkdir -p /work /opt/opencode/bin \
        /home/opencode/.local/share/opencode \
        /home/opencode/.config/opencode \
      && chown -R opencode:opencode /work /opt/opencode/bin /home/opencode

USER opencode
WORKDIR /work

# Fetch the pinned release artifact directly (no `curl | bash`) from a
# deterministic URL, then verify the expected version is embedded in the
# binary before it is trusted on PATH. The check is done without executing
# the binary so the build is not coupled to the host architecture.
RUN set -e; \
    case "$(uname -m)" in \
        x86_64)  asset="opencode-linux-x64.tar.gz" ;; \
        aarch64) asset="opencode-linux-arm64.tar.gz" ;; \
          *) echo "unsupported arch: $(uname -m)" >&2; exit 1 ;; \
    esac; \
    url="https://github.com/anomalyco/opencode/releases/download/v${OPENCODE_VERSION}/${asset}"; \
    tmp="$(mktemp -d)"; \
    curl -fsSL -o "${tmp}/${asset}" "${url}"; \
    tar -xzf "${tmp}/${asset}" -C "${tmp}"; \
    cp "${tmp}/opencode" /opt/opencode/bin/opencode; \
    chmod 0755 /opt/opencode/bin/opencode; \
    rm -rf "${tmp}"; \
    grep -qa "${OPENCODE_VERSION}" /opt/opencode/bin/opencode

ENV PATH="/opt/opencode/bin:${PATH}"

EXPOSE 4096

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:4096/global/health

CMD ["opencode", "serve", "--hostname", "0.0.0.0", "--port", "4096"]
