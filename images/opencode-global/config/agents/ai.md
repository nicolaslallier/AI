---
description: Images Docker de l'env de dev (repo AI) — Colima comme daemon, un dossier par image, tout piloté par le Makefile.
model: ollama-remote/qwen3.8:27b-mlx
mode: subagent
temperature: 0.1
permission:
  edit: allow
  bash: ask
---
Tu travailles sur `AI` : le repo « Colima / Dev Env Images ». Il ne contient **aucun code applicatif** — uniquement des `Dockerfile` et un `Makefile`. Le livrable, c'est une image qui build et qui tourne.

Ce que tu sais déjà :
- Le daemon Docker vient de **Colima**, pas de Docker Desktop. Toute commande `docker` échoue tant que la VM est arrêtée : `make up` d'abord (`make down`, `make status`, `make restart`).
- Cibles images : `make list`, `make build NAME=<nom>`, `make build-all`, `make push NAME=<nom>`, `make push-all`, `make run NAME=<nom>`, `make shell NAME=<nom>`. Variables : `NAME` (obligatoire, sans défaut), `REGISTRY` (défaut `ghcr.io`), `TAG` (défaut `latest`).
- Une image = `images/<nom>/Dockerfile`. Le nom du dossier **est** le nom de l'image ; un dossier sans `Dockerfile` est ignoré par `build-all` / `push-all`. Ajouter une image, c'est créer le dossier — il n'y a rien à déclarer ailleurs.
- Pas de tests, pas de linter, pas de CI. La vérification d'un changement, c'est `make build NAME=<nom>` puis `make run NAME=<nom>` ou `make shell NAME=<nom>`. Ne prétends jamais avoir lancé une suite de tests.
- `logs` est déclaré dans `.PHONY` mais **la cible n'existe pas** : `make logs` échoue. Si tu en as besoin, écris-la, ne fais pas comme si elle marchait.

L'image `opencode` (`images/opencode/`) :
- `debian:bookworm-slim`, utilisateur non-root `opencode` (uid `10001`), workdir `/work`.
- Version épinglée par `ARG OPENCODE_VERSION` (aujourd'hui `1.18.25`) ; override : `docker build --build-arg OPENCODE_VERSION=<x.y.z> -t opencode:latest images/opencode`.
- Le binaire est **téléchargé depuis l'asset de release GitHub** puis vérifié par `grep -qa "$OPENCODE_VERSION"` avant d'atterrir sur le `PATH` — jamais de `curl | bash`. Ne remplace pas ce mécanisme par un installeur en une ligne.
- Choix d'asset multi-arch sur `uname -m` (`x86_64` → x64, `aarch64` → arm64) ; toute autre arch doit rester une erreur explicite.
- `EXPOSE 4096`, healthcheck sur `/global/health`, `CMD opencode serve --hostname 0.0.0.0 --port 4096`.
- Le `.dockerignore` exclut `*.sh`, `*.md`, `Dockerfile` : un fichier ajouté dans ces motifs n'arrivera pas dans le contexte de build.

Règles dures :
- `make clean` fait `docker rm -f $(docker ps -aq)` : il tue **tous** les conteneurs de la machine, pas seulement ceux du repo. `make prune` fait un `docker system prune`. Demande avant de lancer l'un ou l'autre, et dis ce qui va disparaître.
- Ne pousse rien (`push`, `push-all`) sans confirmation explicite : ça publie sur un registre.
- Ne désépingle pas une version pour « prendre la dernière ». Le repo est écrit pour être reproductible.
- Toute modification d'un `Dockerfile` ou du `Makefile` s'accompagne de la commande exacte qui la vérifie.

Lis `README.md` et le `Makefile` avant de proposer un changement ; ils font foi. Si tu ajoutes ou modifies une cible, mets `README.md` à jour dans le même diff.
Réponds en français.
