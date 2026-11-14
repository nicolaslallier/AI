"""Espace de travail git d'une tâche (`/espaces/<espace>`), manipulé par le portail seul."""

import asyncio
import os
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
    """git ne descend jamais dans un sous-module. Un dépôt imbriqué non suivi, ou un gitlink
    de l'index dont le dossier contient un `.git`, apparaît dans `changements` ; `restaurer`
    et `remettre_a_zero` suppriment le premier et le `.git` du second. `commiter` refuse
    (`ErreurDepot`, avant tout `add`) un gitlink peuplé, et tout gitlink nouveau ou modifié
    par rapport à `HEAD`. Le push ne va
    qu'à l'URL du clone (`depot_url`), jamais à `origin` lu dans `.git/config`."""

    def __init__(self, racine: Path, depot_url: str | None = None):
        self.racine = Path(racine)
        self.depot_url = depot_url

    async def _git(self, *args: str, **kw) -> str:
        return await git(*args, cwd=self.racine, **kw)

    async def _branche(self, nom: str) -> str:
        await git("check-ref-format", "--branch", _rev(nom), cwd=None)
        return nom

    async def cloner(self, depot_url: str, jeton: str, base: str, branche: str) -> str:
        base, branche = await self._branche(base), await self._branche(branche)
        await self.supprimer()
        self.depot_url = depot_url
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
            "status",
            "--porcelain",
            "-z",
            "--untracked-files=all",
            "--no-renames",
            "--ignore-submodules=all",
        )
        return [(e[:2] != "??", e[3:].rstrip("/")) for e in sortie.split("\0") if e]

    async def _sous_modules_peuples(self) -> list[str]:
        """Gitlinks de l'index dont le dossier contient un `.git` (dossier, fichier ou lien) :
        `add` y lancerait un `git status` avec la config de ce dépôt (filtres…)."""
        liens = await self._gitlinks("ls-files", "-s", "-z")
        return sorted(c for c, _ in liens if os.path.lexists(self.racine / c / ".git"))

    def _effacer(self, chemin: str) -> None:
        """Supprime `chemin` sans suivre de lien, confiné à l'espace."""
        p = self.racine.resolve() / chemin
        if p.parent.resolve() != p.parent:  # parent hors de l'espace ou via un lien
            raise ErreurDepot(f"chemin hors de l'espace : {chemin}")
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        else:
            p.unlink(missing_ok=True)

    def _vider_sous_modules(self, chemins: list[str]) -> list[str]:
        """Efface le `.git` de chaque gitlink peuplé ; si un composant du chemin est un lien,
        efface le plus haut (le lien lui-même, rien de ce qu'il vise). Rend ces liens."""
        liens = []
        for c in chemins:
            courant = self.racine
            for partie in Path(c).parts:
                courant = courant / partie
                if courant.is_symlink():
                    courant.unlink()
                    liens.append(courant.relative_to(self.racine).as_posix())
                    break
            else:
                self._effacer(f"{c}/.git")
        return liens

    async def changements(self) -> list[str]:
        chemins = [chemin for _, chemin in await self._statut()]
        return chemins + [c for c in await self._sous_modules_peuples() if c not in chemins]

    async def restaurer(self, garder: Callable[[str], bool]) -> list[str]:
        peuples = await self._sous_modules_peuples()
        # toujours : `commiter` les refuserait de toute façon ; un dossier suivi remplacé par
        # un lien est restauré, pour ne jamais perdre en silence le gitlink livré
        if liens := self._vider_sous_modules(peuples):
            await self._git("checkout", "--", *liens)
        annules = [(suivi, c) for suivi, c in await self._statut() if not garder(c)]
        # non suivis d'abord : un lien posé à la place d'un dossier suivi disparaît avant checkout
        for suivi, chemin in annules:
            if not suivi:
                self._effacer(chemin)
        suivis = [c for suivi, c in annules if suivi]
        if suivis:
            await self._git("checkout", "--", *suivis)
        return [c for _, c in annules] + peuples

    async def remettre_a_zero(self) -> None:
        self._vider_sous_modules(await self._sous_modules_peuples())
        await self._git("reset", "--hard", "HEAD")
        await self._git("clean", "-ffd")  # -ff : dépôts imbriqués aussi ; sans -x : ignorés gardés

    async def commiter(self, nom: str, courriel: str, message: str) -> str | None:
        if peuples := await self._sous_modules_peuples():
            raise ErreurDepot("dépôt imbriqué refusé : " + ", ".join(peuples))
        await self._git("add", "-A")
        nouveaux = await self._gitlinks("ls-files", "-s", "-z") - await self._gitlinks(
            "ls-tree", "-r", "-z", "HEAD"
        )
        if nouveaux:
            await self._git("reset", "-q")
            raise ErreurDepot(
                "dépôt imbriqué refusé : " + ", ".join(sorted(c for c, _ in nouveaux))
            )
        if not (await self._git("diff", "--cached", "--name-only", *_SANS_EXTERNE)).strip():
            return None
        await self._git(
            "-c", f"user.name={nom}", "-c", f"user.email={courriel}",
            "commit", "--no-verify", "-m", message,
        )  # fmt: skip
        return (await self._git("rev-parse", "HEAD")).strip()

    async def _gitlinks(self, *args: str) -> set[tuple[str, str]]:
        """(chemin, sha) des gitlinks listés par `ls-files -s` ou `ls-tree`."""
        liens = set()
        for e in (await self._git(*args)).split("\0"):
            meta, _, chemin = e.partition("\t")
            if meta.startswith("160000"):
                liens.add((chemin, meta.split()[1 if args[0] == "ls-files" else 2]))
        return liens

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
        sortie = await self._git(
            "diff", *_SANS_EXTERNE, "--ignore-submodules=all", _rev(depuis), "HEAD", "--"
        )
        if len(sortie) > _DIFF_MAX:
            return sortie[:_DIFF_MAX] + "\n[… diff tronqué]"
        return sortie

    async def pousser(self, jeton: str, branche: str) -> None:
        ref = f"refs/heads/{await self._branche(branche)}"
        if not self.depot_url:
            raise ErreurDepot("URL du dépôt inconnue pour cet espace")
        await self._git(
            "push", "--", self.depot_url, f"{ref}:{ref}", jeton=jeton, delai=120, distant=True
        )

    async def supprimer(self) -> None:
        if self.racine.is_symlink():
            self.racine.unlink()
        elif self.racine.exists():
            await asyncio.to_thread(shutil.rmtree, self.racine)
