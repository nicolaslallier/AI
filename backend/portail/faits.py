"""Faits vérifiés par du code, sans modèle : imports qui existent, affirmations prouvées par une
commande, lint. Ils précèdent le challenger, qui les reçoit tous en annexe."""

import os
import re
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select

from portail.db import CommandeLancee, Etape, Message
from portail.execution import ConfigExecution, correspond

_SORTIE_MAX = 3000


class Fait(BaseModel):
    type: Literal["reference", "affirmation", "lint", "installation"]
    role: Literal["tests", "code"]  # à qui renvoyer le travail
    bloquant: bool
    texte: str


_PYTHON = re.compile(r"^\+\s*(?:from\s+(\.*[\w.]+)\s+import|import\s+([\w.]+))")
_TS = re.compile(r"""^\+.*\bfrom\s+['"](\.{1,2}/[^'"]+)['"]""")
_EXT_TS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".vue"}
_RESOLUTIONS_TS = ("", ".ts", ".tsx", ".js", ".vue", "/index.ts")


def references_ajoutees(diff: str) -> list[tuple[str, str, str]]:
    """`(fichier, langage, cible)` des imports des lignes **ajoutées** seulement."""
    refs, fichier = [], None
    for ligne in diff.splitlines():
        if ligne.startswith("+++"):
            fichier = ligne[6:] if ligne.startswith("+++ b/") else None
            continue
        if fichier is None or not ligne.startswith("+"):
            continue
        ext = PurePosixPath(fichier).suffix
        if ext == ".py" and (m := _PYTHON.match(ligne)):
            refs.append((fichier, "python", m.group(1) or m.group(2)))
        elif ext in _EXT_TS and (m := _TS.match(ligne)):
            refs.append((fichier, "ts", m.group(1)))
    return refs


def _python_local_existe(racine: Path, module: str) -> bool | None:
    """None : module tiers (rien à vérifier ici) ; sinon, le module local existe-t-il ?"""
    segments = module.split(".")
    for base in (racine, racine / "backend", racine / "src"):
        if (base / segments[0]).is_dir() or (base / f"{segments[0]}.py").is_file():
            chemin = base.joinpath(*segments)
            # ponytail: un dossier sans __init__.py (paquet espace de noms) compte comme existant
            return (
                chemin.with_name(chemin.name + ".py").is_file()
                or (chemin / "__init__.py").is_file()
                or chemin.is_dir()
            )
    return None


def verifier_references(racine: Path, refs, cfg: ConfigExecution) -> list[Fait]:
    # ponytail: imports relatifs Python (`from .x`) et `./x.js` pour un `x.ts` non vérifiés
    faits = []
    for fichier, langage, cible in refs:
        if langage == "python":
            existe = None if cible.startswith(".") else _python_local_existe(racine, cible)
        else:
            base = os.path.normpath((racine / fichier).parent / cible)
            existe = any(Path(base + ext).is_file() for ext in _RESOLUTIONS_TS)
        if existe is False:
            role = "tests" if correspond(fichier, cfg.chemins_tests) else "code"
            faits.append(
                Fait(
                    type="reference",
                    role=role,
                    bloquant=True,
                    texte=f"import {cible} introuvable dans {fichier}",
                )
            )
    return faits


AFFIRMATIONS = {
    r"tests? (?:passent|réussissent|sont verts)|all tests pass|tests pass": {
        "tests",
        "tests_cibles",
    },
    r"lint (?:ok|passe)": {"lint"},
    r"build (?:ok|passe|réussit)": {"build"},
}
_NEGATION = re.compile(r"\bne\b.*\bpas\b|\bn['’].*\bpas\b|\bnot\b|\bdon['’]t\b", re.IGNORECASE)


def verifier_affirmations(
    texte: str, commandes: list[CommandeLancee], role: Literal["tests", "code"]
) -> list[Fait]:
    """Chaque affirmation exige que la dernière des commandes qui la prouvent ait réussi."""
    faits = []
    for motif, noms in AFFIRMATIONS.items():
        for m in re.finditer(motif, texte, re.IGNORECASE):
            if _NEGATION.search(texte[max(0, m.start() - 30) : m.start()]):
                continue
            preuves = [c for c in commandes if c.nom in noms]
            if not preuves or preuves[-1].code != 0:
                faits.append(
                    Fait(
                        type="affirmation",
                        role=role,
                        bloquant=True,
                        texte=f"affirmation « {m.group(0)} » sans commande qui la prouve",
                    )
                )
                break  # une seule fois par motif
    return faits


def fait_lint(code: int | None, sortie: str, lint_base_ok: bool | None) -> Fait:
    """Bloquant seulement si le lint passait sur la base : sinon, une dette existante."""
    fin = sortie[-_SORTIE_MAX:]
    if lint_base_ok:
        return Fait(
            type="lint",
            role="code",
            bloquant=True,
            texte=f"le lint échoue sur ce travail (il passait sur la base) :\n{fin}",
        )
    return Fait(
        type="lint",
        role="code",
        bloquant=False,
        texte=f"le lint échoue, mais déjà sur la base (dette existante) :\n{fin}",
    )


async def verifier_faits(
    sessions, pipeline_id, racine, cfg, diff, lint, lint_base_ok
) -> list[Fait]:
    """Références du diff, affirmations des dernières étapes `tests` et `code`, et `lint`
    (le résultat de la commande, ou None si non déclaré)."""
    faits = verifier_references(racine, references_ajoutees(diff), cfg)
    async with sessions() as s:
        for role in ("tests", "code"):
            etape = await s.scalar(
                select(Etape.id)
                .where(Etape.pipeline_id == pipeline_id, Etape.agent == role)
                .order_by(Etape.ordre.desc())
                .limit(1)
            )
            if etape is None:
                continue
            message = await s.scalar(
                select(Message.contenu)
                .where(Message.etape_id == etape, Message.role == "assistant")
                .order_by(Message.id.desc())
                .limit(1)
            )
            commandes = list(
                await s.scalars(
                    select(CommandeLancee)
                    .where(CommandeLancee.etape_id == etape)
                    .order_by(CommandeLancee.id)
                )
            )
            faits += verifier_affirmations(message or "", commandes, role)
    if lint is not None and lint.code != 0:
        faits.append(fait_lint(lint.code, lint.sortie, lint_base_ok))
    return faits
