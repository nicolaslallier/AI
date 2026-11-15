import asyncio
import json
import logging
import sys

from asgi_lifespan import LifespanManager
from conftest import CATALOGUE_TEST, FauxLLM
from httpx import ASGITransport, AsyncClient
from test_conversations import _attendre, _creer, _envoyer
from test_dev import CIBLES, CODE_OK, CONFIG, TESTS_OK, Monde, appel, texte, verdict

from portail import journal
from portail.api import create_app
from portail.db import Projet, Tache
from portail.lanceur import Resultat
from portail.llm import ErreurLLM

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
    m.lanceur.codes = {CIBLES: [1], "pytest": [1]}
    m.llm.reponses = [*TESTS_OK, *CODE_OK]
    await m.lancer(2)
    async with sessions() as s:
        assert MARQUEUR in (await s.get(Tache, 2)).resume_blocage  # la sortie a bien circulé
    # tâche 3 : une ErreurLLM porte le marqueur
    m.lanceur.codes = {CIBLES: [1]}
    m.llm.exception = ErreurLLM(f"LiteLLM a répondu 500 : {MARQUEUR}")
    await m.lancer(3)
    assert MARQUEUR not in caplog.text
    assert "bloqué : ErreurLLM" in caplog.text


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
