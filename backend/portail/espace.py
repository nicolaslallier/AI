"""Espace de travail git d'une tâche (`/espaces/<espace>`), manipulé par le portail seul."""

import asyncio
import shutil
from collections.abc import Callable
from pathlib import Path

from portail.depots import ErreurDepot, git
from portail.outils import EXCLUSIONS

_DIFF_MAX = 200_000
_SANS_EXTERNE = ("--no-ext-diff", "--no-textconv")


def _rev(rev: str) -> str:
    if not rev or rev.startswith("-") or any(c in rev for c in "\0\n"):
        raise ErreurDepot(f"référence invalide : {rev!r}")
    return rev


class Espace:
    def __init__(self, racine: Path):
        self.racine = Path(racine)

    async def _git(self, *args: str, **kw) -> str:
        return await git(*args, cwd=self.racine, **kw)

    async def _branche(self, nom: str) -> str:
        await git("check-ref-format", "--branch", _rev(nom), cwd=None)
        return nom

    async def cloner(self, depot_url: str, jeton: str, base: str, branche: str) -> str:
        base, branche = await self._branche(base), await self._branche(branche)
        await self.supprimer()
        self.racine.parent.mkdir(parents=True, exist_ok=True)
        try:
            await git(
                "clone", "--branch", base, "--single-branch", "--", depot_url, str(self.racine),
                cwd=None, jeton=jeton, delai=120, distant=True,
            )  # fmt: skip
        except BaseException:
            await self.supprimer()
            raise
        await self._git("checkout", "-b", branche)
        info = self.racine / ".git" / "info"
        info.mkdir(exist_ok=True)
        (info / "exclude").write_text("\n".join(EXCLUSIONS) + "\n")
        return (await self._git("rev-parse", "HEAD")).strip()

    async def _statut(self) -> list[tuple[bool, str]]:
        """(suivi, chemin) de chaque changement ; les ignorés n'y sont pas."""
        sortie = await self._git(
            "status", "--porcelain", "-z", "--untracked-files=all", "--no-renames"
        )
        return [(e[:2] != "??", e[3:].rstrip("/")) for e in sortie.split("\0") if e]

    async def changements(self) -> list[str]:
        return [chemin for _, chemin in await self._statut()]

    async def restaurer(self, garder: Callable[[str], bool]) -> list[str]:
        annules = [(suivi, c) for suivi, c in await self._statut() if not garder(c)]
        racine = self.racine.resolve()
        # non suivis d'abord : un lien posé à la place d'un dossier suivi disparaît avant checkout
        for suivi, chemin in annules:
            if suivi:
                continue
            p = racine / chemin
            if p.parent.resolve() != p.parent:  # parent hors de l'espace ou via un lien
                raise ErreurDepot(f"chemin hors de l'espace : {chemin}")
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p)  # dépôt imbriqué, listé comme dossier
            else:
                p.unlink(missing_ok=True)
        suivis = [c for suivi, c in annules if suivi]
        if suivis:
            await self._git("checkout", "--", *suivis)
        return [c for _, c in annules]

    async def remettre_a_zero(self) -> None:
        await self._git("reset", "--hard", "HEAD")
        await self._git("clean", "-fd")  # sans -x : les ignorés restent

    async def commiter(self, nom: str, courriel: str, message: str) -> str | None:
        await self._git("add", "-A")
        if not (await self._git("diff", "--cached", "--name-only", *_SANS_EXTERNE)).strip():
            return None
        await self._git(
            "-c", f"user.name={nom}", "-c", f"user.email={courriel}",
            "commit", "--no-verify", "-m", message,
        )  # fmt: skip
        return (await self._git("rev-parse", "HEAD")).strip()

    async def commits(self, depuis: str) -> list[tuple[str, str, list[str]]]:
        shas = (await self._git("rev-list", "--reverse", f"{_rev(depuis)}..HEAD", "--")).split()
        resultat = []
        for sha in shas:
            auteur = (await self._git("show", "-s", "--format=%ae", sha)).strip()
            fichiers = await self._git(
                "diff-tree", "-r", "-z", "--name-only", "--no-renames", "--no-commit-id",
                "--root", *_SANS_EXTERNE, sha,
            )  # fmt: skip
            resultat.append((sha, auteur, [f for f in fichiers.split("\0") if f]))
        return resultat

    async def fichier_a(self, rev: str, chemin: str) -> str | None:
        objet = f"{_rev(rev)}:{chemin}"
        try:
            return await self._git("cat-file", "blob", objet)
        except ErreurDepot:
            return None

    async def diff(self, depuis: str) -> str:
        sortie = await self._git("diff", *_SANS_EXTERNE, _rev(depuis), "HEAD", "--")
        return sortie[:_DIFF_MAX]

    async def pousser(self, jeton: str, branche: str) -> None:
        ref = f"refs/heads/{await self._branche(branche)}"
        await self._git("push", "origin", f"{ref}:{ref}", jeton=jeton, delai=120, distant=True)

    async def supprimer(self) -> None:
        if self.racine.is_symlink():
            self.racine.unlink()
        elif self.racine.exists():
            await asyncio.to_thread(shutil.rmtree, self.racine)
