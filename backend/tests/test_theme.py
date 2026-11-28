"""Modèle Theme : une seule ligne, nom par défaut « clair », maj_le par défaut func.now()."""

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import ClauseElement

from portail.db import Base, Theme


def test_theme_importable():
    # Critère : le modèle Theme est importable depuis backend/portail/db.py.
    assert Theme is not None
    assert Theme.__name__ == "Theme"


def test_table_theme():
    assert Theme.__tablename__ == "theme"
    assert "theme" in Base.metadata.tables


def test_colonne_id_unique():
    # Critère : id = 1 unique (une seule ligne dans la table).
    col = Theme.__table__.c.id
    assert col.primary_key
    assert col.unique


def test_colonne_nom_server_default_clair():
    # Critère : la colonne nom a un server_default='clair'.
    col = Theme.__table__.c.nom
    assert col.server_default is not None
    assert col.server_default.arg == "clair"


def test_colonne_maj_le_server_default_func_now():
    # Critère : la colonne maj_le a un server_default=func.now().
    col = Theme.__table__.c.maj_le
    assert col.server_default is not None
    assert isinstance(col.server_default.arg, ClauseElement)
    assert col.server_default.arg == func.now()


async def test_insertion_utilise_les_defaults(sessions):
    # La table ne contient qu'une seule ligne ; l'insertion sans valeur prend les defaults.
    async with sessions() as s:
        s.add(Theme(id=1))
        await s.commit()
        theme = await s.get(Theme, 1)
        assert theme.nom == "clair"
        assert theme.maj_le is not None
        # une seule ligne
        assert (await s.scalar(select(func.count()).select_from(Theme))) == 1
