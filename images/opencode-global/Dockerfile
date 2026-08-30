# syntax=docker/dockerfile:1

# opencode-global : l'image `opencode` (binaire epingle, user non-root 10001,
# /work, healthcheck, multi-arch, pas de `curl | bash`) avec la config
# opencode GLOBALE deja fournie -- provider central + agents partages --
# pour qu'un conteneur lance depuis cette image demarre avec tous les agents
# charges.
#
# Pre-requis : build `opencode` d'abord (cette image l'utilise en FROM).
#   make build NAME=opencode
#   make build NAME=opencode-global
#
# Source des fichiers config : le sous-dossier `config/` a la racine de ce
# dossier d'image (miroir de opencode-global/, refresh via `cp` -- voir README).
# Les fichiers restent dans le contexte de build, car un symlink pointant HORS
# du contexte n est pas suivi par BuildKit (verifie : le build echoue avec
# `transferring context: 55B` puis "not found").

# Herite de l'image verifiee : meme opencode (version epinglee), meme user
# opencode (uid 10001), meme /work, meme healthcheck. Ni retetelement ni
# redcouverte du binaire : on se construit dessus.
FROM opencode:latest

# Emplacement ou opencode lit sa config globale dans ce conteneur
# (XDG_CONFIG_HOME par defaut = $HOME/.config). L user opencode a HOME=/home/opencode.
ENV OPENCODE_CONFIG_DIR=/home/opencode/.config/opencode

# Bake le strict necessaire : config, agents, helpers.
# (Pas install.sh ni net.famillelallier.opencode.plist : machinerie macOS /
#  launchd, inutile a bord -- exclus d'office par le .dockerignore.)
COPY --chown=opencode:opencode config/opencode.json     "${OPENCODE_CONFIG_DIR}/opencode.json"
COPY --chown=opencode:opencode config/agents/           "${OPENCODE_CONFIG_DIR}/agents/"
COPY --chown=opencode:opencode config/refresh-models.py "${OPENCODE_CONFIG_DIR}/refresh-models.py"
COPY --chown=opencode:opencode config/pin-model.sh      "${OPENCODE_CONFIG_DIR}/pin-model.sh"
COPY --chown=opencode:opencode config/diag.sh           "${OPENCODE_CONFIG_DIR}/diag.sh"
COPY --chown=opencode:opencode config/fix-service.sh    "${OPENCODE_CONFIG_DIR}/fix-service.sh"
COPY --chown=opencode:opencode config/shell-aliases.sh  "${OPENCODE_CONFIG_DIR}/shell-aliases.sh"

# - agent -> agents : opencode lit l'un ou l'autre selon la version (voir install.sh).
# - L URL du provider (http://192.168.2.40:11434/v1) est conservee a l'identique :
#   une machine LAN en HTTP clair, joignable uniquement depuis ce reseau. On ne la
#   modifie pas ici -- un override build-arg peut la reprendre, decide par le
#   proprietaire de la config.
RUN set -e; \
    cd "$OPENCODE_CONFIG_DIR"; \
    ln -s agents agent; \
    chmod 0755 refresh-models.py pin-model.sh diag.sh fix-service.sh shell-aliases.sh

# refresh-models.py est un helper optionnel (realign la liste des modeles depuis
# Ollama). Il a besoin de python3 a l execution ; si ce binaire n est pas present,
# le provider epingle et les agents fonctionnent quand meme (le champ `model` de
# opencode.json est deja ecrit a la valeur desiree, sans PLACEHOLDER a resoudre).

EXPOSE 4096

# Serveur joignable depuis l'exterieur. L ordre de priorite d opencode donne au
# flag --hostname le pas sur le champ `hostname` de opencode.json (qui reste a
# 127.0.0.1, valeur locale). La CMD force donc 0.0.0.0 sans muter la config
# fournie -- a recharger via l ENV du conteneur si necessary.
CMD ["opencode", "serve", "--hostname", "0.0.0.0", "--port", "4096"]
