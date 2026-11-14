#!/usr/bin/env bash
# Écrit dans $PORTAIL_STACK_ENV (NOM=valeur) les secrets de la pile « portail »
# lus dans OpenBao (KV v2, VAULT_SECRET_PATH, défaut infra/data/portail). Variables : BAO_TOKEN, VAULT_URL,
# VAULT_CA_CERT. Jamais de valeur sur la sortie.
set -euo pipefail
umask 077

OUT="${PORTAIL_STACK_ENV:?PORTAIL_STACK_ENV absent}"
VAULT_URL="${VAULT_URL:-https://vault.infra.famillelallier.net}"
VAULT_SECRET_PATH="${VAULT_SECRET_PATH:-infra/data/portail}"
# variable de la pile <- clé du coffre
MAP="PORTAIL_DB_PASSWORD=PORTAIL_DB_PASSWORD PORTAIL_LITELLM_CLE=PORTAIL_LITELLM_CLE"

die() { echo "::error::vault-render-env.sh : $*" >&2; exit 1; }
BAO_TOKEN="${BAO_TOKEN//[[:space:]]/}"
[ -n "$BAO_TOKEN" ] || die "BAO_TOKEN absent"
case "$VAULT_URL" in https://*) ;; *) die "VAULT_URL doit être en https://" ;; esac
[ -r "${VAULT_CA_CERT:-}" ] || die "VAULT_CA_CERT illisible : ${VAULT_CA_CERT:-}"
command -v jq >/dev/null || die "jq est requis"

# Jeton périodique : le renouveler à chaque déploiement. En cas d'échec on continue,
# la lecture ci-dessous échouera bruyamment si le jeton est mort.
printf 'header = "X-Vault-Token: %s"\n' "$BAO_TOKEN" \
  | curl -fsS -o /dev/null --connect-timeout 10 --max-time 120 --cacert "$VAULT_CA_CERT" -K - \
    -X POST "$VAULT_URL/v1/auth/token/renew-self" \
  || echo "::warning::renouvellement du jeton OpenBao impossible" >&2

# Le jeton passe par un fichier de config curl lu sur stdin, jamais par argv.
secret="$(printf 'header = "X-Vault-Token: %s"\n' "$BAO_TOKEN" \
  | curl -fsS --connect-timeout 10 --max-time 120 --cacert "$VAULT_CA_CERT" -K - "$VAULT_URL/v1/$VAULT_SECRET_PATH" \
  | jq -c .data.data)" || die "coffre illisible (scellé ? jeton expiré ?)"

: > "$OUT"
chmod 600 "$OUT"
for pair in $MAP; do
  var="${pair%%=*}"; key="${pair#*=}"
  val="$(jq -er --arg k "$key" '.[$k]' <<<"$secret")" || die "clé $key absente de $VAULT_SECRET_PATH"
  # Un retour à la ligne injecterait une autre variable dans le fichier.
  case "$val" in *$'\n'* | *$'\r'*) die "$key contient un retour à la ligne" ;; esac
  # Avant toute autre sortie : le journal Actions masque la valeur.
  [ "${GITHUB_ACTIONS:-}" != true ] || printf '::add-mask::%s\n' "$val"
  printf '%s=%s\n' "$var" "$val" >> "$OUT"
  echo "  $var <- $VAULT_SECRET_PATH:$key"
done
