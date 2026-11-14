from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from portail.db import Projet, Tache, TacheDependance, TacheEvenement
from portail.moteur import Refus
from portail.schemas import DonneesTache, DonneesTachePartielles

CHAMPS = ("titre", "description", "criteres", "fichiers")


def verifier_modifiable(tache: Tache) -> None:
    if tache.verrou is not None:
        raise Refus(409, f"tâche verrouillée par le pipeline {tache.verrou}")


def _copie(t: Tache) -> dict:
    return {
        c: (v.isoformat() if hasattr(v, "isoformat") else v)
        for col in Tache.__table__.columns
        for c, v in [(col.name, getattr(t, col.name))]
    }


def _journal(session, t: Tache, type_: str, auteur: str, donnees: dict) -> None:
    session.add(
        TacheEvenement(
            projet_id=t.projet_id, tache_id=t.id, type=type_, auteur=auteur, donnees=donnees
        )
    )


async def _verrouiller_colonnes(session, projet_id: int, colonnes: set[str]) -> list[Tache]:
    """Verrouille le projet puis les lignes des colonnes (par id) : les écritures du tableau se
    sérialisent par projet, même vers une colonne vide."""
    await session.scalar(select(Projet.id).where(Projet.id == projet_id).with_for_update())
    return list(
        (
            await session.scalars(
                select(Tache)
                .where(Tache.projet_id == projet_id, Tache.colonne.in_(colonnes))
                .order_by(Tache.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
    )


async def _verrouiller_tache(session, tache: Tache) -> None:
    """Verrou du projet, puis relecture : colonne et verrou lus après l'attente sont à jour."""
    await session.scalar(select(Projet.id).where(Projet.id == tache.projet_id).with_for_update())
    await session.refresh(tache)


def _renumeroter(taches: list[Tache]) -> None:
    for i, t in enumerate(taches, 1):
        t.rang = i * 1000


async def creer_tache(
    session: AsyncSession,
    projet_id: int,
    donnees: DonneesTache,
    auteur: str,
    origine: str = "manuel",
    document_id: int | None = None,
    protegee: bool = True,
) -> Tache:
    if await session.get(Projet, projet_id) is None:
        raise Refus(404, "projet introuvable")
    colonne = await _verrouiller_colonnes(session, projet_id, {"a_faire"})
    tache = Tache(
        projet_id=projet_id,
        colonne="a_faire",
        rang=max((t.rang for t in colonne), default=0) + 1000,
        origine=origine,
        document_id=document_id,
        protegee=protegee,
        **donnees.model_dump(include=set(CHAMPS)),
    )
    session.add(tache)
    await session.flush()
    await definir_dependances(session, tache, donnees.depend_de)
    _journal(session, tache, "creation", auteur, {**_copie(tache), "depend_de": donnees.depend_de})
    return tache


async def modifier_tache(
    session: AsyncSession, tache: Tache, donnees: DonneesTachePartielles, auteur: str
) -> Tache:
    await _verrouiller_tache(session, tache)
    verifier_modifiable(tache)
    change = {
        c: v
        for c in donnees.model_fields_set
        if c in CHAMPS and (v := getattr(donnees, c)) != getattr(tache, c)
    }
    for c, v in change.items():
        setattr(tache, c, v)
    if donnees.depend_de is not None and sorted(set(donnees.depend_de)) != await _dependances(
        session, tache.id
    ):
        await definir_dependances(session, tache, donnees.depend_de)
        change["depend_de"] = donnees.depend_de
    if not change:  # rien ne change : ni version, ni protection, ni journal
        return tache
    tache.version += 1
    if auteur == "nicolas":
        tache.protegee = True
    _journal(session, tache, "modification", auteur, change)
    await session.flush()
    return tache


async def deplacer_tache(
    session: AsyncSession, tache: Tache, colonne: str, avant_id: int | None, auteur: str
) -> None:
    await _verrouiller_tache(session, tache)
    verifier_modifiable(tache)
    source = tache.colonne
    lignes = await _verrouiller_colonnes(session, tache.projet_id, {colonne, source})
    cible = sorted(
        (t for t in lignes if t.colonne == colonne and t.id != tache.id),
        key=lambda t: (t.rang, t.id),
    )
    pos = next((i for i, t in enumerate(cible) if t.id == avant_id), len(cible))
    cible.insert(pos, tache)
    tache.colonne = colonne
    _renumeroter(cible)
    if source != colonne:
        _renumeroter(
            sorted(
                (t for t in lignes if t.colonne == source and t.id != tache.id),
                key=lambda t: (t.rang, t.id),
            )
        )
    _journal(
        session,
        tache,
        "deplacement",
        auteur,
        {"de": source, "vers": colonne, "avant_id": avant_id},
    )
    await session.flush()


async def supprimer_tache(session: AsyncSession, tache: Tache, auteur: str) -> None:
    await _verrouiller_tache(session, tache)
    verifier_modifiable(tache)
    deps = await _dependances(session, tache.id)
    _journal(session, tache, "suppression", auteur, {**_copie(tache), "depend_de": deps})
    await session.delete(tache)
    await session.flush()


async def _dependances(session: AsyncSession, tache_id: int) -> list[int]:
    return list(
        (
            await session.scalars(
                select(TacheDependance.depend_de_id)
                .where(TacheDependance.tache_id == tache_id)
                .order_by(TacheDependance.depend_de_id)
            )
        ).all()
    )


async def definir_dependances(session: AsyncSession, tache: Tache, ids: list[int]) -> None:
    ids = sorted(set(ids))
    valides = set(
        (
            await session.scalars(
                select(Tache.id).where(Tache.projet_id == tache.projet_id, Tache.id.in_(ids))
            )
        ).all()
    )
    if valides != set(ids):
        raise Refus(422, "dépendance hors projet ou inconnue")
    aretes = (
        await session.execute(
            select(TacheDependance.tache_id, TacheDependance.depend_de_id)
            .join(Tache, Tache.id == TacheDependance.tache_id)
            .where(Tache.projet_id == tache.projet_id, TacheDependance.tache_id != tache.id)
        )
    ).all()
    suivants: dict[int, list[int]] = {}
    for a, b in aretes:
        suivants.setdefault(a, []).append(b)
    vus: set[int] = set()
    pile = list(
        ids
    )  # parcours en profondeur : atteint-on `tache` depuis ses nouvelles dépendances ?
    while pile:
        n = pile.pop()
        if n == tache.id:
            raise Refus(422, "cycle de dépendances")
        if n not in vus:
            vus.add(n)
            pile.extend(suivants.get(n, []))
    await session.execute(delete(TacheDependance).where(TacheDependance.tache_id == tache.id))
    session.add_all(TacheDependance(tache_id=tache.id, depend_de_id=i) for i in ids)
    await session.flush()
