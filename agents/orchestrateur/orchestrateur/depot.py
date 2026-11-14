"""Opérations git sur le dépôt cible, faites par le programme et non par les agents."""

import subprocess
from pathlib import Path


class ErreurDepot(RuntimeError):
    pass


def git(depot: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(depot), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise ErreurDepot(f"git {' '.join(args)} : {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout.strip()


def racine(chemin: Path) -> Path:
    try:
        return Path(git(chemin, "rev-parse", "--show-toplevel"))
    except (ErreurDepot, FileNotFoundError) as e:
        raise ErreurDepot(f"{chemin} n'est pas un dépôt git") from e


def branche_courante(depot: Path) -> str:
    return git(depot, "rev-parse", "--abbrev-ref", "HEAD")


def est_propre(depot: Path) -> bool:
    return git(depot, "status", "--porcelain") == ""


def preparer_branche(depot: Path, branche: str) -> str:
    """Crée `branche` depuis la branche courante et s'y place. Renvoie la branche de départ.

    Refuse un arbre de travail modifié : les agents ne doivent pas committer le travail
    en cours de quelqu'un d'autre.
    """
    if not est_propre(depot):
        raise ErreurDepot(f"{depot} a des modifications non committées : committe-les ou mets-les de côté")
    depart = branche_courante(depot)
    if depart == "HEAD":
        raise ErreurDepot(f"{depot} est en HEAD détachée : place-toi sur une branche")
    git(depot, "checkout", "-q", "-b", branche)
    return depart


def commits_depuis(depot: Path, depart: str) -> list[str]:
    sortie = git(depot, "log", "--oneline", f"{depart}..HEAD")
    return sortie.splitlines() if sortie else []


def ouvrir_pr(depot: Path, branche: str, depart: str, titre: str, corps: str) -> str:
    """Pousse la branche et ouvre une PR en brouillon avec `gh`. Renvoie l'URL."""
    git(depot, "push", "-u", "origin", branche)
    r = subprocess.run(
        ["gh", "pr", "create", "--draft", "--base", depart, "--head", branche, "--title", titre, "--body", corps],
        cwd=depot,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise ErreurDepot(f"gh pr create : {r.stderr.strip()}")
    return r.stdout.strip()
