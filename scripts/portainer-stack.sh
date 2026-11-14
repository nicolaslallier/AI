#!/usr/bin/env bash
# Crée la pile « portail » dans le Portainer de l'Infra, ou la redéploie (image
# retirée de nouveau). Portainer clone GitHub main pour lire le fichier compose.
# L'API de Portainer réécrit TOUTE la liste Env à chaque déploiement : on renvoie
# donc chaque variable à chaque `up`, depuis $PORTAIL_STACK_ENV.
#
# Usage : scripts/portainer-stack.sh up
# Variables : PORTAINER_URL, PORTAINER_API_KEY, PORTAINER_CA_CERT,
#   PORTAIL_STACK_ENV, PORTAINER_ENDPOINT_ID (optionnel).
set -euo pipefail
cd "$(dirname "$0")/.."

STACK=portail
REPO_URL=https://github.com/nicolaslallier/AI
REF=refs/heads/main
COMPOSE_FILE=deploy/portainer-stack.yml
REQUIRED="PORTAIL_DB_PASSWORD PORTAIL_LITELLM_CLE"

die() { echo "::error::portainer-stack.sh : $*" >&2; exit 1; }
[ "${1:-}" = up ] || die "usage : scripts/portainer-stack.sh up"

PORTAINER_URL="${PORTAINER_URL:?PORTAINER_URL absent}"
case "$PORTAINER_URL" in https://*) ;; *) die "PORTAINER_URL doit être en https://" ;; esac
PORTAINER_URL="${PORTAINER_URL%/}"
[ -r "${PORTAINER_CA_CERT:-}" ] || die "PORTAINER_CA_CERT illisible : ${PORTAINER_CA_CERT:-}"
[ -n "${PORTAINER_API_KEY:-}" ] || die "PORTAINER_API_KEY absent"
[ -r "${PORTAIL_STACK_ENV:-}" ] || die "PORTAIL_STACK_ENV illisible : ${PORTAIL_STACK_ENV:-}"
command -v jq >/dev/null || die "jq est requis"

# Fichier NOM=valeur -> [{name,value}]. Rien n'est interprété (un mot de passe
# généré peut contenir `$` ou `#`).
env="$(jq -Rn '[inputs | select(test("^[A-Za-z_][A-Za-z0-9_]*=")) | capture("^(?<name>[^=]+)=(?<value>.*)$")]' < "$PORTAIL_STACK_ENV")"
for n in $REQUIRED; do
  jq -e --arg n "$n" 'any(.[]; .name == $n and .value != "")' <<<"$env" >/dev/null || die "$n absent de la pile"
done

# La clé passe à curl par un fichier de config (mode 600), jamais par argv.
CURL_CFG="$(umask 077 && mktemp)"
trap 'rm -f "$CURL_CFG"' EXIT
# Un secret collé garde souvent un saut de ligne : il casserait l'en-tête.
PORTAINER_API_KEY="${PORTAINER_API_KEY//[[:space:]]/}"
printf 'header = "X-API-Key: %s"\n' "$PORTAINER_API_KEY" > "$CURL_CFG"

api() { # <méthode> <chemin> [corps-json]
  local out
  out="$(printf '%s' "${3:-}" | curl -sS --cacert "$PORTAINER_CA_CERT" -K "$CURL_CFG" --fail-with-body \
    -X "$1" -H "Content-Type: application/json" --data-binary @- "$PORTAINER_URL/api$2" 2>&1)" \
    || { printf '%s\n' "${out//$PORTAINER_API_KEY/***}" >&2; die "$1 $2 a échoué"; }
  printf '%s' "$out"
}

eid="${PORTAINER_ENDPOINT_ID:-$(api GET /endpoints | jq -r '[.[] | select(.Type == 1)][0].Id // empty')}"
[ -n "$eid" ] || die "aucun environnement Docker local dans Portainer"
sid="$(api GET /stacks | jq -r --arg n "$STACK" 'first(.[] | select(.Name == $n)) | .Id // empty')"

if [ -z "$sid" ]; then
  body="$(jq -n --arg name "$STACK" --arg url "$REPO_URL" --arg ref "$REF" --arg file "$COMPOSE_FILE" --argjson env "$env" \
    '{Name: $name, RepositoryURL: $url, RepositoryReferenceName: $ref,
      ComposeFile: $file, RepositoryAuthentication: false, Env: $env}')"
  api POST "/stacks/create/standalone/repository?endpointId=$eid" "$body" > /dev/null
  echo "portainer-stack.sh : pile '$STACK' créée"
else
  body="$(jq -n --arg ref "$REF" --argjson env "$env" \
    '{RepositoryReferenceName: $ref, RepositoryAuthentication: false, Env: $env,
      Prune: false, PullImage: true, RepullImageAndRedeploy: true}')"
  api PUT "/stacks/$sid/git/redeploy?endpointId=$eid" "$body" > /dev/null
  echo "portainer-stack.sh : pile '$STACK' redéployée (image retirée)"
fi
