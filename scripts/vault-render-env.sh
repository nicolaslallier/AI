#!/usr/bin/env bash
# Écrit dans $PORTAIL_STACK_ENV (NOM=valeur) les secrets de la pile « portail »
# lus dans OpenBao (KV v2, infra/env). Variables : BAO_TOKEN, VAULT_URL,
# VAULT_CA_CERT. Jamais de valeur sur la sortie.
set -euo pipefail
umask 077

OUT="${PORTAIL_STACK_ENV:?PORTAIL_STACK_ENV absent}"
VAULT_URL="${VAULT_URL:-https://vault.infra.famillelallier.net}"
# variable de la pile <- clé du coffre
MAP="PORTAIL_DB_PASSWORD=PORTAIL_DB_PASSWORD PORTAIL_LITELLM_CLE=PORTAIL_LITELLM_CLE"

die() { echo "::error::vault-render-env.sh : $*" >&2; exit 1; }
[ -n "${BAO_TOKEN:-}" ] || die "BAO_TOKEN absent"
[ -r "${VAULT_CA_CERT:-}" ] || die "VAULT_CA_CERT illisible : ${VAULT_CA_CERT:-}"
command -v jq >/dev/null || die "jq est requis"

# Le jeton passe par un fichier de config curl lu sur stdin, jamais par argv.
secret="$(printf 'header = "X-Vault-Token: %s"\n' "$BAO_TOKEN" \
  | curl -fsS -m 10 --cacert "$VAULT_CA_CERT" -K - "$VAULT_URL/v1/infra/data/env" \
  | jq -c .data.data)" || die "coffre illisible (scellé ? jeton expiré ?)"

: > "$OUT"
for pair in $MAP; do
  var="${pair%%=*}"; key="${pair#*=}"
  val="$(jq -er --arg k "$key" '.[$k]' <<<"$secret")" || die "clé $key absente de infra/env"
  printf '%s=%s\n' "$var" "$val" >> "$OUT"
  echo "  $var <- infra/env:$key"
done
