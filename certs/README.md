# Certificats

`infra-ca.crt` : les certificats **publics** de l'autorité locale de la stack
[Infra](https://github.com/nicolaslallier/Infra) (« Infra Local Dev CA »), celle qui signe
`litellm.infra.famillelallier.net` et `ollama.infra.famillelallier.net`. Le fichier en
contient quatre, parce que l'autorité a été recréée plusieurs fois (août et septembre
2026) et que le trousseau du Mac les garde toutes. Une autorité de trop ne gêne pas ;
celle qui manque casse la connexion.

Aucune clé privée ici : `infra-ca.key` reste dans `certs/` de l'Infra, ignoré par git.

## S'en servir

- Outil Node (dont Claude Code) : `export NODE_EXTRA_CA_CERTS="$PWD/certs/infra-ca.crt"`.
  L'[orchestrateur](../agents/orchestrateur/) le fait tout seul.
- Outil Python qui ne parle qu'à l'Infra : `SSL_CERT_FILE` ou `REQUESTS_CA_BUNDLE`. Ces
  variables remplacent toutes les autorités : un outil qui appelle aussi GitHub ou une API
  publique ne peut plus les joindre.

## Mettre à jour la copie

Quand `make certs` de l'Infra recrée l'autorité, recopier depuis le trousseau du Mac :

```bash
security find-certificate -a -c "Infra Local Dev CA" -p > certs/infra-ca.crt
```

puis vérifier que LiteLLM répond :

```bash
curl --cacert certs/infra-ca.crt -sS -o /dev/null -w '%{http_code}\n' https://litellm.infra.famillelallier.net/health/liveliness
```
