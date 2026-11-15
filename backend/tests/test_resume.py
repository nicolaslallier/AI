import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from asgi_lifespan import LifespanManager
from conftest import CATALOGUE_TEST, FauxLLM, FauxNotifieur
from sqlalchemy import select

from portail import api, resume
from portail.config import Reglages
from portail.db import Conversation, Projet, Resume, TacheEvenement
from portail.resume import prochaine_echeance, resumer_si_du

TORONTO = ZoneInfo("America/Toronto")
JOUR = date(2026, 11, 16)


def _h(heure, minute=0):
    return datetime(2026, 11, 16, heure, minute, tzinfo=TORONTO)


@pytest.mark.parametrize(
    ("maintenant", "attendu"),
    [
        (_h(6, 59), _h(7)),
        (_h(7, 1), datetime(2026, 11, 17, 7, tzinfo=TORONTO)),
        # passage à l'heure d'été : le 8 mars 2026 à 07:00 locale (UTC-4)
        (datetime(2026, 3, 7, 12, tzinfo=TORONTO), datetime(2026, 3, 8, 7, tzinfo=TORONTO)),
    ],
)
def test_prochaine_echeance(maintenant, attendu):
    r = prochaine_echeance(maintenant, "07:00")
    assert r == attendu
    assert r.astimezone(TORONTO).hour == 7
    if attendu.month == 3:
        assert r.astimezone(UTC).hour == 11


async def _activite(sessions, cree_le):
    async with sessions() as s:
        p = Projet(nom="p", depot_url="https://github.com/x/y")
        s.add(p)
        await s.flush()
        s.add(
            TacheEvenement(
                projet_id=p.id, tache_id=1, type="creation", auteur="nicolas", cree_le=cree_le
            )
        )
        await s.commit()


async def _appeler(client, sessions, notifieur, maintenant, url="https://p.test"):
    svc = client._transport.app.state.conversations
    return await resumer_si_du(sessions, svc, notifieur, maintenant, "07:00", url)


async def test_pas_d_envoi_sans_activite(client, sessions):
    n = FauxNotifieur()
    assert not await _appeler(client, sessions, n, _h(9))
    assert n.envoyes == []
    async with sessions() as s:
        r = (await s.scalars(select(Resume))).all()
        assert [(x.jour, x.conversation_id) for x in r] == [(JOUR, None)]
        assert (await s.scalars(select(Conversation))).all() == []


async def test_envoi_avec_activite_et_une_seule_fois_par_jour(client, sessions, faux_llm):
    await _activite(sessions, _h(5).astimezone(UTC))
    faux_llm.reponses = [{"content": "- rien de bloqué"}]
    n = FauxNotifieur()
    assert await _appeler(client, sessions, n, _h(9))
    assert not await _appeler(client, sessions, n, _h(9, 30))
    assert len(n.envoyes) == 1
    e = n.envoyes[0]
    assert e["titre"] == "Portail — résumé du matin" and e["message"] == "Résumé prêt"
    async with sessions() as s:
        c = (await s.scalars(select(Conversation))).one()
        assert c.agent == "pm" and c.titre == f"Résumé du {JOUR.isoformat()}"
        assert e["lien"] == f"https://p.test/chat/{c.id}"
        assert (await s.scalar(select(Resume.conversation_id))) == c.id
    assert "Ce qui s'est passé" in faux_llm.appels[0]["messages"][1]["content"]


async def test_avant_l_heure_rien(client, sessions):
    await _activite(sessions, _h(5).astimezone(UTC))
    n = FauxNotifieur()
    assert not await _appeler(client, sessions, n, _h(6, 59))
    assert n.envoyes == []
    async with sessions() as s:
        assert (await s.scalars(select(Resume))).all() == []


async def test_erreur_rien_envoye(client, sessions, faux_llm):
    await _activite(sessions, _h(5).astimezone(UTC))
    faux_llm.exception = RuntimeError("boom")
    n = FauxNotifieur()
    assert not await _appeler(client, sessions, n, _h(9))
    assert n.envoyes == []


async def test_deux_appels_croises_un_seul_envoi(client, sessions, faux_llm, caplog):
    await _activite(sessions, _h(5).astimezone(UTC))
    faux_llm.reponses = [{"content": "- ok"}]
    n = FauxNotifieur()
    with caplog.at_level(logging.INFO, logger="portail.resume"):
        r = await asyncio.gather(
            _appeler(client, sessions, n, _h(9)), _appeler(client, sessions, n, _h(9))
        )
    assert sorted(r) == [False, True]
    assert len(n.envoyes) == 1
    assert all(x.exc_info is None for x in caplog.records)


async def test_course_sur_le_jour_sans_trace(client, sessions, caplog):
    await _activite(sessions, _h(5).astimezone(UTC))
    async with sessions() as s:
        s.add(Resume(jour=JOUR, cree_le=_h(8).astimezone(UTC)))
        await s.commit()

    class Aveugle:  # le test d'existence ne voit pas la ligne de l'autre appel
        def __init__(self, s):
            self.s = s

        async def scalar(self, q):
            if str(q).startswith("SELECT resume.id"):
                return None
            return await self.s.scalar(q)

        def __getattr__(self, nom):
            return getattr(self.s, nom)

    @asynccontextmanager
    async def vue():
        async with sessions() as s:
            yield Aveugle(s)

    n = FauxNotifieur()
    svc = client._transport.app.state.conversations
    with caplog.at_level(logging.INFO, logger="portail.resume"):
        assert not await resumer_si_du(vue, svc, n, _h(9), "07:00", "https://p.test")
    assert n.envoyes == []
    assert [x.levelno for x in caplog.records if x.name == "portail.resume"] == [logging.INFO]
    assert all(x.exc_info is None for x in caplog.records)


@pytest.mark.parametrize("heure", ["7h", "7:00", "25:00", "07:60", "0700", "07:00:00", " 07:00"])
def test_heure_invalide_refusee(heure):
    with pytest.raises(ValueError, match="PORTAIL_RESUME_HEURE"):
        Reglages(database_url="x", resume_heure=heure)


@pytest.mark.parametrize("heure", ["", "07:00", "23:59"])
def test_heure_valide_acceptee(heure):
    assert Reglages(database_url="x", resume_heure=heure).resume_heure == heure


async def test_tourner_survit_a_une_exception(monkeypatch, caplog):
    appels, sommeils = [], []

    async def resumer(*a):
        appels.append(1)
        if len(appels) == 1:
            raise RuntimeError("boom")
        if len(appels) == 3:
            raise asyncio.CancelledError

    async def dormir(s):
        sommeils.append(s)

    monkeypatch.setattr(resume, "resumer_si_du", resumer)
    monkeypatch.setattr(resume.asyncio, "sleep", dormir)
    horloge = lambda: _h(9)
    with (
        caplog.at_level(logging.ERROR, logger="portail.resume"),
        pytest.raises(asyncio.CancelledError),
    ):
        await resume.tourner(None, None, None, "07:00", "", horloge)
    assert len(appels) == 3
    assert any("résumé du matin impossible" in x.message for x in caplog.records)


async def test_tourner_survit_a_un_calcul_d_echeance_en_erreur(monkeypatch, caplog):
    tours, sommeils = [], []

    def echeance(maintenant, heure):
        tours.append(1)
        if len(tours) == 1:
            raise ValueError("heure illisible")
        raise asyncio.CancelledError

    async def dormir(s):
        sommeils.append(s)

    async def resumer(*a):
        return False

    monkeypatch.setattr(resume, "resumer_si_du", resumer)
    monkeypatch.setattr(resume, "prochaine_echeance", echeance)
    monkeypatch.setattr(resume.asyncio, "sleep", dormir)
    with (
        caplog.at_level(logging.ERROR, logger="portail.resume"),
        pytest.raises(asyncio.CancelledError),
    ):
        await resume.tourner(None, None, None, "7h", "", lambda: _h(9))
    assert len(tours) == 2 and sommeils and sommeils[0] >= 1
    assert any("résumé du matin impossible" in x.message for x in caplog.records)


async def test_pas_de_boucle_quand_l_heure_est_vide(reglages, sessions, monkeypatch):
    # démarrage tardif (15:00 UTC = 10:00 à Toronto) : un résumé désactivé n'écrit rien
    assert reglages.resume_heure == ""

    class Tard(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 16, 15, tzinfo=UTC)

    monkeypatch.setattr(api, "datetime", Tard)
    app = api.create_app(reglages=reglages, llm=FauxLLM(), catalogue=CATALOGUE_TEST)
    async with LifespanManager(app):
        await asyncio.sleep(0.3)
    async with sessions() as s:
        assert (await s.scalars(select(Resume))).all() == []
