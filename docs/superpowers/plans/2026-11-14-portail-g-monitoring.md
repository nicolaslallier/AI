# Portail G — Monitoring et tableaux de bord : plan d'implémentation

> **Pour les agents qui exécutent :** SOUS-SKILL REQUIS : superpowers:subagent-driven-development (recommandé) ou superpowers:executing-plans, tâche par tâche. Les étapes utilisent des cases `- [ ]`.

**But :** Nicolas voit dans Grafana la santé du portail, l'avancement de la boucle de dev, la consommation de chaque agent et l'activité du lanceur, et il est prévenu par ntfy quand ça casse — sans qu'aucun contenu ne sorte dans une métrique, une étiquette ou un journal.

**Architecture :** aucun service nouveau. Le backend gagne un module `metriques.py` (toutes les métriques, la collecte en base et la route `/metrics`), une table `appel_llm` remplie par `ClientLLM` lui-même, et des journaux JSON portés par le `journal.py` créé en F. Les identifiants (pipeline, étape, tâche, conversation, agent, mission) circulent dans une `ContextVar` posée là où une tâche de fond démarre : les journaux et `ClientLLM` les lisent sans changer aucune signature, donc l'arbitre `LLMArbitre` de D, qui enveloppe `ClientLLM` avec la même interface, ne change rien à la mesure. Les tableaux de bord et les alertes vivent en JSON et en YAML dans `deploy/grafana/` et sont recopiés par une PR Infra.

**Pile :** Python 3.12 / FastAPI / SQLAlchemy / Alembic / pytest ; `prometheus-client` (seule dépendance nouvelle) ; `logging` de la bibliothèque standard ; Grafana (provisionnement par fichiers) ; NGINX.

**Spec :** `docs/superpowers/specs/2026-11-14-portail-f-i-ameliorations-design.md`, section « G — Monitoring et tableaux de bord ». **On suppose D puis F construits sur la même branche** : `LLMArbitre` (D, `backend/portail/arbitre.py`), `journal.erreur` et `deploy/infra/README.md` (F, tâches 3 et 5), la fonction `_flux` de `api.py` (F, tâche 9), le gestionnaire global d'exception (F, tâche 5).

## Contraintes globales

- Toutes les contraintes de F s'appliquent : français partout, pas de refonte de `dev.py` ni de `api.py` (on y ajoute des lignes, on n'y déplace rien), vérifications avant chaque commit backend : `cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest -q`.
- **Aucun contenu** (prompt, réponse du modèle, spec, code, sortie de commande, titre de tâche, message d'exception) dans une métrique, une étiquette, une ligne de journal ou une colonne de `appel_llm`. Seulement identifiants, noms (agent, modèle, outil, commande, route, phase), compteurs, durées, codes.
- **Aucune étiquette à forte cardinalité** : jamais d'identifiant (tâche, pipeline, étape, conversation, mission), jamais de chemin brut, jamais une valeur choisie par le modèle. Valeurs permises : noms tirés de `agents.yaml`, de la configuration d'exécution du projet, des modèles de route FastAPI, ou d'une liste fixe nommée dans ce plan.
- Une seule dépendance nouvelle : `prometheus-client`. Journaux : `logging` seul. Pas de traces distribuées, pas d'OpenTelemetry.
- Un seul processus uvicorn : le registre par défaut de `prometheus-client`, sans mode multiprocessus.
- La migration de G prend **la prochaine révision libre** : nom `backend/migrations/versions/<NNNN>_appel_llm.py`, `down_revision` = la tête donnée par `uv run alembic heads` au moment de l'écrire (D et F en ajoutent avant G). Ne pas figer de numéro dans le code ni dans les tests.
- Tests de métriques par **différence** : lire `REGISTRY.get_sample_value(nom, etiquettes) or 0.0` avant et après, jamais une valeur absolue (le registre vit toute la session de tests). L'aide `valeur(nom, **etiquettes) -> float` va dans `backend/tests/conftest.py` (tâche 1).
- Rien n'est modifié hors de ce dépôt ; ce que l'Infra doit recopier est listé à la tâche 11.

## Points à surveiller en revue

1. **Une étiquette qui explose** : un nom d'outil inventé par le modèle, un chemin brut (`/api/taches/987654`) au lieu du modèle de route, un identifiant glissé en étiquette — tâches 4 et 5, tests `test_tours_et_outils` et `test_requete_par_modele_de_route`.
2. **Une exception de bibliothèque journalisée par `logger.exception`** (uvicorn, SQLAlchemy) dont le message porte du contenu : `FormatJSON` ne rend que la classe et la pile, jamais `str(exception)` — tâche 2, `test_exception_rendue_sans_message`.
3. **Une inscription dans `appel_llm` qui échoue** (base saturée) ne fait jamais échouer l'appel au modèle — tâche 3, `test_inscription_impossible_n_arrete_pas_l_appel`.
4. **L'arbitre de D** : la mesure est dans `ClientLLM`, sous `LLMArbitre` ; la durée inscrite exclut l'attente du tour, et un appel n'est inscrit qu'une fois — tâche 3, `test_sous_l_arbitre`.
5. **Une tâche asyncio enfant qui hérite d'identifiants périmés** (une étape de chat qui lance la suivante, une conversation qui lance une étape) : chaque point d'entrée appelle `journal.commencer`, qui **remplace** le contexte — tâche 2.
6. **`/metrics` avalé par le repli SPA** ou bloqué par l'exigence d'utilisateur : la route est enregistrée avant le repli et hors de `/api/` — tâche 1.

---

### Task 1: Point `/metrics` et échéance du déploiement

**Fichiers :**
- Créer : `backend/portail/metriques.py`, `backend/tests/test_metriques.py`
- Modifier : `backend/pyproject.toml`, `backend/uv.lock`, `backend/portail/config.py`, `backend/portail/api.py` (lifespan, route), `backend/tests/conftest.py`
- Modifier : `deploy/portainer-stack.yml`, `.github/workflows/deploy.yml`, `scripts/portainer-stack.sh`, `deploy/nginx/portail.conf`

**Interfaces :**
- `Reglages` gagne `version: str = ""` (`PORTAIL_VERSION`) et `deploye_le: int = 0` (`PORTAIL_DEPLOYE_LE`, secondes Unix).
- `metriques.py` déclare au niveau du module (les compteurs sans `_total`, que `prometheus-client` ajoute) :
  - `INFO = Gauge("portail_info", …, ["version"])` (valeur 1) ;
  - `DEPLOIEMENT = Gauge("portail_deploiement_horodatage_secondes", …)` ;
  - `DUREE_MAX_TACHE = Gauge("portail_duree_max_tache_secondes", …)` (exporte `duree_max_tache_s` : l'alerte ne recopie pas le seuil à la main).
- `def initialiser(r: Reglages) -> None` : pose ces trois jauges. Appelée dans le lifespan.
- Route `GET /metrics` (`include_in_schema=False`), enregistrée **avant** le repli SPA : `Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)`. Elle n'est pas sous `/api/` : le middleware `_utilisateur` ne l'exige pas d'en-tête.
- `conftest.py` : `def valeur(nom: str, **etiquettes: str) -> float`.

- [ ] **Étape 1 : tests qui échouent** dans `test_metriques.py`, sur une application créée avec `Reglages(database_url=URL, version="sha-test", deploye_le=1_700_000_000, …)` :
  - `test_metrics_format_prometheus` : `GET /metrics` → 200, `content-type` commence par `text/plain`, le corps contient `portail_info{version="sha-test"} 1.0` et `portail_deploiement_horodatage_secondes 1.7e+09` ;
  - `test_metrics_hors_authentification` : avec `exiger_utilisateur=True` et sans `X-Auth-Request-Email`, `/metrics` → 200 alors que `/api/projets` → 401 ;
  - `test_metrics_avant_le_repli_spa` : avec un `static_dir` de test (`index.html` et `assets/`), `/metrics` rend des métriques, pas `index.html` ;
  - `test_vhost_refuse_metrics` : `deploy/nginx/portail.conf` contient un bloc `location ^~ /metrics { return 404; }` (expression régulière tolérante aux espaces).
- [ ] **Étape 2 :** ils échouent.
- [ ] **Étape 3 : implémenter.** `uv add prometheus-client` ; `metriques.py` ; `initialiser(r)` dans le lifespan ; la route. Dans le vhost, au niveau `server`, avant `location /` :

```nginx
    # Métriques : Prometheus les lit sur infra-net (portail:8000), jamais par le frontal.
    location ^~ /metrics {
        return 404;
    }
```

- [ ] **Étape 4 :** la suite passe.
- [ ] **Étape 5 : pile et déploiement.** `deploy/portainer-stack.yml`, service `portail` : `PORTAIL_VERSION: ${IMAGE_TAG:-latest}` et `PORTAIL_DEPLOYE_LE: ${DEPLOYE_LE:-0}`. `deploy.yml`, à côté de la ligne `IMAGE_TAG` : `printf 'DEPLOYE_LE=%s\n' "$(date +%s)" >> "$PORTAIL_STACK_ENV"`. `scripts/portainer-stack.sh` : ajouter `DEPLOYE_LE` à `REQUIRED`.
- [ ] **Étape 6 : commit** `feat(portail): point /metrics et échéance du déploiement`.

### Task 2: Journaux JSON avec identifiants

**Fichiers :**
- Modifier : `backend/portail/journal.py` (créé en F)
- Créer : `backend/journal.json`
- Modifier : `Dockerfile` (`CMD`), `backend/portail/dev.py` (`executer`, `_charger`, `_etape`, `_agent`), `backend/portail/chat.py` (`ServiceChat._tache`), `backend/portail/conversations.py` (`ServiceConversation._tache`), et les tâches de fond de D qui appellent le modèle (`backend/portail/avis.py`, tâche lancée par `ServiceAvis.lancer` ; `backend/portail/resume.py`, `resumer_si_du`)
- Modifier : `backend/tests/conftest.py` (`FauxLLM`)
- Test : `backend/tests/test_journal.py`, `backend/tests/test_dev.py`, `backend/tests/test_conversations.py`

**Interfaces :**
- Dans `journal.py` :
  - `IDS = ("pipeline", "etape", "tache", "conversation", "agent", "mission")` ;
  - `contexte: ContextVar[dict] = ContextVar("contexte_portail", default={})` — jamais muté en place : chaque écriture pose un dict neuf ;
  - `def commencer(**valeurs) -> None` : **remplace** le contexte (point d'entrée d'une tâche de fond) ;
  - `def lier(**valeurs) -> None` : complète le contexte ; une valeur `None` retire la clé ;
  - `def nouvelle_mission(agent: str, contexte_max: int | None = None) -> str` : pose `agent`, `mission` (`uuid4().hex[:12]`) et `contexte_max`, rend l'identifiant de mission ;
  - `class FormatJSON(logging.Formatter)` : une ligne `{"quand": ISO UTC, "niveau", "module": record.name, "message": record.getMessage(), <ids présents de IDS>}` ; si `record.exc_info` : `"exception": <nom de classe>` et `"pile": "".join(traceback.format_tb(tb))`, **jamais** `str(exception)` ni `formatException`. `contexte_max` n'est pas journalisé.
- `backend/journal.json` : `dictConfig` (version 1, `disable_existing_loggers: false`), formateur `{"()": "portail.journal.FormatJSON"}`, un `StreamHandler` sur `ext://sys.stdout`, racine en `INFO` ; `uvicorn`, `uvicorn.error`, `uvicorn.access` sans gestionnaire propre et `propagate: true`.
- `CMD` : `uvicorn … --log-config journal.json --no-access-log` (les requêtes sont comptées par la tâche 5).
- Où le contexte est posé :
  - `Orchestrateur.executer` : `commencer(pipeline=pipeline_id)` ; `_charger` : `lier(tache=ex.tache_id)` ; `_etape` : `lier(etape=etape.id, agent=agent, mission=None)` ; `_agent` : `nouvelle_mission(nom, agent.contexte_max)` après `_etape`. Les relances JSON de `_tri` et `_revue` (et des contrôles de D) restent ainsi dans la mission de l'agent ;
  - `ServiceChat._tache` : `commencer(etape=etape_id)`, puis `lier(pipeline=etape.pipeline_id)` et `nouvelle_mission(agent.nom, agent.contexte_max)` ;
  - `ServiceConversation._tache` : `commencer(conversation=cid)` puis `nouvelle_mission(agent.nom, agent.contexte_max)` ;
  - les tâches de fond de D (avis, résumé du matin) : `commencer(pipeline=…)` puis `nouvelle_mission(…)`.
- `FauxLLM.flux` et `.completer` ajoutent `"contexte": dict(journal.contexte.get())` à chaque entrée de `appels`.

- [ ] **Étape 1 : tests qui échouent.**
  - `test_journal.py` :
    - `test_ligne_json_avec_identifiants` : après `commencer(pipeline=3)` et `lier(etape=7, agent="code")`, un `LogRecord` formaté par `FormatJSON` donne un JSON avec `niveau`, `module`, `message`, `pipeline == 3`, `etape == 7`, `agent == "code"`, et ni `tache` ni `contexte_max` ;
    - `test_exception_rendue_sans_message` : `logging.getLogger("tiers").exception("échec")` dans un `except ValueError(MARQUEUR)`, formaté par `FormatJSON` : contient `"exception": "ValueError"`, pas `MARQUEUR` ;
    - `test_tache_enfant_sans_identifiants_perimes` : sous `commencer(conversation=1)`, une tâche créée qui appelle `commencer(etape=2)` voit `{"etape": 2}` ; le parent garde `{"conversation": 1}`.
  - `test_dev.py`, `test_identifiants_d_un_agent_dev` : sur le parcours de `test_parcours_complet_ouvre_une_pr`, l'appel du `FauxLLM` fait pour l'agent `tests` porte `pipeline`, `tache`, `etape`, `agent == "tests"` et une `mission` ; celui de `code` porte une autre `mission`.
  - `test_conversations.py`, `test_identifiants_d_une_conversation` : l'appel porte `conversation == cid`, `agent == "orchestrateur"`, une `mission`, et aucune clé `etape`.
- [ ] **Étape 2 :** ils échouent.
- [ ] **Étape 3 : implémenter**, puis la suite passe.
- [ ] **Étape 4 : vérifier dans l'image**, avec la base de test et la commande `docker run` de F (tâche 3, étape 7) : `docker logs portail-essai 2>&1 | grep '^{' | head -3 | python -m json.tool` réussit (les lignes d'Alembic au démarrage restent en texte : acceptable).
- [ ] **Étape 5 : commit** `feat(portail): journaux JSON avec identifiants de mission`.

### Task 3: Table `appel_llm`

**Fichiers :**
- Modifier : `backend/portail/db.py` (modèle `AppelLLM`), `backend/portail/llm.py` (`ClientLLM`), `backend/portail/api.py` (lifespan : `ClientLLM` construit après `fabrique_sessions`)
- Créer : `backend/migrations/versions/<NNNN>_appel_llm.py` (prochaine révision libre), `backend/tests/test_appel_llm.py`

**Interfaces :**
- Table `appel_llm` (H la lit pour l'activité du jour par agent et les dernières missions ; I y ajoute le lieu `conteneur`) :
  - `id` (entier, clé primaire) ; `quand` (horodatage avec fuseau, défaut maintenant) ;
  - `agent` (texte) ; `modele` (texte) ;
  - `lieu` (texte, défaut `portail` ; I ajoute `conteneur`, sans contrainte de valeurs) ; `version_image` (texte, nullable) ;
  - `mission` (texte, nullable, indexé) ;
  - `pipeline_id`, `etape_id`, `tache_id`, `conversation_id` (entiers nullables, **sans** clé étrangère : la ligne survit à l'objet, comme `tache_evenement`) ;
  - `jetons_entree`, `jetons_sortie` (entiers nullables : nuls si LiteLLM ne rend pas l'usage) ;
  - `duree_ms` (entier) ; `issue` (texte : `ok` | `erreur` | `delai`) ;
  - index `ix_appel_llm_agent_quand (agent, quand)`.
- `ClientLLM.__init__(self, url, cle, transport=None, sessions: async_sessionmaker[AsyncSession] | None = None, version: str = "")`. Le lifespan passe `sessions=app.state.sessions, version=r.version`.
- `async def _noter(self, modele: str, issue: str, usage: dict | None, debut: float) -> None` : lit `journal.contexte`, inscrit une ligne (`agent` = `contexte.get("agent", "inconnu")`, `lieu` = `contexte.get("lieu", "portail")`, `version_image` = `contexte.get("version_image", self._version)`, les ids présents) dans sa propre session ; toute exception est attrapée et passée à `journal.erreur(logger, "appel_llm non inscrit")`. Sans `sessions`, n'inscrit rien.
- `completer` et `flux` mesurent avec `time.monotonic()` et appellent `_noter` sur succès (`ok`) et sur chaque `ErreurLLM` levée (`delai` pour `httpx.TimeoutException`, `erreur` sinon). *ponytail : une annulation (`CancelledError`, `GeneratorExit` d'un flux abandonné) n'inscrit rien ; l'inscrire si H montre des trous.*
- `flux` envoie `"stream_options": {"include_usage": True}` et retient le dernier `usage` non nul vu dans un morceau (le morceau final de LiteLLM a `choices: []` et `usage`). `completer` lit `reponse.json().get("usage")`.

- [ ] **Étape 1 : tests qui échouent** dans `test_appel_llm.py` (`httpx.MockTransport` comme `test_llm.py`, fixture `sessions`) :
  - `test_completer_inscrit_l_appel` : sous `commencer(pipeline=1, etape=2, tache=3)` et `nouvelle_mission("code", 1000)`, une réponse avec `usage: {prompt_tokens: 10, completion_tokens: 5}` → une ligne : `agent="code"`, `modele="m"`, `lieu="portail"`, `version_image="sha-test"`, la `mission`, les trois ids, `conversation_id` nul, jetons 10 et 5, `issue="ok"`, `duree_ms >= 0` ;
  - `test_flux_demande_l_usage` : le corps envoyé porte `stream_options.include_usage == True` ; un dernier morceau `{"choices": [], "usage": {…}}` donne les jetons de la ligne ; le texte rendu est inchangé ;
  - `test_issue_delai_et_erreur`, paramétré : `httpx.ReadTimeout` → `issue="delai"`, réponse 500 → `issue="erreur"` ; `ErreurLLM` est toujours levée ;
  - `test_inscription_impossible_n_arrete_pas_l_appel` : avec une fabrique de sessions qui lève, `completer` rend la réponse ;
  - `test_sous_l_arbitre` : `LLMArbitre(client, Arbitre(), "fond").completer(…)` inscrit **une** ligne ;
  - `test_colonnes_sans_contenu` : `set(AppelLLM.__table__.columns.keys())` est exactement l'ensemble ci-dessus (un champ de texte libre ajouté plus tard fait échouer ce test).
- [ ] **Étape 2 :** ils échouent.
- [ ] **Étape 3 : implémenter** modèle, migration, `ClientLLM`, lifespan. `uv run alembic upgrade head && uv run alembic check && uv run alembic downgrade -1 && uv run alembic upgrade head` passent.
- [ ] **Étape 4 :** la suite passe (les tests existants de `test_llm.py` aussi : `ClientLLM` sans `sessions` se comporte comme avant).
- [ ] **Étape 5 : commit** `feat(portail): table appel_llm, usage demandé en flux`.

### Task 4: Métriques des agents et des modèles

**Fichiers :**
- Modifier : `backend/portail/metriques.py`, `backend/portail/llm.py` (`_noter`), `backend/portail/boucle.py` (`boucle_outils`)
- Test : `backend/tests/test_appel_llm.py`, `backend/tests/test_boucle.py`

**Interfaces (dans `metriques.py`) :**
- `portail_llm_appels_total{agent, modele, lieu, issue}` ;
- `portail_llm_jetons_total{agent, modele, lieu, sens}`, `sens` ∈ `entree` | `sortie` ;
- `portail_llm_duree_secondes{agent, modele, lieu}`, histogramme, seaux `(1, 5, 15, 30, 60, 120, 300)` ;
- `portail_contexte_remplissage{agent}`, histogramme du rapport `jetons_entree / contexte_max` (vrais jetons rendus par LiteLLM, `contexte_max` lu dans `journal.contexte`), seaux `(0.25, 0.5, 0.75, 0.9, 1.0)` ;
- `portail_tours_mission{agent}`, histogramme du nombre d'appels à `completer` d'une `boucle_outils`, seaux `(1, 2, 4, 8, 12, 16, 20, 30)` ;
- `portail_outils_appels_total{agent, outil, issue}` : `outil` = le nom s'il est dans `agent.outils`, sinon `non_autorise` (outil hors liste) ou `mal_forme` (nom absent ou non textuel) ; `issue` ∈ `ok` | `erreur` (mal formé, ou résultat qui commence par `erreur`) | `refuse` (hors liste).
- `lieu` sert à la comparaison avant/après de I ; `version_image` reste dans `appel_llm` seulement (une valeur nouvelle à chaque déploiement).

- [ ] **Étape 1 : tests qui échouent.**
  - `test_metriques_d_un_appel` (`test_appel_llm.py`) : le scénario de `test_completer_inscrit_l_appel` augmente de 1 `portail_llm_appels_total{agent="code",modele="m",lieu="portail",issue="ok"}`, de 10 et 5 les deux séries de jetons, de 1 `portail_llm_duree_secondes_count` et `portail_contexte_remplissage_count{agent="code"}`, et de 0,01 `portail_contexte_remplissage_sum`.
  - `test_tours_et_outils` (`test_boucle.py`) : tour 1, le `FauxLLM` appelle `lire` (permis) et `zzz_987` (inventé) ; tour 2, il répond. Résultat : `portail_tours_mission_sum{agent=…}` +2, `_count` +1 ; `outil="lire",issue="ok"` +1 ; `outil="non_autorise",issue="refuse"` +1 ; `zzz_987` n'apparaît nulle part dans `generate_latest()`.
- [ ] **Étape 2 :** ils échouent. **Étape 3 :** implémenter. **Étape 4 :** la suite passe.
- [ ] **Étape 5 : commit** `feat(portail): métriques des agents et des modèles`.

### Task 5: Métriques de l'API et des flux en direct

**Fichiers :**
- Modifier : `backend/portail/metriques.py`, `backend/portail/api.py` (un middleware, `_flux`)
- Test : `backend/tests/test_metriques.py`

**Interfaces :**
- `portail_http_requetes_total{methode, route, code}` et `portail_http_duree_secondes{methode, route}` (seaux par défaut). `route` = `request.scope["route"].path` (le modèle, ex. `/api/taches/{tache_id}`), sinon `aucune` (404 sans route, 401 du middleware d'utilisateur).
- Middleware `_mesurer`, déclaré **après** `_utilisateur` dans `create_app` (donc extérieur : il voit aussi les 401 et 403). Si `call_next` lève (le 500 est rendu plus haut par Starlette), il compte `code="500"` puis relève.
- `portail_flux_ouverts{flux}`, `flux` ∈ `etapes` | `conversations` | `evenements`. `_flux(generateur, nom: str) -> StreamingResponse` (F) enveloppe le générateur : `inc()` au premier morceau demandé, `dec()` dans un `finally`. Si F l'a écrite locale à `create_app`, la sortir au niveau du module.

- [ ] **Étape 1 : tests qui échouent** dans `test_metriques.py` :
  - `test_requete_par_modele_de_route` : `GET /api/taches/987654` → `portail_http_requetes_total{methode="GET",route="/api/taches/{tache_id}",code="404"}` +1 ; `987654` absent de `generate_latest()` ;
  - `test_chemin_sans_route` : `GET /api/inconnu/123` → `route="aucune"`, `code="404"` +1 ;
  - `test_flux_ouverts` : `r = _flux(gen(), "conversations")` ; après un `await r.body_iterator.__anext__()`, la jauge vaut +1 ; après `aclose()`, elle revient.
- [ ] **Étape 2 :** ils échouent. **Étape 3 :** implémenter. **Étape 4 :** la suite passe.
- [ ] **Étape 5 : commit** `feat(portail): métriques de l'API et des flux en direct`.

### Task 6: Métriques de la boucle de dev et du lanceur

**Fichiers :**
- Modifier : `backend/portail/metriques.py`, `backend/portail/dev.py` (`_transition`, `_commande`, `_terminer`, `bloquer`, `_echouer_reprise`, `creer_reprise`, et l'endroit — ou les endroits après D — où `renvois` est incrémenté), `backend/portail/ordonnanceur.py` (`_bloquer`, `reprendre_interrompues`)
- Test : `backend/tests/test_dev.py`, `backend/tests/test_reprise.py`, `backend/tests/test_ordonnanceur.py`

**Interfaces :**
- `portail_phases_dev_total{phase, issue}` dans `_transition` : `phase` = `ctx.phase or "reprise"`, `issue` = `echec` si `erreur`, sinon `ok`.
- `portail_executions_dev_total{mode, issue}` : `en_revue` dans `_terminer`, `bloquee` dans `bloquer`, `echouee` dans `_echouer_reprise`.
- `portail_renvois_total{agent, vers}` : `agent` = l'agent de contrôle qui renvoie (`revue` aujourd'hui, les contrôles de D ; `faits` pour un renvoi par faits bloquants de D) ; `vers` ∈ `tests` | `code`.
- `portail_blocages_total{cause, phase}` dans `bloquer`, après le contrôle « déjà terminé » : `bloquer(self, pipeline_id, raison, cause: str)` (mot-clé obligatoire) ; `phase` = `ex.phase` si l'exécution existe, sinon `aucune`. `cause`, liste fixe, posée par `executer` d'après la branche `except` : `blocage` (`_Blocage`), `delai` (`TimeoutError` du délai de la tâche), `config` (`Refus`), `lanceur`, `github`, `depot`, `llm`, `outils` (les cinq classes d'erreur, une valeur chacune), `inattendue` ; `reprendre_interrompues` passe `interrompue`. Le blocage de l'ordonnanceur (`Ordonnanceur._bloquer`, démarrage impossible) compte `cause="demarrage"`, `phase="aucune"`. Aucune ligne `raise _Blocage(…)` ne change : la phase dit où, la cause dit quoi.
- `portail_duree_tache_secondes` dans `_terminer` si `mode == "normal"` : `horloge() - ctx.ex.debut`, seaux `(300, 900, 1800, 3600, 7200, 14400)`. « Prête » = le démarrage de l'exécution (`ExecutionDev.debut`) : l'attente dans « à faire » n'est pas le travail de la boucle.
- `portail_reprises_total` dans `creer_reprise`.
- Lanceur, dans `_commande` (seul appelant de `ClientLanceur.lancer`) : `portail_lanceur_commandes_total{nom, code}` avec `code` = `delai` si `delai_depasse`, `aucun` si `None`, sinon le code en texte ; `portail_lanceur_duree_secondes{nom}`, seaux `(1, 5, 15, 60, 300, 600, 1800)`. `nom` est le nom de la commande (`installer`, `tests`…), **jamais** la commande.

- [ ] **Étape 1 : tests qui échouent** (fixture `monde`, `valeur`) :
  - `test_parcours_compte_phases_duree_et_commandes` : le parcours de `test_parcours_complet_ouvre_une_pr` augmente `phases{phase="tests",issue="ok"}`, `executions{mode="normal",issue="en_revue"}`, `portail_duree_tache_secondes_count`, `lanceur_commandes{nom="installer",code="0"}` et `portail_lanceur_duree_secondes_count{nom="installer"}` ;
  - `test_delai_compte_commande_et_blocage` : le scénario de `test_delai_depasse_en_verification_bloque` augmente `lanceur_commandes{code="delai"}`, `blocages{cause="blocage",phase="verification"}` et `executions{issue="bloquee"}` ;
  - `test_renvoi_compte` : le scénario de `test_revue_renvoie_au_code_puis_ok` augmente `renvois{agent="revue",vers="code"}` de 1 ;
  - dans un test existant de `test_reprise.py` qui crée une reprise : `portail_reprises_total` +1 ; dans un test existant de `test_ordonnanceur.py` où le démarrage échoue : `blocages{cause="demarrage",phase="aucune"}` +1.
- [ ] **Étape 2 :** ils échouent. **Étape 3 :** implémenter. **Étape 4 :** la suite passe.
- [ ] **Étape 5 : commit** `feat(portail): métriques de la boucle de dev et du lanceur`.

### Task 7: Jauges lues en base à chaque collecte

**Fichiers :**
- Modifier : `backend/portail/metriques.py`, `backend/portail/api.py` (route `/metrics`)
- Test : `backend/tests/test_metriques.py`

**Interfaces :**
- `async def rafraichir(sessions) -> None`, appelée par `/metrics` avant `generate_latest()`. Trois requêtes en une session ; en cas d'exception : `journal.erreur`, `portail_base_joignable` à 0, et les autres jauges gardent leur dernière valeur.
  - `portail_taches{colonne}` : `count` par `Tache.colonne` ; `clear()` d'abord, pour qu'une colonne vidée disparaisse ;
  - `portail_tache_en_cours_age_max_secondes` : maintenant moins le plus petit `ExecutionDev.debut` des pipelines `dev` à l'état `en_cours`, 0 s'il n'y en a pas. *ponytail : pour une reprise, `debut` est la création de la reprise (attente des commentaires comprise, 10 min par défaut) ; lire l'heure du passage en cours si l'alerte se trompe.*
  - `portail_echecs_dev_consecutifs` : sur les 10 derniers pipelines `dev` terminés ou échoués (par `maj_le` décroissant), le nombre d'`echouee` avant le premier `terminee` ;
  - `portail_base_joignable` : 1 si les requêtes passent.

- [ ] **Étape 1 : tests qui échouent** :
  - `test_collecte_taches_par_colonne` : deux tâches `a_faire` et une `bloquee` → `/metrics` contient `portail_taches{colonne="a_faire"} 2.0` ; après le déplacement de la tâche bloquée, plus de série `colonne="bloquee"` ;
  - `test_collecte_age_et_echecs_consecutifs` : pipelines `dev` `terminee`, puis trois `echouee` (par `maj_le` croissant) → `portail_echecs_dev_consecutifs` vaut 3 ; une exécution `en_cours` dont `debut` est il y a 3 h → âge ≥ 10 800 ;
  - `test_collecte_base_injoignable` : `rafraichir` avec une fabrique de sessions qui lève → ne lève pas, `portail_base_joignable` vaut 0.
- [ ] **Étape 2 :** ils échouent. **Étape 3 :** implémenter. **Étape 4 :** la suite passe.
- [ ] **Étape 5 : commit** `feat(portail): jauges lues en base à chaque collecte`.

### Task 8: Aucun contenu dans les métriques, les journaux ni `appel_llm`

**Fichiers :**
- Modifier : `backend/tests/test_journal.py` (créé en F, enrichi en tâche 2)

Ces tests fixent l'anti-objectif central. **Un test qui échoue est une fuite : la corriger dans la même tâche, à l'endroit qui écrit le contenu.**

- [ ] **Étape 1 : écrire les tests**, avec `MARQUEUR = "ZZ-secret-7731"` :
  - `test_conversation_sans_contenu_nulle_part` : une application dont le `llm` est un vrai `ClientLLM(…, transport=MockTransport(h), sessions=sessions, version="sha-test")`. Premier message de Nicolas contenant le marqueur ; `h` répond un texte avec le marqueur (et un bloc `<think>` qui le contient) et un `usage`. Second message : `h` répond 500 avec le marqueur dans le corps (le message de `ErreurLLM` le porte). Attendre `fin` puis `erreur` comme les tests voisins. Alors :
    - `MARQUEUR` absent de `GET /metrics` ;
    - absent de chaque `caplog.records` formaté par `FormatJSON` ;
    - absent de `str` de chaque ligne de `appel_llm` (deux lignes : `ok` et `erreur`) ;
  - `test_mission_dev_sans_contenu_dans_les_metriques` : à la fin du scénario de `test_mission_complete_sans_contenu` (F), `MARQUEUR` est absent de `generate_latest()` et de chaque enregistrement formaté par `FormatJSON`.
- [ ] **Étape 2 :** `uv run pytest tests/test_journal.py -v` passe, ou la fuite est corrigée et le test passe.
- [ ] **Étape 3 : commit** `test(portail): aucun contenu dans les métriques, les journaux ni appel_llm`.

### Task 9: Tableaux de bord Grafana

**Fichiers :**
- Créer : `deploy/grafana/portail-sante.json`, `deploy/grafana/portail-boucle-dev.json`, `deploy/grafana/portail-agents.json`, `deploy/grafana/portail-lanceur.json`
- Créer : `backend/tests/test_grafana.py`

**Interfaces :**
- Format de l'Infra (`jarvis.json`) : `schemaVersion: 39`, `id: null`, `tags: ["portail"]`, `time: now-24h`, sources `{"type": "prometheus", "uid": "prometheus"}` et `{"type": "loki", "uid": "loki"}` (uids du `datasources.yml` de l'Infra). `uid` : `portail-sante`, `portail-boucle-dev`, `portail-agents`, `portail-lanceur`.
- Aucun nom d'agent, de modèle ou de commande écrit à la main : les séries viennent des étiquettes, et les filtres sont des variables `query` (`label_values(portail_llm_appels_total, agent)`).
- **Santé** :
  - disponibilité : `up{job="portail"}` ;
  - requêtes par code : `sum by (code) (rate(portail_http_requetes_total[5m]))` ;
  - latence p95 par route : `histogram_quantile(0.95, sum by (le, route) (rate(portail_http_duree_secondes_bucket[5m])))` ;
  - taux de 5xx : `sum(rate(portail_http_requetes_total{code=~"5.."}[5m])) / sum(rate(portail_http_requetes_total[5m]))` ;
  - base : `portail_base_joignable` ;
  - flux ouverts : `portail_flux_ouverts` ;
  - mémoire et CPU : `container_memory_working_set_bytes{name=~"portail-.*"}` et `rate(container_cpu_usage_seconds_total{name=~"portail-.*"}[5m])` (cAdvisor ; la pile Portainer nomme ses conteneurs `portail-<service>-1`, les services de projet `portail-svc-*`) ;
  - âge du déploiement en jours : `(time() - portail_deploiement_horodatage_secondes) / 86400`, seuils 25 et 32 ; version : `portail_info` ;
  - journaux d'erreurs (Loki) : `{container=~"portail-portail.*"} | json | niveau="ERROR"`.
- **Boucle de dev** :
  - tâches par colonne : `portail_taches` ;
  - arrivées en revue par heure : `sum(increase(portail_executions_dev_total{issue="en_revue"}[1h]))` ;
  - issues : `sum by (mode, issue) (increase(portail_executions_dev_total[1d]))` ;
  - phases : `sum by (phase, issue) (increase(portail_phases_dev_total[1d]))` ;
  - renvois : `sum by (agent, vers) (increase(portail_renvois_total[1d]))` ;
  - blocages par cause : `sum by (cause, phase) (increase(portail_blocages_total[7d]))` ;
  - durée p50 et p90 : `histogram_quantile(0.5|0.9, sum by (le) (rate(portail_duree_tache_secondes_bucket[1d])))` ;
  - reprises : `increase(portail_reprises_total[1d])` ;
  - tâche en cours la plus ancienne face au maximum : `portail_tache_en_cours_age_max_secondes` et `portail_duree_max_tache_secondes` ;
  - échecs consécutifs : `portail_echecs_dev_consecutifs`.
- **Agents et modèles** (variables `agent`, `lieu`) :
  - jetons par heure : `sum by (agent, sens) (increase(portail_llm_jetons_total{agent=~"$agent",lieu=~"$lieu"}[1h]))` ;
  - durée p95 : `histogram_quantile(0.95, sum by (le, agent, modele) (rate(portail_llm_duree_secondes_bucket{agent=~"$agent"}[15m])))` ;
  - erreurs LiteLLM : `sum by (agent, modele, issue) (increase(portail_llm_appels_total{issue!="ok",agent=~"$agent"}[1h]))` ;
  - remplissage du contexte p90 : sur `portail_contexte_remplissage_bucket` ;
  - tours par mission p50 et p90 : sur `portail_tours_mission_bucket` ;
  - appels d'outils : `sum by (outil, issue) (increase(portail_outils_appels_total{agent=~"$agent"}[1h]))` ;
  - réussite par lieu (comparaison de I) : `sum by (lieu) (rate(portail_llm_appels_total{issue="ok"}[1d])) / sum by (lieu) (rate(portail_llm_appels_total[1d]))`.
- **Lanceur** :
  - commandes par heure : `sum by (nom) (increase(portail_lanceur_commandes_total[1h]))` ;
  - codes de sortie (tableau) : `sum by (nom, code) (increase(portail_lanceur_commandes_total[1d]))` ;
  - durées p50 et p95 par nom : sur `portail_lanceur_duree_secondes_bucket` ;
  - délais dépassés : `sum by (nom) (increase(portail_lanceur_commandes_total{code="delai"}[1d]))`.

- [ ] **Étape 1 : tests qui échouent** dans `test_grafana.py`, sur `Path(__file__).parents[2] / "deploy/grafana"` :
  - `test_tableaux_valides` : quatre fichiers `*.json` qui se chargent, `uid` uniques, `title` non vide, au moins un panneau, chaque `datasource.uid` ∈ `{prometheus, loki}` ou une variable `$…` ;
  - `test_metriques_existantes` : chaque nom `portail_\w+` trouvé dans les `expr` de `deploy/grafana/*` (JSON et YAML), privé de `_total`, `_bucket`, `_sum`, `_count`, figure parmi les lignes `# TYPE` de `generate_latest()` (importer `portail.metriques` suffit à les déclarer). Un tableau qui cite une métrique renommée ou inventée fait échouer la CI.
- [ ] **Étape 2 :** ils échouent (dossier vide). **Étape 3 :** écrire les quatre tableaux. **Étape 4 :** la suite passe.
- [ ] **Étape 5 : vérification visuelle**, si un Grafana est joignable : importer les quatre JSON (Dashboards → Import), chaque panneau s'affiche sans erreur de requête. Sinon, le noter comme non vérifié pour la PR Infra.
- [ ] **Étape 6 : commit** `feat(deploy): tableaux de bord Grafana du portail`.

### Task 10: Alertes

**Fichiers :**
- Créer : `deploy/grafana/alertes-portail.yml`
- Modifier : `backend/tests/test_grafana.py`, `README.md`

**Interfaces :**
- Même forme que `monitoring/grafana/provisioning/alerting/rules.yml` de l'Infra : `apiVersion: 1`, un groupe `portail` (`orgId: 1`, `folder: Infra`, `interval: 1m`). Chaque règle : requête `A` sur `datasourceUid: prometheus` (`instant: true`), seuil `B` sur `__expr__`, `noDataState: OK`, `execErrState: Error`, `labels: {}`, un `summary` fixe sans contenu. La politique par défaut de l'Infra les envoie au point de contact `ntfy` : rien à ajouter de ce côté.
- Règles (`uid`, expression, seuil, `for`) :
  - `portail-erreurs-modele` : `sum(rate(portail_llm_appels_total{issue!="ok"}[15m])) / clamp_min(sum(rate(portail_llm_appels_total[15m])), 1e-9)`, `gt 0.25`, 15m ;
  - `portail-tache-trop-longue` : `portail_tache_en_cours_age_max_secondes - portail_duree_max_tache_secondes`, `gt 0`, 5m ;
  - `portail-echecs-consecutifs` : `portail_echecs_dev_consecutifs`, `gt 2`, 0m ;
  - `portail-deploiement-ancien` : `time() - portail_deploiement_horodatage_secondes`, `gt 2160000` (25 jours), 1h.
- **Portail injoignable 5 min** : déjà couvert par la règle `infra-target-down` de l'Infra (`up{job!~"…"}`, `for: 5m`), qui vaut pour tout nouveau job ; pas de doublon ici.

- [ ] **Étape 1 : test qui échoue**, `test_alertes_valides` : le YAML se charge ; quatre règles aux `uid` attendus ; chacune a `condition`, `for`, `noDataState`, `annotations.summary`, et aucune annotation ne cite `$values` ni `$labels` (rien de variable dans la notification). `test_metriques_existantes` couvre déjà les expressions.
- [ ] **Étape 2 :** il échoue. **Étape 3 :** écrire `alertes-portail.yml`. **Étape 4 :** la suite passe.
- [ ] **Étape 5 : README**, section « Monitoring » : `/metrics` (lu par Prometheus sur `infra-net`, 404 par le frontal), les quatre tableaux et les alertes dans `deploy/grafana/`, la table `appel_llm`, les journaux JSON (champs `pipeline`, `etape`, `tache`, `conversation`, `agent`, `mission` ; recherche Loki `{container=~"portail-portail.*"} | json | mission="<id>"`), la règle « aucun contenu ».
- [ ] **Étape 6 : commit** `feat(deploy): alertes Grafana du portail`.

### Task 11: Côté Infra

**Fichiers :**
- Modifier : `deploy/infra/README.md` (créé en F)

Rien n'est modifié hors de ce dépôt : cette tâche liste ce que la PR Infra du lot G recopie.

- [ ] **Étape 1 :** ajouter une section « PR Infra du lot G » qui liste :
  1. `monitoring/prometheus/prometheus.yml` : un job `portail`, `metrics_path: /metrics`, `static_configs: [{targets: ["portail:8000"]}]` (le service `portail` est sur `infra-net`, comme pour le vhost) ;
  2. les quatre `deploy/grafana/portail-*.json` → `monitoring/grafana/provisioning/dashboards/json/` ;
  3. `deploy/grafana/alertes-portail.yml` → `monitoring/grafana/provisioning/alerting/portail.yml` ;
  4. `deploy/nginx/portail.conf` → `nginx/conf.d/` (bloc `location ^~ /metrics`) ;
  5. les vérifications après déploiement : la cible `portail` est `UP` dans Prometheus ; `curl -sk -o /dev/null -w '%{http_code}' https://portail.infra.famillelallier.net/metrics` rend `404` ; les quatre tableaux s'affichent dans le dossier Infra ; les quatre règles sont visibles dans Alerting ; Loki rend des lignes JSON avec `{container=~"portail-portail.*"} | json | agent != ""` ; cAdvisor expose bien `name=~"portail-.*"` (sinon corriger le filtre des panneaux mémoire et CPU des deux côtés).
- [ ] **Étape 2 : commit** `docs(deploy): ce que la PR Infra du lot G recopie`.

---

## Ordre et dépendances

Tâche 1 d'abord (dépendance, `metriques.py`, aide `valeur`). La tâche 2 avant 3 (`ClientLLM` lit `journal.contexte`), 3 avant 4 (`_noter`). Les tâches 5, 6 et 7 sont indépendantes entre elles, mais toutes touchent `metriques.py`, et 5 et 7 touchent `api.py` : les faire l'une après l'autre. La tâche 8 après 2 à 7. La tâche 9 après 4 à 7 (le test exige les métriques citées), 10 après 9, 11 en dernier.

**Avant de fusionner dans `main` :** `DEPLOYE_LE` est écrit par le workflow, rien à ranger dans OpenBao. La PR Infra peut partir après la fusion : sans elle, `/metrics` répond sur `infra-net` sans être lu, rien ne casse.
