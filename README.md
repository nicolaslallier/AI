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

Le workflow `.github/workflows/deploy.yml` construit l'image `ghcr.io/nicolaslallier/ai-portail` (amd64) à chaque push sur `main` et la publie avec les tags `latest` et `sha-<commit>`. Il ne redéploie rien.

- **Pile Portainer** : `deploy/portainer-stack.yml`, sur le réseau externe `infra-net`, sans port publié. Variables à renseigner dans la pile : `PORTAIL_DB_PASSWORD` (mot de passe du rôle `portail` de Postgres, sans `@ : / %` ni autre caractère spécial d'URL, ou alors encodé en pourcentage : il est inséré tel quel dans l'URL de la base), `PORTAIL_LITELLM_CLE` (clé LiteLLM) et `IMAGE_TAG` (optionnel, `latest` par défaut).
- **NGINX** : `deploy/nginx/portail.conf` est le vhost `portail.infra.famillelallier.net`. Il se copie dans `Infra/nginx/conf.d/` par une PR séparée sur le dépôt Infra.
- **Authentification** : un utilisateur Keycloak sans adresse e-mail reçoit un 401 sur tous les appels de l'API.
- **Mise à jour** : après la publication de l'image, dans Portainer, ouvrir la pile et cliquer sur « Pull and redeploy ».

### Jeton GitHub (lecture seule)

Le portail lit les dépôts GitHub avec un jeton à grain fin (fine-grained), limité aux dépôts choisis, avec les permissions **Contents : Read** et **Metadata : Read** seulement, et sans aucune permission d'écriture. Il se configure dans les variables de la pile Portainer (`PORTAIL_GITHUB_JETON`) et ne va jamais dans le dépôt. Les données du portail vivent dans le volume `portail-donnees`, monté sur `/donnees`.
