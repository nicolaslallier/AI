import asyncio
import io
import json
import re

from asgi_lifespan import LifespanManager
from conftest import CATALOGUE_TEST, _agent
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from test_archimate import SCHEMA
from test_chat import _chat, _poll

from portail.agents import Catalogue
from portail.api import create_app
from portail.architecture import descendre_titres, sections
from portail.db import Document
from portail.llm import ErreurLLM


def _bloc(prefixe, cites=()):
    """Texte suivi d'un bloc de modèle valide : un élément `<prefixe>a` et une vue."""
    ident = f"{prefixe}a"
    modele = {
        "elements": [{"id": ident, "type": "BusinessActor", "nom": "A"}],
        "vues": [{"nom": "V", "elements": [ident, *cites]}],
    }
    return f"Texte {prefixe}\n\n```json\n{json.dumps(modele)}\n```"


VISION, VOLET, SYNTHESE = _bloc("mot-"), _bloc("aff-", ["mot-a"]), _bloc("ent-", ["aff-a"])


async def _attendre_tout(client):
    """Attend les tâches de fond, y compris celles qu'elles lancent en finissant."""
    chat = _chat(client)
    while chat.taches:
        await asyncio.wait_for(asyncio.gather(*list(chat.taches.values())), 5)


async def _projet(client):
    return (await client.post("/api/projets", json={"nom": "P"})).json()["id"]


async def _architecture(client, projet_id=None):
    projet_id = projet_id or await _projet(client)
    r = await client.post("/api/pipelines", json={"projet_id": projet_id, "type": "architecture"})
    assert r.status_code == 201, r.text
    return r.json()


async def _pipeline(client, pid):
    return (await client.get(f"/api/pipelines/{pid}")).json()


async def _etats(client, pid):
    return [e["etat"] for e in (await _pipeline(client, pid))["etapes"]]


async def _vision_redigee(client, faux_llm, *suite):
    """Pipeline dont la vision a un brouillon valide ; `suite` : réponses des appels suivants."""
    p = await _architecture(client)
    faux_llm.file = [[VISION], *suite]
    eid = p["etapes"][0]["id"]
    assert (await client.post(f"/api/etapes/{eid}/rediger")).status_code == 202
    await _attendre_tout(client)
    return p["id"], [e["id"] for e in p["etapes"]]


async def test_chaine_complete(client, faux_llm):
    pid, (vision, *_) = await _vision_redigee(client, faux_llm, [VOLET], [SYNTHESE])
    assert (await client.post(f"/api/etapes/{vision}/valider")).status_code == 200
    await _attendre_tout(client)
    etapes = (await _pipeline(client, pid))["etapes"]
    assert [e["etat"] for e in etapes] == ["terminee", "terminee", "en_attente"]
    assert etapes[1]["document"]["etat"] == "validee"
    assert etapes[1]["document"]["contenu"] == VOLET
    assert etapes[2]["document"]["etat"] == "brouillon"
    assert etapes[2]["document"]["contenu"] == SYNTHESE
    systeme = [m["content"] for m in faux_llm.appels[2]["messages"] if m["role"] == "system"]
    assert "Vision validée :\n\n" + VISION in systeme
    assert "Volet affaires (volet) :\n\n" + VOLET in systeme


async def test_volet_recoit_la_vision_en_annexe(client, faux_llm):
    _, (vision, *_) = await _vision_redigee(client, faux_llm, [VOLET], [SYNTHESE])
    await client.post(f"/api/etapes/{vision}/valider")
    await _attendre_tout(client)
    systeme = [m["content"] for m in faux_llm.appels[1]["messages"] if m["role"] == "system"]
    [annexe] = [c for c in systeme if c.startswith("Vision validée :")]
    assert annexe.endswith(VISION) and "```json" in annexe


async def test_bloc_absent_fait_echouer_le_volet(client, faux_llm):
    pid, (vision, *_) = await _vision_redigee(
        client, faux_llm, ["Pas de bloc."], ["Toujours pas de bloc."]
    )
    await client.post(f"/api/etapes/{vision}/valider")
    await _attendre_tout(client)
    etapes = (await _pipeline(client, pid))["etapes"]
    assert [e["etat"] for e in etapes] == ["terminee", "echouee", "a_faire"]
    assert len(faux_llm.appels) == 3
    assert "bloc de modèle absent" in etapes[1]["erreur"]
    assert etapes[1]["document"] is None


async def test_reessayer_un_volet_echoue_reprend_la_chaine(client, faux_llm):
    pid, (vision, volet, _) = await _vision_redigee(client, faux_llm, ["Pas de bloc."])
    await client.post(f"/api/etapes/{vision}/valider")
    await _attendre_tout(client)
    faux_llm.file = [[VOLET], [SYNTHESE]]
    assert (await client.post(f"/api/etapes/{volet}/reessayer")).status_code == 202
    await _attendre_tout(client)
    etapes = (await _pipeline(client, pid))["etapes"]
    assert [e["etat"] for e in etapes] == ["terminee", "terminee", "en_attente"]
    assert etapes[1]["action"] == "rediger"
    assert etapes[1]["document"]["etat"] == "validee"


async def test_rediger_un_bloc_invalide_garde_le_brouillon(client, faux_llm):
    pid, (vision, *_) = await _vision_redigee(client, faux_llm, [_bloc("aff-")], [_bloc("aff-")])
    avant = (await _pipeline(client, pid))["etapes"][0]["document"]
    assert (await client.post(f"/api/etapes/{vision}/rediger")).status_code == 202
    await _attendre_tout(client)
    e = (await _pipeline(client, pid))["etapes"][0]
    assert e["etat"] == "en_attente" and e["document"] == avant
    dernier = e["messages"][-1]
    assert dernier["role"] == "assistant"
    assert "préfixe « mot- » attendu" in dernier["contenu"]
    assert "Le brouillon précédent est conservé." in dernier["contenu"]


async def test_bloc_invalide_relance_une_fois_avec_l_erreur(client, faux_llm):
    pid, (vision, *_) = await _vision_redigee(client, faux_llm, [_bloc("aff-")], [VISION + " v2"])
    assert (await client.post(f"/api/etapes/{vision}/rediger")).status_code == 202
    await _attendre_tout(client)
    e = (await _pipeline(client, pid))["etapes"][0]
    assert e["etat"] == "en_attente" and e["document"]["version"] == 2
    assert e["document"]["contenu"] == VISION + " v2"
    relance = faux_llm.appels[2]["messages"]
    assert relance[-2] == {"role": "assistant", "content": _bloc("aff-")}
    assert relance[-1]["content"].startswith("Réponse invalide : ")
    assert relance[-1]["content"].endswith("Rends le document complet corrigé.")


async def test_corriger_un_brouillon_au_bloc_casse_422(client, faux_llm):
    pid, (vision, *_) = await _vision_redigee(client, faux_llm)
    r = await client.put(
        f"/api/etapes/{vision}/document", json={"contenu": "Texte\n\n```json\n{oups\n```"}
    )
    assert r.status_code == 422 and "JSON illisible" in r.json()["detail"]
    doc = (await _pipeline(client, pid))["etapes"][0]["document"]
    assert (doc["contenu"], doc["version"], doc["etat"]) == (VISION, 1, "brouillon")
    r = await client.put(f"/api/etapes/{vision}/document", json={"contenu": _bloc("mot-", [])})
    assert r.status_code == 200 and r.json()["version"] == 2


async def test_valider_la_vision_au_bloc_invalide_422(client, faux_llm, sessions):
    pid, (vision, *_) = await _vision_redigee(client, faux_llm)
    async with sessions() as s:  # brouillon abîmé hors du portail
        await s.execute(
            update(Document).where(Document.etape_id == vision).values(contenu="sans bloc")
        )
        await s.commit()
    r = await client.post(f"/api/etapes/{vision}/valider")
    assert r.status_code == 422 and r.json()["detail"] == "bloc de modèle absent"
    e = (await _pipeline(client, pid))["etapes"][0]
    assert e["etat"] == "en_attente" and e["document"]["etat"] == "brouillon"
    assert await _etats(client, pid) == ["en_attente", "a_faire", "a_faire"]


async def test_deuxieme_architecture_active_409(client, faux_llm):
    projet = await _projet(client)
    premier = await _architecture(client, projet)
    r = await client.post("/api/pipelines", json={"projet_id": projet, "type": "architecture"})
    assert r.status_code == 409
    assert r.json()["detail"] == "une architecture est déjà en cours pour ce projet"
    # la première échoue : une autre peut démarrer, et la première ne se relance plus
    faux_llm.exception = ErreurLLM("injoignable")
    vision = premier["etapes"][0]["id"]
    await client.post(f"/api/etapes/{vision}/rediger")
    await _attendre_tout(client)
    assert (await _etats(client, premier["id"]))[0] == "echouee"
    await _architecture(client, projet)
    r = await client.post(f"/api/etapes/{vision}/reessayer")
    assert r.status_code == 409
    assert r.json()["detail"] == "une autre architecture est active pour ce projet"


async def test_architecture_sans_spec_201(client):
    p = await _architecture(client)
    assert [e["etat"] for e in p["etapes"]] == ["en_attente", "a_faire", "a_faire"]


async def test_annuler_pendant_un_volet_n_enchaine_pas(client, faux_llm):
    pause = asyncio.Event()
    pid, (vision, *_) = await _vision_redigee(client, faux_llm, [pause, VOLET], [SYNTHESE])
    await client.post(f"/api/etapes/{vision}/valider")
    await _poll(lambda: len(faux_llm.appels) == 2)  # le volet attend le modèle
    assert (await client.post(f"/api/pipelines/{pid}/annuler")).status_code == 200
    pause.set()
    await _attendre_tout(client)
    etapes = (await _pipeline(client, pid))["etapes"]
    assert [e["etat"] for e in etapes] == ["terminee", "echouee", "a_faire"]
    assert etapes[1]["erreur"] == "annulé" and etapes[1]["document"] is None
    assert len(faux_llm.appels) == 2


def test_apercu_borne():
    from portail.chat import budget_apercu

    assert budget_apercu(200_000) == 8192
    assert budget_apercu(32_768) == 8192
    assert budget_apercu(16_000) == 4000


# --- document assemblé et fichier d'échange -------------------------------------------------

SOMMAIRE = "## Sommaire exécutif et portée\n\nPhrase du sommaire.\n\n### Portée\n\nDétail.\n\n"
REGISTRES = (
    "## Registre des décisions\n\nADR-1 retenu.\n\n"
    "## Registre des dérogations\n\nAucune dérogation.\n\n"
    "## Registre de la dette\n\nDette modeste.\n\n"
    "## Risques, hypothèses et questions ouvertes\n\nRisque unique.\n\n"
)


def _morceau(prefixe, corps, cites=(), fusions=()):
    modele = {
        "elements": [{"id": f"{prefixe}a", "type": "BusinessActor", "nom": "A"}],
        "vues": [{"nom": "V", "elements": [f"{prefixe}a", *cites]}],
        "fusions": [{"garder": g, "retirer": r} for g, r in fusions],
    }
    return f"{corps}\n\n```json\n{json.dumps(modele)}\n```"


VOLET_TEXTE = "# Volet affaires\n\nLes processus métier restent inchangés.\n\n## Détail\n\n```\n# pas un titre\n```"
SYNTHESE_COMPLETE = _morceau("ent-", SOMMAIRE + REGISTRES, ["aff-a"])


async def _architecture_redigee(client, faux_llm, synthese=SYNTHESE_COMPLETE, volet=VOLET_TEXTE):
    pid, (vision, *_) = await _vision_redigee(
        client, faux_llm, [_morceau("aff-", volet, ["mot-a"])], [synthese]
    )
    await client.post(f"/api/etapes/{vision}/valider")
    await _attendre_tout(client)
    return pid


def _titres(md):
    return re.findall(r"^# (\d+\. .+)$", md, re.MULTILINE)


async def test_document_assemble_aux_sections_numerotees(client, faux_llm):
    pid = await _architecture_redigee(client, faux_llm)
    r = await client.get(f"/api/pipelines/{pid}/architecture.md")
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/markdown; charset=utf-8"
    assert _titres(r.text) == [
        "1. Sommaire exécutif et portée",
        "2. Vision",
        "3. Architecture d'affaires",
        "4. Registre des décisions (ADR)",
        "5. Registre des dérogations",
        "6. Registre de la dette",
        "7. Risques, hypothèses et questions ouvertes",
        "8. Annexe : catalogues",
    ]
    assert "\n### Portée" not in r.text and "\n#### Portée\n" in r.text
    assert "| ent-a | BusinessActor | A | synthèse |" in r.text
    assert "| aff-a | BusinessActor | A | affaires |" in r.text


async def test_document_assemble_a_treize_sections_dans_l_ordre(moteur, reglages, faux_llm):
    volets = ["affaires", "données", "applicatif", "technologique", "sécurité", "solution"]
    prefixes = ["aff-", "don-", "app-", "tec-", "sec-", "sol-"]
    agents = {
        "vision": CATALOGUE_TEST.agents["vision"],
        "synthese": CATALOGUE_TEST.agents["synthese"],
        **{
            f"v{i}": _agent(
                f"v{i}", produit="volet", prefixe=p, volet=v, auto=True, sans_validation=True,
                consigne_redaction="Rédige.",
            )
            for i, (v, p) in enumerate(zip(volets, prefixes, strict=True))
        },
    }  # fmt: skip
    cat = Catalogue(
        agents=agents,
        pipelines={"architecture": ["vision", *(f"v{i}" for i in range(6)), "synthese"]},
    )
    app = create_app(reglages=reglages, llm=faux_llm, catalogue=cat)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        p = await _architecture(c)
        faux_llm.file = [
            [VISION],
            *([_morceau(pre, f"Volet {v}.", ["mot-a"])] for v, pre in zip(volets, prefixes)),
            [SYNTHESE_COMPLETE],
        ]
        await c.post(f"/api/etapes/{p['etapes'][0]['id']}/rediger")
        await _attendre_tout(c)
        await c.post(f"/api/etapes/{p['etapes'][0]['id']}/valider")
        await _attendre_tout(c)
        md = (await c.get(f"/api/pipelines/{p['id']}/architecture.md")).text
    assert _titres(md) == [
        "1. Sommaire exécutif et portée",
        "2. Vision",
        "3. Architecture d'affaires",
        "4. Architecture de données",
        "5. Architecture applicative",
        "6. Architecture technologique",
        "7. Architecture de sécurité",
        "8. Écarts, options de solution et feuille de route",
        "9. Registre des décisions (ADR)",
        "10. Registre des dérogations",
        "11. Registre de la dette",
        "12. Risques, hypothèses et questions ouvertes",
        "13. Annexe : catalogues",
    ]


async def test_document_assemble_sans_bloc_json(client, faux_llm):
    pid = await _architecture_redigee(client, faux_llm)
    md = (await client.get(f"/api/pipelines/{pid}/architecture.md")).text
    assert "```json" not in md
    # le stockage, lui, garde la partie du modèle de synthèse avec son bloc
    assert "```json" in (await _pipeline(client, pid))["etapes"][2]["document"]["contenu"]


async def test_volet_recopie_tel_quel(client, faux_llm):
    pid = await _architecture_redigee(client, faux_llm)
    md = (await client.get(f"/api/pipelines/{pid}/architecture.md")).text
    assert "Les processus métier restent inchangés." in md
    assert "\n## Volet affaires\n" in md and "\n### Détail\n" in md
    assert "\n# pas un titre\n" in md  # le code reste intact


async def test_section_absente_de_la_synthese(client, faux_llm):
    synthese = _morceau("ent-", SOMMAIRE + "## Registre des décisions\n\nADR-1.\n", ["aff-a"])
    pid = await _architecture_redigee(client, faux_llm, synthese)
    md = (await client.get(f"/api/pipelines/{pid}/architecture.md")).text
    assert "# 5. Registre des dérogations\n\nsection absente de la synthèse" in md
    assert "# 4. Registre des décisions (ADR)\n\nADR-1." in md


async def test_xml_telecharge_contient_tous_les_volets(client, faux_llm):
    pid = await _architecture_redigee(client, faux_llm)
    r = await client.get(f"/api/pipelines/{pid}/architecture.xml")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    assert r.headers["content-disposition"] == f'attachment; filename="architecture-{pid}.xml"'
    for ident in ("id-mot-a", "id-aff-a", "id-ent-a"):
        assert f'identifier="{ident}"' in r.text
    assert '<name xml:lang="fr">P</name>' in r.text
    SCHEMA.validate(io.StringIO(r.text))


async def test_fusion_de_la_synthese_appliquee_au_xml(client, faux_llm):
    synthese = _morceau("ent-", SOMMAIRE + REGISTRES, ["aff-a"], [("aff-a", "mot-a")])
    pid = await _architecture_redigee(client, faux_llm, synthese)
    xml = (await client.get(f"/api/pipelines/{pid}/architecture.xml")).text
    assert 'identifier="id-mot-a"' not in xml and 'identifier="id-aff-a"' in xml
    SCHEMA.validate(io.StringIO(xml))


async def test_routes_409_avant_la_synthese(client, faux_llm):
    pid, _ = await _vision_redigee(client, faux_llm)
    for fin in ("md", "xml"):
        r = await client.get(f"/api/pipelines/{pid}/architecture.{fin}")
        assert r.status_code == 409
        assert r.json()["detail"] == "l'architecture n'est pas encore rédigée"


async def test_routes_409_si_un_bloc_stocke_est_illisible(client, faux_llm, sessions):
    pid = await _architecture_redigee(client, faux_llm)
    async with sessions() as s:
        await s.execute(
            update(Document).where(Document.pipeline_id == pid).values(contenu="sans bloc")
        )
        await s.commit()
    for fin in ("md", "xml"):
        r = await client.get(f"/api/pipelines/{pid}/architecture.{fin}")
        assert (r.status_code, r.json()["detail"]) == (409, "bloc de modèle absent")


async def test_routes_404_pipeline_spec(client):
    projet = await _projet(client)
    r = await client.post("/api/pipelines", json={"projet_id": projet, "type": "spec"})
    for pid in (r.json()["id"], 99999):
        for fin in ("md", "xml"):
            assert (await client.get(f"/api/pipelines/{pid}/architecture.{fin}")).status_code == 404


def test_descendre_titres_laisse_le_code():
    texte = "# A\ntexte # non\n```md\n# B\n```\n### C"
    assert descendre_titres(texte) == "## A\ntexte # non\n```md\n# B\n```\n#### C"


def test_sections_par_titre_exact():
    texte = "avant\n## Un\na\n```\n## faux\n```\n## Deux\nb"
    assert sections(texte) == {"Un": "a\n```\n## faux\n```", "Deux": "b"}


async def test_sections_retrouvees_par_titre_normalise_et_inconnues_gardees(client, faux_llm):
    corps = (
        "## 1. Sommaire Exécutif  et portée\n\nSommaire numéroté.\n\n"
        "## REGISTRE DES DÉCISIONS (ADR)\n\nADR-9.\n\n"
        "## Plan de transition\n\nEn trois temps.\n\n"
    )
    pid = await _architecture_redigee(client, faux_llm, _morceau("ent-", corps, ["aff-a"]))
    md = (await client.get(f"/api/pipelines/{pid}/architecture.md")).text
    assert "# 1. Sommaire exécutif et portée\n\nSommaire numéroté." in md
    assert "# 4. Registre des décisions (ADR)\n\nADR-9." in md
    assert md.index("# 8. Plan de transition\n\nEn trois temps.") < md.index("Annexe : catalogues")
    assert md.index("Registre de la dette") < md.index("Plan de transition")


async def test_messages_de_refus_nomment_le_bon_document(client, faux_llm):
    p = await _architecture(client)
    vision = p["etapes"][0]["id"]
    r = await client.post(f"/api/etapes/{vision}/valider")
    assert r.status_code == 409 and "Rédiger la vision" in r.json()["detail"]
    _, (vision, *_) = await _vision_redigee(client, faux_llm, [VOLET], [SYNTHESE])
    await client.post(f"/api/etapes/{vision}/valider")
    r = await client.put(f"/api/etapes/{vision}/document", json={"contenu": VISION})
    assert r.status_code == 409 and r.json()["detail"] == "document déjà validé"
