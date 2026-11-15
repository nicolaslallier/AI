# Portail H — Bureau des agents : plan d'implémentation

> **Pour les agents qui exécutent :** SOUS-SKILL REQUIS : superpowers:subagent-driven-development (recommandé) ou superpowers:executing-plans, tâche par tâche. Les étapes utilisent des cases `- [ ]`.

**But :** une page « Bureau » montre en direct l'état de chaque agent : son poste, ce sur quoi il travaille (avec un lien), son tour en cours, le remplissage de son contexte et son activité du jour. Le même rangement produit un schéma Mermaid des pipelines, repris dans le README et tenu à jour par la CI.

**Architecture :** aucun service, aucune table, aucune dépendance nouvelle. Le rangement (un groupe par pipeline dans l'ordre des étapes, un groupe à part pour les agents hors pipeline) est **une fonction** de `agents.py`, utilisée à la fois par le schéma Mermaid et par le bureau. Le backend gagne un module `bureau.py` qui lit des tables existantes : `etape`, `pipeline`, `execution_dev`, `conversation`, `action_conversation`, `avis` (D) et `appel_llm` (G). Deux routes en lecture (`GET /api/bureau`, `GET /api/bureau/{agent}`). Le bus d'événements gagne un signal `bureau` pour ce qu'il ne signale pas encore (conversations, avis, appels au modèle). La page est une vue Vue en CSS simple, sans bibliothèque de graphe.

**Pile :** Python 3.12 / FastAPI / SQLAlchemy / pytest ; Vue 3 / TypeScript / vitest ; Mermaid rendu par GitHub dans le README (aucun outil Mermaid installé).

**Spec :** `docs/superpowers/specs/2026-11-14-portail-f-i-ameliorations-design.md`, section « H — Bureau des agents ». **On suppose D, F puis G construits sur la même branche.** H consomme :
- de D (`docs/superpowers/plans/2026-11-14-portail-d-agents-transversaux.md`) : `Conversation.agent` (tâche 7), la table `avis` et `Document.pipeline_id` (tâche 6), `pipelines.dev: [tests, code, revue, challenger, securite, doc]` et la section `avis` du catalogue (tâche 1) ;
- de F (`docs/superpowers/plans/2026-11-14-portail-f-securite.md`) : `modeles_permis` exigé par `charger_catalogue` (tâche 4) — le `agents.yaml` du dépôt le porte, donc le test du README le charge sans rien de plus ;
- de G (`docs/superpowers/plans/2026-11-14-portail-g-monitoring.md`) : le modèle `AppelLLM` (table `appel_llm`, tâche 3) avec ses colonnes `quand`, `agent`, `mission`, `pipeline_id`, `etape_id`, `tache_id`, `conversation_id`, `jetons_entree`, `jetons_sortie`, `duree_ms`, `issue`, et l'index `ix_appel_llm_agent_quand` ; une mission = un identifiant posé par `journal.nouvelle_mission(agent, contexte_max)` à chaque exécution d'agent (tâche 2 : une étape de dev, un tour de chat d'étape, un envoi dans une conversation, un avis), inscrit dans `appel_llm.mission` à chaque appel au modèle.

*Point d'extension (après I, hors de H) : le poste montrera aussi si le conteneur de l'agent répond (`GET /sante` du contrat I) et sa version (`appel_llm.version_image`).*

## Contraintes globales

- Toutes les contraintes de D, F et G s'appliquent : français partout, pas de refonte de `dev.py` ni de `api.py` (on y ajoute des routes, on n'y déplace rien). Vérifications avant chaque commit, celles de `.github/workflows/ci.yml` :
  - backend : `cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest -q` ;
  - frontend (tâches 5 et 6) : `cd frontend && npm run typecheck && npm test && npm run build`.
- **Pas de nouvelle table, pas de migration, pas de dépendance** (ni Python, ni npm). Les flèches de la page sont des caractères ou des bordures CSS ; le schéma du README est du texte Mermaid que GitHub rend.
- **Aucun agent codé en dur** dans `bureau.py`, `schema_pipelines.py`, `BureauView.vue` : postes, groupes et ordre viennent du catalogue. Les tests du bureau tournent sur `CATALOGUE_TEST` (`backend/tests/conftest.py`), dont les agents (`a`, `b`, `petit`…) ne sont pas ceux du dépôt.
- **Aucun contenu dans les réponses du bureau** : ni prompt (`prompt_systeme`, `consigne_*`), ni titre de tâche ou de conversation, ni texte d'erreur (`Etape.erreur`, `Conversation.erreur`), ni message. Seulement identifiants, noms tirés de `agents.yaml`, états, compteurs, durées. Les libellés de travaux sont faits d'identifiants (`T12`, `planification #34`, `conversation #5`).
- **« Aujourd'hui »** = depuis minuit, fuseau `America/Toronto` (le fuseau du résumé du matin de D). Les fonctions de `bureau.py` reçoivent `maintenant: datetime` en paramètre ; seules les routes appellent `datetime.now(UTC)`.
- Les requêtes du bureau sont bornées : une par table pour l'ensemble des postes, plus deux par travail en cours (quelques-uns au plus). *ponytail : N+1 sur les travaux en cours ; regrouper en une requête fenêtrée si le bureau en compte des dizaines.*

## Points à surveiller en revue

1. **Un poste rouge pour toujours** : une erreur ne compte que si elle date d'aujourd'hui, et une étape annulée (`erreur == "annulé"`, posé par `annuler_pipeline`) n'est jamais une erreur — tâche 2, `test_erreur_du_jour_seulement`.
2. **Un nom d'agent écrit dans le code** (backend ou page) : les tests tournent sur un catalogue qui n'a aucun agent du dépôt ; relire `BureauView.vue` pour qu'aucune chaîne `orchestrateur`, `tri`, `dev`… n'y figure — tâches 2 et 6, `test_groupes_depuis_le_catalogue`.
3. **Du contenu qui sort par `/api/bureau`** (titre, erreur, prompt) : tâches 2 et 4, `test_bureau_sans_contenu` et `test_detail_sans_prompt`.
4. **Un appel au modèle sans usage** (`jetons_entree` nul) : pas de jauge, mais le tour compte quand même l'appel ; rien ne plante — tâche 3, `test_sans_usage_pas_de_jauge`.
5. **Un rechargement à chaque appel au modèle** : le signal `bureau` part à chaque ligne d'`appel_llm`. La page regroupe les signaux (`regrouper`, 1 s) ; la route reste légère (point ci-dessus sur les requêtes) — tâches 5 et 6.
6. **Le README périmé** après un changement de `agents.yaml` : la suite échoue avec la commande à lancer dans le message — tâche 1, `test_readme_a_jour`.

## D'où vient chaque donnée d'un poste

| Donnée | Source | Requête (tâche) |
|--------|--------|-----------------|
| postes, groupes, ordre | `agents.yaml` (`Catalogue`) | `rangement(cat)` (1) |
| travail « au travail » / « en attente de Nicolas » d'un agent de pipeline | `etape` ⋈ `pipeline` (⟕ `execution_dev` pour le `tache_id`) | `Etape.agent ∈ postes`, `Etape.etat ∈ {en_cours, en_attente}`, `Pipeline.etat ∈ {en_cours, en_attente}` (2) |
| travail « en erreur » d'un agent de pipeline | idem | `Etape.etat == echouee`, `Etape.erreur IS DISTINCT FROM 'annulé'`, `Pipeline.etat == echouee`, `Pipeline.maj_le >= début du jour` (2) |
| travaux d'un agent de conversation (D : `Conversation.agent`) | `conversation`, `action_conversation` | `etat == en_cours` → au travail ; une `ActionConversation` `proposee` → en attente ; `etat == erreur` et `maj_le >= début du jour` → en erreur (2) |
| avis en cours (D) | `avis` ⋈ `document` | `Avis.etat == en_cours` → au travail, lien vers `Document.pipeline_id` (2) |
| tour en cours | `appel_llm` | mission de la dernière ligne du travail (`agent` + `etape_id`, `conversation_id` ou `pipeline_id` pour un avis), puis `count(*) WHERE mission = …` (3) |
| remplissage du contexte | `appel_llm` + `contexte_max` du catalogue | dernier `jetons_entree` non nul de cette mission ÷ `agent.contexte_max` (3) |
| activité du jour | `appel_llm` | `count(*)`, `sum(jetons_entree + jetons_sortie)` `WHERE quand >= début du jour GROUP BY agent` (3) |
| modèle, outils permis (détail) | `agents.yaml` | `Agent.modele`, `modele_si_meme`, `outils`, `tours_max`, `contexte_max` (4) |
| dernières missions (détail) | `appel_llm` | 200 dernières lignes de l'agent, regroupées par `mission` en Python, 10 premières (4) |

---

### Task 1: Rangement et schéma Mermaid des pipelines

**Fichiers :**
- Modifier : `backend/portail/agents.py` (`rangement`), `README.md` (section « Agents et pipelines »)
- Créer : `backend/portail/schema_pipelines.py`, `backend/tests/test_schema_pipelines.py`
- Test : `backend/tests/test_agents.py`

**Interfaces :**
- `agents.py` : `def rangement(cat: Catalogue) -> list[tuple[str | None, list[str]]]` : un couple `(nom du pipeline, agents dans l'ordre des étapes)` par entrée de `cat.pipelines`, dans l'ordre du YAML ; puis `(None, agents qui ne sont dans aucun pipeline)`, dans l'ordre de `cat.agents`, seulement s'il y en a. Un agent placé dans deux pipelines apparaît dans les deux groupes. La section `avis` de D ne crée pas de groupe : un agent d'avis hors pipeline (`architecte`) va dans le groupe `None`.
- `schema_pipelines.py` :
  - `DEBUT = "<!-- schema-pipelines:debut -->"`, `FIN = "<!-- schema-pipelines:fin -->"` ;
  - `def mermaid(cat: Catalogue) -> str` : un bloc ` ```mermaid ` `flowchart LR` ; un `subgraph g<i>["<nom>"]` par groupe de `rangement` (`"hors pipeline"` pour `None`), un nœud `g<i>_<agent>["<agent>"]` par agent (identifiant préfixé par le groupe : un agent présent dans deux groupes donne deux nœuds), et `g<i>_<x> --> g<i>_<y>` entre deux étapes qui se suivent d'un pipeline — aucune flèche dans le groupe hors pipeline ;
  - `def remplacer(texte: str, bloc: str) -> str` : remplace ce qui est **entre** `DEBUT` et `FIN` par `"\n" + bloc + "\n"`, laisse le reste intact ; `ValueError` si un marqueur manque ;
  - `def main() -> None` (et `if __name__ == "__main__": main()`) : lit `RACINE / "agents.yaml"` par `charger_catalogue`, réécrit `RACINE / "README.md"`, où `RACINE = Path(__file__).resolve().parents[2]`. Commande : `cd backend && uv run python -m portail.schema_pipelines`.
- `README.md` : une section `## Agents et pipelines` : une phrase (« généré depuis `agents.yaml` ; après un changement, lancer `cd backend && uv run python -m portail.schema_pipelines` »), puis les deux marqueurs, avec entre eux la sortie de la commande.
- **Contrôle de CI** : le job `backend` de `ci.yml` lance déjà `uv run pytest` ; `test_readme_a_jour` y échoue dès que le README ne correspond plus à `agents.yaml`. Aucune étape de CI ajoutée.

- [ ] **Étape 1 : tests qui échouent.**
  - `test_agents.py`, `test_rangement` : sur `CATALOGUE_TEST`, `rangement` vaut `[("spec", ["spec"]), ("double", ["a", "b"]), ("petit", ["petit"]), ("planification", ["plan", "taches"]), (None, ["orchestrateur"])]` ; sur un catalogue dont tous les agents sont en pipeline, pas de groupe `None` ; un agent listé dans deux pipelines figure dans les deux.
  - `test_schema_pipelines.py` :
    - `test_fleches_entre_etapes_qui_se_suivent` : pipeline `x: [a, b, c]` → la sortie contient `g0_a --> g0_b` et `g0_b --> g0_c`, pas `g0_a --> g0_c` ;
    - `test_hors_pipeline_sans_fleche` : un agent `d` hors pipeline est dans le sous-graphe `"hors pipeline"` et aucune ligne `-->` ne le cite ;
    - `test_remplacer_entre_les_marqueurs` : le texte avant `DEBUT` et après `FIN` est inchangé ; `remplacer(remplacer(t, b), b) == remplacer(t, b)` ;
    - `test_remplacer_sans_marqueurs_refuse` : `ValueError` ;
    - `test_readme_a_jour` : `remplacer(readme, mermaid(charger_catalogue(RACINE / "agents.yaml"))) == readme`, message d'échec : « README périmé : lancer `cd backend && uv run python -m portail.schema_pipelines` ».
- [ ] **Étape 2 :** ils échouent.
- [ ] **Étape 3 : implémenter** `rangement`, `schema_pipelines.py`, ajouter la section et les marqueurs au README, puis lancer la commande.
- [ ] **Étape 4 :** la suite passe. Vérifier à l'œil le rendu Mermaid (aperçu GitHub de la branche, ou https://mermaid.live en y collant le bloc) ; sinon, le noter comme non vérifié dans la PR.
- [ ] **Étape 5 : commit** `feat(portail): schéma des pipelines généré depuis agents.yaml`.

### Task 2: `GET /api/bureau` — postes, groupes et travaux en cours

**Fichiers :**
- Créer : `backend/portail/bureau.py`, `backend/tests/test_bureau.py`
- Modifier : `backend/portail/schemas.py`, `backend/portail/api.py` (une route)

**Interfaces :**
- `schemas.py` :
  - `class Travail(BaseModel)` : `sorte: Literal["etape", "conversation", "avis"]`, `etat: Literal["au_travail", "en_attente", "en_erreur"]`, `libelle: str`, `lien: str`, `tour: int | None = None`, `jauge: Jauge | None = None` (les deux derniers remplis en tâche 3) ;
  - `class Poste(BaseModel)` : `nom: str`, `etat: Literal["libre", "au_travail", "en_attente", "en_erreur"]`, `travaux: list[Travail]`, `appels_jour: int = 0`, `jetons_jour: int = 0` ;
  - `class Groupe(BaseModel)` : `nom: str | None` (`None` = hors pipeline), `agents: list[str]` ;
  - `class Bureau(BaseModel)` : `groupes: list[Groupe]`, `postes: dict[str, Poste]` (une entrée par agent du catalogue, même s'il est dans plusieurs groupes).
- `bureau.py` :
  - `FUSEAU = ZoneInfo("America/Toronto")` ; `def debut_du_jour(maintenant: datetime) -> datetime` : minuit local du jour de `maintenant`, avec fuseau ;
  - `async def lire_bureau(s: AsyncSession, cat: Catalogue, maintenant: datetime) -> Bureau` : groupes de `rangement(cat)` ; puis les trois requêtes de la table « D'où vient chaque donnée » (étapes, conversations, avis), filtrées sur `Etape.agent` / `Conversation.agent` / `Avis.agent` ∈ `cat.agents` (une étape d'agent `portail` ou d'un agent retiré du YAML est ignorée) ;
  - libellés et liens : étape d'un pipeline `dev` → `T<tache_id>` (par `execution_dev`), sinon `<type du pipeline> #<pipeline_id>`, lien `/pipelines/<pipeline_id>` ; conversation → `conversation #<id>`, lien `/chat/<id>` ; avis → `avis <Document.type> #<pipeline_id>`, lien `/pipelines/<pipeline_id>` ;
  - une conversation à la fois `en_cours` et avec une action `proposee` compte une fois, `au_travail` ;
  - état du poste : `au_travail` s'il a un travail au travail, sinon `en_attente`, sinon `en_erreur`, sinon `libre` ; travaux triés dans cet ordre, puis par identifiant.
- `api.py` : `@app.get("/api/bureau", response_model=Bureau)` → `await lire_bureau(s, request.app.state.catalogue, datetime.now(UTC))`. Elle passe par `_utilisateur` comme les autres routes `/api/`.

- [ ] **Étape 1 : tests qui échouent** dans `test_bureau.py` (fixtures `sessions` et `client`, `CATALOGUE_TEST`, données insérées directement ; `maintenant` injecté pour les tests de date) :
  - `test_groupes_depuis_le_catalogue` (route) : `groupes` reprend `rangement(CATALOGUE_TEST)` (`nom: null` pour le dernier) ; `postes` a exactement les clés de `CATALOGUE_TEST.agents`, tous `libre`, `travaux == []` ;
  - `test_etape_en_cours_au_travail_avec_lien` : une étape `en_cours` d'agent `plan` dans un pipeline `planification` `en_cours` → poste `plan` `au_travail`, un travail `{sorte: "etape", libelle: "planification #<id>", lien: "/pipelines/<id>"}` ;
  - `test_etape_dev_libelle_tache` : étape `en_cours` d'agent `a` dans un pipeline `dev` avec une `ExecutionDev(tache_id=T)` → libellé `T<T>` ;
  - `test_etape_en_attente_de_nicolas` : étape `en_attente` → `en_attente` ;
  - `test_deux_conversations_deux_travaux` : deux conversations `en_cours` d'agent `orchestrateur` → deux travaux, liens `/chat/<id>` ;
  - `test_action_proposee_en_attente` : conversation `pret` avec une `ActionConversation` `proposee` → `en_attente` ; la même `en_cours` → un seul travail, `au_travail` ;
  - `test_erreur_du_jour_seulement` : une étape `echouee` (erreur « boum ») d'un pipeline `echouee` et une conversation `erreur` → `en_erreur` avec `maintenant` = maintenant, `libre` avec `maintenant` = maintenant + 2 jours ; une étape `echouee` avec `erreur == "annulé"` n'est jamais un travail ;
  - `test_pipeline_annule_ou_termine_ignore` : une étape `en_attente` dans un pipeline `terminee` → aucun travail ;
  - `test_avis_en_cours_au_travail` : une ligne `Avis(agent="a", etat="en_cours")` sur un document de type `plan` → poste `a` `au_travail`, libellé `avis plan #<pipeline_id>` ;
  - `test_priorite_des_etats` : un travail au travail et un en erreur → poste `au_travail`, le travail au travail en premier ;
  - `test_agent_hors_catalogue_ignore` : une étape `en_cours` d'agent `portail` → aucune clé `portail`, aucun travail ailleurs ;
  - `test_bureau_sans_contenu` : `MARQUEUR = "ZZ-secret-7731"` dans le titre d'une tâche (dev), d'une conversation, dans `Etape.erreur` et `Conversation.erreur` → `MARQUEUR` absent du corps JSON de `/api/bureau`.
- [ ] **Étape 2 :** ils échouent.
- [ ] **Étape 3 : implémenter.**
- [ ] **Étape 4 :** la suite passe.
- [ ] **Étape 5 : commit** `feat(portail): GET /api/bureau, postes et travaux en cours`.

### Task 3: Tour, contexte et activité du jour tirés de `appel_llm`

**Fichiers :**
- Modifier : `backend/portail/contexte.py` (`jauge_jetons`), `backend/portail/bureau.py`
- Test : `backend/tests/test_bureau.py`, `backend/tests/test_contexte.py`

**Interfaces :**
- `contexte.py` : `def jauge_jetons(utilises: int, maximum: int) -> Jauge` (ratio et `_niveau` comme aujourd'hui) ; `jauge(agent, messages_llm)` devient `jauge_jetons(estimer_jetons(messages_llm), agent.contexte_max)`, sans changement de comportement.
- `bureau.py` :
  - activité : une requête `select(AppelLLM.agent, func.count(), func.sum(func.coalesce(AppelLLM.jetons_entree, 0) + func.coalesce(AppelLLM.jetons_sortie, 0))).where(AppelLLM.quand >= debut_du_jour(maintenant)).group_by(AppelLLM.agent)` remplit `appels_jour` et `jetons_jour` ; les agents absents du catalogue sont ignorés ;
  - `async def _mission_du_travail(s, agent: str, **filtre) -> str | None` : `mission` de la dernière ligne (`order_by(AppelLLM.id.desc()).limit(1)`) de `appel_llm` pour cet agent et ce filtre — `etape_id=` pour une étape, `conversation_id=` pour une conversation, `pipeline_id=` pour un avis (G : un avis ne pose que `pipeline` dans le contexte) ;
  - pour chaque travail dont la mission est connue :
    - `tour` = `count(*)` des lignes de cette mission, **seulement si** le travail est `au_travail` (sinon `None`) ;
    - `jauge` = `jauge_jetons(j, agent.contexte_max)` où `j` est le dernier `jetons_entree` non nul de cette mission ; `None` s'il n'y en a pas. Ce sont les vrais jetons rendus par LiteLLM (G demande l'usage, même en flux), là où `construire()` ne voit pas les messages en mémoire d'une boucle d'outils de dev.

- [ ] **Étape 1 : tests qui échouent.**
  - `test_contexte.py`, `test_jauge_jetons` : `jauge_jetons(24_000, 32_768)` → `niveau == "alerte"` ; `jauge_jetons(30_000, 32_768)` → `plein` ; les tests existants de `jauge` passent sans changement.
  - `test_bureau.py` :
    - `test_activite_du_jour` : pour l'agent `a`, deux lignes aujourd'hui (jetons 10+5, puis nuls) et une hier → `appels_jour == 2`, `jetons_jour == 15` ; une ligne d'agent `zzz` hors catalogue ne crée pas de poste ;
    - `test_tour_de_la_mission_en_cours` : étape `en_cours` ; deux lignes de mission `m1` puis trois de mission `m2` avec cet `etape_id` → `tour == 3` ;
    - `test_jauge_des_vrais_jetons` : dernière ligne de `m2` avec `jetons_entree = 24_000`, une précédente à 1 000 → `jauge.utilises == 24_000`, `jauge.max == 32_768`, `niveau == "alerte"` ;
    - `test_sans_usage_pas_de_jauge` (point de revue n° 4) : lignes à `jetons_entree` nul → `jauge is None`, `tour` compte quand même les lignes ;
    - `test_tour_seulement_au_travail` : conversation `pret` avec une action `proposee` et des lignes `conversation_id` → `tour is None`, `jauge` présente ;
    - `test_avis_tour_par_pipeline` : avis en cours, lignes d'agent `a` avec ce `pipeline_id` et sans `etape_id` → `tour` compté.
- [ ] **Étape 2 :** ils échouent. **Étape 3 :** implémenter. **Étape 4 :** la suite passe.
- [ ] **Étape 5 : commit** `feat(portail): tour, contexte et activité du jour des postes`.

### Task 4: Détail d'un poste et dernières missions

**Fichiers :**
- Modifier : `backend/portail/schemas.py`, `backend/portail/bureau.py`, `backend/portail/api.py` (une route)
- Test : `backend/tests/test_bureau.py`

**Interfaces :**
- `schemas.py` :
  - `class MissionOut(BaseModel)` : `mission: str`, `debut: datetime`, `duree_ms: int`, `appels: int`, `jetons_entree: int`, `jetons_sortie: int`, `issue: str` (`ok` | `erreur` | `delai`), `libelle: str | None`, `lien: str | None` ;
  - `class PosteDetail(BaseModel)` : `nom`, `description`, `modele`, `modele_si_meme: str | None`, `outils: list[str]`, `tours_max: int`, `contexte_max: int`, `missions: list[MissionOut]`. **Ni `prompt_systeme`, ni `consigne_redaction`, ni `consigne_avis`.**
- `bureau.py`, `async def lire_poste(s: AsyncSession, cat: Catalogue, nom: str) -> PosteDetail` : `Refus(404, "agent inconnu")` si `nom` n'est pas au catalogue. Missions : les 200 dernières lignes `appel_llm` de l'agent (`order_by(AppelLLM.id.desc())`), regroupées par `mission` dans l'ordre de première apparition, lignes à `mission` nulle ignorées, 10 missions gardées. Pour une mission :
  - `debut` = min de `quand - duree_ms` (G inscrit la ligne à la fin de l'appel) ; `duree_ms` = max de `quand` − `debut` ;
  - `appels` = nombre de lignes ; jetons = sommes, nuls comptés 0 ;
  - `issue` = celle du dernier appel de la mission (*choix : un appel en erreur suivi d'un succès n'est pas une mission en erreur*) ;
  - `libelle` et `lien` par les identifiants de ses lignes : `tache_id` → `T<id>` et `/pipelines/<pipeline_id>` ; sinon `conversation_id` → `conversation #<id>` et `/chat/<id>` ; sinon `pipeline_id` → `pipeline #<id>` et `/pipelines/<id>` ; sinon `None`.
  - *ponytail : fenêtre de 200 lignes, une mission très longue peut être tronquée à son début ; passer à un `GROUP BY mission` SQL si ça gêne.*
- `api.py` : `@app.get("/api/bureau/{agent}", response_model=PosteDetail)` → `await lire_poste(s, request.app.state.catalogue, agent)`.

- [ ] **Étape 1 : tests qui échouent** dans `test_bureau.py` :
  - `test_detail_modele_et_outils` : `GET /api/bureau/spec` → `modele == "m"`, `outils == ["lister", "lire", "chercher"]`, `contexte_max`, `missions == []` ;
  - `test_detail_sans_prompt` : le corps n'a pas de clé `prompt_systeme` et ne contient pas `Tu es spec.` (le prompt de `CATALOGUE_TEST`) ;
  - `test_agent_inconnu_404` : `GET /api/bureau/zzz` → 404 ;
  - `test_dernieres_missions` : trois missions (dev avec `tache_id`, conversation, sans identifiant), la plus récente d'abord ; pour la première : `appels`, sommes de jetons, `duree_ms` = dernier `quand` − (premier `quand` − sa `duree_ms`), `issue` du dernier appel (`erreur` puis `ok` → `ok`), libellé `T<id>` et lien `/pipelines/<id>` ; la conversation donne `/chat/<id>` ; la troisième `lien is None` ;
  - `test_missions_limitees_a_dix` : douze missions → dix ;
  - `test_lignes_sans_mission_ignorees`.
- [ ] **Étape 2 :** ils échouent. **Étape 3 :** implémenter. **Étape 4 :** la suite passe.
- [ ] **Étape 5 : commit** `feat(portail): détail d'un poste et dernières missions`.

### Task 5: Signal `bureau` sur le flux d'événements

**Fichiers :**
- Modifier : `backend/portail/evenements.py`, `frontend/src/evenements.ts`
- Test : `backend/tests/test_evenements.py`, `frontend/src/evenements.test.ts`

**Interfaces :**
- `evenements.py` :
  - `Signal = tuple[Literal["kanban", "pipelines", "bureau"], int | None]` ;
  - `_BUREAU = (Conversation, ActionConversation, Avis, AppelLLM)` ; `_signal` rend `("bureau", None)` pour ces classes ; `_avant_execution` aussi pour un `update`/`delete` en masse sur l'une d'elles (`recuperer_interrompues` des conversations et des avis, `_perimer`) ;
  - `flux` est inchangé : il émet déjà `event: <type>` avec `{}` pour tout type autre que `kanban`.
  - Les étapes et les pipelines continuent d'émettre `pipelines` : la page Bureau écoute les deux.
- `evenements.ts` : `RappelsEvenements` gagne `bureau?: () => void` ; `source.addEventListener('bureau', () => rappels.bureau?.())`.

- [ ] **Étape 1 : tests qui échouent.**
  - `test_evenements.py` (fichier existant, fonction `_vider`) :
    - `test_conversation_signale_bureau` : `POST /api/conversations` → `("bureau", None)` publié ;
    - `test_appel_llm_signale_bureau` : insérer et valider une ligne `AppelLLM` dans une session → `("bureau", None)` ;
    - `test_mise_a_jour_en_masse_signale_bureau` : `update(ActionConversation).values(etat="perimee")` puis `commit` → `("bureau", None)` ;
    - `test_flux_relaye_bureau` : `bus.publier(("bureau", None))` → `flux(bus)` produit `event: bureau\ndata: {}\n\n`.
  - `evenements.test.ts`, `bureau appelle bureau()` : sur le modèle du test `pipelines`.
- [ ] **Étape 2 :** ils échouent. **Étape 3 :** implémenter. **Étape 4 :** la suite backend et `npm run typecheck && npm test` passent.
- [ ] **Étape 5 : commit** `feat(portail): signal bureau sur le flux d'événements`.

### Task 6: Page « Bureau »

**Fichiers :**
- Créer : `frontend/src/views/BureauView.vue`
- Modifier : `frontend/src/api.ts`, `frontend/src/router.ts`, `frontend/src/App.vue`, `frontend/src/components/JaugeContexte.vue`, `README.md`

**Interfaces :**
- `api.ts` : types `Travail`, `Poste`, `Groupe`, `Bureau`, `MissionAgent`, `PosteDetail` (mêmes champs que les schémas des tâches 2 à 4 ; `Groupe.nom: string | null`) ; `lireBureau(): Promise<Bureau>` (`GET /bureau`) et `lirePoste(nom: string): Promise<PosteDetail>` (`GET /bureau/${encodeURIComponent(nom)}`), par la fonction `appel` existante.
- `JaugeContexte.vue` : prop facultative `compacte?: boolean` ; quand elle est vraie, les deux paragraphes d'alerte (qui parlent de rédiger la spec) ne s'affichent pas. `ChatView` et `PipelineView` sont inchangés.
- `router.ts` : `{ path: '/bureau', name: 'bureau', component: BureauView }`. `App.vue` : lien « Bureau » dans le `nav`, après « Chat ».
- `BureauView.vue` :
  - une section par `Groupe`, titrée par son nom ou « Hors pipeline » si `nom === null` ; ses postes en ligne (`display: flex; flex-wrap: wrap`), dans l'ordre reçu ;
  - **flèche** : `<span class="fleche" aria-hidden="true">→</span>` avant chaque poste d'un groupe de pipeline sauf le premier (`g.nom !== null && i > 0`) ; aucune dans le groupe hors pipeline ;
  - un poste (carte cliquable, `button`) : nom ; pastille d'état (`libre`, `au travail`, `en attente de Nicolas`, `en erreur`, couleurs `--gris-doux`, `--succes`, `--alerte`, `--danger` du style existant) ; pour chaque travail, un `RouterLink` vers `lien` avec `libelle`, « tour N » si `tour !== null`, et `<JaugeContexte compacte>` si `jauge` ; l'activité du jour : « N appels · M jetons » ;
  - un clic sur un poste charge `lirePoste(nom)` et l'affiche dans un panneau sous les groupes (modèle, `modele_si_meme` s'il existe, outils permis, tableau des missions : début, durée, appels, jetons, issue, lien) ; un second clic sur le même poste le ferme ;
  - rafraîchissement : `ecouterEvenements({ pipelines: recharger, bureau: recharger })` avec `recharger = regrouper(charger, 1000)` (point de revue n° 5) ; le panneau ouvert se recharge aussi ; `setInterval(charger, 60000)` en filet de sécurité, comme `KanbanView` ; tout est arrêté dans `onUnmounted` ;
  - aucun nom d'agent ni de pipeline écrit dans le fichier (point de revue n° 2).
- `README.md`, section « Agents et pipelines » : une phrase hors des marqueurs : « La page Bureau (`/bureau`) montre en direct l'état de chaque agent, rangé comme ce schéma. »

- [ ] **Étape 1 :** `api.ts`, `JaugeContexte`, route et lien de menu ; `npm run typecheck` passe.
- [ ] **Étape 2 :** `BureauView.vue`.
- [ ] **Étape 3 :** `npm run typecheck && npm test && npm run build` passent ; `grep -nE "'(orchestrateur|tri|plan|code|revue|dev|spec)'" frontend/src/views/BureauView.vue` ne renvoie rien.
- [ ] **Étape 4 : vérification manuelle**, avec la base de test et le serveur de développement (`README.md`, « Lancer en local ») : la page montre un groupe par pipeline de `agents.yaml` et le groupe hors pipeline ; envoyer un message dans une conversation fait passer l'orchestrateur à « au travail » sans recharger la page, puis à « libre » ; un clic ouvre le détail ; à 375 px de large, les postes passent à la ligne sans défilement horizontal. Sans LiteLLM joignable, vérifier au moins l'affichage des postes libres et le détail, et noter le reste comme non vérifié dans la PR.
- [ ] **Étape 5 : commit** `feat(portail): page Bureau`.

---

## Ordre et dépendances

Tâche 1 d'abord (elle ne dépend que du catalogue ; `rangement` sert à la tâche 2). La tâche 2 avant 3 et 4 (`bureau.py`, schémas, et D pour `Conversation.agent` et `avis`). Les tâches 3 et 4 lisent `appel_llm` (G) et touchent `bureau.py` : l'une après l'autre. La tâche 5 est indépendante des tâches 2 à 4 côté backend, mais doit précéder la 6, qui consomme tout.

**Avant de fusionner dans `main` :** rien à ranger dans OpenBao, rien côté Infra (le vhost sert déjà `/api/` et le repli SPA couvre `/bureau`), aucune migration.
