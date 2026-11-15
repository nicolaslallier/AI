# Choix de l'IA de la spec — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un menu en tête du chat de l'étape `spec` permet de choisir le modèle LiteLLM, figé au premier message.

**Architecture:** Colonne `etape.modele` (nullable). Une fonction `agent_effectif` de `agents.py` rend l'agent du catalogue avec le modèle de l'étape substitué ; `chat.py`, `avis.py` et `api._detail` passent par elle. L'écran envoie `modele` avec le premier message.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, pytest ; Vue 3 / TypeScript.

**Spec:** `docs/superpowers/specs/2026-11-15-choix-modele-spec-design.md`

## Global Constraints

- Choix possibles = `Catalogue.modeles_permis` ; présélection = `agent.modele`.
- Le modèle n'est retenu qu'au premier message de l'étape ; ensuite il est ignoré (pas d'erreur, l'étape garde son modèle).
- Un modèle hors `modeles_permis` → `Refus(422, "modèle non permis : <nom>")`.
- `etape.modele` vide (`NULL`) = modèle de `agents.yaml`. Aucune étape existante ne change.
- Alias LiteLLM exact à ajouter : `gemma4:26b-a4b-it-qat`.

## Review Focus

- Premier message refusé (contexte plein, message vide, 409) : le modèle ne doit pas être enregistré → la validation du modèle et son enregistrement se font dans la même transaction que le message (Task 2, test `test_modele_non_enregistre_si_refus`).
- `reessayer` / `rediger` après un choix : utilisent le modèle choisi (Task 2, `test_rediger_utilise_le_modele_choisi`).
- Challenger sur une spec écrite par le modèle choisi : `modele_pour` compare avec le modèle effectif (Task 2, `test_auteur_effectif`).
- Agent en conteneur (`service`) : le modèle part par `Mission` depuis `agent.modele` — couvert par la substitution unique, pas de test dédié.
- Menu affiché sur une étape déjà commencée : non, condition `messages.length === 0` (Task 3, vérification manuelle).

---

### Task 1: Colonne `etape.modele` et `agent_effectif`

**Files:**
- Create: `backend/migrations/versions/0010_etape_modele.py`
- Modify: `backend/portail/db.py` (classe `Etape`), `backend/portail/agents.py`
- Test: `backend/tests/test_agents.py`

**Interfaces:**
- Produces: `Etape.modele: Mapped[str | None]` ; `agent_effectif(cat: Catalogue, nom: str, modele: str | None) -> Agent | None` (None si `nom` absent du catalogue ; copie avec `modele` substitué si `modele` non vide, sinon l'agent tel quel).

- [ ] **Step 1: Tests** dans `test_agents.py` :

```python
def test_agent_effectif():
    cat = Catalogue(modeles_permis=["m", "g"], agents={"spec": _agent("spec")}, pipelines={})
    assert agent_effectif(cat, "spec", None).modele == "m"
    assert agent_effectif(cat, "spec", "g").modele == "g"
    assert cat.agents["spec"].modele == "m"  # le catalogue n'est pas modifié
    assert agent_effectif(cat, "absent", "g") is None
```

- [ ] **Step 2:** `uv run pytest backend/tests/test_agents.py::test_agent_effectif -v` → FAIL (import).
- [ ] **Step 3:** Implémenter `agent_effectif` (`model_copy(update={"modele": modele})`). Ajouter `modele: Mapped[str | None] = mapped_column(String)` à `Etape`. Migration `0010` (revision `"0010"`, down `"0009"`) : `op.add_column("etape", sa.Column("modele", sa.String))` / `drop_column`.
- [ ] **Step 4:** `uv run pytest backend/tests/test_agents.py -v` → PASS ; la suite démarre avec la migration (`uv run pytest backend/tests/test_chat.py -q` → PASS).
- [ ] **Step 5:** Commit `feat(portail): colonne etape.modele et agent_effectif`.

### Task 2: Le serveur prend et applique le modèle choisi

**Files:**
- Modify: `backend/portail/chat.py` (`_agent`, `envoyer`), `backend/portail/avis.py:149`, `backend/portail/api.py` (`MessageIn`, `envoyer_message`, `_detail`), `backend/portail/schemas.py` (`EtapeOut`), `agents.yaml`
- Test: `backend/tests/test_chat.py`, `backend/tests/test_avis.py`

**Interfaces:**
- Consumes: `agent_effectif`, `Etape.modele` (Task 1).
- Produces: `POST /api/etapes/{id}/messages` accepte `{"contenu": str, "modele": str | None}` ; `EtapeOut.modele: str | None` (modèle effectif, None si agent absent) et `EtapeOut.modeles: list[str]` (= `modeles_permis`) ; `ServiceChat.envoyer(etape_id, contenu, modele: str | None = None)`.

- [ ] **Step 1: Tests** dans `test_chat.py`. Le `CATALOGUE_TEST` de `conftest.py` reçoit `modeles_permis=["m", "g"]`.

```python
async def test_modele_choisi_au_premier_message(client, faux_llm):
    pid, eid = await _etape(client)
    e = await _etat(client, pid)
    assert (e["modele"], e["modeles"]) == ("m", ["m", "g"])
    r = await client.post(f"/api/etapes/{eid}/messages", json={"contenu": "A", "modele": "g"})
    assert r.status_code == 202
    await _attendre(client, eid)
    assert faux_llm.appels[-1]["modele"] == "g"
    await client.post(f"/api/etapes/{eid}/messages", json={"contenu": "B", "modele": "m"})
    await _attendre(client, eid)
    assert faux_llm.appels[-1]["modele"] == "g"  # figé
    assert (await _etat(client, pid))["modele"] == "g"

async def test_modele_non_permis_422(client):
    _, eid = await _etape(client)
    r = await client.post(f"/api/etapes/{eid}/messages", json={"contenu": "A", "modele": "x"})
    assert r.status_code == 422

async def test_modele_non_enregistre_si_refus(client):
    pid, eid = await _etape(client)
    r = await client.post(f"/api/etapes/{eid}/messages", json={"contenu": "  ", "modele": "g"})
    assert r.status_code == 422
    assert (await _etat(client, pid))["modele"] == "m"

async def test_rediger_utilise_le_modele_choisi(client, faux_llm):
    # premier message avec "g", puis POST /rediger ; le dernier appel LLM a modele == "g"
```

Dans `test_avis.py`, `test_auteur_effectif` : étape `spec` avec `modele="g"`, challenger avec `modele="g"` et `modele_si_meme="m"` → l'avis est demandé avec `"m"`. (Suivre la construction de catalogue déjà utilisée dans ce fichier.)

- [ ] **Step 2:** `uv run pytest backend/tests/test_chat.py backend/tests/test_avis.py -v` → les nouveaux tests FAIL.
- [ ] **Step 3: Implémenter.**
  - `chat._agent(etape)` → `agent_effectif(self._catalogue, etape.agent, etape.modele)` (même `Refus(409)` si None).
  - `chat.envoyer(..., modele=None)` : après les contrôles d'état et de contenu, si `modele` et que l'étape n'a aucun `Message` : refuser s'il n'est pas dans `modeles_permis`, sinon `etape.modele = modele` **avant** `self._agent(etape)` (la jauge suit le bon agent). Même commit que le message.
  - `avis.py:149` : `auteur = agent_effectif(self._catalogue, etape.agent, etape.modele)`.
  - `api._detail` : `agent = agent_effectif(catalogue, e.agent, e.modele)` ; ajouter `"modele": agent.modele if agent else None, "modeles": catalogue.modeles_permis` ; champs ajoutés à `EtapeOut`.
  - `MessageIn.modele: str | None = None`, transmis à `chat.envoyer`.
  - `agents.yaml` : `modeles_permis: [qwen3.8:27b-mlx, mlx-community/GLM-4.7-Flash-8bit, gemma4:26b-a4b-it-qat]`.
- [ ] **Step 4:** `uv run pytest backend -q` → PASS (toute la suite : `EtapeOut` change).
- [ ] **Step 5:** Commit `feat(portail): choix du modèle au premier message de la spec`.

### Task 3: Le menu dans `ChatEtape.vue`

**Files:**
- Modify: `frontend/src/api.ts` (`Etape`, `envoyerMessage`), `frontend/src/components/ChatEtape.vue`, `frontend/src/views/PipelineView.vue:188`

**Interfaces:**
- Consumes: `EtapeOut.modele`, `EtapeOut.modeles`, `modele` du corps de message (Task 2).
- Produces: `envoyerMessage(etapeId: number, contenu: string, modele?: string)` ; l'événement `envoyer` de `ChatEtape` devient `[contenu: string, vider: () => void, modele?: string]`.

- [ ] **Step 1:** `Etape` gagne `modele: string | null` et `modeles: string[]`. `envoyerMessage` envoie `{ contenu, modele }`.
- [ ] **Step 2:** Dans `ChatEtape.vue`, `const modele = ref(props.etape.modele ?? '')`. Au-dessus de la zone de saisie : si `etape.produit === 'spec' && etape.messages.length === 0`, un `<label>IA <select v-model="modele">` sur `etape.modeles` ; sinon, si `etape.produit === 'spec'`, `<span class="discret">IA : {{ etape.modele }}</span>`. `envoyer()` émet `modele` seulement quand le menu est affiché.
- [ ] **Step 3:** `PipelineView.vue:188` : `@envoyer="(c, vider, m) => action(() => envoyerMessage(e.id, c, m)).then(...)"`.
- [ ] **Step 4:** `cd frontend && npm run build && npm test` → build (vue-tsc) et tests PASS. Vérification à l'œil sur le portail : nouvelle spec → menu présent, qwen présélectionné ; après le premier message → « IA : gemma4… ».
- [ ] **Step 5:** Commit `feat(frontend): menu de choix de l'IA de la spec`.

## Hors dépôt (à signaler dans la PR)

Autoriser `gemma4:26b-a4b-it-qat` sur la clé LiteLLM `portail` (dépôt Infra, README ligne ~261), sinon LiteLLM refuse les appels.
