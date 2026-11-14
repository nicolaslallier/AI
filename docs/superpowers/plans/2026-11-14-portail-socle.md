# Portail — Socle (A) : plan d'implémentation

> **Pour les agents qui exécutent :** SOUS-SKILL REQUIS : superpowers:subagent-driven-development (recommandé) ou superpowers:executing-plans, tâche par tâche. Les étapes utilisent des cases `- [ ]`.

**But :** un portail web (FastAPI + Postgres + Vue) où Nicolas crée un projet, lance un pipeline de spec, discute en streaming avec l'agent de spec via LiteLLM, fait rédiger puis corrige et valide la spec, et suit l'état de ses pipelines.

**Architecture :** un seul service Python, `portail`, sert l'API sous `/api` et l'interface Vue compilée. Le moteur de pipeline est une petite machine d'états en base, générique (N étapes, N agents). Chaque appel au modèle tourne dans une tâche asyncio du processus, qui enregistre lui-même le résultat. La page s'y abonne en SSE. Les agents et les types de pipeline sont décrits dans `agents.yaml`.

**Pile :** Python 3.12, uv, FastAPI, SQLAlchemy 2 (async, psycopg 3), Alembic, httpx, PyYAML, pydantic-settings, pytest + pytest-asyncio, ruff ; Vue 3 + Vite + TypeScript, vue-router, marked, DOMPurify, Vitest ; Docker, GitHub Actions, GHCR, Portainer.

**Spec :** `docs/superpowers/specs/2026-11-14-portail-socle-design.md`. À lire avant toute tâche.

## Contraintes globales

- Dépôt `nicolaslallier/AI`, partir de `main` à jour. Branche de travail : `claude/portail-socle`.
- Les noms du domaine sont en français, comme dans la spec : `projet`, `pipeline`, `etape`, `message`, `document`. Même chose pour les états : `a_faire`, `en_cours`, `en_attente`, `terminee`, `echouee`. Les textes de l'interface sont en français.
- Les agents sont décrits **uniquement** dans `agents.yaml`. Aucun nom d'agent ni de modèle dans le code Python, hors des tests.
- Aucun framework d'agents (ni PydanticAI, ni LangGraph…), aucune file d'attente, aucun worker séparé, pas de Rust.
- LiteLLM : API compatible OpenAI, `POST {url}/v1/chat/completions`, `stream: true`, en-tête `Authorization: Bearer <clé>`. Dans le homelab, l'URL est `http://litellm:4000`.
- Le message de Nicolas est enregistré en base **avant** l'appel au modèle. La réponse partielle n'est jamais enregistrée.
- Les blocs `<think>…</think>` ne sont ni affichés, ni enregistrés, ni mis dans le document.
- Jauge : on estime les jetons à `len(texte) // 4 + 4` par message. Alerte à partir de **0,75** × `contexte_max`. Envoi refusé à partir de **0,90** × `contexte_max`, pour laisser 10 % à la réponse.
- Délais httpx vers LiteLLM : connexion 10 s, lecture 300 s (les modèles locaux sont lents).
- Tout markdown produit par un modèle passe par DOMPurify avant d'être inséré dans la page.
- Variables d'environnement, toutes préfixées `PORTAIL_` : `DATABASE_URL`, `LITELLM_URL`, `LITELLM_CLE`, `AGENTS_FICHIER`, `EXIGER_UTILISATEUR`, `STATIC_DIR`.
- L'image s'appelle `ghcr.io/nicolaslallier/ai-portail`. Le workflow de déploiement n'a **jamais** de déclencheur `pull_request`.

## Points à surveiller en revue

1. **Deux envois simultanés** (double clic, deux onglets) sur la même étape : le second reçoit un `409`, et il n'y a jamais deux appels au modèle en parallèle sur une étape. *Test : tâche 7.*
2. **Une réponse vide, ou qui ne contient qu'un bloc `<think>`** : l'étape passe à `echouee` avec « réponse vide du modèle ». On n'enregistre ni message vide ni brouillon vide. *Test : tâche 7.*
3. **Un rechargement de page en plein flux** : un nouvel abonné reçoit d'abord le texte déjà produit (`partiel`), puis la suite. *Test : tâche 7.*
4. **Du HTML ou un script dans la spec rédigée par le modèle** : l'aperçu ne l'exécute jamais. *Test : tâche 9.*
5. **Valider sans brouillon, ou pendant qu'une réponse arrive** : refusé avec `409` et un message clair. *Test : tâche 8.*

---

### Task 1: squelette du backend et catalogue d'agents

**Fichiers :**
- Créer : `backend/pyproject.toml`, `backend/portail/__init__.py`, `backend/portail/config.py`, `backend/portail/agents.py`, `agents.yaml`, `backend/tests/test_agents.py`, `.github/workflows/ci.yml`, `.gitignore`
- Modifier : `README.md` (comment lancer en local, en quelques lignes)

**Interfaces :**
- Produit :
  - `class Reglages(BaseSettings)` avec `env_prefix="PORTAIL_"` et les champs suivants :
    - `database_url: str` ;
    - `litellm_url: str = "http://litellm:4000"` ;
    - `litellm_cle: str = ""` ;
    - `agents_fichier: Path = Path("agents.yaml")` ;
    - `exiger_utilisateur: bool = False` ;
    - `static_dir: Path | None = None`.
  - `class Agent(BaseModel)` avec les champs suivants :
    - `nom: str` ;
    - `description: str` ;
    - `modele: str` ;
    - `prompt_systeme: str` ;
    - `contexte_max: int` (> 0) ;
    - `temperature: float | None = None` ;
    - `consigne_redaction: str | None = None`.
  - `class Catalogue(BaseModel)` : `agents: dict[str, Agent]`, `pipelines: dict[str, list[str]]`.
  - `class CatalogueInvalide(Exception)`.
  - `def charger_catalogue(chemin: Path) -> Catalogue`.

Le format YAML (le `nom` d'un agent est sa clé) :

```yaml
agents:
  spec:
    description: Discute avec Nicolas pour écrire la spec d'un projet.
    modele: qwen3.8:27b-mlx
    contexte_max: 32768   # à ajuster au contexte réel du modèle dans LiteLLM
    temperature: 0.3
    prompt_systeme: |
      ...
    consigne_redaction: |
      ...
pipelines:
  spec: [spec]
```

- [ ] **Étape 1 : écrire les tests qui échouent** dans `backend/tests/test_agents.py`, avec des fichiers YAML écrits dans `tmp_path` :
  - `test_charge_catalogue_valide` : `cat.agents["spec"].nom == "spec"`, `cat.pipelines["spec"] == ["spec"]`, `cat.agents["spec"].temperature == 0.3`.
  - `test_champ_manquant_nomme_l_agent` : sans `modele`, on obtient `CatalogueInvalide`, et `"spec"` et `"modele"` apparaissent dans `str(exc)`.
  - `test_pipeline_agent_inconnu` : `pipelines: {spec: [inconnu]}` lève `CatalogueInvalide`, avec `"inconnu"` dans le message.
  - `test_pipeline_vide_refuse` : `pipelines: {spec: []}` lève `CatalogueInvalide`.
  - `test_yaml_illisible` : un fichier qui n'est pas du YAML valide lève `CatalogueInvalide`.
  - `test_agents_yaml_du_depot_est_valide` : `charger_catalogue(<racine du dépôt>/agents.yaml)` ne lève rien et contient le pipeline `spec`.
- [ ] **Étape 2 :** `cd backend && uv run pytest tests/test_agents.py -v` doit échouer (import impossible).
- [ ] **Étape 3 : implémenter** `config.py` et `agents.py`. La validation se fait avec Pydantic. On traduit `ValidationError`, `yaml.YAMLError` et les références inconnues en `CatalogueInvalide`, avec un message qui nomme l'agent et le champ. Écrire `agents.yaml`. Dans `prompt_systeme`, l'agent pose une question à la fois, en français, pour faire préciser l'intention, les objectifs, les non-objectifs, les contraintes et les cas limites, et ne rédige pas la spec tant qu'on ne le lui demande pas. Dans `consigne_redaction`, il produit la spec complète en markdown (Intention, Objectifs, Non-objectifs, Contraintes, Décisions, Questions ouvertes), seulement le document, sans préambule.
- [ ] **Étape 4 :** `uv run pytest tests/test_agents.py -v` donne PASS, puis `uv run ruff check . && uv run ruff format --check .` donne OK.
- [ ] **Étape 5 :** écrire `.github/workflows/ci.yml`, déclenché sur `pull_request` et `push` vers `main`. Le job `backend` (sur `ubuntu-latest`) fait : `astral-sh/setup-uv`, `uv sync`, `ruff check`, `ruff format --check`, `pytest`. Les tâches 2 et 9 complètent ce fichier.
- [ ] **Étape 6 : commit** `feat(portail): squelette backend et catalogue d'agents YAML`.

### Task 2: modèle de données, migration et états

**Fichiers :**
- Créer : `backend/portail/etats.py`, `backend/portail/db.py`, `backend/alembic.ini`, `backend/migrations/env.py`, `backend/migrations/versions/0001_initial.py`, `backend/tests/conftest.py`, `backend/tests/test_etats.py`, `docker-compose.test.yml`
- Modifier : `.github/workflows/ci.yml` (service postgres, `alembic upgrade head` avant pytest)

**Interfaces :**
- Produit :
  - `class Etat(StrEnum)` : `A_FAIRE="a_faire"`, `EN_COURS="en_cours"`, `EN_ATTENTE="en_attente"`, `TERMINEE="terminee"`, `ECHOUEE="echouee"`.
  - `def etat_pipeline(etats: list[Etat]) -> Etat`.
  - Les modèles SQLAlchemy de `db.py`, sur une `Base` déclarative. Les tables et colonnes :
    - `Projet` : `id`, `nom` (String 200), `description` (Text, défaut `""`), `cree_le`.
    - `Pipeline` : `id`, `projet_id`, `type`, `etat`, `cree_le`, `maj_le`.
    - `Etape` : `id`, `pipeline_id`, `ordre`, `agent`, `etat`, `erreur` (nullable), `action` (nullable : `"repondre"` | `"rediger"`).
    - `Message` : `id`, `etape_id`, `role` (`user` | `assistant` | `system`), `contenu`, `cree_le`.
    - `Document` : `id`, `projet_id`, `pipeline_id`, `etape_id` (unique), `type`, `contenu`, `etat` (`brouillon` | `validee`), `dernier_message_id` (nullable), `maj_le`.
  - Les relations : `Pipeline.etapes` (triées par `ordre`), `Etape.messages` (triés par `id`), `Etape.document`.
  - `def creer_moteur(url: str) -> AsyncEngine`, et `def fabrique_sessions(moteur) -> async_sessionmaker[AsyncSession]`.
  - Les fixtures pytest : `sessions` (un `async_sessionmaker` sur `PORTAIL_TEST_DATABASE_URL`, par défaut `postgresql+psycopg://portail:portail@localhost:5433/portail_test`). Le schéma est créé une fois par session de tests avec `Base.metadata.create_all`, et les tables sont vidées par `TRUNCATE … RESTART IDENTITY CASCADE` après chaque test.

`etat_pipeline` applique cette règle, dans cet ordre :
1. si une étape est `echouee`, le pipeline est `echouee` ;
2. sinon, si une étape est `en_attente`, il est `en_attente` ;
3. sinon, si toutes les étapes sont `terminee`, il est `terminee` ;
4. sinon, il est `en_cours`.

- [ ] **Étape 1 : écrire `test_etats.py`**, un test paramétré `test_etat_pipeline` avec ces cas :
  - `[TERMINEE, ECHOUEE, EN_ATTENTE]` donne `ECHOUEE` ;
  - `[TERMINEE, EN_ATTENTE]` donne `EN_ATTENTE` ;
  - `[TERMINEE, TERMINEE]` donne `TERMINEE` ;
  - `[TERMINEE, EN_COURS]` donne `EN_COURS` ;
  - `[TERMINEE, A_FAIRE]` donne `EN_COURS` ;
  - `[A_FAIRE, A_FAIRE]` donne `EN_COURS`.
- [ ] **Étape 2 :** pytest échoue.
- [ ] **Étape 3 : implémenter** `etats.py` et `db.py`. Écrire `0001_initial.py` à la main, pour qu'il corresponde exactement aux modèles. `migrations/env.py` lit `PORTAIL_DATABASE_URL`. Dans `docker-compose.test.yml` : un service `postgres:16-alpine`, port `5433:5432`, utilisateur, mot de passe et base `portail` / `portail` / `portail_test`.
- [ ] **Étape 4 :** `docker compose -f docker-compose.test.yml up -d`, puis `PORTAIL_DATABASE_URL=postgresql+psycopg://portail:portail@localhost:5433/portail_test uv run alembic upgrade head` réussit. Ensuite `uv run alembic downgrade base` réussit aussi, avant de relancer `upgrade head`. Puis pytest donne PASS.
- [ ] **Étape 5 :** dans la CI, ajouter le service `postgres:16-alpine` (variables `POSTGRES_USER`, `POSTGRES_PASSWORD` et `POSTGRES_DB` comme ci-dessus, port 5433, healthcheck `pg_isready`). Lancer `alembic upgrade head` puis `alembic downgrade base` avant pytest. Si la migration et les modèles ne correspondent plus, la CI échoue.
- [ ] **Étape 6 : commit** `feat(portail): modèle de données, migration initiale et états`.

### Task 3: moteur de pipeline

**Fichiers :**
- Créer : `backend/portail/moteur.py`, `backend/tests/test_moteur.py`

**Interfaces :**
- Consomme : `Etat` et `etat_pipeline`, les modèles de `db.py`, `Catalogue`.
- Produit (toutes ces fonctions sont `async` et prennent une `AsyncSession` ; l'appelant fait le commit) :
  - `creer_pipeline(session, catalogue: Catalogue, projet_id: int, type_: str) -> Pipeline`. Crée une étape par agent du type (`ordre` 0..n-1, toutes en `a_faire`), puis démarre la première. Lève `Refus(404, …)` si le type est inconnu.
  - `demarrer_etape(session, etape: Etape) -> None`. En A, toutes les étapes sont des chats : l'étape passe à `en_attente`, puisque c'est à Nicolas de parler.
  - `changer_etat(session, etape: Etape, etat: Etat, erreur: str | None = None) -> None`. Recalcule `pipeline.etat` avec `etat_pipeline` et met `pipeline.maj_le` à l'heure actuelle.
  - `terminer_etape(session, etape: Etape) -> None`. Passe l'étape à `terminee`, puis démarre l'étape suivante dans l'ordre, s'il y en a une.
  - `recuperer_interrompues(session) -> int`. Toutes les étapes `en_cours` passent à `echouee`, avec l'erreur `"interrompue par un redémarrage du serveur"`. Renvoie leur nombre.
  - `class Refus(Exception)`, avec `code: int` et `message: str`. Les tâches 6 à 8 le traduisent en réponse HTTP.

- [ ] **Étape 1 : écrire `test_moteur.py`** avec un `Catalogue` construit dans le test, qui contient deux agents `a` et `b` et un type `double: [a, b]` :
  - `test_creer_pipeline_demarre_la_premiere_etape` : 2 étapes, d'ordres 0 et 1. Les états sont `en_attente` et `a_faire`, et le pipeline est `en_attente`.
  - `test_terminer_enchaine_sur_la_suivante` : après `terminer_etape(étape 0)`, les états sont `terminee` et `en_attente`, et le pipeline est `en_attente`.
  - `test_terminer_la_derniere_termine_le_pipeline` : le pipeline passe à `terminee`.
  - `test_type_inconnu` : on obtient `Refus` avec le code 404.
  - `test_recuperer_interrompues` : une étape mise `en_cours`, puis récupérée, donne `echouee`, avec le texte d'erreur exact ci-dessus, et la fonction renvoie `1`. Le pipeline est alors `echouee`.
  - `test_changer_etat_met_a_jour_maj_le` : la nouvelle valeur de `maj_le` est plus grande que l'ancienne.
- [ ] **Étape 2 :** pytest échoue.
- [ ] **Étape 3 : implémenter** `moteur.py`.
- [ ] **Étape 4 :** pytest donne PASS.
- [ ] **Étape 5 : commit** `feat(portail): moteur de pipeline générique`.

### Task 4: client LiteLLM et filtre de réflexion

**Fichiers :**
- Créer : `backend/portail/llm.py`, `backend/tests/test_llm.py`

**Interfaces :**
- Produit :
  - `class ErreurLLM(Exception)`.
  - `class ClientLLM`, avec `__init__(self, url: str, cle: str, transport: httpx.AsyncBaseTransport | None = None)` et `async def flux(self, modele: str, messages: list[dict], temperature: float | None) -> AsyncIterator[str]`. `flux` produit les morceaux bruts de `choices[0].delta.content` et s'arrête sur `data: [DONE]`. Un statut HTTP différent de 2xx, une erreur réseau ou un délai dépassé lèvent `ErreurLLM`, avec le statut et le début du corps dans le message.
  - `class FiltreReflexion`, avec `envoyer(self, morceau: str) -> str` (renvoie la partie visible) et `finir(self) -> str`. Les balises peuvent être coupées entre deux morceaux. Ce que le filtre retient de la fin d'un morceau ne doit pas dépasser la longueur de `"</think>"`. Un `<think>` jamais refermé masque tout ce qui le suit.
  - `def retirer_reflexion(texte: str) -> str`.

- [ ] **Étape 1 : écrire `test_llm.py`** :
  - `test_flux_concatene_les_deltas` : un `httpx.MockTransport` renvoie trois lignes `data:` (`"Bon"`, `"jour"`, un delta sans `content`), puis `data: [DONE]`. Le résultat joint vaut `"Bonjour"`. Le test vérifie aussi que la requête a été envoyée à `/v1/chat/completions` avec `"stream": true` et l'en-tête `Authorization: Bearer k`.
  - `test_flux_erreur_http` : un statut `500` avec le corps `"boom"` lève `ErreurLLM`, et le message contient `500`.
  - `test_flux_erreur_reseau` : le transport lève `httpx.ConnectError`, ce qui donne `ErreurLLM`.
  - Un test paramétré `test_filtre_reflexion` qui découpe l'entrée **à chaque position possible** et vérifie que la sortie est identique :
    - `"<think>x</think>Salut"` donne `"Salut"` ;
    - `"A<think>x</think>B"` donne `"AB"` ;
    - `"pas de balise"` donne `"pas de balise"` ;
    - `"<think>jamais fermé"` donne `""` ;
    - `"a < b"` donne `"a < b"`.
- [ ] **Étape 2 :** pytest échoue.
- [ ] **Étape 3 : implémenter** `llm.py`. Le client utilise `httpx.AsyncClient(timeout=httpx.Timeout(300, connect=10))` et `client.stream("POST", …)`. On lit les lignes avec `aiter_lines()` en ne gardant que celles qui commencent par `data: `. `temperature` n'est envoyée que si elle n'est pas `None`.
- [ ] **Étape 4 :** pytest donne PASS.
- [ ] **Étape 5 : commit** `feat(portail): client LiteLLM en streaming et filtre <think>`.

### Task 5: contexte envoyé au modèle et jauge

**Fichiers :**
- Créer : `backend/portail/contexte.py`, `backend/tests/test_contexte.py`

**Interfaces :**
- Consomme : `Agent`, `Message` et `Document`.
- Produit :
  - `def construire(agent: Agent, messages: list[Message], document: Document | None, consigne: str | None = None) -> list[dict]`. Construit la liste de messages OpenAI, dans cet ordre :
    1. `{"role": "system", "content": agent.prompt_systeme}` ;
    2. s'il y a un `document`, un deuxième message `system` dont le contenu est exactement `"Brouillon courant de la spec (corrections de Nicolas incluses) :\n\n" + document.contenu` ;
    3. les messages `user` et `assistant` de l'étape. S'il y a un document, on ne garde que ceux dont `id > document.dernier_message_id` ; sinon, on les garde tous ;
    4. si une `consigne` est donnée, `{"role": "user", "content": consigne}` à la fin.
  - `def estimer_jetons(messages: list[dict]) -> int` : la somme de `len(content) // 4 + 4` pour chaque message.
  - `class Jauge(BaseModel)` avec `utilises: int`, `max: int`, `ratio: float` et `niveau: Literal["ok", "alerte", "plein"]`.
  - `def jauge(agent: Agent, messages_llm: list[dict]) -> Jauge`. Le niveau est `alerte` si `ratio >= 0.75`, et `plein` si `ratio >= 0.90`.

- [ ] **Étape 1 : écrire `test_contexte.py`**, avec des objets `Message` et `Document` construits en mémoire, sans base :
  - `test_sans_brouillon_tout_l_historique` : 3 messages donnent `system` suivi des 3, dans l'ordre.
  - `test_avec_brouillon_seulement_les_messages_apres` : un document avec `dernier_message_id=2` et les messages 1 à 4 donnent `[system, system(brouillon), msg3, msg4]`. Le deuxième message commence par `"Brouillon courant de la spec"`.
  - `test_consigne_ajoutee_en_dernier`.
  - `test_estimer_jetons` : `[{"role":"user","content":"x"*40}]` donne `14`.
  - Un test paramétré `test_niveaux_jauge`, avec `contexte_max=100` : 74 donne `ok`, 75 `alerte`, 89 `alerte`, 90 `plein`. Il construit les messages pour obtenir ces totaux, ou appelle une fonction interne `_niveau(ratio)`.
- [ ] **Étape 2 :** pytest échoue.
- [ ] **Étape 3 : implémenter** `contexte.py`.
- [ ] **Étape 4 :** pytest donne PASS.
- [ ] **Étape 5 : commit** `feat(portail): contexte envoyé au modèle et jauge`.

### Task 6: application FastAPI, projets et pipelines

**Fichiers :**
- Créer : `backend/portail/api.py`, `backend/portail/schemas.py`, `backend/tests/test_api_projets.py`
- Modifier : `backend/tests/conftest.py`, pour ajouter la fixture `client`

**Interfaces :**
- Consomme : `Reglages`, `charger_catalogue`, `creer_moteur` / `fabrique_sessions`, `creer_pipeline`, `recuperer_interrompues`, `Refus`.
- Produit :
  - `def create_app(reglages: Reglages | None = None, llm: ClientLLM | None = None, catalogue: Catalogue | None = None) -> FastAPI`. Elle est lancée par `uvicorn --factory portail.api:create_app`. Au démarrage (lifespan), elle charge le catalogue (une erreur fait échouer le démarrage), crée le moteur de base, appelle `recuperer_interrompues` puis fait le commit, et range tout dans `app.state`.
  - Le gestionnaire d'exceptions `Refus` renvoie `JSONResponse(status_code=refus.code, content={"detail": refus.message})`.
  - Le middleware d'utilisateur : si `reglages.exiger_utilisateur` est vrai et que le chemin commence par `/api/`, mais pas par `/api/sante`, sans en-tête `X-Auth-Request-Email`, la réponse est `401 {"detail": "non authentifié"}`.
  - Les routes :
    - `GET /api/sante` renvoie `{"ok": true}` ;
    - `GET /api/projets` renvoie la liste `[{id, nom, description, cree_le}]`, triée par `nom` ;
    - `POST /api/projets {nom, description?}` renvoie `201` et le projet. Le `nom` est nettoyé des espaces et doit faire de 1 à 200 caractères, sinon `422` ;
    - `GET /api/projets/{id}` renvoie le projet, plus `pipelines: [...]` (même forme que la liste ci-dessous) et `spec_courante: {id, contenu, maj_le} | null`, c'est-à-dire le dernier `Document` de type `spec`, à l'état `validee`, selon `maj_le` ;
    - `GET /api/pipelines?etat=` renvoie `[{id, projet_id, projet_nom, type, etat, maj_le}]`, triés par `maj_le` décroissant ;
    - `POST /api/pipelines {projet_id, type}` renvoie `201` et le détail. Un projet inconnu donne `404` ;
    - `GET /api/pipelines/{id}` renvoie le détail, dont la forme est fixée dans `schemas.py` : `{id, projet: {id, nom}, type, etat, maj_le, etapes: [{id, ordre, agent, etat, erreur, action, messages: [{id, role, contenu, cree_le}], document: {id, contenu, etat, maj_le} | null, jauge: Jauge}]}`. La `jauge` d'une étape est calculée sur `construire(agent, messages, document)`, c'est-à-dire ce que le prochain envoi transmettrait, avant le nouveau message.
  - La fixture `client` est un `httpx.AsyncClient(transport=ASGITransport(app))`. L'application est créée avec la base de tests, le catalogue de tests et un `FauxLLM`. Le catalogue de tests contient :
    - les agents `spec` (avec `consigne_redaction`, `contexte_max=32768`), `a` et `b`, et `petit` (`contexte_max=50`) ;
    - les types `spec: [spec]`, `double: [a, b]` et `petit: [petit]`.

    Le `FauxLLM`, défini dans `conftest.py`, dont on règle à l'avance les morceaux renvoyés ou l'exception levée. Le lifespan est exécuté avec `asgi-lifespan` (`LifespanManager`), à ajouter aux dépendances de dev.

- [ ] **Étape 1 : écrire `test_api_projets.py`** :
  - `test_creer_et_lister_projets` : on crée « Zeta » puis « Alpha », et la liste revient dans l'ordre `["Alpha", "Zeta"]`.
  - `test_nom_vide_refuse` : `"   "` donne `422`.
  - `test_creer_pipeline_spec` : `201`, une étape `spec` en `en_attente`, `document` à `null`, et `jauge.niveau == "ok"`.
  - `test_pipeline_projet_inconnu` donne `404`, et `test_pipeline_type_inconnu` donne `404`.
  - `test_filtre_par_etat` : sur deux pipelines, l'un terminé avec `moteur.terminer_etape` directement en base, `?etat=terminee` n'en renvoie qu'un.
  - `test_spec_courante_est_la_derniere_validee` : deux documents `spec` validés, le plus récent selon `maj_le` est renvoyé. Un brouillon plus récent est ignoré.
  - `test_utilisateur_exige` : avec `exiger_utilisateur=True`, `GET /api/projets` sans l'en-tête donne `401`, avec l'en-tête donne `200`, et `GET /api/sante` sans l'en-tête donne `200`.
  - `test_redemarrage_marque_les_etapes_interrompues` : une étape mise `en_cours` en base, puis une nouvelle application démarrée sur la même base, donne `echouee`.
- [ ] **Étape 2 :** pytest échoue.
- [ ] **Étape 3 : implémenter** `api.py` et `schemas.py`.
- [ ] **Étape 4 :** pytest donne PASS (tous les tests).
- [ ] **Étape 5 : commit** `feat(portail): API projets et pipelines`.

### Task 7: chat en streaming (tâche de fond et SSE)

**Fichiers :**
- Créer : `backend/portail/chat.py`, `backend/tests/test_chat.py`
- Modifier : `backend/portail/api.py`, pour ajouter les routes du chat

**Interfaces :**
- Consomme : `ClientLLM.flux`, `FiltreReflexion`, `construire`, `jauge`, `changer_etat`, `Refus`.
- Produit :
  - `class Diffuseur` :
    - `abonner(etape_id) -> tuple[str, asyncio.Queue]` renvoie le texte partiel déjà produit et une file ;
    - `desabonner(etape_id, file)` ;
    - `publier(etape_id, evenement: dict)` ;
    - `ajouter_partiel(etape_id, texte)` ;
    - `oublier(etape_id)`.
  - `class ServiceChat` :
    - `__init__(sessions, catalogue, llm, diffuseur)` ;
    - `async envoyer(etape_id: int, contenu: str) -> None` ;
    - `async rediger(etape_id: int) -> None` ;
    - `async reessayer(etape_id: int) -> None` ;
    - `taches: dict[int, asyncio.Task]` : les tests attendent `service.taches[etape_id]`.
  - Les règles :
    - `envoyer` n'est accepté que si l'étape est `en_attente`, sinon `Refus(409, "une réponse est déjà en cours" | "étape non active")`. Le contenu est nettoyé des espaces et ne doit pas être vide, sinon `Refus(422, …)`. Si la jauge calculée **avec** le nouveau message est `plein`, on renvoie `Refus(409, "contexte presque plein : clique « Rédiger la spec » pour continuer")`. Sinon, dans une même transaction : on enregistre le message `user`, on passe l'étape à `en_cours` avec `action="repondre"`, puis on fait le **commit**, et seulement ensuite on lance la tâche de fond.
    - `rediger` : l'étape doit être `en_attente` et l'agent doit avoir une `consigne_redaction`, sinon `Refus(409, …)`. On passe l'étape à `en_cours` avec `action="rediger"`, puis on lance la tâche.
    - `reessayer` : l'étape doit être `echouee`, sinon `Refus(409, …)`. On passe l'étape à `en_cours` en gardant la même `action`, puis on lance la tâche.
    - La tâche de fond :
      1. Elle construit les messages. En `rediger`, elle ajoute `consigne=agent.consigne_redaction`.
      2. Elle lit `llm.flux(...)` à travers `FiltreReflexion` et, pour chaque partie visible, appelle `ajouter_partiel` puis publie `{"type": "delta", "texte": ...}`.
      3. À la fin, le texte visible est nettoyé des espaces. S'il est vide, l'étape passe à `echouee` avec « réponse vide du modèle ».
      4. Sinon, en `repondre`, on enregistre un message `assistant`. En `rediger`, on crée ou met à jour le `Document` de l'étape avec : `type="spec"` (c'est le nom du type de pipeline), `contenu`, `etat="brouillon"`, `dernier_message_id` = le plus grand id de message de l'étape, et `maj_le`.
      5. L'étape passe à `en_attente` et on publie `{"type": "fin"}`.
      6. Toute exception (dont `ErreurLLM`) fait passer l'étape à `echouee` avec `str(exc)`, et on publie `{"type": "erreur", "message": ...}`.
      7. Dans tous les cas, on finit par `oublier(etape_id)`.
  - Les routes renvoient `202 {}`, ou l'erreur de `Refus` :
    - `POST /api/etapes/{id}/messages {contenu}` ;
    - `POST /api/etapes/{id}/rediger` ;
    - `POST /api/etapes/{id}/reessayer`.
  - `GET /api/etapes/{id}/flux` est un `text/event-stream`. Chaque événement s'écrit `event: <type>\ndata: <json>\n\n`. Si l'étape n'est pas `en_cours`, le serveur envoie `fin` et ferme. Sinon, il envoie d'abord `partiel {"texte": <partiel>}`, puis relaie les événements de la file jusqu'à `fin` ou `erreur`, et se désabonne même si le client se déconnecte.

- [ ] **Étape 1 : écrire `test_chat.py`** avec le `FauxLLM` :
  - `test_echange_complet` : le faux modèle renvoie `["<think>hm</think>", "Quelle ", "cible ?"]`. Après l'envoi de « Un portail », on attend la tâche. Les messages sont alors `[user "Un portail", assistant "Quelle cible ?"]`, l'étape est `en_attente`, et ce que le faux modèle a reçu commence par le prompt système.
  - `test_message_enregistre_avant_l_appel_et_reessayer` : le faux modèle lève `ErreurLLM("injoignable")`. L'étape passe à `echouee`, son erreur contient « injoignable », et le message `user` est bien en base. Ensuite, le faux modèle renvoie `["Ok"]`. Après `POST reessayer` et l'attente de la tâche, il y a un message `assistant` « Ok », l'étape est `en_attente`, et le message `user` n'a **pas** été dupliqué.
  - `test_double_envoi_409` : le faux modèle est bloqué sur un `asyncio.Event`. Le deuxième `POST messages` donne `409`. Puis on libère l'événement.
  - `test_reponse_vide_echoue` : le faux modèle renvoie `["<think>rien</think>", "  "]`. L'étape passe à `echouee`, avec l'erreur exacte « réponse vide du modèle », et aucun message `assistant` n'est enregistré.
  - `test_rediger_cree_le_brouillon_et_reduit_le_contexte` : deux échanges, puis `rediger` avec un faux modèle qui renvoie `"# Spec\n..."`. Le document est un `brouillon` avec ce contenu, et `dernier_message_id` est le dernier id. Après un nouvel envoi, les messages transmis au faux modèle sont `[system, system(brouillon), user(nouveau)]`.
  - `test_contexte_plein_refuse` : sur un pipeline de type `petit` (agent dont `contexte_max=50`), un message de 400 caractères donne `409`, avec « Rédiger la spec » dans `detail`, et rien n'est enregistré.
  - `test_flux_sse_et_reprise_en_cours` : le faux modèle produit `"A"`, puis attend un événement, puis produit `"B"`. Pendant l'attente, on ouvre `GET flux` : le premier événement est `partiel` avec `{"texte": "A"}`. On libère l'événement : on reçoit `delta` « B », puis `fin`.
  - `test_flux_etape_inactive` : sur une étape `en_attente`, on reçoit tout de suite `fin`.
- [ ] **Étape 2 :** pytest échoue.
- [ ] **Étape 3 : implémenter** `chat.py` et les routes. Chaque tâche de fond ouvre sa propre session à partir de `sessions`.
- [ ] **Étape 4 :** pytest donne PASS (tous les tests).
- [ ] **Étape 5 : commit** `feat(portail): chat en streaming avec tâche de fond et SSE`.

### Task 8: édition et validation du document

**Fichiers :**
- Modifier : `backend/portail/chat.py` (ou `api.py` si c'est plus simple), pour ajouter deux routes
- Créer : `backend/tests/test_document.py`

**Interfaces :**
- Consomme : `terminer_etape`, `Refus`.
- Produit :
  - `PUT /api/etapes/{id}/document {contenu}` renvoie `200` et le document. Le document doit exister, sinon `409` « aucun brouillon à corriger ». Il doit être à l'état `brouillon`, sinon `409` « spec déjà validée ». L'étape ne doit pas être `en_cours`, sinon `409`. Cette route met à jour `contenu` et `maj_le`, mais **pas** `dernier_message_id`.
  - `POST /api/etapes/{id}/valider` renvoie `200` et le détail du pipeline. L'étape doit être `en_attente` et avoir un document à l'état `brouillon`, sinon `409` avec, selon le cas, « rien à valider : clique d'abord « Rédiger la spec » » ou « une réponse est en cours ». La validation passe le document à `validee`, puis appelle `terminer_etape`.

- [ ] **Étape 1 : écrire `test_document.py`** :
  - `test_corriger_puis_valider` : on fait rédiger, puis `PUT` « # Spec corrigée », puis `valider`. On obtient un document `validee` avec le contenu corrigé, une étape `terminee` et un pipeline `terminee`. `GET /api/projets/{id}` renvoie cette spec dans `spec_courante`.
  - `test_correction_prise_en_compte_par_l_agent` : après le `PUT`, un envoi transmet au faux modèle un brouillon qui contient « Spec corrigée ».
  - `test_valider_sans_brouillon_409`.
  - `test_valider_pendant_une_reponse_409` (le faux modèle est bloqué).
  - `test_spec_validee_figee` : un `PUT` après la validation donne `409`.
- [ ] **Étape 2 :** pytest échoue.
- [ ] **Étape 3 : implémenter.**
- [ ] **Étape 4 :** pytest donne PASS (tous les tests).
- [ ] **Étape 5 : commit** `feat(portail): correction et validation de la spec`.

### Task 9: frontend, squelette, liste des pipelines et projets

**Fichiers :**
- Créer : `frontend/` (Vite, Vue 3, TS : `package.json`, `vite.config.ts`, `tsconfig.json`, `index.html`, `src/main.ts`, `src/App.vue`, `src/router.ts`), `src/api.ts`, `src/markdown.ts`, `src/markdown.test.ts`, `src/views/PipelinesView.vue`, `src/views/ProjetsView.vue`, `src/views/ProjetView.vue`, `src/components/EtatBadge.vue`
- Modifier : `.github/workflows/ci.yml`, pour ajouter le job `frontend`

**Interfaces :**
- Consomme : les routes des tâches 6 à 8.
- Produit :
  - `src/api.ts` contient les types TS qui reflètent `schemas.py` (`Projet`, `PipelineResume`, `PipelineDetail`, `Etape`, `Message`, `Document`, `Jauge`), et des fonctions `fetch` sous `/api` :
    - `listerProjets`, `creerProjet`, `lireProjet` ;
    - `listerPipelines(etat?)`, `creerPipeline`, `lirePipeline` ;
    - `envoyerMessage`, `rediger`, `reessayer`, `enregistrerDocument`, `valider`.

    Chaque fonction lève `ErreurApi(status, detail)` quand la réponse n'est pas OK.
  - `rendreMarkdown(texte: string): string` vaut `DOMPurify.sanitize(marked.parse(texte))`.
  - Les routes Vue : `/` (`PipelinesView`), `/projets`, `/projets/:id`, `/pipelines/:id`. La dernière est faite à la tâche 10 ; pour l'instant, la route peut pointer vers un composant vide.
  - `EtatBadge` affiche ces libellés : `a_faire` « À faire », `en_cours` « En cours », `en_attente` « En attente de toi », `terminee` « Terminé », `echouee` « Échoué ».
  - Dans `vite.config.ts`, le serveur de dev renvoie `/api` vers `http://localhost:8000`.

- [ ] **Étape 1 : écrire `src/markdown.test.ts`** :
  - `rendreMarkdown("# T")` contient `<h1>` ;
  - `rendreMarkdown("<img src=x onerror=alert(1)>")` ne contient pas `onerror` ;
  - `rendreMarkdown("<script>alert(1)</script>")` ne contient pas `<script`.
- [ ] **Étape 2 :** `cd frontend && npm test` échoue.
- [ ] **Étape 3 : implémenter** le squelette, `api.ts`, `markdown.ts`, puis les vues :
  - `PipelinesView` : un tableau avec projet, type, `EtatBadge` et la date de mise à jour. Un filtre par état (`<select>`). La liste est rafraîchie toutes les **5 s** par `setInterval`, arrêté au démontage. Le bouton « Nouveau pipeline » ouvre un formulaire pour choisir un projet existant ou en créer un ; il crée un pipeline de type `spec` et ouvre `/pipelines/:id`.
  - `ProjetsView` : la liste des projets et un formulaire de création.
  - `ProjetView` : les pipelines du projet et la spec courante, rendue avec `rendreMarkdown`.

  Les scripts de `package.json` : `dev`, `build` (`vue-tsc --noEmit && vite build`), `typecheck`, `test` (`vitest run`).
- [ ] **Étape 4 :** `npm test` donne PASS, puis `npm run build` réussit.
- [ ] **Étape 5 :** dans la CI, ajouter le job `frontend` : `actions/setup-node` (node 22), `npm ci`, `npm run typecheck`, `npm test`, `npm run build`.
- [ ] **Étape 6 : commit** `feat(portail): interface Vue, liste des pipelines et projets`.

### Task 10: frontend, détail d'un pipeline (chat, jauge, éditeur)

**Fichiers :**
- Créer : `frontend/src/views/PipelineView.vue`, `frontend/src/components/ChatEtape.vue`, `frontend/src/components/JaugeContexte.vue`, `frontend/src/components/EditeurDocument.vue`, `frontend/src/flux.ts`, `frontend/src/flux.test.ts`

**Interfaces :**
- Consomme : `api.ts`, `rendreMarkdown`, `EtatBadge`, la route SSE de la tâche 7.
- Produit :
  - `ecouterFlux(etapeId: number, rappels: {partiel(t: string), delta(t: string), fin(), erreur(m: string)}): () => void`. Elle passe par `EventSource` sur `/api/etapes/{id}/flux`, s'abonne aux événements nommés, et ferme la connexion sur `fin` ou `erreur`. La fonction renvoyée sert à se désabonner.
  - Le comportement de `PipelineView` :
    - Au montage, on charge le pipeline. Pour chaque étape `en_cours`, on appelle `ecouterFlux`.
    - Le texte en cours de réception s'affiche comme une bulle `assistant` provisoire : `partiel` la remplace, `delta` s'y ajoute.
    - Sur `fin` ou `erreur`, on recharge le pipeline.
    - Après un `POST` accepté (`envoyer`, `rediger`, `reessayer`), on recharge le pipeline, puis on appelle `ecouterFlux`.
    - Une `ErreurApi` en `409` ou `422` affiche son `detail` au-dessus de la zone de saisie.
  - `ChatEtape` affiche :
    - les messages : ceux de l'utilisateur à droite ; ceux de l'assistant à gauche, rendus avec `rendreMarkdown` ;
    - une zone de saisie : Entrée envoie, Maj+Entrée fait un saut de ligne. Elle est désactivée si l'étape n'est pas `en_attente` ou si la jauge est `plein` ;
    - les boutons « Rédiger la spec » (actif seulement si l'étape est `en_attente`) et « Réessayer » (visible seulement si elle est `echouee`, avec le texte de `erreur`).
  - `JaugeContexte` affiche une barre `utilises / max`. Au niveau `alerte`, elle affiche « Le contexte se remplit : clique « Rédiger la spec » pour que l'agent reparte du brouillon. ». Au niveau `plein`, « Contexte plein : rédige la spec pour continuer. ».
  - `EditeurDocument` affiche un `<textarea>` et l'aperçu rendu par `rendreMarkdown`, côte à côte. « Enregistrer » est actif s'il y a des changements. « Valider » est désactivé s'il y a des changements non enregistrés, si l'étape n'est pas `en_attente` ou si le document n'est pas un `brouillon`. Une spec `validee` s'affiche en lecture seule, avec le badge « Validée ».

- [ ] **Étape 1 : écrire `src/flux.test.ts`** avec un faux `EventSource` (une classe injectée par `globalThis.EventSource`) :
  - `partiel` puis `delta` appellent les rappels avec les bons textes ;
  - `fin` appelle `fin()` puis ferme la source (`close` est appelé) ;
  - la fonction de désabonnement ferme la source.
- [ ] **Étape 2 :** `npm test` échoue.
- [ ] **Étape 3 : implémenter** `flux.ts` et les composants.
- [ ] **Étape 4 :** `npm test` et `npm run build` donnent PASS.
- [ ] **Étape 5 : vérification manuelle**, avec `docker compose -f docker-compose.test.yml up -d`, le backend lancé par `uvicorn --factory portail.api:create_app --reload` (avec `PORTAIL_LITELLM_URL` et `PORTAIL_LITELLM_CLE` qui pointent vers le vrai LiteLLM, si on y a accès) et `npm run dev`. Parcours :
  1. créer un projet, puis lancer un pipeline ;
  2. échanger deux messages, et recharger la page pendant une réponse : le texte reprend là où il en était ;
  3. cliquer « Rédiger la spec », corriger le brouillon, l'enregistrer, puis valider.

  Le pipeline est alors « Terminé » dans la liste, et la spec apparaît sur la page du projet. Sans accès à LiteLLM, on fait le même parcours avec un faux serveur OpenAI minimal ; à défaut, on le note comme non vérifié.
- [ ] **Étape 6 : commit** `feat(portail): détail d'un pipeline avec chat, jauge et éditeur de spec`.

### Task 11: image, service des fichiers statiques et déploiement

**Fichiers :**
- Créer : `Dockerfile`, `.dockerignore`, `deploy/portainer-stack.yml`, `deploy/nginx/portail.conf`, `.github/workflows/deploy.yml`, `backend/tests/test_static.py`
- Modifier : `backend/portail/api.py`, pour servir les fichiers statiques et le repli SPA ; `README.md`, pour la section Déploiement

**Interfaces :**
- Produit :
  - Si `reglages.static_dir` est défini, on sert `/assets/*` depuis `static_dir/assets`. Tout `GET` qui ne commence pas par `/api/` et ne correspond à aucun fichier existant renvoie `static_dir/index.html` : c'est le repli SPA.
  - L'image `ghcr.io/nicolaslallier/ai-portail` :
    - l'étape `node:22-alpine` lance `npm ci && npm run build` ;
    - l'étape `python:3.12-slim` contient uv, lance `uv sync --frozen --no-dev` dans `/app/backend`, copie `dist` dans `/app/static` et `agents.yaml` dans `/app/agents.yaml`, et tourne en utilisateur non root ;
    - les variables `PORTAIL_STATIC_DIR=/app/static` et `PORTAIL_AGENTS_FICHIER=/app/agents.yaml` sont fixées ;
    - `CMD ["sh","-c","alembic upgrade head && exec uvicorn --factory portail.api:create_app --host 0.0.0.0 --port 8000"]`.

- [ ] **Étape 1 : écrire `test_static.py`.** Avec un `static_dir` dans `tmp_path`, qui contient `index.html` (`"<html>portail</html>"`) et `assets/a.js` :
  - `GET /pipelines/3` donne `200` et contient `portail` ;
  - `GET /assets/a.js` donne `200` ;
  - `GET /api/inexistant` donne `404` en JSON, pas l'`index.html`.
- [ ] **Étape 2 :** pytest échoue.
- [ ] **Étape 3 : implémenter** le service des fichiers statiques, puis écrire `Dockerfile` et `.dockerignore` (en excluant `node_modules`, `.venv`, `.git` et `docs`).
- [ ] **Étape 4 :** pytest donne PASS. Ensuite, `docker build -t portail:local .` réussit, et `docker run --rm -e PORTAIL_DATABASE_URL=… -p 8000:8000 portail:local` (contre la base de tests) répond `{"ok": true}` sur `GET /api/sante` et sert l'interface sur `/`.
- [ ] **Étape 5 :** écrire `deploy/portainer-stack.yml`, avec un service `portail` :
  - `image: ghcr.io/nicolaslallier/ai-portail:${IMAGE_TAG:-latest}` ;
  - l'environnement : `PORTAIL_DATABASE_URL=postgresql+psycopg://portail:${PORTAIL_DB_PASSWORD:?}@postgres:5432/portail`, `PORTAIL_LITELLM_URL=http://litellm:4000`, `PORTAIL_LITELLM_CLE=${PORTAIL_LITELLM_CLE:?}`, `PORTAIL_EXIGER_UTILISATEUR=true` ;
  - le réseau externe `infra-net`, **aucun port publié** ;
  - un healthcheck en Python, `urllib` sur `http://localhost:8000/api/sante` ;
  - `mem_limit: 512m` ;
  - `restart: unless-stopped`.
- [ ] **Étape 6 :** écrire `deploy/nginx/portail.conf`, sur le modèle de `Infra/nginx/conf.d/jarvis.conf` :
  - `server_name portail.infra.famillelallier.net` ;
  - `resolver 127.0.0.11` et `set $upstream http://portail:8000` ;
  - les locations `/oauth2/auth` et `/oauth2/` vers l'oauth2-proxy, avec les tampons de 16k ;
  - `auth_request /oauth2/auth` sur **tout** le site, `/api/` compris, avec `auth_request_set $email $upstream_http_x_auth_request_email` et `proxy_set_header X-Auth-Request-Email $email` (l'en-tête envoyé par le client est ainsi toujours écrasé) ;
  - pour `location /api/etapes/` (le SSE) : `proxy_buffering off`, `proxy_read_timeout 1h` et `proxy_http_version 1.1`.
- [ ] **Étape 7 :** écrire `.github/workflows/deploy.yml`, sur le modèle du `deploy.yml` de DarkAngel, en gardant son commentaire d'avertissement sur `pull_request` :
  - déclenché par `push` sur `main` et `workflow_dispatch` ;
  - un seul job sur `ubuntu-latest`, avec `permissions: packages: write` ;
  - `docker/metadata-action`, avec `images: ghcr.io/${{ github.repository }}-portail` et les tags `latest` et `sha` ;
  - `docker/build-push-action`, en amd64 seulement. Ajouter le commentaire `# ponytail: amd64 seul (hôte de déploiement) ; ajouter arm64 comme DarkAngel si la pile doit tourner sur le Mac mini.` ;
  - pas de redéploiement Portainer automatique : on fait « Pull and redeploy » à la main, comme l'indique le README.
- [ ] **Étape 8 : commit** `feat(portail): image Docker, pile Portainer et vhost NGINX`.

### Task 12: PR dans le dépôt Infra (brouillon, sans fusion)

À confier à l'agent `dev-infra`, dans `~/Code/Infra`, sur une branche dédiée, en **PR brouillon**. On ne pousse jamais sur `main` et on ne fusionne pas.

**Changements :**
- **Base** : ajouter `portail` à `APP_DATABASES`, et `PORTAIL_DB_PASSWORD` à `.env.example`. Documenter `make provision-app app=portail` pour une base déjà en service.
- **Vhost** : copier `deploy/nginx/portail.conf` du dépôt `AI` dans `nginx/conf.d/portail.conf`. Ajouter l'entrée DNS de `portail.infra.famillelallier.net` par la même voie que les autres vhosts (`dns-provision` ou la config DNS du dépôt).
- **Porte Keycloak** : suivre `keycloak/CLAUDE.md`. Réutiliser l'oauth2-proxy existant si son domaine de cookie et son client couvrent `portail.infra.famillelallier.net` ; sinon, ajouter un client Keycloak et une instance oauth2-proxy dédiée, avec la même recette que Jarvis. Justifier le choix dans la PR.
- **LiteLLM** : documenter la création d'une clé virtuelle `portail`, limitée aux modèles de `agents.yaml`, et sa variable `PORTAIL_LITELLM_CLE`. La clé n'est jamais mise dans le dépôt.
- **Portainer** : ajouter la pile `portail` (qui pointe vers `deploy/portainer-stack.yml` du dépôt `AI`) à l'endroit où l'Infra liste ses piles (`stacks.conf`).
- **Vérification** : `make check-env` passe, et `nginx -t` passe dans le conteneur nginx (ou avec la commande de test existante du dépôt).
- [ ] **Commit et PR brouillon** `feat(portail): base, vhost, porte Keycloak et clé LiteLLM du portail`. Le lien vers la PR du dépôt `AI` va dans la description.
