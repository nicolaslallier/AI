# rust:1-slim suit Debian trixie : la variante bookworm garde la glibc de l'image finale.
FROM rust:1-slim-bookworm AS compilation
WORKDIR /src
COPY Cargo.toml Cargo.lock ./
COPY src ./src
RUN cargo build --release --locked

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=compilation /src/target/release/lanceur /usr/local/bin/lanceur
# ponytail: root pour le socket ; passer par un groupe docker dédié si l'hôte le permet
USER root
CMD ["lanceur"]
