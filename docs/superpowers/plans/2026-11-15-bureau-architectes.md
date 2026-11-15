# Bureau d'architectes — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter au portail un pipeline `architecture` où Nicolas discute d'une vision avec un architecte d'entreprise, puis reçoit un document TOGAF et un fichier modèle ArchiMate 3.2, produits par huit agents en chaîne.

**Architecture:** Le moteur de pipelines existant est réutilisé : une étape de discussion (vision), six étapes automatiques qui s'enchaînent sans validation (volets), une étape de synthèse. Chaque document se termine par un bloc JSON de modèle que le portail valide ; le portail fusionne ces blocs, assemble le document final à la lecture et produit le XML d'échange par du code. Aucune migration : le bloc reste dans `Document.contenu` et `Document.type` est déjà une chaîne libre.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, pytest ; Vue 3, TypeScript, vitest, `marked` ; Rust (catalogue des agents) ; `xmlschema` ajouté au groupe `dev` pour valider le XML dans un test.

**Spec:** `docs/superpowers/specs/2026-11-15-bureau-architectes-design.md` — à lire en entier avant la tâche 1. Les prompts des agents y sont, mot pour mot.

## Global Constraints

- Tout en français : code, messages d'erreur, tests, commits (style du dépôt : `feat(portail): …`).
- Les noms d'agents sont exactement : `archi-entreprise`, `archi-affaires`, `archi-donnees`, `archi-applicatif`, `archi-techno`, `archi-securite`, `archi-solution`, `archi-entreprise-synthese`.
- Les préfixes d'identifiants sont exactement : `mot-`, `aff-`, `don-`, `app-`, `tec-`, `sec-`, `sol-`, `ent-`, dans l'ordre des étapes.
- Les agents déjà en place gardent leur modèle local et leur comportement : aucun test existant ne change de sens.
- Le XML d'échange est produit par du code, jamais par un modèle.
- Les listes de types d'éléments, de relations et de points de vue ArchiMate viennent du XSD officiel de l'Open Group (format d'échange 3.x), pas de la mémoire.
- Aucun nom de modèle infonuagique n'est inventé : Nicolas fournit les trois noms LiteLLM et leur contexte avant la tâche 7. S'ils manquent à ce moment-là, arrêter et les lui demander.
- `uv run ruff check . && uv run ruff format --check . && uv run pytest` passent dans `backend/` à la fin de chaque tâche backend.

## Review Focus

1. **Réponse coupée ou sans bloc** : l'étape échoue avec « bloc de modèle absent », aucun document n'est validé, l'étape suivante ne démarre pas. → test tâche 5.
2. **Un volet cite un identifiant qui n'existe pas** : l'étape échoue et le message nomme l'identifiant. → test tâche 1.
3. **Nicolas corrige un brouillon à la main et casse le JSON** : `PUT …/document` répond 422, le brouillon précédent est intact. → test tâche 5.
4. **Fusions tordues à l'étape 8** (identifiant inconnu, `garder` lui-même retiré ailleurs, `garder == retirer`) : refusées avec un message précis ; une vue vidée par les fusions est retirée plutôt que rendue vide. → tests tâche 2.
5. **Caractères spéciaux dans un nom ou une description** (`&`, `<`, guillemets, accents) : le XML reste valide. → test tâche 3.

---

### Task 1: Lire et valider un bloc de modèle

**Files:**
- Create: `backend/portail/archimate.py`
- Create: `backend/portail/archimate_types.py` (trois `frozenset` : `ELEMENTS`, `RELATIONS`, `POINTS_DE_VUE`, recopiés du XSD avec un commentaire qui cite sa version)
- Test: `backend/tests/test_archimate.py`

**Interfaces:**
- Produces:
  - `class Element(BaseModel)`: `id: str`, `type: str`, `nom: str`, `description: str = ""`
  - `class Relation(BaseModel)`: `type: str`, `source: str`, `cible: str`, `nom: str = ""`
  - `class Vue(BaseModel)`: `nom: str`, `point_de_vue: str = ""`, `elements: list[str]`
  - `class Fusion(BaseModel)`: `garder: str`, `retirer: str`
  - `class Modele(BaseModel)`: `elements: list[Element] = []`, `relations: list[Relation] = []`, `vues: list[Vue] = []`, `fusions: list[Fusion] = []`
  - `class BlocInvalide(ValueError)`
  - `lire_bloc(contenu: str) -> tuple[str, Modele]` — rend le texte sans le bloc et le modèle. Le bloc est le **dernier** bloc clôturé ` ```json ` du contenu.
  - `valider(modele: Modele, prefixe: str, connus: set[str]) -> None` — lève `BlocInvalide`. `connus` : identifiants des étapes précédentes.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
VOLET = 'Texte.\n\n```json\n{"elements":[{"id":"app-portail","type":"ApplicationComponent","nom":"Portail"}],' \
        '"relations":[{"type":"Serving","source":"app-portail","cible":"aff-rediger"}],' \
        '"vues":[{"nom":"Coopération","elements":["app-portail","aff-rediger"]}]}\n```\n'

def test_lire_bloc_rend_le_texte_et_le_modele():
    texte, m = lire_bloc(VOLET)
    assert texte.strip() == "Texte." and m.elements[0].id == "app-portail"

@pytest.mark.parametrize("contenu, message", [
    ("Pas de bloc.", "bloc de modèle absent"),
    ("```json\n{pas du json\n```", "JSON illisible"),
    ("```json\n[1]\n```", "un objet est attendu"),
])
def test_lire_bloc_refuse(contenu, message): ...  # BlocInvalide, message contenu dans str(e)

def test_valider_accepte_un_volet_qui_cite_un_volet_precedent():
    valider(lire_bloc(VOLET)[1], "app-", {"aff-rediger"})

@pytest.mark.parametrize("modif, message", [
    (type_element="Bidule",          "type d'élément inconnu : Bidule"),
    (type_relation="Utilise",        "type de relation inconnu : Utilise"),
    (id_element="tec-portail",       "identifiant « tec-portail » : préfixe « app- » attendu"),
    (id_element="app-Portail X",     "identifiant « app-Portail X » : minuscules, chiffres et tirets"),
    (element en double,              "identifiant en double : app-portail"),
    (element déjà dans connus,       "identifiant déjà pris par une étape précédente"),
    (connus=set(),                   "relation : identifiant inconnu « aff-rediger »"),
    (vue cite "app-rien",            "vue « Coopération » : identifiant inconnu « app-rien »"),
    (vues=[],                        "au moins une vue est attendue"),
    (vue sans élément,               "vue « Coopération » vide"),
    (fusions non vides, prefixe app-,"fusions réservées à la synthèse"),
])
def test_valider_refuse(modif, message): ...
```

- [ ] **Step 2: Lancer, vérifier l'échec** — `cd backend && uv run pytest tests/test_archimate.py -q` → erreur d'import.
- [ ] **Step 3: Écrire `archimate_types.py`** à partir du XSD officiel (`archimate3_Model.xsd` : types dérivés de `ElementType` et de `RelationshipType` ; `archimate3_View.xsd` : énumération des points de vue).
- [ ] **Step 4: Implémenter `lire_bloc` et `valider`.** Identifiant valide : `^<prefixe>[a-z0-9]+(-[a-z0-9]+)*$`. `valider` rapporte la **première** erreur. Une `Modele` Pydantic invalide (champ manquant) devient `BlocInvalide` avec le chemin du champ.
- [ ] **Step 5: Lancer, vérifier le succès**, puis `uv run ruff check . && uv run ruff format --check .`
- [ ] **Step 6: Commit** — `feat(portail): lecture et validation du bloc de modèle ArchiMate`

### Task 2: Fusionner les blocs et rendre les catalogues

**Files:**
- Modify: `backend/portail/archimate.py`
- Test: `backend/tests/test_archimate.py`

**Interfaces:**
- Consumes: `Modele`, `BlocInvalide` (tâche 1).
- Produces:
  - `valider_synthese(modele: Modele, connus: set[str]) -> None` — règles de l'étape 8 : éléments propres préfixés `ent-` ; relations et vues citent `connus` ou ses propres éléments ; chaque fusion a `garder` et `retirer` dans `connus`, différents ; un identifiant n'est `retirer` qu'une fois ; un `garder` n'est jamais un `retirer` d'une autre fusion ; au moins une vue.
  - `fusionner(blocs: list[Modele], synthese: Modele | None) -> Modele` — union dans l'ordre des blocs, puis ajouts de la synthèse, puis fusions appliquées : l'élément `retirer` disparaît, relations et vues pointent vers `garder`, une relation devenue identique à une autre ou bouclant sur elle-même est retirée, une vue vide est retirée. Le résultat a `fusions == []`.
  - `catalogues_markdown(modele: Modele, origine: dict[str, str]) -> str` — trois tableaux markdown : éléments (`identifiant | type | nom | volet d'origine`), relations (`source | relation | cible | note`), vues (`nom | point de vue | nombre d'éléments`). `origine` : préfixe → nom du volet.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
def test_fusionner_unit_les_blocs_dans_l_ordre(): ...          # ids du résultat = ids de a puis de b
def test_fusion_remplace_partout():                             # retirer app-x, garder app-y
    # la relation tec-n → app-x devient tec-n → app-y ; la vue cite app-y une seule fois
def test_fusion_retire_relation_devenue_boucle_ou_doublon(): ...
def test_fusion_retire_une_vue_videe(): ...
@pytest.mark.parametrize("fusions, message", [
    ([("app-y", "app-inconnu")], "fusion : identifiant inconnu « app-inconnu »"),
    ([("app-y", "app-y")],       "fusion : « app-y » ne peut pas se remplacer lui-même"),
    ([("app-y", "app-x"), ("app-z", "app-y")], "fusion : « app-y » est gardé et retiré"),
    ([("app-y", "app-x"), ("app-z", "app-x")], "fusion : « app-x » retiré deux fois"),
])
def test_valider_synthese_refuse(fusions, message): ...
def test_valider_synthese_refuse_un_ajout_mal_prefixe(): ...    # "préfixe « ent- » attendu"
def test_catalogues_markdown_nomme_le_volet_d_origine():        # "| app-portail | ApplicationComponent | Portail | applicatif |"
```

- [ ] **Step 2: Lancer, vérifier l'échec.**
- [ ] **Step 3: Implémenter les trois fonctions.**
- [ ] **Step 4: Lancer, vérifier le succès ; ruff.**
- [ ] **Step 5: Commit** — `feat(portail): fusion des modèles et catalogues ArchiMate`

### Task 3: Produire le fichier d'échange ArchiMate

**Files:**
- Modify: `backend/portail/archimate.py`
- Modify: `backend/pyproject.toml` (ajouter `xmlschema` au groupe `dev`), `backend/uv.lock`
- Create: `backend/tests/xsd/` — les trois XSD officiels (`archimate3_Model.xsd`, `archimate3_View.xsd`, `archimate3_Diagram.xsd`) et leur avis de droits d'auteur
- Test: `backend/tests/test_archimate.py`

**Interfaces:**
- Consumes: `Modele` fusionné (tâche 2).
- Produces: `xml_echange(modele: Modele, nom: str) -> str` — document XML complet, encodage UTF-8.

Décisions :
- Écrit avec `xml.etree.ElementTree` (échappement fait par la bibliothèque).
- Identifiant XML : `id-` + identifiant du modèle. Relations : `id-rel-<n>`. Vues : `id-vue-<n>`. Nœuds : `id-vue-<n>-n<k>`. Connexions : `id-vue-<n>-c<k>`.
- Toutes les étiquettes `name` et `documentation` portent `xml:lang="fr"`.
- Chaque vue devient un diagramme. Grille : 4 colonnes, nœud 160 × 60, origine (40, 40), pas horizontal 200, pas vertical 100, dans l'ordre de la liste de la vue. Une connexion par relation dont les deux extrémités sont dans la vue.
- `point_de_vue` absent de `POINTS_DE_VUE` : l'attribut `viewpoint` est omis.
- La structure exacte (espace de noms, `xsi:type`, ordre des enfants) se lit dans les XSD ; le test de validation tranche.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
SCHEMA = xmlschema.XMLSchema(Path(__file__).parent / "xsd" / "archimate3_Diagram.xsd")

def test_xml_valide_contre_le_xsd():
    SCHEMA.validate(io.StringIO(xml_echange(MODELE_COMPLET, "Projet P")))

def test_xml_echappe_les_caracteres_speciaux():
    # élément nommé 'R&D <cœur> "x"' : validation XSD réussie, et le nom relu par ElementTree est identique

def test_xml_une_vue_devient_un_diagramme_en_grille():
    # vue de 5 éléments : 5 nœuds ; le 5e est en x=40, y=140 ; w=160, h=60

def test_xml_ne_trace_que_les_relations_internes_a_la_vue(): ...
def test_xml_omet_un_point_de_vue_inconnu(): ...
def test_xml_modele_sans_vue_ni_relation_reste_valide(): ...
```

- [ ] **Step 2: Lancer, vérifier l'échec.**
- [ ] **Step 3: Télécharger les XSD** depuis le site de l'Open Group dans `backend/tests/xsd/`, `uv add --dev xmlschema`. Si les droits d'auteur des XSD interdisent de les ranger dans le dépôt, s'arrêter et le signaler à Nicolas.
- [ ] **Step 4: Implémenter `xml_echange`.**
- [ ] **Step 5: Lancer, vérifier le succès ; ruff.**
- [ ] **Step 6: Commit** — `feat(portail): fichier d'échange ArchiMate 3 avec vues en grille`

### Task 4: Le catalogue connaît les agents d'architecture

**Files:**
- Modify: `backend/portail/agents.py` (classe `Agent`, `_coherent`, `charger_catalogue`)
- Test: `backend/tests/test_agents.py`

**Interfaces:**
- Produces, sur `Agent` :
  - `produit` accepte en plus `"vision"`, `"volet"`, `"architecture"`
  - `sans_validation: bool = False`
  - `prefixe: str | None = None` (motif `^[a-z]{3}-$`)
  - `volet: str | None = None` (nom lisible : « affaires », « données »…, sert au catalogue d'origine)
  - constante `PRODUITS_ARCHITECTURE = ("vision", "volet", "architecture")`

Règles ajoutées à `_coherent` (un message par règle, au format des messages existants) :
- produit d'architecture ⇒ `prefixe` et `consigne_redaction` requis ; sinon `prefixe` interdit.
- `sans_validation` ⇒ `auto` et produit `volet`.
- produit `volet` ou `architecture` ⇒ `auto`.
- produit `architecture` ⇒ aucun outil.

Règles ajoutées à `charger_catalogue` : dans un pipeline, les `prefixe` sont uniques ; un agent `volet` ou `architecture` est précédé d'un agent `vision` ; un agent `architecture` est le dernier.

- [ ] **Step 1: Écrire les tests qui échouent** — un test paramétré `test_agent_architecture_refuse` (une ligne par règle ci-dessus, avec le fragment de message attendu) et `test_catalogue_architecture_accepte` (pipeline vision → volet → architecture valide).
- [ ] **Step 2: Lancer, vérifier l'échec** — `uv run pytest tests/test_agents.py -q`
- [ ] **Step 3: Implémenter.**
- [ ] **Step 4: Lancer toute la suite backend ; ruff.**
- [ ] **Step 5: Commit** — `feat(portail): produits vision, volet et architecture au catalogue`

### Task 5: Le pipeline s'enchaîne et valide ses blocs

**Files:**
- Create: `backend/portail/architecture.py`
- Modify: `backend/portail/chat.py` (`annexes`, `_preparer`, `_tache`, `corriger`, `valider`, `reessayer`)
- Modify: `backend/portail/moteur.py` (`creer_pipeline`)
- Modify: `backend/tests/conftest.py` (`CATALOGUE_TEST`)
- Test: `backend/tests/test_architecture.py`

**Interfaces:**
- Consumes: `lire_bloc`, `valider`, `valider_synthese`, `BlocInvalide` ; champs `prefixe`, `sans_validation` (tâche 4).
- Produces, dans `architecture.py` :
  - `async def documents_precedents(s: AsyncSession, etape: Etape) -> list[tuple[Etape, Document]]` — documents `validee` des étapes d'ordre inférieur du même pipeline, dans l'ordre.
  - `async def annexes_architecture(s, catalogue, etape) -> list[str]` — une annexe par document précédent : `"Vision validée :\n\n…"` pour la vision, `"Volet <volet> (<agent>) :\n\n…"` pour un volet, **bloc JSON compris**.
  - `async def verifier_bloc(s, catalogue, etape, contenu: str) -> None` — lève `BlocInvalide` ; choisit `valider` ou `valider_synthese` selon le produit ; `connus` = identifiants des documents précédents.

Comportements :
- `CATALOGUE_TEST` gagne un pipeline `architecture` de trois agents : `vision` (discussion, préfixe `mot-`), `volet` (auto, `sans_validation`, préfixe `aff-`), `synthese` (auto, produit `architecture`, préfixe `ent-`).
- `annexes()` : pour un produit `volet` ou `architecture`, ajoute `annexes_architecture`.
- `_tache`, après la rédaction d'un document d'architecture : `verifier_bloc` avant d'écrire le document. Un `BlocInvalide` fait échouer l'étape par le chemin d'erreur existant, avec son message ; aucun document n'est écrit.
- `_tache`, agent `sans_validation` : le document est écrit à l'état `validee` et `terminer_etape` est appelé dans la même transaction ; l'étape suivante est lancée après le commit. Aucun avis n'est lancé.
- `corriger` et `valider` : pour un document d'architecture, `verifier_bloc` d'abord ; `BlocInvalide` → `Refus(422, message)`.
- `creer_pipeline` et `reessayer` : la règle « un seul actif par projet » s'applique aussi au type `architecture`, avec le message « une architecture est déjà en cours pour ce projet ». La règle « spec validée requise » reste propre à `planification`.
- `_preparer` : l'aperçu est borné à `min(int(0.25 * agent.contexte_max), 8192)` jetons. Les agents à 32 768 de contexte ne changent pas.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
async def test_chaine_complete(client, faux_llm):
    # créer le pipeline architecture ; « rédiger » la vision (bloc mot- valide) ; valider
    # → le volet se rédige seul, son document est « validee », la synthèse se rédige seule
    # et attend : états des étapes == ["terminee", "terminee", "en_attente"]

async def test_volet_recoit_la_vision_en_annexe(client, faux_llm):
    # un message système de l'appel du volet commence par "Vision validée :" et contient le bloc

async def test_bloc_absent_fait_echouer_le_volet(client, faux_llm):
    # volet sans bloc → étape « echouee », erreur contient "bloc de modèle absent",
    # aucun document pour cette étape, la synthèse reste « a_faire »

async def test_reessayer_un_volet_echoue_reprend_la_chaine(client, faux_llm): ...

async def test_corriger_un_brouillon_au_bloc_casse_422(client, faux_llm):
    # PUT /api/etapes/{id}/document avec un JSON cassé → 422 ; GET rend l'ancien contenu et l'ancienne version

async def test_valider_la_vision_au_bloc_invalide_422(client, faux_llm): ...
async def test_deuxieme_architecture_active_409(client): ...
async def test_architecture_sans_spec_201(client): ...
async def test_annuler_pendant_un_volet_n_enchaine_pas(client, faux_llm): ...
def test_apercu_borne(): ...   # contexte_max 200_000 → budget 8192 ; 32_768 → 8192
```

- [ ] **Step 2: Lancer, vérifier l'échec** — `uv run pytest tests/test_architecture.py -q`
- [ ] **Step 3: Implémenter `architecture.py`, puis les changements de `chat.py` et `moteur.py`.**
- [ ] **Step 4: Lancer toute la suite backend ; ruff.** `tests/test_chat.py` et `tests/test_moteur.py` passent sans modification.
- [ ] **Step 5: Commit** — `feat(portail): pipeline architecture, enchaînement des volets et validation des blocs`

### Task 6: Assembler le document et servir les deux fichiers

**Files:**
- Modify: `backend/portail/architecture.py`
- Modify: `backend/portail/api.py`
- Test: `backend/tests/test_architecture.py`

**Interfaces:**
- Consumes: `documents_precedents` (tâche 5), `fusionner`, `catalogues_markdown`, `xml_echange`, `lire_bloc`.
- Produces :
  - `async def modele_fusionne(s, catalogue, pipeline_id: int) -> Modele`
  - `async def assembler(s, catalogue, pipeline_id: int) -> str`
  - `GET /api/pipelines/{pipeline_id}/architecture.md` → `text/markdown; charset=utf-8`
  - `GET /api/pipelines/{pipeline_id}/architecture.xml` → `application/xml`, `Content-Disposition: attachment; filename="architecture-<pipeline_id>.xml"`

Décisions :
- `Document.contenu` de l'étape 8 garde **la partie écrite par le modèle** (sommaire, registres, risques, bloc). Le document complet est assemblé à la lecture, jamais stocké.
- Les deux routes répondent dès que l'étape 8 a un document, brouillon ou validé ; sinon 409 « l'architecture n'est pas encore rédigée » ; 404 si le pipeline n'existe pas ou n'est pas de type `architecture`.
- Ordre du document assemblé, titres de niveau 1 numérotés de 1 à 13 comme dans la spec : 1 = section « Sommaire exécutif et portée » de la synthèse ; 2 = la vision ; 3 à 8 = les volets dans l'ordre des étapes ; 9 à 12 = les quatre autres sections de la synthèse ; 13 = `catalogues_markdown`.
- Les blocs JSON sont retirés de tous les morceaux. Les titres d'un morceau inséré descendent d'un niveau pour tenir sous son titre numéroté.
- Les sections de la synthèse se retrouvent par leurs titres `## …` exacts (ceux de la consigne). Un titre manquant : la section assemblée contient « section absente de la synthèse » ; ce n'est pas une erreur.
- Nom du modèle dans le XML : nom du projet.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
async def test_document_assemble_a_treize_sections_dans_l_ordre(client, faux_llm):
    # titres de niveau 1 == ["1. Sommaire exécutif et portée", "2. Vision", …, "13. Annexe : catalogues"]
async def test_document_assemble_sans_bloc_json(client, faux_llm): ...      # "```json" absent
async def test_volet_recopie_tel_quel(client, faux_llm): ...                # une phrase du volet se retrouve mot pour mot
async def test_section_absente_de_la_synthese(client, faux_llm): ...
async def test_xml_telecharge_contient_tous_les_volets(client, faux_llm):   # un élément mot-, un aff-, un ent- ; valide contre le XSD
async def test_fusion_de_la_synthese_appliquee_au_xml(client, faux_llm): ...
async def test_routes_409_avant_la_synthese(client, faux_llm): ...
async def test_routes_404_pipeline_spec(client): ...
```

- [ ] **Step 2: Lancer, vérifier l'échec.**
- [ ] **Step 3: Implémenter.**
- [ ] **Step 4: Lancer toute la suite backend ; ruff.**
- [ ] **Step 5: Commit** — `feat(portail): document d'architecture assemblé et modèle ArchiMate téléchargeable`

### Task 7: Les huit agents, leurs conteneurs et la doc

**Préalable :** les trois noms de modèles LiteLLM et leur contexte, fournis par Nicolas.

**Files:**
- Modify: `agents.yaml`
- Modify: `agents/catalogue/src/lib.rs` (`NOMS` passe de 13 à 21), `agents/catalogue/tests/catalogue.rs`
- Create: `agents/catalogue/src/bin/archi-*.rs` (huit fichiers, sur le modèle de `tri.rs`)
- Modify: `deploy/portainer-stack.yml`, `scripts/vault-render-env.sh`
- Modify: `README.md`
- Test: `backend/tests/test_agents.py`, `backend/tests/test_pile.py` (existants, non modifiés sauf ajout ci-dessous)

Décisions :
- `agents.yaml` : les trois modèles dans `modeles_permis` ; les huit agents avec `prompt_systeme` et `consigne_redaction` **recopiés mot pour mot de la spec** (section « Les prompts »). Le bloc commun est collé à la fin du `prompt_systeme` des agents 2 à 8. Dans la consigne des volets, `<VOLET>` et `<préfixe>` sont remplacés. Le volet solution et le volet sécurité portent les sections supplémentaires que leur prompt annonce.
- Répartition des modèles et températures : tableau « Les modèles » de la spec. Un modèle qui refuse la température : champ omis.
- `outils: [lister, lire, chercher]` pour les agents 1 à 7 ; aucun pour `archi-entreprise-synthese`. `tours_max: 20`.
- `sans_validation: true` pour les six volets. `prefixe` et `volet` selon les contraintes globales.
- Pipeline : `architecture: [archi-entreprise, archi-affaires, archi-donnees, archi-applicatif, archi-techno, archi-securite, archi-solution, archi-entreprise-synthese]`.
- Le filtre de noms du test Rust accepte le tiret (`|| b == b'-'`) : aujourd'hui il ignorerait les nouveaux noms.
- Pile : huit services `agent-archi-*` sur l'ancre `*agent` et huit variables `PORTAIL_AGENT_SECRET_ARCHI_*` (tirets remplacés par des soulignés), côté portail et côté agent ; même liste dans `MAP` de `vault-render-env.sh`.
- README : le pipeline `architecture`, les trois modèles, la réémission de la clé LiteLLM limitée à `modeles_permis`, les huit secrets à créer dans OpenBao (`infra/portail`, 32 caractères au moins), et le rappel que ces agents envoient du contenu chez Anthropic, OpenAI et Google.

- [ ] **Step 1: Écrire le test qui échoue** dans `backend/tests/test_agents.py`

```python
def test_agents_yaml_reel_bureau_d_architectes():
    cat = charger_catalogue(RACINE / "agents.yaml")
    assert cat.pipelines["architecture"] == [
        "archi-entreprise", "archi-affaires", "archi-donnees", "archi-applicatif",
        "archi-techno", "archi-securite", "archi-solution", "archi-entreprise-synthese",
    ]
    assert [cat.agents[a].prefixe for a in cat.pipelines["architecture"]] == [
        "mot-", "aff-", "don-", "app-", "tec-", "sec-", "sol-", "ent-",
    ]
    locaux = {"qwen3.8:27b-mlx", "mlx-community/GLM-4.7-Flash-8bit"}
    for nom, a in cat.agents.items():
        assert nom.startswith("archi-") or a.modele in locaux, nom
    for a in cat.pipelines["architecture"][1:]:
        assert "Règles communes du bureau d'architectes" in cat.agents[a].prompt_systeme
```

- [ ] **Step 2: Lancer, vérifier l'échec** — `uv run pytest tests/test_agents.py tests/test_pile.py -q`
- [ ] **Step 3: Écrire `agents.yaml`.**
- [ ] **Step 4: Rust** — `NOMS`, les huit binaires, le filtre du test. `cd agents && cargo test` → vert.
- [ ] **Step 5: Pile et script OpenBao.** `uv run pytest tests/test_pile.py -q` → vert. Vérifier avec `grep -rn PORTAIL_AGENT_SECRET_TRI .` qu'aucun autre fichier ne liste les secrets un par un ; s'il y en a, y ajouter les huit.
- [ ] **Step 6: README.**
- [ ] **Step 7: Lancer les trois suites** (backend, `cargo test`, ruff).
- [ ] **Step 8: Commit** — `feat(portail): les huit agents du bureau d'architectes et leurs conteneurs`

### Task 8: L'écran

**Files:**
- Modify: `frontend/src/markdown.ts`, `frontend/src/markdown.test.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/views/ProjetView.vue`, `frontend/src/views/PipelineView.vue`
- Modify: `frontend/src/components/ChatEtape.vue`, `frontend/src/components/JaugeContexte.vue`

**Interfaces:**
- Consumes: les deux routes de la tâche 6 ; `produit` vaut `vision`, `volet` ou `architecture` sur une étape.
- Produces:
  - `sansBlocModele(md: string): string` dans `markdown.ts` — retire le dernier bloc ` ```json ` ; rend le texte tel quel s'il n'y en a pas.
  - `lireArchitecture(pipelineId: number): Promise<string>` et `urlModeleArchimate(pipelineId: number): string` dans `api.ts`.

Comportements :
- `ProjetView` : bouton « Lancer l'architecture », toujours actif (aucune spec requise), qui crée un pipeline `architecture` et y navigue, comme le bouton de planification.
- `PipelineView` : le panneau de document s'affiche aussi pour `vision`, `volet` et `architecture`.
  - `vision` et `volet` : rendu de `sansBlocModele(contenu)`. L'éditeur de correction garde le contenu complet, bloc compris.
  - `architecture` : rendu du document assemblé (`lireArchitecture`), rechargé quand la version du document change ; deux liens : « Télécharger le modèle ArchiMate » (`urlModeleArchimate`) et « Télécharger le document » (la route `.md`). L'éditeur de correction porte sur la partie de la synthèse.
- `ChatEtape` : le bouton dit « Rédiger la vision » pour `vision`. `JaugeContexte` : même libellé selon le produit.
- Les tableaux markdown se lisent : vérifier le rendu de `marked` et ajouter au besoin les règles de table à la classe `.markdown` dans `style.css`.

- [ ] **Step 1: Écrire les tests qui échouent** dans `markdown.test.ts`

```ts
it('retire le dernier bloc json', () => {
  expect(sansBlocModele('Texte\n\n```json\n{"a":1}\n```\n').trim()).toBe('Texte')
})
it('garde un bloc json qui n’est pas le dernier', () => { /* deux blocs : seul le dernier part */ })
it('rend le texte tel quel sans bloc', () => { expect(sansBlocModele('Texte')).toBe('Texte') })
```

- [ ] **Step 2: Lancer, vérifier l'échec** — `cd frontend && npm test`
- [ ] **Step 3: Implémenter `sansBlocModele`, les deux fonctions d'API, puis les vues.**
- [ ] **Step 4: `npm run typecheck && npm test && npm run build`** → verts.
- [ ] **Step 5: Vérifier à l'écran** avec le portail lancé en local et le faux modèle de `docker-compose.test.yml` : lancer une architecture, valider la vision, voir les étapes s'enchaîner, ouvrir le document assemblé, télécharger le XML.
- [ ] **Step 6: Commit** — `feat(portail): écran du pipeline architecture`

---

## Après la dernière tâche

Vérification manuelle que les tests ne couvrent pas, à faire par Nicolas ou avec lui : importer le XML téléchargé dans Archi et confirmer que les éléments, les relations et au moins une vue par volet s'affichent (critère de réussite 3 de la spec).

Avant le déploiement : les trois modèles et les clés de fournisseurs dans LiteLLM (dépôt Infra), la clé `PORTAIL_LITELLM_CLE` réémise, les huit secrets d'agents dans OpenBao.
