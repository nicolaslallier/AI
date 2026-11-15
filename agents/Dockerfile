# Une seule image pour tous les agents : chaque service nomme son binaire (entrypoint).
# rust:1-slim suit Debian trixie : la variante bookworm garde la glibc de l'image finale.
FROM rust:1-slim-bookworm@sha256:7c7d4eb4d05b7781187a327809466cfddf29753f6defdc3d19a0e291951b7a37 AS compilation
WORKDIR /src
COPY . .
RUN cargo build --release --locked --bins \
    && mkdir /sortie \
    && find target/release -maxdepth 1 -type f -executable ! -name '*.so' -exec cp {} /sortie/ \;

# glibc, aucun shell, utilisateur non root (65532) ; pas de CMD.
FROM gcr.io/distroless/cc-debian12:nonroot@sha256:9dac0a79194e45a7da0158a9c6da57b217585af0786db3845d1f0ec1a0dd182f
COPY --from=compilation /sortie/ /usr/local/bin/
EXPOSE 8080
