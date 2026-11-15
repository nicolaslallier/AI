"""Schéma Mermaid des pipelines, généré depuis agents.yaml et recopié dans le README."""

from itertools import pairwise
from pathlib import Path

from portail.agents import Catalogue, charger_catalogue, rangement

DEBUT = "<!-- schema-pipelines:debut -->"
FIN = "<!-- schema-pipelines:fin -->"
RACINE = Path(__file__).resolve().parents[2]


def mermaid(cat: Catalogue) -> str:
    lignes = ["```mermaid", "flowchart LR"]
    for i, (nom, agents) in enumerate(rangement(cat)):
        lignes.append(f'  subgraph g{i}["{nom or "hors pipeline"}"]')
        lignes += [f'    g{i}_{a}["{a}"]' for a in agents]
        if nom is not None:
            lignes += [f"    g{i}_{x} --> g{i}_{y}" for x, y in pairwise(agents)]
        lignes.append("  end")
    return "\n".join([*lignes, "```"])


def remplacer(texte: str, bloc: str) -> str:
    debut, fin = texte.find(DEBUT), texte.find(FIN)
    if texte.count(DEBUT) != 1 or texte.count(FIN) != 1 or fin < debut:
        raise ValueError("il faut un seul marqueur schema-pipelines de début puis un de fin")
    return texte[: debut + len(DEBUT)] + "\n" + bloc + "\n" + texte[fin:]


def main() -> None:
    readme = RACINE / "README.md"
    bloc = mermaid(charger_catalogue(RACINE / "agents.yaml"))
    readme.write_text(remplacer(readme.read_text(encoding="utf-8"), bloc), encoding="utf-8")


if __name__ == "__main__":
    main()
