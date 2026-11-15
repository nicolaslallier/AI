import asyncio
import json
import subprocess

import httpx
import pytest

from portail import journal
from portail.boucle import _IGNORE, ErreurOutils
from portail.config import Reglages
from portail.llm import ClientLLM, ErreurLLM
from portail.missions import Missions
from tests.conftest import CATALOGUE_TEST, URL, _agent, valeur

MSG = {"messages": [{"role": "user", "content": "salut"}]}


def _reponse(contenu="ok", **kw):
    return {"role": "assistant", "content": contenu, **kw}


async def test_jeton_absent_ou_inconnu_401(interne):
    interne.ouvrir()
    for entetes in ({}, {"Authorization": "Bearer inconnu"}):
        r = await interne.client.post("/interne/modele", json=MSG, headers=entetes)
        assert r.status_code == 401
        assert r.json() == {"erreur": "jeton de mission invalide"}
    assert interne.llm.appels == []


async def test_mission_fermee_401(interne):
    m = interne.ouvrir()
    await interne.missions.fermer(m)
    assert (await interne.post("modele", m, MSG)).status_code == 401


async def test_modele_et_outils_imposes(interne, tmp_path):
    import subprocess

    from portail.outils import OutilsEspace
    from tests.test_missions import CFG

    await asyncio.to_thread(subprocess.run, ["git", "-C", str(tmp_path), "init", "-q"], check=True)
    outils = OutilsEspace(tmp_path, "tests", CFG, None)
    m = interne.ouvrir(_agent("revue", outils=["lister", "lire"], temperature=0.2), outils)
    interne.llm.reponses = [_reponse(), _reponse()]
    assert (await interne.post("modele", m, {**MSG, "outils": True})).status_code == 200
    appel = interne.llm.appels[-1]
    assert (appel["modele"], appel["temperature"], appel["outils"]) == ("m", 0.2, m.schemas)
    assert (await interne.post("modele", m, {**MSG, "outils": False})).status_code == 200
    assert interne.llm.appels[-1]["outils"] is None
    for extra in ({"model": "x"}, {"tools": []}, {"temperature": 2}):
        r = await interne.post("modele", m, {**MSG, **extra})
        assert r.status_code == 422
    assert len(interne.llm.appels) == 2
    assert m.appels_modele == 2


async def test_reflexion_retiree(interne):
    m = interne.ouvrir()
    interne.llm.reponses = [_reponse("<think>x</think>ok")]
    r = await interne.post("modele", m, MSG)
    assert r.json()["message"]["content"] == "ok"


async def test_tool_calls_relayes_et_content_nul(interne):
    m = interne.ouvrir()
    appels = [{"id": "a", "type": "function", "function": {"name": "lire", "arguments": "{}"}}]
    interne.llm.reponses = [{"role": "assistant", "content": None, "tool_calls": appels}]
    message = (await interne.post("modele", m, MSG)).json()["message"]
    assert message["content"] is None
    assert message["tool_calls"] == appels


async def test_limite_tours_max_plus_un(interne):
    m = interne.ouvrir(_agent("revue", tours_max=2))
    interne.llm.reponses = [_reponse()] * 3
    for _ in range(3):
        assert (await interne.post("modele", m, MSG)).status_code == 200
    r = await interne.post("modele", m, MSG)
    assert r.status_code == 429
    assert m.limite_atteinte
    assert len(interne.llm.appels) == 3


async def test_contexte_max_refuse(interne):
    m = interne.ouvrir(_agent("revue", contexte_max=50))
    corps = {"messages": [{"role": "user", "content": "x" * 400}]}
    r = await interne.post("modele", m, corps)
    assert r.status_code == 413
    assert interne.llm.appels == []
    assert m.appels_modele == 0


async def test_flux_sans_outils_seulement(interne):
    m = interne.ouvrir()
    r = await interne.post("modele", m, {**MSG, "flux": True, "outils": True})
    assert r.status_code == 422
    interne.llm.morceaux = ["<thi", "nk>x</think>sa", "lut"]
    r = await interne.post("modele", m, {**MSG, "flux": True})
    assert r.headers["content-type"].startswith("application/x-ndjson")
    lignes = [json.loads(ligne) for ligne in r.text.splitlines()]
    assert [x["type"] for x in lignes] == ["texte", "texte", "fin"]
    assert "".join(x["texte"] for x in lignes[:-1]) == "salut"
    assert lignes[-1]["message"] == {"role": "assistant", "content": "salut"}


async def test_flux_erreur(interne):
    m = interne.ouvrir()
    interne.llm.exception = ErreurLLM("corps ZZ-secret-7731")
    r = await interne.post("modele", m, {**MSG, "flux": True})
    assert json.loads(r.text.splitlines()[-1]) == {
        "type": "erreur",
        "erreur": "modèle indisponible",
    }
    assert "ZZ-secret" not in r.text
    assert isinstance(m.erreur, ErreurLLM)


async def test_erreur_llm_retenue(interne):
    m = interne.ouvrir()
    interne.llm.exception = ErreurLLM("corps ZZ-secret-7731")
    r = await interne.post("modele", m, MSG)
    assert r.status_code == 502
    assert "ZZ-secret" not in r.text
    assert isinstance(m.erreur, ErreurLLM)
    premiere = m.erreur
    interne.llm.exception = ErreurLLM("autre")
    r = await interne.post("modele", m, MSG)  # mission en erreur : plus d'appel
    assert (r.status_code, r.json()) == (409, {"erreur": "mission arrêtée"})
    assert m.erreur is premiere
    assert len(interne.llm.appels) == 1


async def test_message_rendu_sans_champs_inventes(interne):
    m = interne.ouvrir()
    interne.llm.reponses = [_reponse("ok", reasoning_content="ZZ", refusal=None)]
    message = (await interne.post("modele", m, MSG)).json()["message"]
    assert message == {"role": "assistant", "content": "ok"}


async def test_message_inconnu_refuse_sans_recopie(interne):
    m = interne.ouvrir()
    corps = {"messages": [{"role": "user", "content": "x", "ZZ-champ": "ZZ-valeur"}]}
    r = await interne.post("modele", m, corps)
    assert r.status_code == 422
    assert "ZZ" not in r.text
    assert interne.llm.appels == []


async def test_contexte_mesure_sur_le_message_entier(interne):
    m = interne.ouvrir(_agent("revue", contexte_max=50))
    appel = {"id": "a", "type": "function", "function": {"name": "lire", "arguments": "y" * 400}}
    corps = {"messages": [{"role": "assistant", "content": None, "tool_calls": [appel]}]}
    assert (await interne.post("modele", m, corps)).status_code == 413
    assert interne.llm.appels == []


async def test_corps_trop_grand_413(interne, monkeypatch):
    from portail import missions

    monkeypatch.setattr(missions, "CORPS_MAX", 100)
    m = interne.ouvrir()
    r = await interne.post("modele", m, {"messages": [{"role": "user", "content": "x" * 300}]})
    assert r.status_code == 413
    assert interne.llm.appels == []


async def test_appel_en_vol_interrompu_par_la_fermeture(interne):
    m = interne.ouvrir()
    interne.llm.reponses = [asyncio.Event(), _reponse()]
    tache = asyncio.create_task(interne.post("modele", m, MSG))
    while not interne.llm.appels:
        await asyncio.sleep(0)
    await interne.missions.fermer(m)
    r = await tache
    assert (r.status_code, r.json()) == (409, {"erreur": "mission arrêtée"})


async def test_flux_interrompu_par_la_fermeture(interne):
    m = interne.ouvrir()
    interne.llm.morceaux = ["a", asyncio.Event()]  # bloqué après le premier morceau
    tache = asyncio.create_task(interne.post("modele", m, {**MSG, "flux": True}))
    while not interne.llm.appels:
        await asyncio.sleep(0)
    await asyncio.sleep(0.05)
    await interne.missions.fermer(m)
    r = await asyncio.wait_for(tache, 5)
    lignes = [json.loads(ligne) for ligne in r.text.splitlines()]
    assert lignes[-1] == {"type": "erreur", "erreur": "mission arrêtée"}
    assert not m.occupee


async def test_corps_illisible_422(interne):
    m = interne.ouvrir()
    r = await interne.client.post(
        "/interne/modele", content=b"pas du json", headers={"Authorization": f"Bearer {m.jeton}"}
    )
    assert (r.status_code, r.json()) == (422, {"erreur": "demande invalide"})


async def test_appel_llm_lieu_conteneur(interne, sessions):
    from sqlalchemy import select

    from portail.db import AppelLLM

    def h(request):
        corps = {"choices": [{"message": _reponse()}], "usage": {"prompt_tokens": 3}}
        return httpx.Response(200, json=corps)

    llm = ClientLLM(
        "http://llm", "", transport=httpx.MockTransport(h), sessions=sessions, version="sha-portail"
    )
    journal.commencer(pipeline=1, etape=2, tache=3)
    mission = journal.nouvelle_mission("revue", 1000)
    m = interne.ouvrir(_agent("revue"), llm=llm, version="sha-agent")
    journal.commencer()  # l'appelant est ailleurs : la requête n'a pas son contexte
    avant = valeur(
        "portail_llm_appels_total", agent="revue", modele="m", lieu="conteneur", issue="ok"
    )
    r = await asyncio.create_task(interne.post("modele", m, MSG))
    assert r.status_code == 200
    async with sessions() as s:
        (ligne,) = (await s.scalars(select(AppelLLM))).all()
    assert (ligne.agent, ligne.lieu, ligne.version_image) == ("revue", "conteneur", "sha-agent")
    assert (ligne.mission, ligne.pipeline_id, ligne.etape_id, ligne.tache_id) == (mission, 1, 2, 3)
    assert (
        valeur("portail_llm_appels_total", agent="revue", modele="m", lieu="conteneur", issue="ok")
        == avant + 1
    )


async def test_interne_avant_le_repli_spa(moteur, tmp_path, faux_llm):
    from asgi_lifespan import LifespanManager

    from portail.api import create_app

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>portail</html>")
    r = Reglages(database_url=URL, static_dir=tmp_path, exiger_utilisateur=True, resume_heure="")
    app = create_app(reglages=r, llm=faux_llm, catalogue=CATALOGUE_TEST)
    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://t") as c,
    ):
        rep = await c.post("/interne/modele", json=MSG)
        assert rep.status_code == 401
        assert rep.json() == {"erreur": "jeton de mission invalide"}
        assert isinstance(app.state.missions, Missions)


# --- /interne/outils ---------------------------------------------------------------------


@pytest.fixture
def espace(tmp_path):
    from portail.outils import OutilsEspace
    from tests.test_missions import CFG

    (tmp_path / "README.md").write_text("# Projet\n")
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    return OutilsEspace(tmp_path, "revue", CFG, None)


def _outil(nom_, **args):
    return {"nom": nom_, "arguments": json.dumps(args)}


async def test_outil_execute_et_affiche(interne, espace):
    vus = []

    async def sur_appel(libelle, resultat):
        vus.append((libelle, resultat))

    m = interne.ouvrir(_agent("revue", outils=["lister", "lire"]), espace, sur_appel=sur_appel)
    r = await interne.post("outils", m, _outil("lire", chemin="README.md"))
    assert r.status_code == 200
    assert "Projet" in r.json()["resultat"] and r.json()["arret"] is False
    assert vus == [("lire(README.md)", r.json()["resultat"])]


async def test_outil_non_offert_refuse(interne, espace, tmp_path):
    m = interne.ouvrir(_agent("revue", outils=["lister", "lire", "ecrire"]), espace)
    # `ecrire` est dans agent.outils mais le rôle revue ne l'offre pas : m.schemas fait foi
    assert "ecrire" not in m.noms
    avant = valeur("portail_outils_appels_total", agent="revue", outil="ecrire", issue="erreur")
    r = await interne.post("outils", m, _outil("ecrire", chemin="x.txt", contenu="x"))
    assert r.json()["resultat"] == "erreur : outil non autorisé : ecrire"
    assert not (tmp_path / "x.txt").exists()
    assert (
        valeur("portail_outils_appels_total", agent="revue", outil="ecrire", issue="erreur")
        == avant + 1
    )


async def test_outil_hors_liste_etiquette_fixe(interne, espace):
    m = interne.ouvrir(_agent("revue", outils=["lister", "lire"]), espace)
    avant = valeur(
        "portail_outils_appels_total", agent="revue", outil="non_autorise", issue="refuse"
    )
    await interne.post("outils", m, _outil("zzz-inventé"))
    assert (
        valeur("portail_outils_appels_total", agent="revue", outil="non_autorise", issue="refuse")
        == avant + 1
    )


async def test_huit_par_tour(interne, espace):
    vus = []

    async def sur_appel(libelle, resultat):
        vus.append(libelle)

    m = interne.ouvrir(_agent("revue", outils=["lire"]), espace, sur_appel=sur_appel)
    interne.llm.reponses = [_reponse()]
    for _ in range(8):
        await interne.post("outils", m, _outil("lire", chemin="README.md"))
    r = await interne.post("outils", m, _outil("lire", chemin="README.md"))
    assert r.json() == {
        "resultat": "erreur : trop d'appels dans un même tour, ignoré",
        "arret": False,
    }
    assert len(vus) == 8
    await interne.post("modele", m, {**MSG, "outils": True})
    r = await interne.post("outils", m, _outil("lire", chemin="README.md"))
    assert "Projet" in r.json()["resultat"]


async def test_trois_mal_formes_arretent(interne, espace):
    m = interne.ouvrir(_agent("revue", outils=["lire"]), espace)
    m.tache = asyncio.create_task(asyncio.Event().wait())
    avant = valeur(
        "portail_outils_appels_total", agent="revue", outil="non_autorise", issue="refuse"
    )
    codes = [(await interne.post("outils", m, _outil("zzz"))).status_code for _ in range(3)]
    assert codes == [200, 200, 409]
    assert isinstance(m.erreur, ErreurOutils)
    assert (await interne.post("outils", m, _outil("lire", chemin="README.md"))).status_code == 409
    await asyncio.sleep(0)
    assert m.tache.cancelled()
    assert (
        valeur("portail_outils_appels_total", agent="revue", outil="non_autorise", issue="refuse")
        == avant + 3
    )


async def test_mal_forme_puis_valide_remet_a_zero(interne, espace):
    m = interne.ouvrir(_agent("revue", outils=["lire"]), espace)
    for corps in (_outil("zzz"), _outil("zzz"), _outil("lire", chemin="README.md"), _outil("zzz")):
        assert (await interne.post("outils", m, corps)).status_code == 200
    assert m.erreur is None


async def test_demande_invalide_compte_comme_mal_formee(interne, espace):
    m = interne.ouvrir(_agent("revue", outils=["lire"]), espace)
    for _ in range(2):
        r = await interne.post("outils", m, {"nom": "lire", "args": "{}"})
        assert (r.status_code, r.json()) == (422, {"erreur": "demande invalide"})
    r = await interne.post("outils", m, {"inconnu": 1})
    assert r.status_code == 409
    assert isinstance(m.erreur, ErreurOutils)


async def test_outil_apres_fermeture_401(interne, espace):
    m = interne.ouvrir(_agent("revue", outils=["lire"]), espace)
    await interne.missions.fermer(m)
    assert (await interne.post("outils", m, _outil("lire", chemin="README.md"))).status_code == 401


async def test_outil_en_vol_annule_par_la_fermeture(interne):
    class Lent:
        def schemas(self):
            return [{"type": "function", "function": {"name": "lire"}}]

        async def executer(self, nom, arguments):
            self.demarre.set()
            await asyncio.Event().wait()

    outils = Lent()
    outils.demarre = asyncio.Event()
    m = interne.ouvrir(_agent("revue", outils=["lire"]), outils)
    tache = asyncio.create_task(interne.post("outils", m, _outil("lire")))
    await outils.demarre.wait()
    await interne.missions.fermer(m)
    r = await tache
    assert (r.status_code, r.json()) == (409, {"erreur": "mission arrêtée"})


async def test_outil_qui_leve_arrete_la_mission(interne):
    class Casse:
        def schemas(self):
            return [{"type": "function", "function": {"name": "lire"}}]

        async def executer(self, nom, arguments):
            raise RuntimeError("ZZ-secret-7731")

    m = interne.ouvrir(_agent("revue", outils=["lire"]), Casse())
    r = await interne.post("outils", m, _outil("lire"))
    assert r.status_code == 409
    assert "ZZ-secret" not in r.text and isinstance(m.erreur, ErreurOutils)


async def test_arret_apres_proposition(interne, sessions):
    from portail.db import Conversation
    from portail.outils_portail import OutilsPortail

    async with sessions() as s:
        conv = Conversation()
        s.add(conv)
        await s.commit()
        cid = conv.id
    outils = OutilsPortail(sessions, ["creer_projet", "lister_projets"], CATALOGUE_TEST, cid)
    m = interne.ouvrir(_agent("orchestrateur", outils=["creer_projet", "lister_projets"]), outils)
    r = await interne.post("outils", m, _outil("creer_projet", nom="A"))
    assert r.json()["arret"] is True and r.json()["resultat"].startswith("action n°")
    r = await interne.post("outils", m, _outil("lister_projets"))
    assert r.json() == {"resultat": _IGNORE, "arret": True}
    interne.llm.reponses = [_reponse()]
    await interne.post("modele", m, {**MSG, "outils": True})
    assert interne.llm.appels[-1]["outils"] is None


# --- revue de sécurité : échéance, outils liés au modèle, simultanéité, format ---------------


async def _corps_lent(avant, apres):
    """Un corps de requête en deux morceaux ; `avant` s'exécute entre les deux."""
    yield b'{"messages": [{"role": "user", '
    await avant()
    yield apres


async def test_echeance_depassee_pendant_la_lecture_du_corps(interne, espace):
    m = interne.ouvrir(_agent("revue", outils=["lire"]), espace)
    entetes = {"Authorization": f"Bearer {m.jeton}"}

    async def passe_l_echeance():
        interne.horloge.t = 100

    r = await interne.client.post(
        "/interne/modele",
        content=_corps_lent(passe_l_echeance, b'"content": "x"}]}'),
        headers=entetes,
    )
    assert r.status_code == 409 and interne.llm.appels == []
    m = interne.ouvrir(_agent("revue", outils=["lire"]), espace)
    entetes = {"Authorization": f"Bearer {m.jeton}"}
    interne.horloge.t = 0

    async def passe_encore():
        interne.horloge.t = 200

    async def corps():
        yield b'{"nom": "lire", '
        await passe_encore()
        yield b'"arguments": "{}"}'

    r = await interne.client.post("/interne/outils", content=corps(), headers=entetes)
    assert r.status_code == 409


async def test_outils_refuses_sans_appel_modele_qui_les_offre(interne, espace):
    m = interne.ouvrir(_agent("revue", outils=["lire"]), espace)
    m.outils_ouverts = False
    r = await interne.post("outils", m, _outil("lire", chemin="README.md"))
    assert r.status_code == 409
    interne.llm.reponses = [_reponse(), _reponse()]
    await interne.post("modele", m, {**MSG, "outils": False})
    assert (await interne.post("outils", m, _outil("lire", chemin="README.md"))).status_code == 409
    await interne.post("modele", m, {**MSG, "outils": True})
    assert (await interne.post("outils", m, _outil("lire", chemin="README.md"))).status_code == 200
    interne.llm.reponses = [_reponse()]
    await interne.post("modele", m, {**MSG, "outils": False})  # tout autre appel retire le droit
    assert (await interne.post("outils", m, _outil("lire", chemin="README.md"))).status_code == 409


async def test_tours_max_borne_les_executions_d_outils(interne, espace):
    vus = []

    async def sur_appel(libelle, resultat):
        vus.append(libelle)

    m = interne.ouvrir(_agent("revue", outils=["lire"], tours_max=1), espace, sur_appel=sur_appel)
    m.outils_ouverts = False
    interne.llm.reponses = [_reponse(), _reponse()]
    codes = []
    for _ in range(3):  # l'agent enchaîne appels au modèle et rafales d'outils
        r = await interne.post("modele", m, {**MSG, "outils": True})
        codes.append(r.status_code)
        for _ in range(12):
            await interne.post("outils", m, _outil("lire", chemin="README.md"))
    assert codes == [200, 200, 429]
    assert len(vus) <= 8  # `_MAX_APPELS_PAR_TOUR`, comme dans boucle.py
    assert interne.llm.appels[0]["outils"] == m.schemas
    assert interne.llm.appels[1]["outils"] is None  # appel tours_max + 1 : plus d'outils
    assert m.limite_atteinte


async def test_demande_simultanee_refusee_429(interne):
    m = interne.ouvrir()
    bloque = asyncio.Event()
    interne.llm.reponses = [bloque, _reponse(), _reponse()]
    premiere = asyncio.create_task(interne.post("modele", m, MSG))
    while not interne.llm.appels:
        await asyncio.sleep(0)
    r = await interne.post("modele", m, MSG)
    assert (r.status_code, r.json()) == (429, {"erreur": "une demande est déjà en cours"})
    r = await interne.post("outils", m, _outil("lire"))
    assert r.status_code == 429
    bloque.set()
    assert (await premiere).status_code == 200
    assert not m.occupee
    assert (await interne.post("modele", m, MSG)).status_code == 200


async def test_corps_lent_interrompu_par_la_fermeture(interne):
    m = interne.ouvrir()
    lu = asyncio.Event()

    async def corps():
        yield b'{"messages": ['
        lu.set()
        await asyncio.Event().wait()
        yield b"]}"

    tache = asyncio.create_task(
        interne.client.post(
            "/interne/modele", content=corps(), headers={"Authorization": f"Bearer {m.jeton}"}
        )
    )
    await lu.wait()
    await asyncio.sleep(0.02)
    assert m.occupee
    await interne.missions.fermer(m)
    r = await asyncio.wait_for(tache, 5)
    assert r.status_code == 409 and not m.occupee


async def test_lecteur_bloque_puis_fermer_libere_le_verrou(interne):
    from portail import missions as mod

    m = interne.ouvrir()
    interne.llm.morceaux = [f"m{i}" for i in range(500)]  # plus que la file bornée
    m.occupee = True  # pris par la route, rendu par le flux
    flux = mod._flux_modele(interne.missions, m, [{"role": "user", "content": "x"}])
    premiere = await anext(flux)  # puis l'agent cesse de lire
    assert json.loads(premiere)["type"] == "texte"
    await asyncio.sleep(0.05)
    assert m.en_vol and not m.tache  # le producteur est bloqué sur la file pleine
    await interne.missions.fermer(m)
    assert not m.occupee and not m.en_vol
    lignes = [json.loads(x) async for x in flux]
    assert lignes[-1] == {"type": "erreur", "erreur": "mission arrêtée"}


async def test_corps_en_morceaux_sans_content_length_borne(interne, monkeypatch):
    from portail import missions as mod

    monkeypatch.setattr(mod, "CORPS_MAX", 1000)
    m = interne.ouvrir()

    async def corps():
        for _ in range(100):
            yield b" " * 100

    r = await interne.client.post(
        "/interne/modele", content=corps(), headers={"Authorization": f"Bearer {m.jeton}"}
    )
    assert r.status_code == 413 and interne.llm.appels == []


@pytest.mark.parametrize(
    "format_",
    [
        {"type": "zzz"},
        {"type": "json_object", "extra": 1},
        {"type": "json_schema"},
        {"type": "json_schema", "json_schema": "x"},
        {"type": "json_schema", "json_schema": {"x": "y" * 40_000}},
        "json",
    ],
)
async def test_response_format_strict_et_borne(interne, format_):
    m = interne.ouvrir()
    r = await interne.post("modele", m, {**MSG, "response_format": format_})
    assert (r.status_code, r.json()) == (422, {"erreur": "demande invalide"})
    assert interne.llm.appels == []


async def test_response_format_permis_et_compte_dans_le_contexte(interne):
    m = interne.ouvrir(_agent("revue", contexte_max=200))
    interne.llm.reponses = [_reponse()]
    permis = {"type": "json_schema", "json_schema": {"name": "n", "schema": {"type": "object"}}}
    assert (await interne.post("modele", m, {**MSG, "response_format": permis})).status_code == 200
    assert interne.llm.appels[-1]["response_format"] == permis
    gros = {"type": "json_schema", "json_schema": {"name": "n", "schema": {"x": "y" * 2000}}}
    r = await interne.post("modele", m, {**MSG, "response_format": gros})
    assert r.status_code == 413
    assert len(interne.llm.appels) == 1


async def test_contexte_deja_porteur_de_lieu(interne):
    journal.commencer(lieu="portail", version_image="v-ancienne")
    m = interne.ouvrir()
    journal.commencer()
    interne.llm.reponses = [_reponse()]
    assert (await interne.post("modele", m, MSG)).status_code == 200
    assert interne.llm.appels[-1]["contexte"]["lieu"] == "conteneur"


async def test_exception_inattendue_du_modele(interne):
    m = interne.ouvrir()
    m.tache = asyncio.create_task(asyncio.Event().wait())
    interne.llm.exception = RuntimeError("ZZ-secret-7731")
    r = await interne.post("modele", m, MSG)
    assert (r.status_code, r.json()) == (502, {"erreur": "modèle indisponible"})
    assert isinstance(m.erreur, ErreurLLM) and "ZZ-secret" not in str(m.erreur)
    await asyncio.sleep(0)
    assert m.tache.cancelled()  # M4 : le flux vers l'agent est coupé aussi


async def test_exception_inattendue_du_flux(interne):
    m = interne.ouvrir()
    interne.llm.exception = RuntimeError("ZZ-secret-7731")
    r = await interne.post("modele", m, {**MSG, "flux": True})
    assert json.loads(r.text.splitlines()[-1]) == {
        "type": "erreur",
        "erreur": "modèle indisponible",
    }
    assert "ZZ-secret" not in r.text
    assert isinstance(m.erreur, ErreurLLM) and not m.occupee


async def test_erreur_llm_coupe_le_flux_vers_l_agent(interne):
    m = interne.ouvrir()
    m.tache = asyncio.create_task(asyncio.Event().wait())
    interne.llm.exception = ErreurLLM("x")
    assert (await interne.post("modele", m, MSG)).status_code == 502
    await asyncio.sleep(0)
    assert m.tache.cancelled()


async def test_sur_appel_ne_survit_pas_a_la_fermeture(interne, espace):
    ecrits, bloque = [], asyncio.Event()

    async def sur_appel(libelle, resultat):
        await bloque.wait()
        ecrits.append(libelle)

    m = interne.ouvrir(_agent("revue", outils=["lire"]), espace, sur_appel=sur_appel)
    tache = asyncio.create_task(interne.post("outils", m, _outil("lire", chemin="README.md")))
    await asyncio.sleep(0.05)
    await interne.missions.fermer(m)
    r = await asyncio.wait_for(tache, 5)
    bloque.set()
    await asyncio.sleep(0.02)
    assert r.status_code == 409 and ecrits == []


async def test_jeton_d_une_mission_n_agit_pas_sur_une_autre(interne, espace):
    vus_a, vus_b = [], []

    async def sur_a(libelle, resultat):
        vus_a.append(libelle)

    async def sur_b(libelle, resultat):
        vus_b.append(libelle)

    a = interne.ouvrir(_agent("revue", outils=["lire"]), espace, sur_appel=sur_a)
    b = interne.ouvrir(_agent("code", outils=["lire"]), espace, sur_appel=sur_b)
    interne.llm.reponses = [_reponse()]
    await interne.post("modele", a, {**MSG, "outils": True})
    await interne.post("outils", a, _outil("lire", chemin="README.md"))
    assert (a.appels_modele, a.appels_tour, len(vus_a)) == (1, 1, 1)
    assert (b.appels_modele, b.appels_tour, vus_b) == (0, 0, [])
    await interne.missions.fermer(a)
    assert (await interne.post("outils", a, _outil("lire", chemin="README.md"))).status_code == 401
    assert (await interne.post("outils", b, _outil("lire", chemin="README.md"))).status_code == 200
    assert vus_b == ["lire(README.md)"] and len(vus_a) == 1


async def test_message_rendu_normalise_les_tool_calls(interne):
    m = interne.ouvrir()
    interne.llm.reponses = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "z", "index": 0, "function": {"name": "lire", "arguments": {"a": 1}}}
            ],
        }
    ]
    message = (await interne.post("modele", m, MSG)).json()["message"]
    assert message["tool_calls"] == [
        {"id": "z", "type": "function", "function": {"name": "lire", "arguments": '{"a": 1}'}}
    ]
