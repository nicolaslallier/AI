# Une seule image pour tous les agents : chaque service nomme son binaire (entrypoint).
FROM rust:1-slim-bookworm@sha256:7c7d4eb4d05b7781187a327809466cfddf29753f6defdc3d19a0e291951b7a37 AS compilation
WORKDIR /src
COPY . .
# Binaires statiques (musl) : aucune dépendance C, donc aucune bibliothèque système à corriger.
RUN cible="$(uname -m)-unknown-linux-musl" \
    && rustup target add "$cible" \
    && cargo build --release --locked --bins --target "$cible" \
    && mkdir /sortie \
    && find "target/$cible/release" -maxdepth 1 -type f -executable ! -name '*.so' -exec cp {} /sortie/ \;

# Ni libc ni libssl, aucun shell, utilisateur non root (65532) ; pas de CMD.
FROM gcr.io/distroless/static-debian12:nonroot@sha256:afa5c872c891853ca7fcf1f12c3edb23f7eeef36189728842dd51042ff57f7ab
COPY --from=compilation /sortie/ /usr/local/bin/
EXPOSE 8080
