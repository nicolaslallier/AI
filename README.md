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

Le workflow `.github/workflows/deploy.yml` construit les images `ghcr.io/nicolaslallier/ai-portail`, `ai-lanceur` et `ai-execution` (amd64) à chaque push sur `main` et la publie avec les tags `latest` et `sha-<7 premiers caractères du commit>`. Le job `deploy` enchaîne alors le redéploiement de la pile `portail` dans Portainer (voir « Redéploiement automatique »).

- **Pile Portainer** : `deploy/portainer-stack.yml`, sur le réseau externe `infra-net`, sans port publié. Variables à renseigner dans la pile : `PORTAIL_DB_PASSWORD` (mot de passe du rôle `portail` de Postgres, sans `@ : / %` ni autre caractère spécial d'URL, ou alors encodé en pourcentage : il est inséré tel quel dans l'URL de la base), `PORTAIL_LITELLM_CLE` (clé LiteLLM) et `IMAGE_TAG` (le déploiement automatique l'impose à `sha-<7>` ; `latest` n'est que le défaut quand il est absent, par exemple pour une pile créée à la main).
- **NGINX** : `deploy/nginx/portail.conf` est le vhost `portail.infra.famillelallier.net`. Il se copie dans `Infra/nginx/conf.d/` par une PR séparée sur le dépôt Infra.
- **Authentification** : `oauth2-proxy-portail` de l'Infra (Keycloak, realm `infra`, groupe `portail`). Un utilisateur sans adresse e-mail reçoit un 401 sur tous les appels de l'API.
- **Redéploiement automatique** : le job `deploy` (runner auto-hébergé `ai`) lit `PORTAIL_DB_PASSWORD` et `PORTAIL_LITELLM_CLE` dans OpenBao (secret KV v2 `infra/portail`, lu via l'API à `infra/data/portail` ; `scripts/vault-render-env.sh`), puis `scripts/portainer-stack.sh up` crée la pile `portail` depuis `deploy/portainer-stack.yml` (premier passage) ou la redéploie en retirant l'image `sha-<7>` que ce run vient de construire. Portainer relit le compose sur GitHub `main` ; l'API réécrit toute la liste des variables à chaque déploiement, le script les renvoie donc toutes. Sans effet sur `*.md` et `docs/**`.
  - Environnement GitHub `production` (Settings → Environments), limité à la branche `main`, qui porte les secrets `PORTAINER_API_KEY` (jeton d'accès Portainer) et `BAO_TOKEN` (jeton OpenBao, lecture seule de `infra/data/portail`). Le job `deploy` ne tourne que sur `main`.
  - Le jeton OpenBao est périodique (32 jours) et renouvelé à chaque déploiement ; sans déploiement pendant 32 jours, en créer un nouveau.
  - Variables du dépôt : `PORTAINER_URL` (défaut `https://portainer.infra.famillelallier.net`), `VAULT_URL` (défaut `https://vault.infra.famillelallier.net`), `PORTAINER_ENDPOINT_ID` (obligatoire), `VAULT_SECRET_PATH` (défaut `infra/data/portail`), `INFRA_CA_CERT_PATH` (chemin de la CA de l'Infra dans le runner, défaut `/etc/ai/infra-ca.crt`).
  - Clés du secret KV v2 `infra/portail` (lu via l'API à `infra/data/portail`) : `PORTAIL_DB_PASSWORD`, `PORTAIL_LITELLM_CLE`, `PORTAIL_GITHUB_JETON`, `PORTAIL_GITHUB_APP_ID`, `PORTAIL_GITHUB_APP_CLE`, `PORTAIL_LANCEUR_SECRET`, `PORTAIL_NTFY_JETON`.
  - Aucun workflow du dépôt ne doit avoir de déclencheur `pull_request`, `pull_request_target`, `issue_comment` ou `workflow_run` pouvant atteindre le label self-hosted `ai` : une PR de fork peut modifier `ci.yml` elle-même. Le dépôt est public : exiger l'approbation pour tous les collaborateurs externes (Settings → Actions → General → Fork pull request workflows from outside collaborators), et le runner `ai` doit être éphémère (conteneur neuf par job, aucun volume de travail persistant).
  - Le déploiement n'attend pas la CI : activer la protection de branche sur `main` avec les contrôles de CI obligatoires.

### Jeton GitHub (lecture seule)

Le portail lit les dépôts GitHub avec un jeton à grain fin (fine-grained), limité aux dépôts choisis, avec les permissions **Contents : Read** et **Metadata : Read** seulement, et sans aucune permission d'écriture. Il est rangé dans OpenBao (clé `PORTAIL_GITHUB_JETON` du secret `infra/portail`), que le déploiement automatique recopie dans la pile, et ne va jamais dans le dépôt. Les données du portail vivent dans le volume `portail-donnees-2`, monté sur `/donnees` (l'ancien `portail-donnees` appartient à l'ancien uid et reste orphelin : à supprimer à la main).

### GitHub App du portail (boucle de dev)

La boucle de dev pousse des branches et ouvre des PR par une GitHub App, jamais par le jeton en lecture seule ci-dessus.

1. Créer l'App (Settings → Developer settings → GitHub Apps) avec les permissions **Contents : Read & write**, **Pull requests : Read & write**, **Metadata : Read**, et **sans** Administration ni webhook. Générer une clé privée (`cle.pem`).
2. L'installer sur les seuls dépôts voulus. La branche par défaut de chaque dépôt doit être **protégée** : sinon le portail refuse de lancer le pipeline `dev`.
3. Ranger dans OpenBao, secret `infra/portail` : `PORTAIL_GITHUB_APP_ID` (l'id de l'App), `PORTAIL_GITHUB_APP_CLE` (le PEM en **base64 sur une seule ligne** : `base64 -w0 cle.pem` sous Linux, `base64 -i cle.pem | tr -d '\n'` sous macOS) et `PORTAIL_LANCEUR_SECRET` (`openssl rand -hex 32`, 32 caractères au moins).
4. Le lanceur (service `lanceur`, seul à monter `/var/run/docker.sock`) démarre les commandes des agents dans des conteneurs jetables de l'image `ai-execution`, sur le réseau `run-net` et le proxy `run-egress` de l'Infra (PR « run-net » du dépôt Infra, à déployer avant ce dépôt). Hôte Docker en version **26 ou plus** (montage de sous-chemin de volume).
5. **Prérequis bloquant :** `PORTAIL_LANCEUR_SECRET` (32 caractères au moins) doit exister dans OpenBao `infra/portail` **avant** la fusion et le déploiement de ce dépôt. Sinon le déploiement échoue : `scripts/vault-render-env.sh` s'arrête si la clé manque et le lanceur quitte (redémarrage en boucle) avec un secret de moins de 32 caractères. `PORTAIL_GITHUB_APP_ID` et `PORTAIL_GITHUB_APP_CLE` sont facultatives : absentes, le script les écrit vides avec un avertissement, et le portail garde son ordonnanceur éteint ; le reste fonctionne comme avant.

### Reprise sur commentaires et ntfy

Quand Nicolas commente la PR d'une tâche *En revue*, le portail reprend la boucle de dev sur la même branche et la même PR, puis notifie par ntfy.

- Le jeton ntfy s'obtient avec `make ntfy-provision app=portail` dans l'Infra et se range dans OpenBao, secret `infra/portail`, clé `PORTAIL_NTFY_JETON`, clé facultative : absente, `scripts/vault-render-env.sh` l'écrit vide avec un avertissement et le portail n'envoie pas de notification.
- Seuls les commentaires de `PORTAIL_GITHUB_PROPRIETAIRE` déclenchent une reprise.
- Une revue part tout de suite ; des commentaires isolés partent 10 minutes après le dernier.
- Recommenter relance une reprise échouée.

Exemple de configuration d'exécution pour EA (l'image doit figurer dans `LANCEUR_IMAGES`). Les commandes partent de la racine du dépôt, et `{fichiers}` y est remplacé par des chemins relatifs à cette racine (`backend/tests/test_x.py`) : ne pas faire `cd backend` avant `{fichiers}`. Les motifs de `chemins_tests` désignent des fichiers : `backend/tests/**`, pas `backend/tests`.

```yaml
image: ghcr.io/nicolaslallier/ai-execution:latest
chemins_tests: ["backend/tests/**"]
commandes:
  installer: uv sync --project backend
  tests: uv run --project backend pytest -q backend/tests
  tests_cibles: uv run --project backend pytest -q {fichiers}
  lint: uv run --project backend ruff check backend
services:
  - nom: db
    image: pgvector/pgvector:pg16
    env: {POSTGRES_PASSWORD: test}
```

La commande `tests_cibles` doit sortir en non-zéro seulement quand des tests échouent : à la vérification « rouge », les codes 3 et 4 (erreur interne ou d'usage de pytest) bloquent la tâche (« commande de tests invalide ») et le code 5 (aucun test collecté) la bloque comme « aucun test écrit ». Tout autre code non nul compte comme un vrai rouge (pytest 1 et 2, jest et vitest 1, cargo 101).
