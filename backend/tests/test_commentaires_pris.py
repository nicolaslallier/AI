from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from portail.db import CommentairePris, ExecutionDev, Pipeline, Projet, Tache


async def _base(s):
    p = Projet(nom="p")
    s.add(p)
    await s.flush()
    t = Tache(projet_id=p.id, titre="t", colonne="en_revue", rang=1000, origine="manuel")
    pl = Pipeline(projet_id=p.id, type="dev")
    s.add_all([t, pl])
    await s.flush()
    return t, pl


def _commentaire(t, ex, type="revue", github_id=1):
    return CommentairePris(
        tache_id=t.id, execution_id=ex.id, github_id=github_id, type=type,
        auteur="nicolas", texte="x", url="https://github.com/x", cree_le=datetime.now(UTC),
    )  # fmt: skip


async def _execution(s, t, pl):
    ex = ExecutionDev(
        pipeline_id=pl.id, tache_id=t.id, n=1, branche="b", espace="e", base="main",
        base_sha="abc", phase="fini", remarques=[], fichiers_tests=[],
    )  # fmt: skip
    s.add(ex)
    await s.flush()
    return ex


async def test_commentaire_pris_unique(sessions):
    async with sessions() as s:
        t, pl = await _base(s)
        ex = await _execution(s, t, pl)
        s.add_all([_commentaire(t, ex), _commentaire(t, ex, type="ligne")])
        await s.commit()  # même github_id, autre type : accepté
        s.add(_commentaire(t, ex))
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_github_id_64_bits(sessions):
    async with sessions() as s:
        t, pl = await _base(s)
        ex = await _execution(s, t, pl)
        c = _commentaire(t, ex, github_id=3_000_000_000)
        s.add(c)
        await s.commit()
        cid = c.id
    async with sessions() as s:
        assert (await s.get(CommentairePris, cid)).github_id == 3_000_000_000


async def test_execution_mode_par_defaut(sessions):
    async with sessions() as s:
        t, pl = await _base(s)
        ex = await _execution(s, t, pl)
        await s.commit()
        assert ex.mode == "normal"
        assert ex.depart_revue is None
