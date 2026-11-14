"""Outils de lecture du portail (projets, pipelines, kanban) pour l'agent orchestrateur."""

import json

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from portail.db import Etape, Pipeline, Projet, Tache
from portail.moteur import spec_courante
from portail.outils import _fonction
from portail.schemas import COLONNES, Id

_MAX_SORTIE = 8_000
_MAX_SPEC = 3_000


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Vide(_Args):
    pass


class _ProjetId(_Args):
    projet_id: Id


class _PipelineId(_Args):
    pipeline_id: Id


class _Pipelines(_Args):
    projet_id: Id | None = None
    etat: str | None = None


_ARGS: dict[str, type[_Args]] = {
    "lister_projets": _Vide,
    "lire_projet": _ProjetId,
    "lister_pipelines": _Pipelines,
    "lire_pipeline": _PipelineId,
    "lire_kanban": _ProjetId,
}

_PROJET_ID = {"projet_id": {"type": "integer", "description": "Identifiant du projet."}}

SCHEMAS_PORTAIL: dict[str, dict] = {
    "lister_projets": _fonction("lister_projets", "Liste les projets du portail.", {}, []),
    "lire_projet": _fonction(
        "lire_projet",
        "Lit un projet : description, dépôt et spec courante (tronquée).",
        _PROJET_ID,
        ["projet_id"],
    ),
    "lister_pipelines": _fonction(
        "lister_pipelines",
        "Liste les pipelines, éventuellement d'un projet ou dans un état donné.",
        {
            **_PROJET_ID,
            "etat": {"type": "string", "description": "État du pipeline, ex. en_cours."},
        },
        [],
    ),
    "lire_pipeline": _fonction(
        "lire_pipeline",
        "Lit un pipeline et ses étapes (ordre, agent, état, erreur).",
        {"pipeline_id": {"type": "integer", "description": "Identifiant du pipeline."}},
        ["pipeline_id"],
    ),
    "lire_kanban": _fonction(
        "lire_kanban",
        "Lit le kanban d'un projet : les tâches par colonne.",
        _PROJET_ID,
        ["projet_id"],
    ),
}


def _borner(texte: str) -> str:
    return texte if len(texte) <= _MAX_SORTIE else texte[:_MAX_SORTIE] + "… (tronqué)"


class OutilsPortail:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], noms: list[str]):
        self.sessions = sessions
        self.noms = [n for n in noms if n in SCHEMAS_PORTAIL]

    def schemas(self) -> list[dict]:
        return [SCHEMAS_PORTAIL[n] for n in self.noms]

    async def executer(self, nom: str, arguments: str) -> tuple[str, bool]:
        if nom not in self.noms:
            return f"erreur : outil inconnu : {nom}", True
        try:
            brut = json.loads(arguments or "{}")
            args = _ARGS[nom].model_validate(brut)
        except (ValueError, RecursionError, ValidationError) as e:  # ValidationError : ValueError
            return f"erreur : arguments invalides : {e}".replace("\n", " ")[:300], True
        async with self.sessions() as s:
            return _borner(await getattr(self, f"_{nom}")(s, args)), False

    async def _lister_projets(self, s: AsyncSession, _: _Vide) -> str:
        projets = (await s.scalars(select(Projet).order_by(Projet.id))).all()
        return "\n".join(f"#{p.id} {p.nom}" for p in projets) or "aucun projet"

    async def _lire_projet(self, s: AsyncSession, a: _ProjetId) -> str:
        p = await s.get(Projet, a.projet_id)
        if p is None:
            return f"erreur : projet {a.projet_id} introuvable"
        spec = await spec_courante(s, p.id)
        corps = spec.contenu if spec else "(aucune spec validée)"
        if len(corps) > _MAX_SPEC:
            corps = corps[:_MAX_SPEC] + "… (tronqué)"
        return (
            f"#{p.id} {p.nom}\ndescription : {p.description or '-'}\n"
            f"dépôt : {p.depot_url or '-'}\nspec courante :\n{corps}"
        )

    async def _lister_pipelines(self, s: AsyncSession, a: _Pipelines) -> str:
        req = select(Pipeline).order_by(Pipeline.id)
        if a.projet_id is not None:
            req = req.where(Pipeline.projet_id == a.projet_id)
        if a.etat is not None:
            req = req.where(Pipeline.etat == a.etat)
        pipelines = (await s.scalars(req)).all()
        return (
            "\n".join(f"#{p.id} {p.type} projet {p.projet_id} : {p.etat}" for p in pipelines)
            or "aucun pipeline"
        )

    async def _lire_pipeline(self, s: AsyncSession, a: _PipelineId) -> str:
        p = await s.get(Pipeline, a.pipeline_id)
        if p is None:
            return f"erreur : pipeline {a.pipeline_id} introuvable"
        etapes = (
            await s.scalars(select(Etape).where(Etape.pipeline_id == p.id).order_by(Etape.ordre))
        ).all()
        lignes = [f"#{p.id} {p.type} projet {p.projet_id} : {p.etat}"]
        for e in etapes:
            erreur = f" — {e.erreur}" if e.erreur else ""
            lignes.append(f"{e.ordre}. {e.agent} : {e.etat}{erreur}")
        return "\n".join(lignes)

    async def _lire_kanban(self, s: AsyncSession, a: _ProjetId) -> str:
        if await s.get(Projet, a.projet_id) is None:
            return f"erreur : projet {a.projet_id} introuvable"
        taches = (
            await s.scalars(
                select(Tache).where(Tache.projet_id == a.projet_id).order_by(Tache.rang, Tache.id)
            )
        ).all()
        lignes = []
        for col in COLONNES:
            lignes.append(f"## {col}")
            for t in (t for t in taches if t.colonne == col):
                marques = (" [protégée]" if t.protegee else "") + (
                    f" [verrou pipeline {t.verrou}]" if t.verrou else ""
                )
                lignes.append(f"#{t.id} {t.titre}{marques}")
        return "\n".join(lignes)
