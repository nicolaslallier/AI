from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from conftest import FauxNotifieur
from sqlalchemy import select

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
    assert e["titre"] == "Résumé du matin" and e["message"] == "- rien de bloqué"
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


async def test_texte_coupe_a_4000(client, sessions, faux_llm):
    await _activite(sessions, _h(5).astimezone(UTC))
    faux_llm.reponses = [{"content": "x" * 5000}]
    n = FauxNotifieur()
    assert await _appeler(client, sessions, n, _h(9))
    assert len(n.envoyes[0]["message"]) == 4000


async def test_erreur_rien_envoye(client, sessions, faux_llm):
    await _activite(sessions, _h(5).astimezone(UTC))
    faux_llm.exception = RuntimeError("boom")
    n = FauxNotifieur()
    assert not await _appeler(client, sessions, n, _h(9))
    assert n.envoyes == []
