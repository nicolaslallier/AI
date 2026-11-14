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

Le workflow `.github/workflows/deploy.yml` construit l'image `ghcr.io/nicolaslallier/ai-portail` (amd64) à chaque push sur `main` et la publie avec les tags `latest` et `sha-<7 premiers caractères du commit>`. Le job `deploy` enchaîne alors le redéploiement de la pile `portail` dans Portainer (voir « Redéploiement automatique »).

- **Pile Portainer** : `deploy/portainer-stack.yml`, sur le réseau externe `infra-net`, sans port publié. Variables à renseigner dans la pile : `PORTAIL_DB_PASSWORD` (mot de passe du rôle `portail` de Postgres, sans `@ : / %` ni autre caractère spécial d'URL, ou alors encodé en pourcentage : il est inséré tel quel dans l'URL de la base), `PORTAIL_LITELLM_CLE` (clé LiteLLM) et `IMAGE_TAG` (le déploiement automatique l'impose à `sha-<7>` ; `latest` n'est que le défaut quand il est absent, par exemple pour une pile créée à la main).
- **NGINX** : `deploy/nginx/portail.conf` est le vhost `portail.infra.famillelallier.net`. Il se copie dans `Infra/nginx/conf.d/` par une PR séparée sur le dépôt Infra.
- **Authentification** : `oauth2-proxy-portail` de l'Infra (Keycloak, realm `infra`, groupe `portail`). Un utilisateur sans adresse e-mail reçoit un 401 sur tous les appels de l'API.
- **Redéploiement automatique** : le job `deploy` (runner auto-hébergé `ai`) lit `PORTAIL_DB_PASSWORD` et `PORTAIL_LITELLM_CLE` dans OpenBao (secret KV v2 `infra/portail`, lu via l'API à `infra/data/portail` ; `scripts/vault-render-env.sh`), puis `scripts/portainer-stack.sh up` crée la pile `portail` depuis `deploy/portainer-stack.yml` (premier passage) ou la redéploie en retirant l'image `sha-<7>` que ce run vient de construire. Portainer relit le compose sur GitHub `main` ; l'API réécrit toute la liste des variables à chaque déploiement, le script les renvoie donc toutes. Sans effet sur `*.md` et `docs/**`.
  - Environnement GitHub `production` (Settings → Environments), limité à la branche `main`, qui porte les secrets `PORTAINER_API_KEY` (jeton d'accès Portainer) et `BAO_TOKEN` (jeton OpenBao, lecture seule de `infra/data/portail`). Le job `deploy` ne tourne que sur `main`.
  - Le jeton OpenBao est périodique (32 jours) et renouvelé à chaque déploiement ; sans déploiement pendant 32 jours, en créer un nouveau.
  - Variables du dépôt : `PORTAINER_URL` (défaut `https://portainer.infra.famillelallier.net`), `VAULT_URL` (défaut `https://vault.infra.famillelallier.net`), `PORTAINER_ENDPOINT_ID` (obligatoire), `VAULT_SECRET_PATH` (défaut `infra/data/portail`), `INFRA_CA_CERT_PATH` (chemin de la CA de l'Infra dans le runner, défaut `/etc/ai/infra-ca.crt`).
  - Clés du secret KV v2 `infra/portail` (lu via l'API à `infra/data/portail`) : `PORTAIL_DB_PASSWORD`, `PORTAIL_LITELLM_CLE`, `PORTAIL_GITHUB_JETON`.
  - Aucun workflow du dépôt ne doit avoir de déclencheur `pull_request`, `pull_request_target`, `issue_comment` ou `workflow_run` pouvant atteindre le label self-hosted `ai` : une PR de fork peut modifier `ci.yml` elle-même. Le dépôt est public : exiger l'approbation pour tous les collaborateurs externes (Settings → Actions → General → Fork pull request workflows from outside collaborators), et le runner `ai` doit être éphémère (conteneur neuf par job, aucun volume de travail persistant).
  - Le déploiement n'attend pas la CI : activer la protection de branche sur `main` avec les contrôles de CI obligatoires.

### Jeton GitHub (lecture seule)

Le portail lit les dépôts GitHub avec un jeton à grain fin (fine-grained), limité aux dépôts choisis, avec les permissions **Contents : Read** et **Metadata : Read** seulement, et sans aucune permission d'écriture. Il est rangé dans OpenBao (clé `PORTAIL_GITHUB_JETON` du secret `infra/portail`), que le déploiement automatique recopie dans la pile, et ne va jamais dans le dépôt. Les données du portail vivent dans le volume `portail-donnees`, monté sur `/donnees`.
