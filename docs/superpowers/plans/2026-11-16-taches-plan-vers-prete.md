# Le plan validé fait avancer le kanban — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** l'étape `taches` ne finit plus à vide sur des cibles non modifiables, et ses tâches créées partent en Prête.

**Architecture:** la vérification « tâche modifiable » remonte dans `lire_propositions`, donc dans la relance déjà présente de `ChatService._proposer`. Après l'acceptation d'office (`sans_validation`), `_enregistrer` déplace les tâches créées vers `prete` avec `deplacer_tache`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, pytest (`backend/`, lancé avec `uv run pytest`).

**Spec:** `docs/superpowers/specs/2026-11-16-taches-plan-vers-prete-design.md`

## Global Constraints

- Messages et noms en français, comme le reste du code.
- `enregistrer_propositions` garde sa vérification `_raison` sous verrou (course entre lecture et écriture).
- Seules les tâches **créées** par l'étape bougent ; une tâche modifiée reste dans sa colonne.
- Auteur du déplacement : `f"agent:{agent.nom}"`.

## Review Focus

- Dépendance `"T<id>"` vers une tâche protégée : reste permise (seules modification/retrait sont refusées) — test dans la tâche 1.
- Modification d'une tâche inconnue du projet : refusée avec « tâche absente du projet » — test dans la tâche 1.
- Étape `sans_validation` où une proposition est périmée au moment d'accepter : pas de `tache_creee_id`, donc rien à déplacer — couvert par la requête de la tâche 2 (filtre `is_not(None)`).
- Ordre en Prête = ordre de création (`Proposition.id`), pour que l'ordonnanceur suive le plan — test dans la tâche 2.
- Agent sans `sans_validation` : tâches toujours en `a_faire` quand Nicolas accepte — inchangé, couvert par les tests existants d'acceptation.

---

### Task 1: Refuser à la lecture les cibles non modifiables

**Files:**
- Modify: `backend/portail/propositions.py` (`lire_propositions`)
- Modify: `backend/portail/chat.py` (construction de `cles` dans `_tache`, `_proposer`)
- Modify: `agents.yaml` (`taches.consigne_redaction`)
- Test: `backend/tests/test_propositions.py`

**Interfaces:**
- Produces: `lire_propositions(texte: str, taches: dict[int, str | None]) -> list[PropositionLue]` — `taches` : chaque tâche du projet → raison de non-modification (`_raison(t, projet_id)`) ou `None`. Une `Modification`/`Retrait` dont `tache_id` est absent de `taches` lève `ValueError(f"T{id} : tâche absente du projet ; propose une tâche nouvelle")` ; avec une raison : `ValueError(f"T{id} : {raison} ; propose une tâche nouvelle")`. Les dépendances `T<id>` se vérifient contre les clés de `taches`.
- `ChatService._proposer(agent, demande, taches: dict[int, str | None])`.

- [ ] **Step 1: Tests qui échouent**

Dans `test_lire_propositions`, appeler `lire_propositions(texte, {1: None, 2: None})`. Ajouter :

```python
@pytest.mark.parametrize(
    "prop, attendu",
    [(_m(2, "x"), "T2 : tâche protégée ; propose une tâche nouvelle"),
     (_m(9, "x"), "T9 : tâche absente du projet"),
     ({"sorte": "retrait", "tache_id": 2, "raison": "r"}, "T2 : tâche protégée")],
)
def test_lire_propositions_cible_non_modifiable(prop, attendu):
    with pytest.raises(ValueError, match=attendu):
        lire_propositions(_json(prop), {1: None, 2: "tâche protégée"})


def test_lire_propositions_depend_d_une_protegee():
    (n,) = lire_propositions(_json(_n("n1", depend_de=["T2"])), {2: "tâche protégée"})
    assert n.depend_de == ["T2"]
```

Remplacer `test_proposition_sur_tache_protegee_ecartee` par :

```python
async def test_proposition_sur_tache_protegee_relance(client, sessions, faux_llm):
    pid = await _projet(sessions)
    tid = (await client.post(f"/api/projets/{pid}/taches", json={"titre": "Manuelle"})).json()["id"]
    _, _, eid = await _lancer(
        client, sessions, faux_llm, _json(_m(tid, "Réécrite"), _n("n1")), _json(_n("n1")), pid=pid
    )
    assert [p.sorte for p in await _propositions(sessions, eid)] == ["nouvelle"]
    dernier = faux_llm.appels[-1]["messages"][-1]["content"]
    assert f"T{tid} : tâche protégée ; propose une tâche nouvelle" in dernier


async def test_proposition_sur_tache_protegee_deux_fois_echoue(client, sessions, faux_llm):
    pid = await _projet(sessions)
    tid = (await client.post(f"/api/projets/{pid}/taches", json={"titre": "Manuelle"})).json()["id"]
    m = _json(_m(tid, "Réécrite"))
    _, _, eid = await _lancer(client, sessions, faux_llm, m, m, pid=pid)
    async with sessions() as s:
        etape = await s.get(Etape, eid)
    assert etape.etat == "echouee"
    assert "tâche protégée" in etape.erreur
```

Les autres appels de `lire_propositions` du fichier (`{1}` → `{1: None}`) suivent la nouvelle signature.

- [ ] **Step 2: Vérifier l'échec**

Run: `cd backend && uv run pytest tests/test_propositions.py -q`
Expected: FAIL sur les nouveaux tests (aucune erreur levée / étape terminée).

- [ ] **Step 3: Implémenter**

`lire_propositions` : dans la boucle sur `lues`, pour un non-`Nouvelle`, vérifier `p.tache_id` contre `taches` avant les dépendances. Dans `chat.py`, remplacer le `set` d'ids par `{t.id: _raison(t, projet.id) for t in <tâches du projet>}` (importer `_raison` depuis `portail.propositions`, comme `_dependances` ailleurs). Dans `agents.yaml`, ajouter à `consigne_redaction` du `taches` :

```
Une tâche protégée, verrouillée ou hors a_faire/prete ne se modifie pas et ne se retire pas :
une étape du plan devient une tâche nouvelle (elle peut en dépendre avec "T<id>").
```

- [ ] **Step 4: Vérifier**

Run: `cd backend && uv run pytest tests/test_propositions.py tests/test_agents.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/portail/propositions.py backend/portail/chat.py agents.yaml backend/tests/test_propositions.py
git commit -m "fix(portail): l'agent de tâches est relancé s'il vise une tâche non modifiable"
```

### Task 2: Les tâches créées d'office partent en Prête

**Files:**
- Modify: `backend/portail/chat.py` (`ChatService._enregistrer`)
- Test: `backend/tests/test_propositions.py`

**Interfaces:**
- Consumes: `tout_accepter(session, etape_id) -> int`, `deplacer_tache(session, tache, colonne, avant_id, auteur) -> None` (existants).

- [ ] **Step 1: Tests qui échouent**

Dans `test_sans_validation_les_taches_vont_au_kanban`, ajouter :

```python
    taches = sorted(kanban["taches"], key=lambda t: t["rang"])
    assert [(t["titre"], t["colonne"]) for t in taches] == [("n1", "prete"), ("n2", "prete")]
    async with sessions() as s:
        evs = (await s.scalars(select(TacheEvenement).where(
            TacheEvenement.type == "deplacement").order_by(TacheEvenement.id))).all()
    assert [(e.auteur, e.donnees["vers"]) for e in evs] == [("agent:taches", "prete")] * 2
```

Ajouter :

```python
async def test_sans_validation_modification_reste_en_place(client, sessions, faux_llm, monkeypatch):
    from conftest import CATALOGUE_TEST

    monkeypatch.setattr(CATALOGUE_TEST.agents["taches"], "sans_validation", True)
    pid = await _projet(sessions)
    tid = await _tache_agent(sessions, pid)
    await _lancer(client, sessions, faux_llm, _json(_m(tid, "Par l'agent")), pid=pid)
    async with sessions() as s:
        assert (await s.get(Tache, tid)).colonne == "a_faire"
```

- [ ] **Step 2: Vérifier l'échec**

Run: `cd backend && uv run pytest tests/test_propositions.py -k sans_validation -q`
Expected: FAIL (colonne `a_faire`).

- [ ] **Step 3: Implémenter**

Dans `_enregistrer`, sous `if agent.sans_validation:` après `tout_accepter` : pour chaque `Proposition.tache_creee_id` non nul de l'étape, par `Proposition.id`, `deplacer_tache(s, await s.get(Tache, tid), "prete", None, f"agent:{agent.nom}")`.

- [ ] **Step 4: Vérifier toute la suite et le lint**

Run: `cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: tout passe, lint propre.

- [ ] **Step 5: Commit**

```bash
git add backend/portail/chat.py backend/tests/test_propositions.py
git commit -m "feat(portail): les tâches du plan validé partent en Prête"
```
