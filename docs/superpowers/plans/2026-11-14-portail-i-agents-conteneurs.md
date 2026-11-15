# Portail I — Un conteneur par agent, en Rust : plan d'implémentation

> **Pour les agents qui exécutent :** SOUS-SKILL REQUIS : superpowers:subagent-driven-development (recommandé) ou superpowers:executing-plans, tâche par tâche. Les étapes utilisent des cases `- [ ]`.

**But :** chaque agent peut tourner dans son conteneur, écrit en Rust et capable de porter du code propre à lui, sans que le portail perde le contrôle de ce que l'agent a le droit de faire. Ce plan livre l'outillage et les binaires de **tous** les agents, mais n'en migre **aucun** : la migration est une décision de Nicolas, agent par agent, en posant le champ `service:` dans `agents.yaml`.

**Architecture :** approche 1 de la spec (services permanents, modèle et outils servis par le portail). Côté portail, un seul module nouveau, `backend/portail/missions.py` : les types du contrat `v1`, le registre des missions en cours avec leur jeton, les deux routes `/interne/modele` et `/interne/outils` (qui réutilisent `ClientLLM`, `OutilsDepot`/`OutilsEspace`, `OutilsPortail` et donc `protections.py` tels quels), et le client de mission qui remplace l'appel à `boucle_outils` quand l'agent a un `service:`. Côté agents, un espace de travail Cargo `agents/` : une bibliothèque `agent` (serveur de missions, client du portail, boucle par défaut, journaux JSON, suite de conformité) et un paquet `catalogue` avec un binaire par agent. Une seule image `ai-agents`, un service par agent dans la pile, sur un réseau interne `portail-agents` où ils ne voient que le portail.

**Pile :** Python 3.12 / FastAPI / httpx / pytest ; Rust édition 2024 / axum 0.8 / tokio / serde (comme le lanceur) + `reqwest` sans TLS (seule dépendance nouvelle) ; GitHub Actions ; Docker Compose (Portainer) ; NGINX.

**Spec :** `docs/superpowers/specs/2026-11-14-portail-f-i-ameliorations-design.md`, section « I — Un conteneur par agent, en Rust », approche 1. **On suppose D, F, G puis H construits sur la même branche** :
- D (`docs/superpowers/plans/2026-11-14-portail-d-agents-transversaux.md`) : `LLMArbitre` (tâche 2), `_controles` et ses relances JSON (tâche 4), `ServiceAvis` (`backend/portail/avis.py`, tâche 6), conversations par agent (tâche 7) ;
- F (`docs/superpowers/plans/2026-11-14-portail-f-securite.md`) : `journal.erreur` (tâche 5), job `securite` et actions épinglées (tâche 1), sortie `execution_digest` et lecture seule des conteneurs (tâches 2 et 3), `deploy/infra/README.md` (tâche 3), en-têtes du vhost (tâche 9) ;
- G (`docs/superpowers/plans/2026-11-14-portail-g-monitoring.md`) : `journal.contexte`, `journal.commencer`, `journal.nouvelle_mission` (tâche 2), table `appel_llm` avec `lieu` et `version_image`, `ClientLLM._noter` qui lit `lieu` et `version_image` dans `journal.contexte` (tâche 3), métriques `portail_tours_mission` et `portail_outils_appels_total` (tâche 4), aide `valeur` de `conftest.py` (tâche 1) ;
- H : la route `GET /api/bureau` et la page Bureau. **H n'a pas encore de plan dans `docs/superpowers/plans/`** à la date de celui-ci : la tâche 12 nomme seulement ce que la spec fixe (§ H) et prend les noms réels du code de H au moment de construire.

## Contraintes globales

- Toutes les contraintes de F et G s'appliquent : français partout, aucun contenu (prompt, réponse, code, sortie, message d'erreur venu d'un agent) dans un journal, une métrique ou une étiquette, pas de refonte de `dev.py`, `chat.py`, `conversations.py` ni `api.py` (on y change des lignes, on n'y déplace rien).
- **Sans `service:`, rien ne change.** Toute la suite existante passe sans modification de fond à chaque tâche ; c'est la preuve du « comportement actuel inchangé ».
- **Aucun agent ne reçoit `service:` dans `agents.yaml` dans ce plan.** Les tests construisent leurs propres catalogues.
- **C'est le portail qui autorise.** Le portail ne lit dans une demande d'agent que les messages, le drapeau `outils`, `response_format`, `flux`, et le nom et les arguments d'un outil. Le modèle, la température, les schémas d'outils offerts, les compteurs et la fin de mission sont à lui. Les demandes de l'agent sont validées avec `extra="forbid"`.
- Côté portail : aucune dépendance nouvelle. `ClientLLM`, `OutilsDepot`, `OutilsEspace`, `OutilsPortail`, `protections.py`, `contexte.estimer_jetons`, `llm.retirer_reflexion` et `llm.FiltreReflexion` sont réutilisés sans changement ; de `boucle.py`, on importe `ResultatBoucle`, `ErreurOutils`, `_libelle`, `_IGNORE`, `_MAL_FORMES_MAX` et `_MAX_APPELS_PAR_TOUR` sans les déplacer.
- Côté agents : les dépendances du lanceur (`axum`, `tokio`, `serde`, `serde_json`, `subtle`, `futures-util`) plus `reqwest` (`default-features = false`, `features = ["json", "stream"]`) ; rien d'autre (pas de `tracing`, pas de `chrono`, pas de `serde_yaml`).
- Un seul processus uvicorn (G) : le registre des missions vit en mémoire. Un redémarrage du portail perd les missions en cours ; la reprise existante s'applique (spec, « Reprise »).
- Vérifications avant chaque commit :
  - backend : `cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest -q` ;
  - agents : `cd agents && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test` ;
  - la base de test est partagée : ne lancer qu'une suite backend à la fois.
- Le retrait de `boucle.py` n'est pas dans ce plan.

## Points à surveiller en revue

1. **Un outil exécuté après la fin de sa mission** (agent lent, pipeline annulé, durée dépassée) : il écrirait dans un espace déjà nettoyé. Les appels en vol sont des tâches de la mission, annulées à sa fermeture, et le jeton meurt avec elle — tâche 2, `test_outil_en_vol_annule_a_la_fermeture` ; tâche 7, `test_annulee_ne_peut_plus_ecrire`.
2. **Un champ de l'agent cru par le portail** : un `model`, des `tools` ou une `temperature` glissés dans `/interne/modele`, un `limite_atteinte: false` qui masquerait une limite tenue par le portail — tâches 3 et 7, `test_modele_et_outils_imposes`, `test_depasse_les_tours`.
3. **L'erreur rendue à `dev.py`** doit être celle que le portail a vue (`ErreurLLM`, `ErreurOutils`), pas le texte de la ligne `erreur` de l'agent : sinon les causes de blocage de G (`llm`, `outils`) changent — tâche 5, `test_erreur_du_portail_relevee`.
4. **Le contexte de journal perdu** : la requête `/interne/modele` tourne dans une autre tâche asyncio que l'appelant ; sans `journal.commencer(**mission.contexte, …)`, la ligne `appel_llm` n'aurait ni pipeline, ni étape, ni mission — tâche 3, `test_appel_llm_lieu_conteneur`.
5. **`/interne/` exposé** : par le vhost (tâche 11, `test_vhost_ne_sert_pas_interne`), avalé par le repli SPA (tâche 3, routeur inclus avant le repli), ou soumis à l'en-tête d'utilisateur (`/interne/` n'est pas sous `/api/`, le jeton le remplace).
6. **Un secret qui fuit vers l'agent** : le corps de mission ne porte ni clé LiteLLM, ni jeton GitHub, ni secret du lanceur, ni le secret de l'agent lui-même (il est dans l'en-tête) — tâche 7, `test_aucun_secret_dans_la_mission` ; tâche 11, `test_agent_isole`.
7. **Un journal d'agent qui porte du contenu** : l'API de `agent::journal` n'accepte que des `&'static str` et des compteurs, donc aucun texte venu de la mission — tâche 8.

---

### Task 1: Contrat `v1` et champ `service:`

**Fichiers :**
- Créer : `docs/agents-contrat-v1.md`, `docs/agents-contrat-v1.json`, `backend/portail/missions.py`, `backend/tests/test_missions.py`
- Modifier : `backend/portail/agents.py` (`Agent`), `backend/tests/test_agents.py`

**Interfaces :**
- `Agent` gagne `service: str | None = Field(default=None, pattern=r"^http://[a-z0-9-]+:[0-9]+$")` (l'adresse du conteneur sur `portail-agents`, ex. `http://agent-revue:8080`).
- `missions.py`, constante `CONTRAT = "v1"` et modèles pydantic (les demandes venues de l'agent en `extra="forbid"`, les autres en `extra="ignore"`) :
  - `MessageLLM` (`extra="allow"`) : `role: Literal["system", "user", "assistant", "tool"]`, `content: str | None = None` ;
  - `ParametresAgent` : `modele: str`, `temperature: float | None`, `contexte_max: int`, `tours_max: int`, `produit: str`, `role: str | None` ;
  - `DemandeMission` : `contrat: Literal["v1"]`, `mission: str`, `agent: str`, `jeton: str`, `messages: list[MessageLLM]`, `outils: list[dict]` (schémas OpenAI offerts), `parametres: ParametresAgent`, `response_format: dict | None = None`, `flux: bool = False` ;
  - lignes du flux de `/missions`, union discriminée sur `type` : `LigneTexte(type: Literal["texte"], texte: str)`, `LigneFin(type: Literal["fin"], texte: str, messages: list[MessageLLM], limite_atteinte: bool)`, `LigneErreur(type: Literal["erreur"], erreur: str)` ; `LigneMission = Annotated[LigneTexte | LigneFin | LigneErreur, Field(discriminator="type")]` ;
  - `DemandeModele` (`forbid`) : `messages: list[MessageLLM]`, `outils: bool = False`, `response_format: dict | None = None`, `flux: bool = False` ;
  - `ReponseModele` : `message: MessageLLM` ;
  - `DemandeOutil` (`forbid`) : `nom: str`, `arguments: str` (JSON en chaîne, comme OpenAI) ;
  - `ReponseOutil` : `resultat: str`, `arret: bool = False` ;
  - `Sante` : `contrat: str`, `agent: str`, `version: str`.
- `docs/agents-contrat-v1.md` décrit, dans cet ordre :
  - rôles (le portail autorise, l'agent raisonne) ;
  - `POST /missions` (portail → agent, `Authorization: Bearer <secret de l'agent>`, corps `DemandeMission`, réponse `application/x-ndjson` : zéro ou plusieurs `texte`, puis exactement une `fin` ou une `erreur` ; fermer la connexion annule la mission ; 401 mauvais secret, 403 mission pour un autre agent, 422 contrat inconnu ou corps invalide) ;
  - `GET /sante` (agent, sans authentification, réponse `Sante`) ;
  - `POST /interne/modele` et `POST /interne/outils` (agent → portail, `Authorization: Bearer <jeton de mission>`), avec les codes : 401 jeton invalide ou expiré, 409 mission arrêtée, 413 contexte dépassé, 422 demande invalide, 429 limite d'appels au modèle, 502 modèle indisponible ; corps d'erreur `{"erreur": "<texte fixe>"}` ;
  - option `flux` de `/interne/modele` : permise seulement avec `outils: false` ; lignes `{"type": "texte", "texte"}` puis `{"type": "fin", "message": {"role": "assistant", "content"}}` ou `{"type": "erreur", "erreur"}` ;
  - les limites tenues par le portail (tâches 3 et 4) et ce que fait le portail au-delà ;
  - validité du jeton : une mission, un agent, la durée de la mission, mort à la fin de la mission ;
  - règles de compatibilité : un champ nouveau facultatif ne change pas `v1` ; tout le reste demande `v2`.
- `docs/agents-contrat-v1.json` : un exemple par message, clés `mission`, `ligne_texte`, `ligne_fin`, `ligne_erreur`, `demande_modele`, `reponse_modele`, `demande_modele_flux_lignes` (liste), `demande_outil`, `reponse_outil`, `sante`, `erreur`. Le même fichier est relu par les tests Rust (tâche 8) : les deux côtés parlent du même JSON.

- [ ] **Étape 1 : tests qui échouent.**
  - `test_missions.py` :
    - `test_exemples_du_contrat` : chaque exemple de `docs/agents-contrat-v1.json` (lu par `Path(__file__).parents[2] / "docs/agents-contrat-v1.json"`) se valide avec son modèle ; les trois lignes avec `TypeAdapter(LigneMission)` ;
    - `test_demande_modele_refuse_les_champs_inconnus` : `{"messages": [], "model": "gpt-x"}` et `{"messages": [], "tools": []}` lèvent `ValidationError`.
  - `test_agents.py` :
    - `test_service_adresse_valide` : `service: http://agent-revue:8080` est accepté ;
    - `test_service_adresse_invalide`, paramétré : `https://agent-revue:8080`, `http://agent-revue`, `http://10.0.0.1:8080/x`, `agent-revue:8080` → `CatalogueInvalide` qui nomme l'agent.
- [ ] **Étape 2 :** ils échouent. **Étape 3 :** implémenter (modèles, champ, document, exemples). **Étape 4 :** la suite passe.
- [ ] **Étape 5 : commit** `feat(portail): contrat v1 des agents en conteneur et champ service`.

### Task 2: Registre des missions et jetons

**Fichiers :**
- Modifier : `backend/portail/missions.py`, `backend/portail/config.py`
- Test : `backend/tests/test_missions.py`

**Interfaces :**
- `Reglages.duree_mission_s: int = 3600` (`PORTAIL_DUREE_MISSION_S`).
- `class ErreurMission(ErreurOutils)` : une mission qui ne se termine pas proprement (agent injoignable, contrat incompatible, ligne `erreur`, flux coupé, durée dépassée). Sous-classe d'`ErreurOutils` : `dev.py` la range déjà dans sa branche `outils` (cause G `outils`), `chat.py` et `conversations.py` la traitent comme toute erreur (étape ou conversation en erreur, « réessayer » existant).
- `@dataclass class Mission` : `id: str`, `jeton: str`, `agent: Agent`, `llm`, `outils` (`OutilsDepot | OutilsPortail | None`), `schemas: list[dict]`, `sur_appel: Callable[[str, str], Awaitable[None]]`, `echeance: float`, `version: str`, `contexte: dict` (copie de `journal.contexte.get()` à l'ouverture), `appels_modele: int = 0`, `appels_tour: int = 0`, `mal_formes: int = 0`, `limite_atteinte: bool = False`, `erreur: Exception | None = None`, `tache: asyncio.Task | None = None` (lecture du flux de l'agent), `verrou: asyncio.Lock` (une demande `/interne/` à la fois par mission, comme la boucle actuelle), `en_vol: set[asyncio.Task]`. Propriété `noms -> set[str]` : les noms des `schemas`.
- `class Missions` :
  - `__init__(self, secrets: dict[str, str], duree_s: int, transport: httpx.AsyncBaseTransport | None = None, horloge: Callable[[], float] = time.monotonic)` ;
  - `ouvrir(self, llm, agent, outils, sur_appel, version: str) -> Mission` : `id` = `journal.contexte.get().get("mission")` (l'identifiant de mission de G ; une relance garde l'identifiant mais reçoit un nouveau jeton), sinon `uuid4().hex[:12]` ; `jeton = secrets.token_urlsafe(32)` ; `schemas` = ceux de `outils.schemas()` dont le nom est dans `agent.outils`, dans l'ordre de `agent.outils` (même règle que `boucle_outils`), `[]` si `outils is None` ; `echeance = horloge() + duree_s` ;
  - `trouver(self, autorisation: str | None) -> Mission | None` : `None` si l'en-tête n'est pas `Bearer <jeton>`, si le jeton est inconnu ou si `horloge() > echeance` ;
  - `async def fermer(self, m: Mission) -> None` : retire le jeton, annule et attend les tâches de `m.en_vol` ;
  - `async def en_vol(self, m: Mission, attente: Awaitable[T]) -> T` : exécute `attente` dans une tâche ajoutée à `m.en_vol` (retirée à la fin).
- `def lire_secrets(catalogue: Catalogue, environ: Mapping[str, str]) -> dict[str, str]` : pour chaque agent qui a un `service:`, la variable `PORTAIL_AGENT_SECRET_<NOM EN MAJUSCULES>` ; `CatalogueInvalide` si elle manque ou fait moins de 32 caractères (le message nomme l'agent et la variable, jamais la valeur). Les agents sans `service:` sont ignorés.

- [ ] **Étape 1 : tests qui échouent** (`test_missions.py`, horloge injectée) :
  - `test_jeton_trouve_puis_mort_a_la_fermeture` ;
  - `test_jeton_inconnu_ou_mal_forme`, paramétré : `None`, `""`, `"Bearer "`, `"Basic x"`, `"Bearer <autre jeton>"` → `None` ;
  - `test_jeton_expire` : horloge avancée au-delà de `duree_s` → `None` ;
  - `test_deux_missions_deux_jetons` : deux `ouvrir` du même agent sous le même identifiant G → deux jetons différents, chacun ne trouve que sa mission ;
  - `test_schemas_offerts` : un agent `revue` (`lister`, `lire`, `chercher`) avec `OutilsEspace(…, "tests", …)` → seulement les trois schémas de lecture ;
  - `test_outil_en_vol_annule_a_la_fermeture` : une attente bloquée sur un `Event` lancée par `en_vol`, puis `fermer` → la tâche est annulée ;
  - `test_lire_secrets`, paramétré : secret absent, secret de 31 caractères → `CatalogueInvalide` sans la valeur dans le message ; agent sans `service:` → ignoré ; 32 caractères → rendu.
- [ ] **Étape 2 :** ils échouent. **Étape 3 :** implémenter. **Étape 4 :** la suite passe.
- [ ] **Étape 5 : commit** `feat(portail): registre des missions et jetons de mission`.

### Task 3: Route `/interne/modele`

**Fichiers :**
- Modifier : `backend/portail/missions.py`, `backend/portail/api.py` (`include_router` avant le repli SPA ; `create_app(…, missions: Missions | None = None)` ; dans le lifespan `app.state.missions = missions or Missions({}, r.duree_mission_s)`, remplacé par les vrais secrets à la tâche 6)
- Créer : `backend/tests/test_interne.py`
- Modifier : `backend/tests/conftest.py` (fixture `interne`)

**Interfaces :**
- `ROUTEUR_INTERNE = APIRouter(prefix="/interne", include_in_schema=False)` ; les routes lisent `request.app.state.missions` et rendent elles-mêmes leurs `JSONResponse` (pas besoin du gestionnaire de `Refus`).
- `POST /interne/modele`, dans cet ordre :
  1. `missions.trouver(Authorization)` sinon **401** `{"erreur": "jeton de mission invalide"}` ;
  2. corps `DemandeModele` sinon **422** `{"erreur": "demande invalide"}` ;
  3. `flux` et `outils` ensemble → **422** `{"erreur": "flux permis seulement sans outils"}` ;
  4. `estimer_jetons(messages) > agent.contexte_max` → **413** `{"erreur": "contexte dépassé"}` (l'élagage est l'affaire de l'agent) ;
  5. `appels_modele >= agent.tours_max + 1` → `limite_atteinte = True`, **429** `{"erreur": "limite d'appels au modèle atteinte"}` ;
  6. sinon, sous `m.verrou` : `appels_modele += 1`, `appels_tour = 0` ; outils offerts = `m.schemas` si `outils` est vrai, que `m.schemas` n'est pas vide et que `getattr(m.outils, "arret", False)` est faux, sinon `None` (une action proposée : le modèle conclut sans outils, comme aujourd'hui) ;
  7. `journal.commencer(**m.contexte, lieu="conteneur", version_image=m.version)` : `ClientLLM._noter` (G) inscrit la ligne `appel_llm` avec `lieu="conteneur"` et la version de l'image, et les métriques de G portent `lieu="conteneur"` ;
  8. `await missions.en_vol(m, m.llm.completer(agent.modele, messages, agent.temperature, outils=offerts, response_format=d.response_format))` — le modèle et la température sont ceux de l'agent passé à la mission (donc le `model_copy` du challenger de D) ; `m.llm` est le client de l'appelant (`LLMArbitre` interactif ou fond de D) ;
  9. réponse `{"message": {...}}`, `content` passé par `retirer_reflexion` s'il n'est pas nul, `tool_calls` relayés tels quels ;
  10. `ErreurLLM` → `m.erreur` (la première seulement), **502** `{"erreur": "modèle indisponible"}` (le texte de LiteLLM ne part pas vers l'agent).
- Avec `flux` : `StreamingResponse(media_type="application/x-ndjson")` sur `m.llm.flux(…)`, filtré par `FiltreReflexion()` comme `chat._streamer` : lignes `{"type": "texte", "texte": part}`, puis `{"type": "fin", "message": {"role": "assistant", "content": retirer_reflexion(brut).strip()}}`, ou `{"type": "erreur", "erreur": "modèle indisponible"}`. Le verrou est tenu pendant tout le flux.
- Fixture `interne` (`conftest.py`) : une `FastAPI()` nue avec `app.state.missions = Missions({}, 60, horloge=…)` et `ROUTEUR_INTERNE`, un `AsyncClient(ASGITransport)` dessus, et un `FauxLLM` ; elle sert les tâches 3, 4, 5 et 7 sans base ni lifespan.

- [ ] **Étape 1 : tests qui échouent** dans `test_interne.py` :
  - `test_jeton_absent_ou_inconnu_401` ;
  - `test_modele_et_outils_imposes` : l'agent (`modele="m"`, `temperature=0.2`) envoie `outils: true` → `FauxLLM.appels[-1]` a `modele == "m"`, `temperature == 0.2`, `outils == m.schemas` ; avec `outils: false` → `outils is None` ; un corps avec `model`, `tools` ou `temperature` → 422 et `FauxLLM` non appelé ;
  - `test_reflexion_retiree` : `content` `"<think>x</think>ok"` → `"ok"` ;
  - `test_limite_tours_max_plus_un` : `tours_max=2` → trois appels 200, le quatrième 429, `m.limite_atteinte`, `FauxLLM` appelé trois fois ;
  - `test_contexte_max_refuse` : `contexte_max=50` et un message de 400 caractères → 413, `FauxLLM` non appelé, compteur inchangé ;
  - `test_flux_sans_outils_seulement` : `flux` + `outils` → 422 ; `flux` seul → lignes `texte` sans le bloc `<think>`, puis `fin` ;
  - `test_erreur_llm_retenue` : `FauxLLM.exception = ErreurLLM("corps ZZ-secret-7731")` → 502 dont le corps ne contient pas le marqueur, `isinstance(m.erreur, ErreurLLM)` ;
  - `test_appel_llm_lieu_conteneur` (fixture `sessions`, vrai `ClientLLM(…, transport=MockTransport(h), sessions=sessions, version="sha-portail")`) : la mission est ouverte sous `journal.commencer(pipeline=1, etape=2, tache=3)` puis `journal.nouvelle_mission("revue", 1000)` avec `version="sha-agent"` ; la requête `/interne/modele` est faite **depuis une autre tâche** (le contexte n'y est pas) → une ligne `appel_llm` avec `agent="revue"`, `lieu="conteneur"`, `version_image="sha-agent"`, `mission` = l'identifiant de G, et les trois identifiants ; `valeur("portail_llm_appels_total", agent="revue", modele="m", lieu="conteneur", issue="ok")` +1 ;
  - `test_interne_avant_le_repli_spa` (`test_static.py` ou le fichier qui teste le repli) : avec un `static_dir`, `POST /interne/modele` sans jeton rend 401 JSON, pas `index.html` ni 405 ; et `exiger_utilisateur=True` ne la soumet pas à l'en-tête d'utilisateur (401 « jeton », pas « non authentifié »).
- [ ] **Étape 2 :** ils échouent. **Étape 3 :** implémenter. **Étape 4 :** la suite passe.
- [ ] **Étape 5 : commit** `feat(portail): route /interne/modele, limites d'appels et de contexte`.

### Task 4: Route `/interne/outils`

**Fichiers :**
- Modifier : `backend/portail/missions.py`, et `backend/portail/metriques.py` (G) si le comptage d'un appel d'outil est écrit en ligne dans `boucle_outils` : le sortir en `def noter_outil(agent: Agent, nom: object, issue: str) -> None` (même règle `non_autorise` / `mal_forme`), appelé par les deux chemins
- Test : `backend/tests/test_interne.py`

**Interfaces :**
- `POST /interne/outils`, sous `m.verrou`, dans cet ordre :
  1. jeton → sinon **401** ;
  2. `m.erreur` déjà posée ou mission arrêtée → **409** `{"erreur": "mission arrêtée"}` ;
  3. corps `DemandeOutil` sinon **422** `{"erreur": "demande invalide"}`, compté comme appel mal formé (étape 7) ;
  4. `getattr(m.outils, "arret", False)` → `{"resultat": _IGNORE, "arret": true}` sans rien exécuter (comme `boucle_outils`) ;
  5. `appels_tour += 1` ; au-delà de `_MAX_APPELS_PAR_TOUR` (8) → `{"resultat": "erreur : trop d'appels dans un même tour, ignoré", "arret": false}`, rien d'exécuté ;
  6. `nom not in m.noms` → résultat `f"erreur : outil non autorisé : {nom}"`, mal formé, libellé `nom` (un outil que l'agent ne s'est pas vu offrir, même s'il figure dans `agent.outils` : une relance JSON n'offre aucun outil) ; sinon `resultat, mal_forme = await missions.en_vol(m, m.outils.executer(nom, arguments))` et libellé `_libelle(nom, arguments)` — `OutilsEspace` applique ses règles de rôle et `protections.py` comme aujourd'hui ;
  7. `m.mal_formes = m.mal_formes + 1 if mal_forme else 0` ; `await m.sur_appel(libelle, resultat)` (l'appel s'affiche et s'enregistre comme aujourd'hui) ; `noter_outil(…)` ;
  8. si `m.mal_formes >= _MAL_FORMES_MAX` (3) : `m.erreur = ErreurOutils(f"le modèle {agent.modele} ne gère pas correctement les outils")`, `m.tache.cancel()` si elle existe, **409** `{"erreur": "mission arrêtée"}` ;
  9. sinon `{"resultat": resultat, "arret": getattr(m.outils, "arret", False)}`.

- [ ] **Étape 1 : tests qui échouent** dans `test_interne.py` (un dépôt `tmp_path` avec `README.md`) :
  - `test_outil_execute_et_affiche` : `lire` sur `README.md` → résultat du fichier ; `sur_appel` reçoit `("lire(README.md)", <contenu>)` ;
  - `test_outil_non_offert_refuse` : `ecrire` pour un agent `revue` → `erreur : outil non autorisé : ecrire`, fichier absent ;
  - `test_huit_par_tour` : neuf `lire` de suite → le neuvième « trop d'appels » sans `sur_appel` ; après un `/interne/modele`, un nouveau `lire` passe ;
  - `test_trois_mal_formes_arretent` : trois appels à `zzz` → le troisième 409, `m.erreur` est une `ErreurOutils` ; un quatrième appel → 409 ; `valeur("portail_outils_appels_total", agent=…, outil="non_autorise", issue="refuse")` +3 ;
  - `test_mal_forme_puis_valide_remet_a_zero` : `zzz`, `zzz`, `lire`, `zzz` → pas d'arrêt ;
  - `test_arret_apres_proposition` : mission d'orchestrateur avec `OutilsPortail(sessions, …, conversation_id)` ; `creer_tache` → proposition enregistrée, `arret: true` ; un `lire_kanban` suivant → `_IGNORE`, rien exécuté ; un `/interne/modele` avec `outils: true` → `FauxLLM.appels[-1]["outils"] is None`.
- [ ] **Étape 2 :** ils échouent. **Étape 3 :** implémenter. **Étape 4 :** la suite passe (`test_boucle.py` inchangé, y compris `test_tours_et_outils` de G).
- [ ] **Étape 5 : commit** `feat(portail): route /interne/outils, outils permis et protections tenus par le portail`.

### Task 5: Client de mission

**Fichiers :**
- Modifier : `backend/portail/missions.py`, `backend/tests/conftest.py` (`FauxAgent`)
- Test : `backend/tests/test_missions.py`

**Interfaces :**
- `async def sante(self, agent: Agent, delai_s: float = 2) -> Sante | None` : `GET {agent.service}/sante` ; `None` si injoignable, hors délai, code ≠ 200 ou corps invalide.
- `async def faire_tourner(self, llm, agent, messages: list[dict], outils, sur_appel, *, sur_texte: Callable[[str], Awaitable[None]] | None = None, response_format: dict | None = None) -> ResultatBoucle` :
  1. `s = await self.sante(agent)` ; `None` → `ErreurMission(f"agent « {agent.nom} » injoignable")` ; `s.contrat != CONTRAT` → `ErreurMission(f"agent « {agent.nom} » : contrat {s.contrat} incompatible")` ;
  2. `m = self.ouvrir(llm, agent, outils, sur_appel, s.version)` ;
  3. `POST {agent.service}/missions`, `Authorization: Bearer {secrets[agent.nom]}`, corps `DemandeMission` (`flux = sur_texte is not None and not m.schemas`, `parametres` tirés de l'agent), lu en flux par httpx (`timeout=httpx.Timeout(None, connect=10)`), dans une tâche `m.tache`, le tout sous `asyncio.timeout(echeance restante)` ;
  4. chaque ligne lue par `TypeAdapter(LigneMission)` : `texte` → `await sur_texte(texte)` s'il est donné ; `fin` → résultat ; `erreur` → `ErreurMission(f"agent « {nom} » : {erreur[:300]}")` ; ligne illisible, ou flux fini sans `fin` → `ErreurMission(f"agent « {nom} » : mission interrompue")` ; code HTTP ≠ 200 → `ErreurMission(f"agent « {nom} » a refusé la mission ({code})")` ; `TimeoutError` → `ErreurMission("durée de mission dépassée")` ;
  5. `finally` : `await self.fermer(m)` (le flux httpx se ferme, donc l'agent voit la connexion coupée et annule) ; observer `portail_tours_mission{agent}` (G) avec `m.appels_modele` ;
  6. **si `m.erreur` est posée, c'est elle qui est levée**, avant toute `ErreurMission` (point de revue n° 3) ;
  7. `messages[:] = [x.model_dump(exclude_none=True) for x in fin.messages]` (les appelants qui relancent avec `messages` gardent l'historique rendu, comme avec `boucle_outils` qui l'allonge en place) ; rend `ResultatBoucle(texte=fin.texte, limite_atteinte=fin.limite_atteinte or m.limite_atteinte)`.
- Aucun texte venu de l'agent n'est journalisé ; `ErreurMission` porte le texte jusqu'à l'étape ou la conversation, comme le message d'une `ErreurLLM` aujourd'hui.
- Deux aides au niveau du module, utilisées à la tâche 6 :
  - `async def tourner(llm, missions: Missions | None, agent, messages, outils, sur_appel) -> ResultatBoucle` : `boucle_outils(llm, agent, messages, outils, sur_appel)` si `agent.service` est nul ; sinon `missions.faire_tourner(…)` (`ErreurMission("registre des missions absent")` si `missions is None`) ;
  - `async def completer(llm, missions, agent, messages, response_format: dict) -> str` : sans `service:`, `retirer_reflexion((await llm.completer(agent.modele, messages, agent.temperature, response_format=response_format)).get("content") or "")` ; avec, `(await missions.faire_tourner(llm, agent, messages, None, _rien, response_format=response_format)).texte` — une **nouvelle mission** sans outils, pour la réponse structurée et sa relance.
- `FauxAgent` (`conftest.py`) : un faux conteneur pour `Missions(transport=httpx.MockTransport(faux.repondre))`. Il sert `/sante` (`contrat`, `version="sha-agent"` modifiables) et `/missions` : il garde la requête reçue (`faux.missions`, en-têtes compris), puis joue `faux.jouer(demande, portail)`, un générateur asynchrone de lignes, en appelant le portail par `portail` (client ASGI sur une application qui porte `ROUTEUR_INTERNE` et le même registre). `jouer` par défaut est la boucle de `boucle_outils` en vingt lignes (modèle avec `outils` si la mission en offre, chaque `tool_call` envoyé à `/interne/outils`, fin quand le modèle répond sans outil) ; les tests la remplacent pour tricher. `faux.deconnecte` (un `asyncio.Event`) passe à vrai quand le portail ferme le flux.

- [ ] **Étape 1 : tests qui échouent** dans `test_missions.py` (`interne`, `FauxAgent`, `FauxLLM`) :
  - `test_requete_de_mission` : en-tête `Authorization: Bearer <secret de revue>` ; corps avec `contrat == "v1"`, `agent == "revue"`, `mission` = l'identifiant posé par `journal.nouvelle_mission`, un `jeton`, les `outils` = `m.schemas`, `parametres.tours_max`, `flux == False` ;
  - `test_mission_avec_outils` : le `FauxLLM` demande `lire(README.md)` puis répond « fini » → `ResultatBoucle(texte="fini", limite_atteinte=False)`, `sur_appel` appelé une fois, `messages` remplacé par l'historique rendu (`system`, `user`, `assistant` avec `tool_calls`, `tool`, `assistant`) ;
  - `test_flux_relaye_le_texte` : sans outils et avec `sur_texte`, `flux == True` dans la demande, et `sur_texte` reçoit les morceaux émis par l'agent ;
  - `test_agent_injoignable` et `test_contrat_incompatible` → `ErreurMission`, aucune mission envoyée ;
  - `test_ligne_erreur_et_flux_coupe`, paramétré → `ErreurMission`, le jeton est mort ;
  - `test_erreur_du_portail_relevee` : le `FauxLLM` lève `ErreurLLM` ; l'agent finit par une ligne `erreur` → c'est l'`ErreurLLM` qui est levée ;
  - `test_annulation_ferme_la_connexion` : la tâche appelante est annulée pendant que l'agent attend → `faux.deconnecte` est posé, un appel `/interne/outils` ultérieur avec ce jeton → 401 ;
  - `test_sans_service_c_est_boucle_outils` : `tourner` avec un agent sans `service:` n'appelle jamais `FauxAgent` et rend le même résultat que `boucle_outils` ;
  - `test_completer_ouvre_une_mission_sans_outils` : avec `service:`, `completer` envoie une mission avec `outils == []` et `response_format` ; `/interne/outils` y refuse tout outil.
- [ ] **Étape 2 :** ils échouent. **Étape 3 :** implémenter. **Étape 4 :** la suite passe.
- [ ] **Étape 5 : commit** `feat(portail): client de mission vers les agents en conteneur`.

### Task 6: Le portail fait tourner un agent `service:` dans son conteneur

**Fichiers :**
- Modifier : `backend/portail/dev.py` (`Orchestrateur.__init__`, `_agent`, les relances JSON de `_tri` et de `_controles` (D, tâche 4)), `backend/portail/chat.py` (`ServiceChat.__init__`, `_streamer`, `_boucle`, `_proposer`), `backend/portail/conversations.py` (`ServiceConversation.__init__`, `_streamer`, `_boucle`), `backend/portail/avis.py` (D, tâche 6 : son appel à `boucle_outils` et à `llm.completer`), `backend/portail/api.py` (lifespan, `_orchestrateur`)
- Test : `backend/tests/test_dev.py`, `backend/tests/test_chat.py`, `backend/tests/test_conversations.py`, `backend/tests/test_api_projets.py`

**Interfaces :**
- `Orchestrateur`, `ServiceChat`, `ServiceConversation` et `ServiceAvis` gagnent le paramètre nommé `missions: Missions | None = None`, gardé en `self._missions`. Les tests qui les construisent sans lui ne changent pas.
- Remplacements, ligne pour ligne (rien d'autre ne bouge) :
  - `boucle_outils(self._llm, agent, messages, outils, sur_appel)` → `tourner(self._llm, self._missions, agent, messages, outils, sur_appel)` dans `dev._agent`, `chat._boucle`, `conversations._boucle` et `avis.py` ;
  - les relances JSON `self._llm.completer(agent.modele, messages, agent.temperature, response_format=F)` suivies de `retirer_reflexion(…)` → `texte = (await completer(self._llm, self._missions, agent, messages, F)).strip()` dans `_tri`, `_controles` et `chat._proposer` (et l'appel sans outils de `avis.py`). La validation (`_lire_verdict`, `lire_tri`, `lire_propositions`) et la relance restent où elles sont ;
  - `chat._streamer` et `conversations._streamer` : si `agent.service`, `faire_tourner(self._llm, agent, demande, None, _rien, sur_texte=publier)` où `publier` fait ce que fait la boucle actuelle sur chaque morceau (`ajouter_partiel` puis `publier` d'un `delta`) ; le texte rendu est `resultat.texte.strip()`. Le texte affiché est donc celui que l'agent émet.
- Lifespan : `app.state.missions = missions or Missions(lire_secrets(catalogue, os.environ), r.duree_mission_s)` — un agent `service:` sans secret valide empêche le démarrage (`CatalogueInvalide`, comme `modeles_permis` en F) ; `missions=app.state.missions` passé aux quatre services et à `_orchestrateur(r, sessions, catalogue, llm, missions)`. L'`LLMArbitre` passé à chaque service reste celui de D : c'est lui que `Mission.llm` appelle, avec la priorité de l'appelant.

- [ ] **Étape 1 : tests qui échouent.**
  - `test_dev.py` :
    - `test_revue_en_conteneur_parcours_complet` : `Monde` construit avec un catalogue où `revue` a `service: http://agent-revue:8080` et un `Missions` branché sur un `FauxAgent` (boucle par défaut) ; le scénario de `test_parcours_complet_ouvre_une_pr` ouvre la PR ; `FauxAgent.missions` contient exactement une mission, d'agent `revue` ; les messages `tool` de l'étape `revue` sont ceux exécutés par `/interne/outils` ; `tests` et `code` sont passés par `boucle_outils` (aucune autre mission) ;
    - `test_relance_verdict_par_une_nouvelle_mission` : la revue en conteneur répond d'abord un texte illisible → une deuxième mission avec `outils == []`, `response_format == FORMAT_VERDICT`, et des messages qui finissent par la réponse illisible puis « Réponse invalide : renvoie uniquement le JSON. » ;
    - `test_agent_en_conteneur_injoignable_bloque` : `FauxAgent` hors service → le pipeline est bloqué avec la cause `outils` (G) et une raison qui nomme l'agent.
  - `test_chat.py`, `test_agent_en_conteneur_streame` : un agent sans outils avec `service:` → les `delta` reçus par l'abonné sont les lignes `texte` de l'agent ; le document écrit est le `texte` de la ligne `fin`.
  - `test_chat.py`, `test_taches_en_conteneur_relance` : l'agent `taches` en conteneur rend un JSON invalide puis valide → deux missions, propositions enregistrées.
  - `test_conversations.py`, `test_orchestrateur_en_conteneur_propose` : une conversation dont l'agent a `service:` ; l'agent appelle `creer_tache` → une `ActionConversation`, un message `tool` enregistré, la réponse finale enregistrée.
  - `test_api_projets.py` (ou le fichier qui teste le démarrage), `test_demarrage_refuse_un_agent_service_sans_secret` : `create_app` avec un catalogue où un agent a `service:` et sans `PORTAIL_AGENT_SECRET_<NOM>` (`monkeypatch.delenv`) → le lifespan lève `CatalogueInvalide`.
- [ ] **Étape 2 :** ils échouent. **Étape 3 :** implémenter. **Étape 4 :** **toute** la suite passe : c'est la preuve que sans `service:`, rien ne change.
- [ ] **Étape 5 : commit** `feat(portail): un agent avec service tourne dans son conteneur`.

### Task 7: Garde-fous face à un agent qui triche

**Fichiers :**
- Créer : `backend/tests/test_agents_tricheurs.py`

Ces tests fixent l'anti-objectif « un agent qui applique lui-même ses propres limites ». Chaque test remplace `FauxAgent.jouer` par un agent qui triche ; le portail doit tenir **sans changer de code**. **Un test qui échoue est une faille : s'arrêter, la décrire, et la corriger dans la même tâche avec son test.**

- [ ] **Étape 1 : écrire les tests** (fixtures `interne`, `monde`, `FauxAgent`, `FauxLanceur`, et `test_injection.py` de F pour les chemins piégés) :
  - `test_outil_non_permis` : l'agent `revue` appelle `ecrire` puis `lancer` → `erreur : outil non autorisé`, fichier absent, `FauxLanceur.appels` vide ;
  - `test_chemin_hors_espace` : agent `code` en mission sur `OutilsEspace(…, "code", …)` : `lire` sur `../../etc/passwd`, un chemin absolu et un lien symbolique sortant ; `ecrire` sur `.git/config` et sur un fichier de `chemins_tests` → refus à chaque fois, disque inchangé ;
  - `test_jeton_d_une_autre_mission` : missions A (`revue`) et B (`code`) ouvertes ; le jeton de A sur `ecrire` → refusé (A n'a pas `ecrire`), même si B l'a ; après la fin de B, son jeton → 401 ; un jeton forgé → 401 ; un jeton de A après l'échéance → 401 ;
  - `test_depasse_les_tours` : l'agent appelle le modèle sans fin puis rend `fin` avec `limite_atteinte: false` → `FauxLLM` appelé `tours_max + 1` fois, les suivants 429, résultat `limite_atteinte == True` ;
  - `test_neuf_outils_par_tour` : neuf appels sans repasser par le modèle → huit exécutés ;
  - `test_mal_formes_arretent_la_mission` : trois outils inventés → `ErreurOutils` levée à l'appelant, flux de l'agent coupé ; dans `Monde`, le pipeline est bloqué avec la cause `outils` ;
  - `test_duree_depassee` : l'agent attend au-delà de `duree_mission_s` → `ErreurMission("durée de mission dépassée")`, `faux.deconnecte` posé, le jeton → 401 ;
  - `test_contexte_gonfle` : des messages au-delà de `contexte_max` → 413, aucun appel au modèle ;
  - `test_modele_et_outils_choisis_par_l_agent` : corps avec `model`, `tools`, `temperature` → 422 ; `flux` avec `outils` → 422 ;
  - `test_annulee_ne_peut_plus_ecrire` : la tâche appelante est annulée pendant que l'agent prépare un `ecrire` ; l'`ecrire` arrive ensuite → 401, fichier absent ;
  - `test_aucun_secret_dans_la_mission` : `Reglages` avec des valeurs distinctes pour `litellm_cle`, `github_jeton`, `lanceur_secret`, `github_app_cle`, `ntfy_jeton` ; aucune n'apparaît dans le corps ni dans les en-têtes reçus par `FauxAgent` (sur `/missions` comme sur `/sante`) ; l'en-tête `Authorization` vaut `Bearer <secret de l'agent>` et ce secret n'est pas dans le corps.
- [ ] **Étape 2 :** `uv run pytest tests/test_agents_tricheurs.py -v` passe, ou la faille est corrigée et le test passe ; puis toute la suite.
- [ ] **Étape 3 : commit** `test(portail): le portail tient les limites d'un agent qui triche`.

### Task 8: Bibliothèque `agent` : contrat, client du portail, serveur de missions, journaux

**Fichiers :**
- Créer : `agents/Cargo.toml` (espace de travail : `members = ["agent", "catalogue"]`, `resolver = "3"`, `[workspace.dependencies]` : `axum = "0.8"`, `futures-util = "0.3"`, `reqwest = { version = "0.12", default-features = false, features = ["json", "stream"] }`, `serde = { version = "1", features = ["derive"] }`, `serde_json = "1"`, `subtle = "2"`, `tokio = { version = "1", features = ["full"] }`), `agents/Cargo.lock`, `agents/.gitignore` (`target/`)
- Créer : `agents/agent/Cargo.toml`, `agents/agent/src/lib.rs`, `agents/agent/src/contrat.rs`, `agents/agent/src/portail.rs`, `agents/agent/src/serveur.rs`, `agents/agent/src/journal.rs`, `agents/agent/tests/exemples.rs`

**Interfaces :**
- `contrat.rs` : `pub const CONTRAT: &str = "v1";` et les types `serde` du contrat, mêmes noms de champs que la tâche 1 : `Mission`, `Parametres`, `Ligne` (`#[serde(tag = "type", rename_all = "lowercase")] enum { Texte { texte }, Fin { texte, messages, limite_atteinte }, Erreur { erreur } }`), `DemandeModele`, `ReponseModele`, `DemandeOutil`, `ReponseOutil`, `Sante`. Les messages restent des `serde_json::Value` (l'agent les rejoue tels quels).
- `portail.rs` : `pub struct Portail { url: String, jeton: String, client: reqwest::Client }` (`connect_timeout` 10 s, pas de délai total : le portail tient la durée) ; `pub enum ErreurPortail { Refus { statut: u16, erreur: String }, Reseau }` ;
  - `pub async fn modele(&self, d: &DemandeModele) -> Result<serde_json::Value, ErreurPortail>` (le `message`) ;
  - `pub async fn modele_en_flux(&self, messages: &[Value], sortie: &Sortie) -> Result<Value, ErreurPortail>` : chaque ligne `texte` est relayée sur `sortie`, la ligne `fin` rend le `message` ;
  - `pub async fn outil(&self, nom: &str, arguments: &str) -> Result<ReponseOutil, ErreurPortail>` ;
  - chaque requête porte `Authorization: Bearer <jeton>`.
- `serveur.rs` :
  - `pub struct Sortie(tokio::sync::mpsc::Sender<Ligne>)` avec `pub async fn texte(&self, t: &str)` ;
  - `pub type Tourner = fn(Mission, Portail, Sortie) -> futures_util::future::BoxFuture<'static, Result<Fin, String>>` où `pub struct Fin { pub texte: String, pub messages: Vec<Value>, pub limite_atteinte: bool }` ;
  - `pub fn routeur(nom: &'static str, secret: String, version: String, portail_url: String, tourner: Tourner) -> axum::Router` : `GET /sante` → `Sante { contrat: CONTRAT, agent: nom, version }` ; `POST /missions` derrière une vérification du secret en temps constant (`subtle`, comme `lanceur/src/api.rs`) → 401 ; `mission.agent != nom` → 403 ; `contrat != "v1"` ou corps invalide → 422 ; sinon la mission tourne dans une tâche `tokio::spawn` et la réponse est `Body::from_stream` d'un flux de lignes NDJSON lu sur le canal ; la ligne `fin` ou `erreur` est la dernière ; le flux tient un garde dont le `Drop` fait `abort()` sur la tâche (connexion fermée = mission annulée) ;
  - `pub async fn servir(nom: &'static str, tourner: Tourner)` : lit `AGENT_SECRET` (au moins 32 caractères, sinon message sur la sortie d'erreur et code 1), `AGENT_PORTAIL_URL` (défaut `http://portail:8000`), `AGENT_VERSION` (défaut `inconnue`) ; écoute `0.0.0.0:8080`.
- `journal.rs` : une ligne JSON par événement sur la sortie standard, `{"niveau", "module": "agent", "agent", "mission", "message", <compteurs>}` ; `pub fn info(agent: &str, mission: &str, message: &'static str, compteurs: &[(&'static str, u64)])` et `pub fn erreur(…)` de même forme. **Le message est un `&'static str`** : aucun texte venu d'une mission ou du portail ne peut y entrer. Pas de champ `quand` : Docker horodate chaque ligne et Loki garde cet horodatage. Le serveur journalise `mission reçue`, `mission finie` (avec `appels_modele`, `appels_outils`), `mission annulée`, `mission en erreur`.

- [ ] **Étape 1 : tests qui échouent.**
  - `agents/agent/tests/exemples.rs`, `exemples_du_contrat` : `include_str!("../../../docs/agents-contrat-v1.json")`, chaque exemple se désérialise dans son type et se resérialise sans perte de champ.
  - Dans `serveur.rs` (`tokio::test`, serveur sur `127.0.0.1:0`, un `Tourner` de test qui émet un texte puis une `Fin`) : `sante_rend_contrat_et_version` ; `mauvais_secret_401` ; `autre_agent_403` ; `contrat_inconnu_422` ; `lignes_ndjson_puis_fin` (chaque ligne est un JSON complet, la dernière est `fin`) ; `erreur_de_mission_en_ligne_erreur` ; `deconnexion_annule_la_mission` (le `Tourner` de test attend un signal ; le client coupe ; un drapeau posé par un garde `Drop` dans la mission prouve l'annulation).
  - Dans `portail.rs`, contre un faux portail axum : `jeton_sur_chaque_appel` (le faux portail répond 401 sans le bon jeton) ; `refus_du_portail_rendu` (429 → `ErreurPortail::Refus { statut: 429, … }`) ; `flux_relaye_le_texte`.
- [ ] **Étape 2 :** ils échouent. **Étape 3 :** implémenter. **Étape 4 :** `cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test` passent.
- [ ] **Étape 5 : commit** `feat(agents): bibliothèque agent, serveur de missions et client du portail`.

### Task 9: Boucle par défaut, suite de conformité, un binaire par agent

**Fichiers :**
- Créer : `agents/agent/src/boucle.rs`, `agents/agent/src/conformite.rs`
- Créer : `agents/catalogue/Cargo.toml`, `agents/catalogue/src/lib.rs`, `agents/catalogue/src/bin/{spec,orchestrateur,plan,taches,tests,code,revue,architecte,challenger,securite,doc,pm,tri}.rs`, `agents/catalogue/tests/conformite.rs`, `agents/catalogue/tests/catalogue.rs`

**Interfaces :**
- `boucle.rs` :
  - `pub fn par_defaut(m: Mission, p: Portail, s: Sortie) -> BoxFuture<'static, Result<Fin, String>>`, la boucle de `boucle_outils` côté agent :
    - sans outils offerts : un appel, en flux (`modele_en_flux`, morceaux relayés sur `s`) si `m.flux`, sinon simple avec `m.response_format` ; `Fin { texte: content, messages: m.messages + réponse, limite_atteinte: false }` ;
    - avec outils : jusqu'à `parametres.tours_max` tours ; chaque tour élague, appelle le modèle avec `outils: true`, s'arrête sur une réponse sans `tool_calls` ; sinon ajoute le message `assistant` **rendu rejouable comme le fait `boucle.py`** (ids uniques, `appel_N` si absent ou répété, arguments en chaîne, un appel par entrée), puis chaque appel passe par `p.outil` et son résultat devient un message `tool` ; si une réponse d'outil a `arret: true`, un dernier appel sans outils et fin ; au bout de `tours_max`, le message utilisateur `_LIMITE` de `boucle.py` (même texte), un dernier appel sans outils, `limite_atteinte: true` ;
    - un refus du portail (`409`, `429`, `502`, …) termine la mission par `Err(<texte fixe>)`, donc une ligne `erreur` ; le portail relève sa propre erreur (tâche 5).
  - `pub fn elaguer(messages: &mut [Value], contexte_max: u64) -> usize` : même règle que `contexte.elaguer_resultats_outils` (estimation `len(content) / 4 + 4` par message, déclenché à 0,90, résultats d'outils remplacés par `[résultat retiré : relire si besoin]` du plus ancien au plus récent jusqu'à 0,75).
- `conformite.rs` : `pub async fn verifier(nom: &'static str, tourner: Tourner)`, qui panique avec le nom du cas en échec. Elle démarre un **faux portail** axum (`127.0.0.1:0`) dont le modèle est scripté (un tour avec un `tool_call` vers le premier outil offert, puis une réponse texte), et l'agent par `serveur::routeur`. Cas, chacun une fonction `cas_*` :
  - `cas_sante` : `contrat == "v1"`, `agent == nom` ;
  - `cas_secret` : mauvais secret → 401 ; `cas_autre_agent` → 403 ;
  - `cas_mission_sans_outils` et `cas_mission_avec_outils` : le flux est du NDJSON valide, finit par exactement une ligne `fin` ou `erreur`, et après la dernière ligne la connexion se ferme ;
  - `cas_jeton` : chaque appel reçu par le faux portail porte le jeton de la mission (sinon 401 et le cas échoue) ;
  - `cas_refus_respecte` : le faux portail répond 429 au premier appel au modèle → l'agent finit (`fin` ou `erreur`) sans plus rien demander ;
  - `cas_annulation` : la connexion coupée pendant un appel au modèle → plus aucun appel au faux portail ensuite ;
  - `cas_flux` : `flux: true` sans outils → au moins une ligne `texte` avant la fin.
  Ces cas vérifient le contrat, pas le raisonnement : un agent sur mesure les passe s'il respecte `v1`.
- `catalogue/src/lib.rs` : `pub const NOMS: [&str; 13]` (les agents de `agents.yaml`) ; `pub fn tourner(nom: &str) -> Option<Tourner>` (aujourd'hui `boucle::par_defaut` pour tous ; un agent sur mesure y gagne sa branche et son module) ; `pub async fn principal(nom: &'static str)` = `agent::serveur::servir(nom, tourner(nom).expect(…))`.
- Chaque `src/bin/<nom>.rs` : `#[tokio::main] async fn main() { catalogue::principal("<nom>").await }`.

- [ ] **Étape 1 : tests qui échouent.**
  - `boucle.rs` : `boucle_sans_outils` ; `boucle_avec_outils_rejouable` (deux `tool_calls` au même id → `appel_0`, `appel_1` ; arguments objet → chaîne) ; `boucle_limite_tours` (`tours_max = 2` : deux appels avec outils, un sans, `limite_atteinte`) ; `boucle_arret` ; `elaguer_comme_le_portail` (mêmes cas que `test_contexte.py` pour l'élagage, recopiés en Rust).
  - `catalogue/tests/conformite.rs`, `chaque_agent_passe_la_conformite` : pour chaque nom de `NOMS`, `verifier(nom, tourner(nom).unwrap())`.
  - `catalogue/tests/catalogue.rs` : `noms_egaux_a_agents_yaml` (les clés de second niveau sous `agents:` de `../../agents.yaml`, lues ligne à ligne avec le motif `^  ([a-z_]+):$`, sans dépendance YAML) ; `un_binaire_par_agent` (les fichiers de `src/bin/` sont exactement `NOMS`).
- [ ] **Étape 2 :** ils échouent. **Étape 3 :** implémenter. **Étape 4 :** `cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test` passent.
- [ ] **Étape 5 : commit** `feat(agents): boucle par défaut, suite de conformité et un binaire par agent`.

### Task 10: Image `ai-agents`, CI et déploiement

**Fichiers :**
- Créer : `agents/Dockerfile`, `agents/.dockerignore` (`target`)
- Modifier : `.github/workflows/ci.yml` (job `agents`, `cargo audit` du job `securite` de F), `.github/workflows/deploy.yml` (job `image`, job `deploy`), `scripts/portainer-stack.sh` (`REQUIRED`), `renovate.json` (F) si ses gestionnaires sont limités par chemin

**Interfaces :**
- `agents/Dockerfile` :
  - compilation : `FROM rust:1-slim-bookworm@sha256:… AS compilation`, `COPY . .`, `cargo build --release --locked --bins`, puis copie de tous les exécutables de `target/release/` (fichiers exécutables au premier niveau) dans `/sortie` — aucune liste d'agents tenue à la main ;
  - image finale : `FROM gcr.io/distroless/cc-debian12:nonroot@sha256:…` (glibc, aucun shell, utilisateur non root), `COPY --from=compilation /sortie/ /usr/local/bin/`, `EXPOSE 8080`, pas de `CMD` (chaque service nomme son binaire) ;
  - digests résolus comme en F (`docker buildx imagetools inspect <image:tag> --format '{{.Manifest.Digest}}'`).
- `ci.yml`, job `agents`, calqué sur le job `lanceur` (actions épinglées par SHA comme en F, `working-directory: agents`, `Swatinem/rust-cache` sur `agents`) : `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, `cargo test` (donc la conformité de chaque agent). Le job `securite` ajoute `cargo audit` dans `agents`. La protection de `main` exige désormais aussi `agents` (étape manuelle).
- `deploy.yml`, job `image` : `meta-agents` (`ghcr.io/${{ github.repository }}-agents`, mêmes tags), une étape `construire-agents` (`context: agents`, `file: agents/Dockerfile`, `cache` de portée `agents`), une analyse `trivy` sur `…-agents@${{ steps.construire-agents.outputs.digest }}` avec les réglages de F, et la sortie `agents_digest`. Job `deploy` : `AGENTS_DIGEST: ${{ needs.image.outputs.agents_digest }}`, écrit dans `$PORTAIL_STACK_ENV` à côté de `IMAGE_TAG` et vérifié avec les autres variables obligatoires.
- `scripts/portainer-stack.sh` : `AGENTS_DIGEST` dans `REQUIRED`.

- [ ] **Étape 1 : vérifier l'image.**
  - `docker build -t ai-agents-local agents` réussit ;
  - `docker run --rm --entrypoint revue ai-agents-local` sans `AGENT_SECRET` → code 1 et le message sur la sortie d'erreur ;
  - avec `-e AGENT_SECRET=$(openssl rand -hex 32) -p 18080:8080 --read-only --cap-drop ALL --security-opt no-new-privileges` → `curl -s localhost:18080/sante` rend `{"contrat":"v1","agent":"revue",…}` ;
  - `docker run --rm --entrypoint id ai-agents-local` échoue (aucun shell ni outil dans l'image) ;
  - `trivy image --severity CRITICAL,HIGH --ignore-unfixed ai-agents-local` sans résultat.
- [ ] **Étape 2 : vérifier les workflows** : `actionlint` sur les deux fichiers ; `grep -nE 'uses: [^@]+@v?[0-9]' .github/workflows/*.yml` ne renvoie rien ; `cd agents && cargo audit` passe.
- [ ] **Étape 3 : commit** `ci: image ai-agents construite, analysée et épinglée par digest`.

### Task 11: Pile, secrets et vhost

**Fichiers :**
- Modifier : `deploy/portainer-stack.yml`, `scripts/vault-render-env.sh`, `deploy/nginx/portail.conf`
- Créer : `backend/tests/test_pile.py`

**Interfaces :**
- `deploy/portainer-stack.yml` :
  - un bloc commun `x-agent: &agent` : `image: ghcr.io/nicolaslallier/ai-agents:${IMAGE_TAG:-latest}@${AGENTS_DIGEST:?}`, `networks: [portail-agents]`, `read_only: true`, `cap_drop: [ALL]`, `security_opt: ["no-new-privileges:true"]`, `mem_limit: 64m`, `pids_limit: 64`, `restart: unless-stopped` ;
  - un service `agent-<nom>` par agent de `agents.yaml` : `<<: *agent`, `entrypoint: [<nom>]`, `environment: {AGENT_SECRET: ${PORTAIL_AGENT_SECRET_<NOM>:?}, AGENT_PORTAIL_URL: http://portail:8000, AGENT_VERSION: ${IMAGE_TAG:-latest}}`. Aucun `volumes`, aucun `ports`, aucun autre réseau ;
  - le service `portail` rejoint `portail-agents` et reçoit chaque `PORTAIL_AGENT_SECRET_<NOM>: ${PORTAIL_AGENT_SECRET_<NOM>:?}` ;
  - réseau `portail-agents: {internal: true}`. Le lanceur et le reste de l'Infra n'y sont pas.
- `scripts/vault-render-env.sh` : `MAP` gagne `PORTAIL_AGENT_SECRET_<NOM>=PORTAIL_AGENT_SECRET_<NOM>` pour chaque agent (obligatoires, hors `FACULTATIVES`) ; dans la boucle, une clé qui commence par `PORTAIL_AGENT_SECRET_` et fait moins de 32 caractères → `die "$key trop court (32 caractères au moins)"`, sans afficher la valeur.
- `deploy/nginx/portail.conf`, au niveau `server`, avant `location /` :

```nginx
    # Missions des agents : servies au seul réseau portail-agents, jamais par le frontal.
    location ^~ /interne/ {
        return 404;
    }
```

- [ ] **Étape 1 : tests qui échouent** dans `test_pile.py` (`yaml.safe_load` résout l'ancre et la clé de fusion ; `agents.yaml` relu par `charger_catalogue`) :
  - `test_un_service_par_agent` : les services `agent-*` sont exactement `agent-<nom>` pour chaque agent du catalogue du dépôt, chacun avec `entrypoint == [<nom>]` ;
  - `test_agent_isole` : pour chaque service `agent-*` : `networks == ["portail-agents"]`, pas de `volumes`, pas de `ports`, `read_only`, `cap_drop == ["ALL"]`, `no-new-privileges:true`, image `ai-agents` avec `@${AGENTS_DIGEST:?}`, et des clés d'environnement **exactement** `{AGENT_SECRET, AGENT_PORTAIL_URL, AGENT_VERSION}`, `AGENT_SECRET` valant `${PORTAIL_AGENT_SECRET_<NOM>:?}` (aucune clé LiteLLM, aucun jeton GitHub, aucun secret du lanceur, aucun secret d'un autre agent) ;
  - `test_reseau_agents_interne` : `portail-agents` est `internal: true` et ses membres sont `portail` et les `agent-*`, rien d'autre ;
  - `test_portail_recoit_chaque_secret` ;
  - `test_coffre_rend_chaque_secret` : `MAP` de `vault-render-env.sh` contient chaque `PORTAIL_AGENT_SECRET_<NOM>`, absent de `FACULTATIVES` ;
  - `test_secret_court_refuse` : `vault-render-env.sh` lancé avec un `curl` factice en tête de `PATH` (il imprime un JSON `{"data": {"data": {…}}}` où un secret d'agent fait 31 caractères), `VAULT_CA_CERT` sur un fichier de `tmp_path`, `PORTAIL_STACK_ENV` dans `tmp_path` → code non nul, message « trop court », la valeur absente de la sortie ;
  - `test_vhost_ne_sert_pas_interne` : `deploy/nginx/portail.conf` contient `location ^~ /interne/ { return 404; }` (expression régulière tolérante aux espaces).
- [ ] **Étape 2 :** ils échouent. **Étape 3 :** implémenter. **Étape 4 :** la suite passe ; `docker compose -f deploy/portainer-stack.yml config -q` avec un fichier d'environnement factice (toutes les variables obligatoires remplies) passe.
- [ ] **Étape 5 : commit** `feat(deploy): un service par agent sur un réseau interne, secrets par agent, /interne/ hors du frontal`.

### Task 12: Bureau — le conteneur répond-il, quelle version

**Fichiers :**
- Modifier : le module de H qui construit la réponse de `GET /api/bureau` et son schéma ; le composant de poste de la page Bureau de H et `frontend/src/api.ts` (noms réels pris dans le code de H)
- Test : le fichier de tests backend de H pour `/api/bureau` ; un test vitest à côté du composant de poste

**Interfaces :**
- Chaque poste gagne `conteneur: ConteneurVue | None` avec `ConteneurVue(repond: bool, version: str | None)` : `None` pour un agent sans `service:` ; sinon le résultat de `missions.sante(agent, delai_s=2)` — `repond=False, version=None` si `None`, sinon `repond=True, version=sante.version`. Les appels se font en parallèle (`asyncio.gather`) pour tous les agents `service:`, une fois par requête `GET /api/bureau`.
- `api.ts` : `conteneur: { repond: boolean; version: string | null } | null` sur le type du poste.
- Le poste affiche, pour un agent en conteneur : « conteneur ● <version> » ou « conteneur injoignable » (même style d'état que les autres badges du poste) ; rien pour un agent du portail. Fonction pure `libelleConteneur(c)` dans le module de H qui porte les fonctions du bureau, testée par vitest.

- [ ] **Étape 1 : tests qui échouent.**
  - backend, `test_bureau_conteneur` : catalogue de test avec `revue` (`service:`, `FauxAgent` en marche, version `sha-agent`), `tri` (`service:`, injoignable) et `code` (sans `service:`) → `revue.conteneur == {"repond": true, "version": "sha-agent"}`, `tri.conteneur == {"repond": false, "version": null}`, `code.conteneur is None`, et la réponse arrive même si `tri` ne répond jamais (délai de 2 s respecté) ;
  - frontend, `libelleConteneur` : `null` → `""` ; `{repond: false}` → « conteneur injoignable » ; `{repond: true, version: "sha-abc"}` → « conteneur ● sha-abc ».
- [ ] **Étape 2 :** ils échouent. **Étape 3 :** implémenter. **Étape 4 :** suite backend ; `cd frontend && npm run typecheck && npm test && npm run build`.
- [ ] **Étape 5 : commit** `feat(portail): le bureau montre si le conteneur d'un agent répond et sa version`.

### Task 13: Documentation — migrer un agent, comparer, revenir en arrière

**Fichiers :**
- Modifier : `README.md`, `deploy/infra/README.md` (F)

- [ ] **Étape 1 : README**, section « Agents en conteneur » :
  - le principe en cinq lignes (rôles, réseau `portail-agents`, aucun secret dans l'agent hormis le sien, limites tenues par le portail) et le lien vers `docs/agents-contrat-v1.md` ;
  - **écrire du code sur mesure** pour un agent : un module dans `agents/catalogue/src/`, sa branche dans `catalogue::tourner`, la conformité qui doit passer (`cargo test` dans `agents`) ;
  - **migrer le pilote `revue`** :
    1. relever la référence dans Grafana, tableau « Agents et modèles » filtré sur `agent=revue`, `lieu=portail` (réussite, jetons par heure, durée p95, erreurs) et tableau « Boucle de dev » (renvois `agent="revue"`, blocages par cause), sur au moins une semaine ;
    2. vérifier sur la page Bureau que le poste `revue` montre « conteneur ● <version> » ;
    3. ouvrir une PR qui ajoute `service: http://agent-revue:8080` à `revue` dans `agents.yaml`, la fusionner (le déploiement suit) ;
    4. comparer après quelques jours : mêmes panneaux avec `lieu=conteneur`, le panneau « réussite par lieu », la requête SQL `select lieu, version_image, issue, count(*), avg(duree_ms), sum(jetons_entree + jetons_sortie) from appel_llm where agent = 'revue' group by 1, 2, 3` ; suivre une mission dans Loki : `{container=~"portail-agent-revue.*"} | json | mission="<id>"`, et la même mission côté portail ;
    5. **revenir en arrière** : une PR qui retire la ligne `service:` ; rien d'autre (le conteneur reste en marche, inoccupé) ;
  - l'ordre de la spec pour la suite, un agent à la fois et seulement sur décision de Nicolas : `tri`, `plan`, `taches`, `spec`, `orchestrateur`, `tests`, `code` (puis les agents de D) ; le retrait de `boucle.py` vient après deux semaines où tous ont tenu, hors de ce plan ;
  - les **étapes manuelles** du lot I (voir plus bas).
- [ ] **Étape 2 :** `deploy/infra/README.md`, section « PR Infra du lot I » :
  1. `deploy/nginx/portail.conf` → `nginx/conf.d/` (bloc `location ^~ /interne/`) ;
  2. vérifications après déploiement : `curl -sk -o /dev/null -w '%{http_code}' -X POST https://portail.infra.famillelallier.net/interne/modele` rend `404` ; Loki rend des lignes JSON pour `{container=~"portail-agent-.*"} | json | agent != ""` (Alloy les ramasse déjà, rien à ajouter) ; `docker network inspect portail_portail-agents` ne liste que `portail` et les `agent-*`.
- [ ] **Étape 3 : commit** `docs: agents en conteneur, migration du pilote revue et retour arrière`.

---

## Ordre et dépendances

- Côté portail, dans l'ordre : 1 → 2 → 3 → 4 → 5 → 6 → 7 (chaque tâche s'appuie sur `missions.py` de la précédente ; 3 et 5 touchent `api.py` et `conftest.py`).
- Côté agents : 8 → 9, après 1 (le fichier d'exemples du contrat). Ces deux tâches ne touchent aucun fichier du portail et peuvent avancer en parallèle de 2 à 7 ; garder pourtant l'ordre des numéros pour la PR, afin que la conformité (9) décrive le contrat que les tests de triche (7) ont fixé.
- 10 après 9 (l'image compile les binaires), 11 après 10 (`AGENTS_DIGEST`) et après 6 (le portail lit les secrets), 12 après 5 (`Missions.sante`) et H, 13 en dernier.

**Avant de fusionner la tâche 11 dans `main`** (sinon le déploiement échoue sur les `:?`), étapes manuelles de Nicolas :
1. ranger dans OpenBao, au chemin de la pile (`infra/data/portail`), une clé par agent `PORTAIL_AGENT_SECRET_<NOM>` (13 clés : `SPEC`, `ORCHESTRATEUR`, `PLAN`, `TACHES`, `TESTS`, `CODE`, `REVUE`, `ARCHITECTE`, `CHALLENGER`, `SECURITE`, `DOC`, `PM`, `TRI`), chacune tirée de `openssl rand -hex 32` ;
2. ajouter le contrôle `agents` à la protection de `main` ;
3. après la fusion, ouvrir la PR Infra décrite dans `deploy/infra/README.md` (vhost seulement ; sans elle, `/interne/` passe par `location /` derrière oauth2-proxy, donc pas exposé sans session, mais le 404 voulu manque) ;
4. décider, agent par agent, de poser `service:` (README, tâche 13) — aucun agent ne migre dans ce plan.
