"""Propositions de l'agent de tâches : lecture de sa réponse, enregistrement, acceptation."""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from portail.agents import Catalogue
from portail.db import Document, Etape, Pipeline, Projet, Proposition, Tache
from portail.etats import Etat
from portail.moteur import Refus, terminer_etape
from portail.schemas import DonneesTache, DonneesTachePartielles, _titre_valide
from portail.taches import (
    _dependances,
    creer_tache,
    definir_dependances,
    modifier_tache,
    supprimer_tache,
)

MODIFIABLES = ("a_faire", "prete")
PERIMEE = "proposition périmée : la tâche a changé depuis"


class _Contenu(BaseModel):
    titre: str
    description: str = ""
    criteres: list[str] = []
    fichiers: list[str] = []
    depend_de: list[str] = []

    _titre = field_validator("titre")(_titre_valide)


class Nouvelle(_Contenu):
    sorte: Literal["nouvelle"]
    cle: str


class Modification(_Contenu):
    sorte: Literal["modification"]
    tache_id: int


class Retrait(BaseModel):
    sorte: Literal["retrait"]
    tache_id: int
    raison: str


PropositionLue = Annotated[Nouvelle | Modification | Retrait, Field(discriminator="sorte")]


class _Reponse(BaseModel):
    propositions: list[PropositionLue]


SCHEMA_PROPOSITIONS = _Reponse.model_json_schema()
_REF = re.compile(r"T(\d+)")


def lire_propositions(texte: str, cles_existantes: set[int]) -> list[PropositionLue]:
    try:
        lues = _Reponse.model_validate_json(texte).propositions
    except ValidationError as e:
        details = "; ".join(f"{'.'.join(map(str, x['loc']))} : {x['msg']}" for x in e.errors())
        raise ValueError(f"JSON invalide ou mal formé ({details})") from None
    cles = [p.cle for p in lues if isinstance(p, Nouvelle)]
    if doubles := sorted({c for c in cles if cles.count(c) > 1}):
        raise ValueError(f"clé en double : {', '.join(doubles)}")
    for p in lues:
        nom = p.cle if isinstance(p, Nouvelle) else f"T{getattr(p, 'tache_id', '')}"
        for d in getattr(p, "depend_de", []):
            if d == nom:
                raise ValueError(f"{nom} dépend d'elle-même")
            if d in cles:
                continue
            if (m := _REF.fullmatch(d)) and int(m[1]) in cles_existantes:
                continue
            if m:
                raise ValueError(f"{nom} : la tâche {d} n'existe pas dans le projet")
            raise ValueError(f"{nom} : dépendance inconnue « {d} »")
    return lues


async def _verrouiller_projet(session: AsyncSession, projet_id: int) -> None:
    await session.scalar(select(Projet.id).where(Projet.id == projet_id).with_for_update())


async def _tache_verrouillee(session: AsyncSession, tache_id: int | None) -> Tache | None:
    if tache_id is None:
        return None
    return await session.scalar(
        select(Tache)
        .where(Tache.id == tache_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _raison(tache: Tache | None, projet_id: int) -> str | None:
    if tache is None or tache.projet_id != projet_id:
        return "tâche absente du projet"
    if tache.colonne not in MODIFIABLES:
        return f"tâche en colonne {tache.colonne}"
    if tache.protegee:
        return "tâche protégée"
    if tache.verrou is not None:
        return "tâche verrouillée"
    return None


async def plan_du_pipeline(session: AsyncSession, pipeline_id: int) -> Document | None:
    return await session.scalar(
        select(Document).where(
            Document.pipeline_id == pipeline_id,
            Document.type == "plan",
            Document.etat == "validee",
        )
    )


async def enregistrer_propositions(
    session: AsyncSession, etape: Etape, lues: list[PropositionLue], auteur: str
) -> list[str]:
    """Enregistre les propositions `ouverte` ; renvoie les refus « T<id> : <raison> ».
    `auteur` n'est pas stocké : l'acceptation le retrouve par l'agent de l'étape."""
    projet_id = (await session.get(Pipeline, etape.pipeline_id)).projet_id
    await _verrouiller_projet(session, projet_id)
    refus = []
    for p in lues:
        version = None
        if not isinstance(p, Nouvelle):
            tache = await _tache_verrouillee(session, p.tache_id)
            if raison := _raison(tache, projet_id):
                refus.append(f"T{p.tache_id} : {raison}")
                continue
            version = tache.version
        session.add(
            Proposition(
                pipeline_id=etape.pipeline_id,
                etape_id=etape.id,
                projet_id=projet_id,
                sorte=p.sorte,
                cle=getattr(p, "cle", None),
                tache_id=getattr(p, "tache_id", None),
                version_tache=version,
                donnees=p.model_dump(exclude={"sorte", "cle", "tache_id"}),
                etat="ouverte",
            )
        )
    await session.flush()
    return refus


async def _ouvrir(session: AsyncSession, proposition: Proposition) -> None:
    """Projet verrouillé d'abord, puis la proposition relue sous verrou."""
    await _verrouiller_projet(session, proposition.projet_id)
    await session.refresh(proposition, with_for_update=True)
    if proposition.etat != "ouverte":
        raise Refus(409, f"proposition déjà traitée ({proposition.etat})")


async def _resoudre(session: AsyncSession, proposition: Proposition, acceptees) -> list[int]:
    """Clés acceptées → tâches créées ; « T<id> » → tâches encore présentes dans le projet."""
    par_cle = {p.cle: p.tache_creee_id for p in acceptees if p.cle and p.tache_creee_id}
    ids = set()
    for d in proposition.donnees.get("depend_de", []):
        if d in par_cle:
            ids.add(par_cle[d])
        elif m := _REF.fullmatch(d):
            ids.add(int(m[1]))
    presents = await session.scalars(
        select(Tache.id).where(Tache.projet_id == proposition.projet_id, Tache.id.in_(ids))
    )
    return sorted(presents.all())


async def accepter(
    session: AsyncSession, proposition: Proposition, donnees_modifiees: DonneesTache | None
) -> None:
    """Ne commite pas. Une proposition périmée est marquée (flush) avant le Refus 409 :
    l'appelant commite ce marquage."""
    await _ouvrir(session, proposition)
    etape = await session.get(Etape, proposition.etape_id)
    auteur = "nicolas" if donnees_modifiees else f"agent:{etape.agent}"
    acceptees = (
        await session.scalars(
            select(Proposition).where(
                Proposition.pipeline_id == proposition.pipeline_id,
                Proposition.etat == "acceptee",
            )
        )
    ).all()
    d = proposition.donnees
    if proposition.sorte != "nouvelle":
        tache = await _tache_verrouillee(session, proposition.tache_id)
        if _raison(tache, proposition.projet_id) or tache.version != proposition.version_tache:
            proposition.etat = "perimee"
            await session.flush()
            raise Refus(409, PERIMEE)
    if proposition.sorte == "retrait":
        await supprimer_tache(session, tache, auteur)
        proposition.etat = "acceptee"
        await session.flush()
        return
    deps = await _resoudre(session, proposition, acceptees)
    base = donnees_modifiees or DonneesTache(
        titre=d.get("titre", ""),
        description=d.get("description", ""),
        criteres=d.get("criteres", []),
        fichiers=d.get("fichiers", []),
    )
    deps = sorted(set(deps) | set(base.depend_de))
    if proposition.sorte == "nouvelle":
        plan = await plan_du_pipeline(session, proposition.pipeline_id)
        tache = await creer_tache(
            session,
            proposition.projet_id,
            base.model_copy(update={"depend_de": deps}),
            auteur,
            origine="agent",
            document_id=plan.id if plan else None,
            protegee=donnees_modifiees is not None,
        )
        proposition.tache_creee_id = tache.id
        # les propositions acceptées plus tôt qui dépendaient de cette clé sont reliées
        # seulement les tâches créées par une `nouvelle` : une cible de modification peut être
        # devenue protégée, verrouillée ou sortie de a_faire/prete
        for p in acceptees:
            if proposition.cle in p.donnees.get("depend_de", []) and p.tache_creee_id:
                cible = await session.get(Tache, p.tache_creee_id)
                if cible is not None:
                    actuelles = await _dependances(session, cible.id)
                    await definir_dependances(session, cible, actuelles + [tache.id])
    else:
        partielles = DonneesTachePartielles(
            **base.model_dump(include={"titre", "description", "criteres", "fichiers"}),
            depend_de=deps,
        )
        await modifier_tache(session, tache, partielles, auteur)
    proposition.etat = "acceptee"
    await session.flush()


async def rejeter(session: AsyncSession, proposition: Proposition) -> None:
    await _ouvrir(session, proposition)
    proposition.etat = "rejetee"
    await session.flush()


async def fermer_si_fini(
    session: AsyncSession, catalogue: Catalogue, etape_id: int
) -> Etape | None:
    """Termine l'étape quand plus aucune proposition n'est ouverte ; renvoie la suivante à lancer."""
    ouvertes = await session.scalar(
        select(func.count()).where(Proposition.etape_id == etape_id, Proposition.etat == "ouverte")
    )
    if ouvertes:
        return None
    etape = await session.scalar(select(Etape).where(Etape.id == etape_id).with_for_update())
    if etape.etat != Etat.EN_ATTENTE:
        return None
    return await terminer_etape(session, catalogue, etape)
