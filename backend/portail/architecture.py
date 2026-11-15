"""Pipeline architecture : annexes des étapes et contrôle des blocs de modèle."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from portail.agents import Catalogue
from portail.archimate import (
    Modele,
    catalogues_markdown,
    fusionner,
    lire_bloc,
    valider,
    valider_synthese,
)
from portail.db import Document, Etape, Pipeline
from portail.moteur import Refus


async def documents_precedents(s: AsyncSession, etape: Etape) -> list[tuple[Etape, Document]]:
    """Documents validés des étapes d'ordre inférieur du même pipeline, dans l'ordre."""
    lignes = await s.execute(
        select(Etape, Document)
        .join(Document, Document.etape_id == Etape.id)
        .where(
            Etape.pipeline_id == etape.pipeline_id,
            Etape.ordre < etape.ordre,
            Document.etat == "validee",
        )
        .order_by(Etape.ordre)
    )
    return [(e, d) for e, d in lignes.all()]


async def annexes_architecture(s: AsyncSession, catalogue: Catalogue, etape: Etape) -> list[str]:
    """La vision validée puis chaque volet précédent, bloc JSON compris."""
    sortie = []
    for e, doc in await documents_precedents(s, etape):
        agent = catalogue.agents.get(e.agent)
        if agent and agent.produit == "volet":
            sortie.append(f"Volet {agent.volet} ({agent.nom}) :\n\n{doc.contenu}")
        elif agent and agent.produit == "vision":
            sortie.append("Vision validée :\n\n" + doc.contenu)
    return sortie


async def verifier_bloc(s: AsyncSession, catalogue: Catalogue, etape: Etape, contenu: str) -> None:
    """Lève BlocInvalide si le bloc de modèle de `contenu` ne respecte pas les règles de l'étape."""
    agent = catalogue.agents[etape.agent]
    _, modele = lire_bloc(contenu)
    connus = {
        el.id
        for _, doc in await documents_precedents(s, etape)
        for el in lire_bloc(doc.contenu)[1].elements
    }
    if agent.produit == "architecture":
        valider_synthese(modele, connus)
    else:
        valider(modele, agent.prefixe, connus)


# --- document assemblé à la lecture ---------------------------------------------------------

TITRES_VOLET = {
    "affaires": "Architecture d'affaires",
    "données": "Architecture de données",
    "applicatif": "Architecture applicative",
    "technologique": "Architecture technologique",
    "sécurité": "Architecture de sécurité",
    "solution": "Écarts, options de solution et feuille de route",
}
SOMMAIRE = "Sommaire exécutif et portée"
REGISTRES = {
    "Registre des décisions": "Registre des décisions (ADR)",
    "Registre des dérogations": "Registre des dérogations",
    "Registre de la dette": "Registre de la dette",
    "Risques, hypothèses et questions ouvertes": "Risques, hypothèses et questions ouvertes",
}


def _hors_code(texte: str):
    """(ligne, dans_un_bloc_de_code) pour chaque ligne ; les lignes ``` sont dans le bloc."""
    dedans = False
    for ligne in texte.split("\n"):
        if ligne.lstrip().startswith("```"):
            dedans = not dedans
            yield ligne, True
        else:
            yield ligne, dedans


def descendre_titres(texte: str) -> str:
    """Chaque titre markdown gagne un `#`, sauf dans les blocs de code."""
    return "\n".join(
        "#" + ligne if not code and ligne.startswith("#") else ligne
        for ligne, code in _hors_code(texte)
    )


def sections(texte: str) -> dict[str, str]:
    """Corps des sections `## Titre` (jusqu'au `## ` suivant), titre sans les dièses."""
    trouvees: dict[str, list[str]] = {}
    courante: list[str] | None = None
    for ligne, code in _hors_code(texte):
        if not code and ligne.startswith("## "):
            courante = trouvees.setdefault(ligne[3:].strip(), [])
        elif courante is not None:
            courante.append(ligne)
    return {titre: "\n".join(corps).strip() for titre, corps in trouvees.items()}


async def _derniere(s: AsyncSession, pipeline_id: int) -> tuple[Pipeline, Etape, Document]:
    pipeline = await s.get(Pipeline, pipeline_id)
    if pipeline is None or pipeline.type != "architecture":
        raise Refus(404, "pipeline d'architecture introuvable")
    etape = await s.scalar(
        select(Etape).where(Etape.pipeline_id == pipeline_id).order_by(Etape.ordre.desc()).limit(1)
    )
    doc = etape and await s.scalar(select(Document).where(Document.etape_id == etape.id))
    if doc is None:
        raise Refus(409, "l'architecture n'est pas encore rédigée")
    return pipeline, etape, doc


async def modele_fusionne(s: AsyncSession, catalogue: Catalogue, pipeline_id: int) -> Modele:
    """Blocs des documents validés, puis celui de la synthèse (brouillon ou validé)."""
    _, etape, doc = await _derniere(s, pipeline_id)
    blocs = [lire_bloc(d.contenu)[1] for _, d in await documents_precedents(s, etape)]
    return fusionner(blocs, lire_bloc(doc.contenu)[1])


async def assembler(s: AsyncSession, catalogue: Catalogue, pipeline_id: int) -> str:
    """Le document d'architecture complet, sans bloc JSON ; jamais stocké."""
    _, etape, doc = await _derniere(s, pipeline_id)
    precedents = await documents_precedents(s, etape)
    modele = await modele_fusionne(s, catalogue, pipeline_id)
    propres = {t: descendre_titres(c) for t, c in sections(lire_bloc(doc.contenu)[0]).items()}
    vision, volets = "", []
    for e, d in precedents:
        agent = catalogue.agents.get(e.agent)
        texte = descendre_titres(lire_bloc(d.contenu)[0].strip())
        if agent and agent.produit == "vision":
            vision = texte
        elif agent and agent.produit == "volet":
            titre = TITRES_VOLET.get(agent.volet or "", f"Architecture : {agent.volet}")
            volets.append((titre, texte))
    ordre = [
        (SOMMAIRE, propres.get(SOMMAIRE)),
        ("Vision", vision),
        *volets,
        *((titre, propres.get(brut)) for brut, titre in REGISTRES.items()),
    ]
    origine = {
        a.prefixe: "vision"
        if a.produit == "vision"
        else "synthèse"
        if a.produit == "architecture"
        else a.volet or a.nom
        for a in catalogue.agents.values()
        if a.prefixe
    }
    annexe = catalogues_markdown(modele, origine)
    morceaux = [
        f"# {n}. {titre}\n\n" + (corps if corps is not None else "section absente de la synthèse")
        for n, (titre, corps) in enumerate(ordre, 1)
    ]
    morceaux.append(f"# {len(ordre) + 1}. Annexe : catalogues\n\n{annexe}")
    return "\n\n".join(m.strip() for m in morceaux) + "\n"
