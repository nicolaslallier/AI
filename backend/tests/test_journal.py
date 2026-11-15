import logging

from asgi_lifespan import LifespanManager
from conftest import CATALOGUE_TEST, FauxLLM
from httpx import ASGITransport, AsyncClient
from test_conversations import _attendre, _creer, _envoyer
from test_dev import CIBLES, CODE_OK, CONFIG, Monde, appel, texte, verdict

from portail import journal
from portail.api import create_app
from portail.db import Projet, Tache
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
        for rang, titre in ((1000, f"Titre {MARQUEUR}"), (2000, "Deuxième")):
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
    # tâche 2 : la sortie d'une commande porte le marqueur, puis une ErreurLLM le porte aussi
    m.lanceur.codes = {CIBLES: [1]}
    m.llm.exception = ErreurLLM(f"LiteLLM a répondu 500 : {MARQUEUR}")
    await m.lancer(2)
    assert MARQUEUR not in caplog.text


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
            transport=ASGITransport(app, raise_app_exceptions=False), base_url="http://t"
        ) as c,
    ):
        r = await c.get("/api/boom/valeur-url")
    assert (r.status_code, r.json()) == (500, {"detail": "erreur interne"})
    assert MARQUEUR not in caplog.text and "/api/boom/{x}" in caplog.text
