from dataclasses import dataclass, field

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from portail.agents import Catalogue
from portail.db import ActionConversation, Document, Pipeline, Projet, Tache
from portail.etats import Etat
from portail.moteur import Refus, creer_pipeline, terminer_etape
from portail.schemas import (
    COLONNES,
    DonneesTache,
    DonneesTachePartielles,
    Id,
    PipelineIn,
    ProjetIn,
    verifier_depot,
)
from portail.taches import creer_tache, deplacer_tache, modifier_tache

AUTEUR = "nicolas"


class DeposerSpec(BaseModel):
    projet_id: Id
    contenu: str


class LancerPipeline(PipelineIn):
    projet_id: Id


class CreerTache(DonneesTache):
    projet_id: Id
    depend_de: list[Id] = Field(default_factory=list)


class ModifierTache(DonneesTachePartielles):
    tache_id: Id
    depend_de: list[Id] | None = None


class DeplacerTache(BaseModel):
    tache_id: Id
    colonne: str


class AnnulerTache(BaseModel):
    tache_id: Id


ACTIONS: dict[str, type[BaseModel]] = {
    "creer_projet": ProjetIn,
    "deposer_spec": DeposerSpec,
    "lancer_pipeline": LancerPipeline,
    "creer_tache": CreerTache,
    "modifier_tache": ModifierTache,
    "deplacer_tache": DeplacerTache,
    "annuler_tache": AnnulerTache,
}


@dataclass
class Execution:
    resultat: str
    lien: str | None
    etapes_a_lancer: list[int] = field(default_factory=list)


def _lire(nom: str, parametres: dict) -> BaseModel:
    if nom not in ACTIONS:
        raise Refus(422, f"action inconnue : {nom}")
    try:
        return ACTIONS[nom].model_validate(parametres)
    except ValidationError as e:
        details = "; ".join(
            f"{'.'.join(map(str, err['loc'])) or 'paramètres'} : {err['msg']}" for err in e.errors()
        )
        raise Refus(422, f"paramètres invalides ({details})") from None


async def _verifier(s: AsyncSession, catalogue: Catalogue, nom: str, p: BaseModel) -> None:
    if (pid := getattr(p, "projet_id", None)) is not None and await s.get(Projet, pid) is None:
        raise Refus(422, f"projet {pid} introuvable")
    if (tid := getattr(p, "tache_id", None)) is not None and await s.get(Tache, tid) is None:
        raise Refus(422, f"tâche {tid} introuvable")
    if nom == "creer_projet":
        verifier_depot(p.depot_url)
    elif nom == "lancer_pipeline":
        if p.type == "dev":
            raise Refus(422, "un pipeline dev se lance depuis une tâche Prête du kanban")
        if p.type not in catalogue.pipelines:
            raise Refus(422, f"type de pipeline inconnu : {p.type}")
    elif nom == "deplacer_tache" and p.colonne not in COLONNES:
        raise Refus(422, f"colonne inconnue : {p.colonne} (attendu : {', '.join(COLONNES)})")
    elif nom == "deposer_spec":
        if not p.contenu.strip():
            raise Refus(422, "le contenu de la spec est vide")
        ouvert = await s.scalar(
            select(Pipeline.id)
            .where(
                Pipeline.projet_id == p.projet_id,
                Pipeline.type == "spec",
                Pipeline.etat.not_in([Etat.TERMINEE, Etat.ECHOUEE]),
            )
            .limit(1)
        )
        if ouvert is not None:
            raise Refus(422, "un pipeline de spec est déjà ouvert : finis-le ou annule-le")


async def valider_action(s: AsyncSession, catalogue: Catalogue, nom: str, parametres: dict) -> dict:
    """Paramètres normalisés (champs absents omis), ou Refus(422)."""
    p = _lire(nom, parametres)
    await _verifier(s, catalogue, nom, p)
    return p.model_dump(exclude_unset=True)


async def executer_action(
    s: AsyncSession, catalogue: Catalogue, action: ActionConversation
) -> Execution:
    """Refait les vérifications puis exécute ; l'appelant commit et lance `etapes_a_lancer`."""
    nom = action.nom
    p = _lire(nom, action.parametres)
    await _verifier(s, catalogue, nom, p)
    if nom == "creer_projet":
        projet = Projet(**p.model_dump())
        s.add(projet)
        await s.flush()
        return Execution(f"projet « {projet.nom} » créé", f"/projets/{projet.id}")
    if nom == "deposer_spec":
        pipeline, _ = await creer_pipeline(s, catalogue, p.projet_id, "spec")
        etape = pipeline.etapes[0]
        s.add(
            Document(
                projet_id=p.projet_id,
                pipeline_id=pipeline.id,
                etape_id=etape.id,
                type="spec",
                contenu=p.contenu,
                etat="validee",
            )
        )
        await s.flush()
        suivante = await terminer_etape(s, catalogue, etape)
        lancer = [suivante.id] if suivante else []
        return Execution("spec déposée et validée", f"/pipelines/{pipeline.id}", lancer)
    if nom == "lancer_pipeline":
        pipeline, etape = await creer_pipeline(s, catalogue, p.projet_id, p.type)
        lancer = [etape.id] if etape else []
        return Execution(f"pipeline {p.type} lancé", f"/pipelines/{pipeline.id}", lancer)
    if nom == "creer_tache":
        t = await creer_tache(s, p.projet_id, p, AUTEUR)
        return Execution(f"tâche « {t.titre} » créée", f"/projets/{t.projet_id}/kanban")
    tache = await s.get(Tache, p.tache_id)
    if nom == "modifier_tache":
        await modifier_tache(s, tache, p, AUTEUR)
        return Execution(f"tâche « {tache.titre} » modifiée", f"/projets/{tache.projet_id}/kanban")
    if nom == "deplacer_tache":
        await deplacer_tache(s, tache, p.colonne, None, AUTEUR)
        return Execution(
            f"tâche « {tache.titre} » déplacée vers {p.colonne}",
            f"/projets/{tache.projet_id}/kanban",
        )
    raise ValueError(f"action non exécutée ici : {nom}")  # annuler_tache : voir chat
