"""Lecture des définitions d'agents Claude Code (`agents/<nom>.md`).

Le même fichier sert à Claude Code (lien dans `~/.claude/agents/`) et à ce programme :
on lit son en-tête (`name`, `description`, `tools`, `model`) et son corps (le prompt).
"""

from dataclasses import dataclass
from pathlib import Path

from claude_agent_sdk import AgentDefinition

SOUS_AGENTS = ("explorateur", "codeur", "testeur", "relecteur")
DOSSIER_AGENTS = Path(__file__).resolve().parents[2]  # agents/ du dépôt


@dataclass(frozen=True)
class DefinitionAgent:
    nom: str
    description: str
    prompt: str
    outils: list[str] | None
    modele: str | None

    def vers_sdk(self, modele: str | None = None) -> AgentDefinition:
        return AgentDefinition(
            description=self.description,
            prompt=self.prompt,
            tools=self.outils,
            model=modele or self.modele,
        )


def lire(chemin: Path) -> DefinitionAgent:
    texte = chemin.read_text(encoding="utf-8")
    lignes = texte.splitlines()
    if not lignes or lignes[0].strip() != "---":
        raise ValueError(f"{chemin} : en-tête `---` manquant")
    try:
        fin = lignes.index("---", 1)
    except ValueError:
        raise ValueError(f"{chemin} : en-tête non fermé") from None
    entete: dict[str, str] = {}
    for ligne in lignes[1:fin]:
        if not ligne.strip() or ligne.lstrip().startswith("#"):
            continue
        cle, sep, valeur = ligne.partition(":")
        if not sep:
            raise ValueError(f"{chemin} : ligne d'en-tête invalide : {ligne!r}")
        entete[cle.strip()] = valeur.strip()
    for requis in ("name", "description"):
        if not entete.get(requis):
            raise ValueError(f"{chemin} : champ `{requis}` manquant")
    if entete["name"] != chemin.stem:
        raise ValueError(f"{chemin} : `name` ({entete['name']}) différent du nom du fichier")
    outils = [o.strip() for o in entete["tools"].split(",") if o.strip()] if entete.get("tools") else None
    return DefinitionAgent(
        nom=entete["name"],
        description=entete["description"],
        prompt="\n".join(lignes[fin + 1 :]).strip(),
        outils=outils,
        modele=entete.get("model") or None,
    )


def charger(dossier: Path = DOSSIER_AGENTS) -> tuple[DefinitionAgent, dict[str, DefinitionAgent]]:
    """Renvoie l'orchestrateur et ses sous-agents."""
    orchestrateur = lire(dossier / "orchestrateur.md")
    sous_agents = {nom: lire(dossier / f"{nom}.md") for nom in SOUS_AGENTS}
    return orchestrateur, sous_agents
