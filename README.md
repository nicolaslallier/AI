# AI

Dépôt remis à zéro le 14 novembre 2026.

L'historique précédent (labo MLX, dépôt d'outils IA, mcp-fichiers) reste dans `git log`.

## Lancer en local

```sh
cd backend
uv sync
uv run pytest
```

## Déploiement

Le workflow `.github/workflows/deploy.yml` construit l'image `ghcr.io/nicolaslallier/ai-portail` (amd64) à chaque push sur `main` et la publie avec les tags `latest` et `sha-<commit>`. Le job `deploy` enchaîne alors le redéploiement de la pile `portail` dans Portainer (voir « Redéploiement automatique »).

- **Pile Portainer** : `deploy/portainer-stack.yml`, sur le réseau externe `infra-net`, sans port publié. Variables à renseigner dans la pile : `PORTAIL_DB_PASSWORD` (mot de passe du rôle `portail` de Postgres, sans `@ : / %` ni autre caractère spécial d'URL, ou alors encodé en pourcentage : il est inséré tel quel dans l'URL de la base), `PORTAIL_LITELLM_CLE` (clé LiteLLM) et `IMAGE_TAG` (optionnel, `latest` par défaut).
- **NGINX** : `deploy/nginx/portail.conf` est le vhost `portail.infra.famillelallier.net`. Il se copie dans `Infra/nginx/conf.d/` par une PR séparée sur le dépôt Infra.
- **Authentification** : un utilisateur Keycloak sans adresse e-mail reçoit un 401 sur tous les appels de l'API.
- **Redéploiement automatique** : le job `deploy` (runner auto-hébergé `ai`) lit `PORTAIL_DB_PASSWORD` et `PORTAIL_LITELLM_CLE` dans OpenBao (`infra/env`, `scripts/vault-render-env.sh`), puis `scripts/portainer-stack.sh up` crée la pile `portail` depuis `deploy/portainer-stack.yml` (premier passage) ou la redéploie en retirant l'image `latest`. Portainer relit le compose sur GitHub `main` ; l'API réécrit toute la liste des variables à chaque déploiement, le script les renvoie donc toutes. Sans effet sur `*.md` et `docs/**`.
  - Secrets du dépôt : `PORTAINER_API_KEY` (jeton d'accès Portainer), `BAO_TOKEN` (jeton OpenBao en lecture de `infra/env`).
  - Variables du dépôt : `PORTAINER_URL` (défaut `https://portainer.infra.famillelallier.net`), `VAULT_URL` (défaut `https://vault.infra.famillelallier.net`), `PORTAINER_ENDPOINT_ID` (optionnel, sinon le premier environnement Docker local), `INFRA_CA_CERT_PATH` (chemin de la CA de l'Infra dans le runner, défaut `/etc/ai/infra-ca.crt`).
  - Clés du coffre (`infra/env`) : `PORTAIL_DB_PASSWORD`, `PORTAIL_LITELLM_CLE`.
  - Ne jamais ajouter de déclencheur `pull_request` à ce workflow : le dépôt est public et le runner tient les secrets.
