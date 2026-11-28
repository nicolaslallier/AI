# rust:1-slim suit Debian trixie : la variante bookworm garde la glibc de l'image finale.
FROM rust:1-slim-bookworm@sha256:7c7d4eb4d05b7781187a327809466cfddf29753f6defdc3d19a0e291951b7a37 AS compilation
WORKDIR /src
COPY Cargo.toml Cargo.lock ./
COPY src ./src
RUN cargo build --release --locked

FROM debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc
# upgrade : l'image de base épinglée peut retarder sur les correctifs Debian (Trivy bloque sinon).
# APT_DATE (date du jour, passée par deploy.yml) reconstruit cette couche une fois par jour.
ARG APT_DATE
RUN echo "apt: ${APT_DATE}" && apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=compilation /src/target/release/lanceur /usr/local/bin/lanceur
# ponytail: root pour le socket ; passer par un groupe docker dédié si l'hôte le permet
USER root
CMD ["lanceur"]
