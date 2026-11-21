from pathlib import Path

import pytest

from portail.agents import (
    OUTILS_ACTIONS_PORTAIL,
    OUTILS_PORTAIL,
    OUTILS_SUIVI,
    Agent,
    Catalogue,
    CatalogueInvalide,
    agent_effectif,
    charger_catalogue,
    modele_pour,
    rangement,
)

VALIDE = """
modeles_permis: [m]
agents:
  spec:
    description: d
    modele: m
    contexte_max: 1000
    temperature: 0.3
    prompt_systeme: p
pipelines:
  spec: [spec]
"""


def ecrire(tmp_path: Path, texte: str) -> Path:
    f = tmp_path / "agents.yaml"
    f.write_text(texte)
    return f


def test_charge_catalogue_valide(tmp_path):
    cat = charger_catalogue(ecrire(tmp_path, VALIDE))
    assert cat.agents["spec"].nom == "spec"
    assert cat.pipelines["spec"] == ["spec"]
    assert cat.agents["spec"].temperature == 0.3


def test_champ_manquant_nomme_l_agent(tmp_path):
    with pytest.raises(CatalogueInvalide) as exc:
        charger_catalogue(ecrire(tmp_path, VALIDE.replace("    modele: m\n", "")))
    assert "spec" in str(exc.value) and "modele" in str(exc.value)


def test_pipeline_agent_inconnu(tmp_path):
    with pytest.raises(CatalogueInvalide, match="inconnu"):
        charger_catalogue(ecrire(tmp_path, VALIDE.replace("spec: [spec]", "spec: [inconnu]")))


def test_pipeline_vide_refuse(tmp_path):
    with pytest.raises(CatalogueInvalide):
        charger_catalogue(ecrire(tmp_path, VALIDE.replace("spec: [spec]", "spec: []")))


def test_modeles_permis_absents(tmp_path):
    with pytest.raises(CatalogueInvalide, match="modeles_permis"):
        charger_catalogue(ecrire(tmp_path, VALIDE.replace("modeles_permis: [m]\n", "")))


def test_modeles_permis_vides(tmp_path):
    with pytest.raises(CatalogueInvalide, match="modeles_permis"):
        charger_catalogue(ecrire(tmp_path, VALIDE.replace("[m]", "[]", 1)))


def test_modele_hors_liste(tmp_path):
    texte = VALIDE.replace("    modele: m\n", "    modele: gpt-x\n")
    with pytest.raises(CatalogueInvalide) as exc:
        charger_catalogue(ecrire(tmp_path, texte))
    assert "agent « spec »" in str(exc.value) and "gpt-x" in str(exc.value)


def test_catalogue_du_depot():
    assert charger_catalogue(Path("../agents.yaml")).modeles_permis


def test_yaml_illisible(tmp_path):
    with pytest.raises(CatalogueInvalide):
        charger_catalogue(ecrire(tmp_path, "agents: [unclosed\n  : :"))


def test_agents_yaml_du_depot_est_valide():
    racine = Path(__file__).resolve().parents[2]
    cat = charger_catalogue(racine / "agents.yaml")
    assert "spec" in cat.pipelines
    assert cat.pipelines["planification"] == ["plan", "taches"]
    assert cat.pipelines["dev"] == [
        "tests",
        "code",
        "revue",
        "challenger",
        "securite",
        "documentaliste",
    ]
    assert cat.avis == {"spec": ["challenger"], "plan": ["architecte", "challenger"]}
    assert "pm" not in cat.pipelines
    a = cat.agents
    assert (a["tests"].produit, a["tests"].role, a["tests"].tours_max) == ("travail", "tests", 40)
    assert (a["code"].produit, a["code"].role, a["code"].tours_max) == ("travail", "code", 40)
    assert set(a["tests"].outils) == set(a["code"].outils) == {
        "lister", "lire", "chercher", "ecrire", "supprimer", "lancer",
    }  # fmt: skip
    assert (a["revue"].produit, a["revue"].role) == ("verdict", "revue")
    assert a["revue"].outils == ["lister", "lire", "chercher"]
    assert a["tests"].modele == a["code"].modele == a["revue"].modele == a["plan"].modele
    assert (a["tri"].produit, a["tri"].role) == ("verdict", "revue")
    assert a["tri"].outils == ["lister", "lire", "chercher"]
    assert a["tri"].modele == a["revue"].modele
    assert all("tri" not in etapes for etapes in cat.pipelines.values())
    assert "notes" in a["revue"].prompt_systeme
    assert (
        a["architecte"].outils == ["lister", "lire", "chercher"] and a["architecte"].consigne_avis
    )
    c = a["challenger"]
    assert (c.produit, c.role, c.modele) == ("verdict", "revue", "qwen3.8:27b-mlx")
    assert c.modele_si_meme == "mlx-community/GLM-4.7-Flash-8bit"
    assert c.outils == ["lister", "lire", "chercher"] and c.consigne_avis
    s = a["securite"]
    assert (s.produit, s.role) == ("verdict", "revue")
    assert s.outils == ["lister", "lire", "chercher", "lancer"]
    d = a["doc"]
    assert (d.produit, d.role) == ("travail", "doc")
    assert d.outils == ["lister", "lire", "chercher", "ecrire", "supprimer"]
    doc2 = a["documentaliste"]
    assert (doc2.produit, doc2.role, doc2.modele) == ("travail", "doc", "gemma4:26b-a4b-it-qat")
    assert doc2.outils == ["lister", "lire", "chercher", "ecrire", "supprimer"]
    assert doc2.tours_max <= 30 and "à confirmer" in doc2.prompt_systeme
    pm = a["pm"]
    assert (
        set(pm.outils) == set(OUTILS_PORTAIL) - set(OUTILS_ACTIONS_PORTAIL) and pm.tours_max == 10
    )
    assert {"en_attente_de_nicolas", "activite"} <= set(pm.outils)


def test_pipelines_mauvaise_forme(tmp_path):
    with pytest.raises(CatalogueInvalide) as exc:
        charger_catalogue(ecrire(tmp_path, VALIDE.replace("spec: [spec]", 'spec: "spec"')))
    assert "pipelines" in str(exc.value) and "?" not in str(exc.value)


def test_nom_dans_agent_refuse(tmp_path):
    with pytest.raises(CatalogueInvalide, match="spec"):
        charger_catalogue(
            ecrire(tmp_path, VALIDE.replace("    modele: m", "    nom: x\n    modele: m"))
        )


def test_agent_auto_sans_consigne_refuse(tmp_path):
    with pytest.raises(CatalogueInvalide, match="spec"):
        charger_catalogue(
            ecrire(
                tmp_path,
                VALIDE.replace("    prompt_systeme: p", "    prompt_systeme: p\n    auto: true"),
            )
        )


def test_agent_taches_avec_outils_refuse(tmp_path):
    texte = VALIDE.replace(
        "    prompt_systeme: p", "    prompt_systeme: p\n    produit: taches\n    outils: [lire]"
    )
    with pytest.raises(CatalogueInvalide, match="spec"):
        charger_catalogue(ecrire(tmp_path, texte))


def test_outil_inconnu_refuse(tmp_path):
    texte = VALIDE.replace("    prompt_systeme: p", "    prompt_systeme: p\n    outils: [shell]")
    with pytest.raises(CatalogueInvalide, match="shell"):
        charger_catalogue(ecrire(tmp_path, texte))


def test_valeurs_par_defaut(tmp_path):
    a = charger_catalogue(ecrire(tmp_path, VALIDE)).agents["spec"]
    assert (a.produit, a.auto, a.outils, a.tours_max) == ("spec", False, [], 20)


def _avec(tmp_path, lignes: str):
    return charger_catalogue(
        ecrire(
            tmp_path, VALIDE.replace("    prompt_systeme: p", "    prompt_systeme: p\n" + lignes)
        )
    )


def test_agent_travail_valide(tmp_path):
    a = _avec(
        tmp_path,
        "    produit: travail\n    role: code\n"
        "    outils: [lister, lire, chercher, ecrire, supprimer, lancer]",
    ).agents["spec"]
    assert (a.produit, a.role) == ("travail", "code")


def test_role_par_defaut_aucun(tmp_path):
    assert _avec(tmp_path, "    outils: [lire]").agents["spec"].role is None


def test_travail_exige_role_et_lancer(tmp_path):
    with pytest.raises(CatalogueInvalide, match="spec"):
        _avec(tmp_path, "    produit: travail\n    outils: [lire, lancer]")
    with pytest.raises(CatalogueInvalide, match="spec"):
        _avec(tmp_path, "    produit: travail\n    role: tests\n    outils: [lire, ecrire]")


def test_verdict_exige_revue_sans_ecriture(tmp_path):
    assert _avec(tmp_path, "    produit: verdict\n    role: revue\n    outils: [lire]")
    with pytest.raises(CatalogueInvalide, match="spec"):
        _avec(tmp_path, "    produit: verdict\n    role: code\n    outils: [lire]")
    for outil in ("ecrire", "supprimer"):
        with pytest.raises(CatalogueInvalide, match="spec"):
            _avec(tmp_path, f"    produit: verdict\n    role: revue\n    outils: [lire, {outil}]")


def test_verdict_avec_lancer_accepte(tmp_path):
    assert _avec(tmp_path, "    produit: verdict\n    role: revue\n    outils: [lire, lancer]")


def test_modele_si_meme_identique_refuse(tmp_path):
    with pytest.raises(CatalogueInvalide, match="spec"):
        _avec(tmp_path, "    modele_si_meme: m")


def test_modele_si_meme_hors_liste_refuse(tmp_path):
    with pytest.raises(CatalogueInvalide, match="gpt-x"):
        _avec(tmp_path, "    modele_si_meme: gpt-x")


def test_doc_avec_lancer_refuse(tmp_path):
    with pytest.raises(CatalogueInvalide, match="spec"):
        _avec(tmp_path, "    produit: travail\n    role: doc\n    outils: [lire, ecrire, lancer]")


def test_doc_sans_lancer_accepte(tmp_path):
    a = _avec(tmp_path, "    produit: travail\n    role: doc\n    outils: [lire, ecrire]")
    assert a.agents["spec"].role == "doc"


AVIS = VALIDE.replace("pipelines:", "avis:\n  plan: [spec]\npipelines:")


def test_avis_agent_sans_consigne_refuse(tmp_path):
    with pytest.raises(CatalogueInvalide, match="« spec »"):
        charger_catalogue(ecrire(tmp_path, AVIS))
    texte = AVIS.replace("    prompt_systeme: p", "    prompt_systeme: p\n    consigne_avis: c")
    assert charger_catalogue(ecrire(tmp_path, texte)).avis == {"plan": ["spec"]}


def test_avis_agent_inconnu_refuse(tmp_path):
    with pytest.raises(CatalogueInvalide, match="« fantome »"):
        charger_catalogue(ecrire(tmp_path, AVIS.replace("[spec]", "[fantome]", 1)))


def test_pm_avec_outil_d_action_refuse(tmp_path):
    texte = PORTAIL.replace("  x:", "  pm:").replace(
        "[lister_projets, lire_kanban]", "[lire_kanban, creer_tache]"
    )
    with pytest.raises(CatalogueInvalide, match="« pm »"):
        charger_catalogue(ecrire(tmp_path, texte))


def test_role_inconnu_refuse(tmp_path):
    with pytest.raises(CatalogueInvalide, match="systeme"):
        _avec(tmp_path, "    role: systeme")


PORTAIL = VALIDE.replace(
    "pipelines:\n  spec: [spec]\n",
    "  x:\n    description: d\n    modele: m\n    contexte_max: 1000\n    prompt_systeme: p\n"
    "    outils: [lister_projets, lire_kanban]\npipelines:\n  spec: [spec]\n",
)


def test_outils_portail_acceptes(tmp_path):
    cat = charger_catalogue(ecrire(tmp_path, PORTAIL))
    assert cat.agents["x"].outils == ["lister_projets", "lire_kanban"]


def test_outils_portail_et_depot_melanges_refuses(tmp_path):
    texte = PORTAIL.replace("[lister_projets, lire_kanban]", "[lire, lister_projets]")
    with pytest.raises(CatalogueInvalide, match="« x »"):
        charger_catalogue(ecrire(tmp_path, texte))


def test_agent_portail_dans_un_pipeline_refuse(tmp_path):
    with pytest.raises(CatalogueInvalide, match="« x »"):
        charger_catalogue(ecrire(tmp_path, PORTAIL.replace("spec: [spec]", "spec: [x]")))


def test_agents_yaml_du_depot_a_l_orchestrateur():
    racine = Path(__file__).resolve().parents[2]
    a = charger_catalogue(racine / "agents.yaml").agents["orchestrateur"]
    assert set(a.outils) == set(OUTILS_PORTAIL) - set(OUTILS_SUIVI)
    assert (a.temperature, a.tours_max) == (0.3, 10)


def test_modele_pour():
    def agent(nom, modele, si_meme=None):
        return Agent(
            nom=nom, description=nom, modele=modele, prompt_systeme="p", contexte_max=1000,
            modele_si_meme=si_meme,
        )  # fmt: skip

    code = agent("code", "x")
    assert modele_pour(agent("challenger", "x", "y"), code) == "y"
    assert modele_pour(agent("challenger", "z", "y"), code) == "z"
    assert modele_pour(agent("revue", "x"), code) == "x"


def test_rangement():
    from tests.conftest import CATALOGUE_TEST

    assert rangement(CATALOGUE_TEST) == [
        ("spec", ["spec"]),
        ("double", ["a", "b"]),
        ("petit", ["petit"]),
        ("planification", ["plan", "taches"]),
        ("architecture", ["vision", "volet", "synthese"]),
        (None, ["orchestrateur", "pm"]),
    ]


def test_rangement_sans_groupe_hors_pipeline_et_agent_dans_deux_pipelines():
    from tests.conftest import CATALOGUE_TEST

    cat = CATALOGUE_TEST.model_copy(
        update={
            "agents": {k: v for k, v in CATALOGUE_TEST.agents.items() if k in ("a", "b")},
            "pipelines": {"x": ["a", "b"], "y": ["b"]},
        }
    )
    assert rangement(cat) == [("x", ["a", "b"]), ("y", ["b"])]


def test_rangement_agent_cite_seulement_dans_avis_est_hors_pipeline():
    from tests.conftest import CATALOGUE_TEST

    cat = CATALOGUE_TEST.model_copy(
        update={
            "agents": {k: v for k, v in CATALOGUE_TEST.agents.items() if k in ("a", "b")},
            "pipelines": {"x": ["a"]},
            "avis": {"plan": ["b"]},
        }
    )
    assert rangement(cat) == [("x", ["a"]), (None, ["b"])]


def test_service_adresse_valide(tmp_path):
    cat = charger_catalogue(
        ecrire(
            tmp_path,
            VALIDE.replace(
                "prompt_systeme: p", "prompt_systeme: p\n    service: http://agent-revue:8080"
            ),
        )
    )
    assert cat.agents["spec"].service == "http://agent-revue:8080"
    assert charger_catalogue(ecrire(tmp_path, VALIDE)).agents["spec"].service is None


@pytest.mark.parametrize(
    "adresse",
    [
        "https://agent-revue:8080",
        "http://agent-revue",
        "http://10.0.0.1:8080/x",
        "agent-revue:8080",
        "http://10.0.0.1:8080",
        "http://localhost:8080",
        "http://litellm:4000",
        "http://postgres:5432",
    ],
)
def test_service_adresse_invalide(tmp_path, adresse):
    texte = VALIDE.replace("prompt_systeme: p", f"prompt_systeme: p\n    service: {adresse}")
    with pytest.raises(CatalogueInvalide, match="« spec »"):
        charger_catalogue(ecrire(tmp_path, texte))


def _agent_yaml(nom: str, lignes: str) -> str:
    return (
        f"  {nom}:\n    description: d\n    modele: m\n    contexte_max: 1000\n"
        f"    prompt_systeme: p\n{lignes}"
    )


def _architecture(agents: dict[str, str], etapes: list[str]) -> str:
    corps = "".join(_agent_yaml(n, lignes) for n, lignes in agents.items())
    return (
        f"modeles_permis: [m]\nagents:\n{corps}pipelines:\n  architecture: [{', '.join(etapes)}]\n"
    )


VISION = "    produit: vision\n    prefixe: mot-\n    consigne_redaction: c\n"
VOLET = "    produit: volet\n    prefixe: aff-\n    volet: affaires\n    auto: true\n    consigne_redaction: c\n"
FINALE = "    produit: architecture\n    prefixe: sol-\n    auto: true\n    consigne_redaction: c\n"
TROIS = {"vision": VISION, "volet": VOLET, "finale": FINALE}


def test_catalogue_architecture_accepte(tmp_path):
    texte = _architecture(
        {"vision": VISION, "volet": VOLET + "    sans_validation: true\n", "finale": FINALE},
        ["vision", "volet", "finale"],
    )
    a = charger_catalogue(ecrire(tmp_path, texte)).agents
    assert (a["vision"].produit, a["vision"].auto, a["vision"].prefixe) == ("vision", False, "mot-")
    assert (a["volet"].volet, a["volet"].sans_validation) == ("affaires", True)
    assert a["finale"].outils == [] and a["finale"].sans_validation is False


@pytest.mark.parametrize(
    ("agents", "etapes", "fragment"),
    [
        (
            {"vision": VISION.replace("    prefixe: mot-\n", "")},
            ["vision"],
            "l'agent « vision » produit vision : prefixe requis",
        ),
        (
            {"vision": VISION.replace("    consigne_redaction: c\n", "")},
            ["vision"],
            "l'agent « vision » produit vision : consigne_redaction requise",
        ),
        (
            {"vision": VISION.replace("mot-", "mot")},
            ["vision"],
            "prefixe",
        ),
        (
            {"vision": "    prefixe: mot-\n"},
            ["vision"],
            "l'agent « vision » ne produit pas d'architecture : prefixe interdit",
        ),
        (
            {"vision": VISION, "volet": VOLET.replace("    volet: affaires\n", "")},
            ["vision", "volet"],
            "l'agent « volet » produit un volet : volet requis",
        ),
        (
            {"vision": VISION + "    volet: x\n", "autre": "    volet: x\n"},
            ["vision"],
            "l'agent « autre » ne produit pas un volet : volet interdit",
        ),
        (
            {"vision": VISION + "    auto: true\n"},
            ["vision"],
            "l'agent « vision » est une discussion : pas auto",
        ),
        (
            {"vision": VISION + "    sans_validation: true\n"},
            ["vision"],
            "l'agent « vision » : sans_validation réservé aux volets et tâches auto",
        ),
        (
            {"vision": VISION, "volet": VOLET.replace("    auto: true\n", "")},
            ["vision", "volet"],
            "l'agent « volet » produit un volet : auto requis",
        ),
        (
            {"vision": VISION, "finale": FINALE.replace("    auto: true\n", "")},
            ["vision", "finale"],
            "l'agent « finale » produit l'architecture : auto requis",
        ),
        (
            {"vision": VISION, "finale": FINALE + "    outils: [lire]\n"},
            ["vision", "finale"],
            "l'agent « finale » produit l'architecture : pas d'outils",
        ),
        (
            {"vision": VISION, "volet": VOLET, "dup": VOLET.replace("affaires", "données")},
            ["vision", "volet", "dup"],
            "pipeline « architecture » : le préfixe « aff- » est utilisé par « volet » et « dup »",
        ),
        (
            {"volet": VOLET, "vision": VISION},
            ["volet", "vision"],
            "pipeline « architecture » : l'agent « volet » n'est pas précédé d'un agent vision",
        ),
        (
            {"vision": VISION, "finale": FINALE, "volet": VOLET},
            ["vision", "finale", "volet"],
            "pipeline « architecture » : l'agent « finale » doit être la dernière étape",
        ),
        (
            {"vision": VISION, "autre": VISION.replace("mot-", "aff-")},
            ["vision", "autre"],
            "pipeline « architecture » : un seul agent vision est permis",
        ),
        (
            {"vision": VISION, "finale": FINALE, "autre": FINALE.replace("sol-", "ent-")},
            ["vision", "finale", "autre"],
            "pipeline « architecture » : un seul agent architecture est permis",
        ),
    ],
)
def test_agent_architecture_refuse(tmp_path, agents, etapes, fragment):
    with pytest.raises(CatalogueInvalide) as exc:
        charger_catalogue(ecrire(tmp_path, _architecture(agents, etapes)))
    assert fragment in str(exc.value)


RACINE = Path(__file__).parents[2]


def test_agents_yaml_reel_bureau_d_architectes():
    cat = charger_catalogue(RACINE / "agents.yaml")
    assert cat.pipelines["architecture"] == [
        "archi-entreprise",
        "archi-affaires",
        "archi-donnees",
        "archi-applicatif",
        "archi-techno",
        "archi-securite",
        "archi-solution",
        "archi-entreprise-synthese",
    ]
    assert [cat.agents[a].prefixe for a in cat.pipelines["architecture"]] == [
        "mot-",
        "aff-",
        "don-",
        "app-",
        "tec-",
        "sec-",
        "sol-",
        "ent-",
    ]
    locaux = {"qwen3.8:27b-mlx", "mlx-community/GLM-4.7-Flash-8bit", "gemma4:26b-a4b-it-qat"}
    for nom, a in cat.agents.items():
        assert nom.startswith("archi-") or a.modele in locaux, nom
    for a in cat.pipelines["architecture"][1:]:
        assert "Règles communes du bureau d'architectes" in cat.agents[a].prompt_systeme
    volets = cat.pipelines["architecture"][1:7]
    assert [cat.agents[a].volet for a in volets] == [
        "affaires",
        "données",
        "applicatif",
        "technologique",
        "sécurité",
        "solution",
    ]
    assert cat.agents["archi-entreprise-synthese"].outils == []
    for a in cat.pipelines["architecture"]:
        assert cat.agents[a].modele == "cloud-openai", a
    synthese = cat.agents["archi-entreprise-synthese"].consigne_redaction
    assert "Ne recopie pas les éléments des volets" in synthese
    assert "le modèle complet, fusionné" not in synthese
    assert synthese.count("Réponds uniquement avec le document") == 1


def test_agents_yaml_sortie_max_et_temperature_du_bureau_d_architectes():
    cat = charger_catalogue(RACINE / "agents.yaml")
    for nom in cat.pipelines["architecture"]:
        a = cat.agents[nom]
        assert a.sortie_max == 16000
        if a.modele in ("cloud-openai", "cloud-anthropic"):
            assert a.temperature is None, nom
    assert cat.agents["orchestrateur"].sortie_max is None


def test_agents_yaml_reflexion_coupee_pour_les_agents_de_dev():
    cat = charger_catalogue(RACINE / "agents.yaml")
    for nom in ("tests", "code", "revue"):
        assert cat.agents[nom].reflexion is False, nom
    assert cat.agents["spec"].reflexion is True  # défaut


def test_sortie_max_doit_etre_positive():
    with pytest.raises(ValueError):
        Agent(
            nom="a", description="d", modele="m", prompt_systeme="p", contexte_max=1, sortie_max=0
        )


def test_agent_effectif():
    from conftest import _agent

    spec = _agent("spec").model_copy(update={"temperature": 0.3, "reflexion": False})
    cat = Catalogue(modeles_permis=["m", "g"], agents={"spec": spec}, pipelines={})
    assert agent_effectif(cat, "spec", None).temperature == 0.3
    assert agent_effectif(cat, "spec", "m").temperature == 0.3
    autre = agent_effectif(cat, "spec", "g")
    assert (autre.modele, autre.temperature) == ("g", None)  # cloud-anthropic refuse la température
    assert autre.reflexion is True  # le réglage vaut pour le modèle de l'agent seulement
    assert agent_effectif(cat, "spec", "m").reflexion is False
    assert cat.agents["spec"].modele == "m"  # le catalogue n'est pas modifié
    assert agent_effectif(cat, "spec", "retire").modele == "m"  # retiré d'agents.yaml : repli
    assert agent_effectif(cat, "absent", "g") is None
