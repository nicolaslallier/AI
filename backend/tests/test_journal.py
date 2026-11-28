import asyncio
import json
import logging
import sys

import httpx
from asgi_lifespan import LifespanManager
from conftest import CATALOGUE_TEST, FauxLLM, _agent
from httpx import ASGITransport, AsyncClient
from prometheus_client import generate_latest
from sqlalchemy import select
from test_conversations import _attendre, _creer, _envoyer
from test_dev import CIBLES, CODE_OK, CONFIG, TESTS_OK, Monde, appel, texte, verdict

from portail import journal
from portail.agents import Catalogue
from portail.api import create_app
from portail.db import AppelLLM, Projet, Tache
from portail.lanceur import Resultat
from portail.llm import ClientLLM, ErreurLLM

MARQUEUR = "ZZ-secret-7731"
logger = logging.getLogger("portail.test_journal")


def test_erreur_sans_message_d_exception(caplog):
    try:
        raise ValueError(MARQUEUR)
    except ValueError:
        journal.erreur(logger, "tâche %s", 4)
    assert "tâche 4" in caplog.text and "ValueError" in caplog.text
    assert MARQUEUR not in caplog.text


async def test_mission_complete_sans_contenu(tmp_path, sessions, caplog):
    caplog.set_level(logging.DEBUG)
    m = Monde(tmp_path, sessions)
    async with sessions() as s:
        p = Projet(nom="p", depot_url=f"file://{m.origine}", config_execution=CONFIG)
        s.add(p)
        await s.flush()
        for rang, titre in ((1000, f"Titre {MARQUEUR}"), (2000, "Deuxième"), (3000, "Troisième")):
            s.add(Tache(
                projet_id=p.id, titre=titre, description="d", criteres=["x"],
                fichiers=["src/x.py"], colonne="prete", rang=rang, origine="manuel",
            ))  # fmt: skip
        await s.commit()
    # tâche 1 : le marqueur est dans le titre, un fichier, une réponse du LLM et un verdict
    m.lanceur.codes = {CIBLES: [1]}
    m.llm.reponses = [
        appel("ecrire", chemin="tests/test_x.py", contenu=f"# {MARQUEUR}\ndef test_x(): ...\n"),
        texte(f"réponse {MARQUEUR}"),
        *CODE_OK,
        verdict("ok", MARQUEUR),
    ]
    await m.lancer(1)
    # tâche 2 : la vérification échoue et la sortie de pytest porte le marqueur ; la raison de
    # blocage (en base) la reprend, pas le journal
    lancer = m.lanceur.lancer

    async def lancer_bruyant(espace, image, commande, *args, **kw):
        r = await lancer(espace, image, commande, *args, **kw)
        return Resultat(code=r.code, sortie=f"échec {MARQUEUR}", delai_depasse=False) if (
            commande == "pytest" and r.code
        ) else r  # fmt: skip

    m.lanceur.lancer = lancer_bruyant
    m.reglages.renvois_max = 0  # blocage dès la vérification
    m.lanceur.codes = {CIBLES: [1], "pytest": [0, 1]}  # verte sur la base
    m.llm.reponses = [*TESTS_OK, *CODE_OK]
    await m.lancer(2)
    async with sessions() as s:
        assert MARQUEUR in (await s.get(Tache, 2)).resume_blocage  # la sortie a bien circulé
    # tâche 3 : une ErreurLLM porte le marqueur
    m.lanceur.codes = {CIBLES: [1]}
    m.llm.exception = ErreurLLM(f"LiteLLM a répondu 500 : {MARQUEUR}")
    await m.lancer(3)
    assert MARQUEUR not in caplog.text
    assert "bloqué : llm" in caplog.text
    assert m.notifieur.envoyes  # les notifications ntfy sont sur le chemin
    _sans_contenu(
        generate_latest().decode(), *_lignes_formatees(caplog), json.dumps(m.notifieur.envoyes)
    )


def _lignes_formatees(caplog) -> list[str]:
    formateur = journal.FormatJSON()
    return [formateur.format(r) for r in caplog.records]


def _sans_contenu(*textes: str) -> None:
    # le slug d'une branche met le titre en minuscules : on cherche aussi cette forme
    for t in textes:
        assert MARQUEUR not in t and MARQUEUR.lower() not in t.lower()


async def test_conversation_sans_contenu(client, faux_llm, caplog):
    caplog.set_level(logging.DEBUG)
    cid = await _creer(client)
    faux_llm.exception = ErreurLLM(MARQUEUR)
    await _envoyer(client, cid, f"message {MARQUEUR}")
    await _attendre(client, cid)
    assert MARQUEUR not in caplog.text


async def test_route_500_sans_contenu(moteur, reglages, caplog):
    app = create_app(reglages=reglages, llm=FauxLLM(), catalogue=CATALOGUE_TEST)

    @app.get("/api/boom/{x}")
    async def boom(x: str):
        raise RuntimeError(MARQUEUR)

    caplog.set_level(logging.DEBUG)
    async with (
        LifespanManager(app),
        AsyncClient(
            transport=ASGITransport(app, raise_app_exceptions=True), base_url="http://t"
        ) as c,
    ):
        # raise_app_exceptions=True : si l'exception remontait au serveur (uvicorn la journalise
        # avec son message), ce client la relèverait ici
        r = await c.get("/api/boom/valeur-url")
    assert (r.status_code, r.json()) == (500, {"detail": "erreur interne"})
    assert MARQUEUR not in caplog.text and "/api/boom/{x}" in caplog.text


def _formater(logger_nom="portail.test_journal", exc=None):
    rec = logging.LogRecord(logger_nom, logging.INFO, __file__, 1, "message %s", ("x",), exc)
    return json.loads(journal.FormatJSON().format(rec))


def test_ligne_json_avec_identifiants():
    journal.commencer(pipeline=3)
    journal.lier(etape=7, agent="code")
    journal.nouvelle_mission("code", 4096)
    ligne = _formater()
    assert (ligne["niveau"], ligne["module"], ligne["message"]) == (
        "INFO", "portail.test_journal", "message x"
    )  # fmt: skip
    assert (ligne["pipeline"], ligne["etape"], ligne["agent"]) == (3, 7, "code")
    assert len(ligne["mission"]) == 12
    assert "tache" not in ligne and "contexte_max" not in ligne
    journal.lier(etape=None)
    assert "etape" not in _formater()
    journal.commencer()


def test_exception_rendue_sans_message():
    try:
        raise ValueError(MARQUEUR)
    except ValueError:
        ligne = _formater("tiers", sys.exc_info())
    assert ligne["exception"] == "ValueError" and "pile" in ligne
    assert MARQUEUR not in json.dumps(ligne)


async def test_tache_enfant_sans_identifiants_perimes():
    journal.commencer(conversation=1)

    async def enfant():
        journal.commencer(etape=2)
        return dict(journal.contexte.get())

    assert await asyncio.create_task(enfant()) == {"etape": 2}
    assert journal.contexte.get() == {"conversation": 1}
    journal.commencer()


def test_journal_json_charge_par_dictconfig(capsys):
    import logging.config
    from pathlib import Path

    config = json.loads((Path(__file__).parent.parent / "journal.json").read_text())
    racine = logging.getLogger()
    avant = (racine.level, racine.handlers[:])
    try:
        logging.config.dictConfig(config)
        journal.commencer(pipeline=8)
        logging.getLogger("portail.test_json").info("bonjour %s", "toi")
        sortie = capsys.readouterr().out.strip().splitlines()
        assert len(sortie) == 1
        ligne = json.loads(sortie[0])
        assert (ligne["niveau"], ligne["module"], ligne["message"], ligne["pipeline"]) == (
            "INFO", "portail.test_json", "bonjour toi", 8
        )  # fmt: skip
    finally:
        journal.commencer()
        racine.handlers[:] = avant[1]
        racine.setLevel(avant[0])
        for nom in ("httpx", "httpcore", "uvicorn", "uvicorn.error", "uvicorn.access"):
            lg = logging.getLogger(nom)
            lg.handlers.clear()
            lg.setLevel(logging.NOTSET)
            lg.propagate = True


def test_identifiant_non_serialisable_ne_casse_pas_le_formateur():
    journal.commencer(pipeline=object())
    try:
        assert "object" in _formater()["pipeline"]
    finally:
        journal.commencer()


async def test_conversation_sans_contenu_nulle_part(moteur, sessions, reglages, caplog):
    usage = {"prompt_tokens": 10, "completion_tokens": 5}
    texte = f"<think>{MARQUEUR}</think>réponse {MARQUEUR}"

    def h(requete: httpx.Request) -> httpx.Response:
        corps = json.loads(requete.content)
        if f"second {MARQUEUR}" in json.dumps(corps["messages"]):
            return httpx.Response(500, text=f"panne {MARQUEUR}")
        if not corps.get("stream"):  # l'agent a des outils : tour non diffusé
            reponse = {"choices": [{"message": {"content": texte}}], "usage": usage}
            return httpx.Response(200, json=reponse)
        morceaux = [{"choices": [{"delta": {"content": texte}}]}, {"choices": [], "usage": usage}]
        flux = "".join(f"data: {json.dumps(m)}\n\n" for m in morceaux) + "data: [DONE]\n\n"
        return httpx.Response(200, text=flux)

    llm = ClientLLM(
        "http://l", "k", transport=httpx.MockTransport(h), sessions=sessions, version="sha-test"
    )
    app = create_app(reglages=reglages, llm=llm, catalogue=CATALOGUE_TEST)
    caplog.set_level(logging.DEBUG)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        cid = await _creer(c)
        await _envoyer(c, cid, f"message {MARQUEUR}")
        await _attendre(c, cid)
        await _envoyer(c, cid, f"second {MARQUEUR}")
        await _attendre(c, cid)
        metriques = (await c.get("/metrics")).text
    async with sessions() as s:
        lignes = list((await s.scalars(select(AppelLLM))).all())
    assert sorted(x.issue for x in lignes) == ["erreur", "ok"]
    _sans_contenu(metriques, *_lignes_formatees(caplog), *(str(vars(x)) for x in lignes))


async def test_conversation_en_flux_sans_contenu_nulle_part(moteur, sessions, reglages, caplog):
    usage = {"prompt_tokens": 10, "completion_tokens": 5}

    def h(requete: httpx.Request) -> httpx.Response:
        corps = json.loads(requete.content)
        if f"second {MARQUEUR}" in json.dumps(corps["messages"]):
            return httpx.Response(500, text=f"panne {MARQUEUR}")
        morceaux = [
            {"choices": [{"delta": {"content": f"<think>{MARQUEUR}</think>réponse "}}]},
            {"choices": [{"delta": {"content": MARQUEUR}}]},
            {"choices": [], "usage": usage},
        ]
        flux = "".join(f"data: {json.dumps(m)}\n\n" for m in morceaux) + "data: [DONE]\n\n"
        return httpx.Response(200, text=flux)

    llm = ClientLLM(
        "http://l", "k", transport=httpx.MockTransport(h), sessions=sessions, version="sha-test"
    )
    catalogue = Catalogue(
        agents={**CATALOGUE_TEST.agents, "orchestrateur": _agent("orchestrateur")},  # sans outil
        pipelines=CATALOGUE_TEST.pipelines,
    )
    app = create_app(reglages=reglages, llm=llm, catalogue=catalogue)
    caplog.set_level(logging.DEBUG)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        cid = await _creer(c)
        await _envoyer(c, cid, f"message {MARQUEUR}")
        await _attendre(c, cid)
        await _envoyer(c, cid, f"second {MARQUEUR}")
        await _attendre(c, cid)
        metriques = (await c.get("/metrics")).text
    async with sessions() as s:
        lignes = list((await s.scalars(select(AppelLLM))).all())
    assert sorted(x.issue for x in lignes) == ["erreur", "ok"]
    _sans_contenu(metriques, *_lignes_formatees(caplog), *(str(vars(x)) for x in lignes))
