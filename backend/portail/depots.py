"""Clones nus (un par projet) et arbres de travail figés (un par étape), via git. Lecture seule."""

import asyncio
import base64
import contextlib
import os
import re
import shutil
from pathlib import Path


class ErreurDepot(Exception):
    pass


_SHA = re.compile(r"[0-9a-f]{40}")
_BRANCHE = re.compile(r"[A-Za-z0-9._/@+-]+")


class Depots:
    def __init__(self, donnees_dir: Path, jeton: str):
        self.racine = Path(donnees_dir)
        self.jeton = jeton
        self._verrous: dict[int, asyncio.Lock] = {}

    def _scrub(self, texte: str) -> str:
        for secret in self._secrets():
            texte = texte.replace(secret, "***")
        return texte

    def _secrets(self) -> list[str]:
        if not self.jeton:
            return []
        b64 = base64.b64encode(f"x-access-token:{self.jeton}".encode()).decode()
        return [b64, self.jeton]  # base64 d'abord : il contient le jeton encodé, pas en clair

    async def _git(
        self, *args: str, cwd: Path | None = None, delai: int = 30, distant: bool = False
    ) -> str:
        opts = []
        if distant and self.jeton:
            b64 = self._secrets()[0]
            opts = ["-c", f"http.extraHeader=Authorization: Basic {b64}"]
        env = {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
        }
        proc = await asyncio.create_subprocess_exec(
            "git",
            *opts,
            *args,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), delai)
        except BaseException as e:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
            if isinstance(e, TimeoutError):
                raise ErreurDepot(f"git {args[0]} : délai dépassé ({delai} s)") from None
            raise
        if proc.returncode != 0:
            raise ErreurDepot(self._scrub(err.decode(errors="replace").strip()) or "git a échoué")
        return out.decode(errors="replace").strip()

    def _dossier(self, etape_id: int) -> Path:
        return self.racine / "arbres" / str(etape_id)

    async def preparer(
        self,
        projet_id: int,
        depot_url: str,
        branche_ref: str | None,
        etape_id: int,
        sha: str | None,
    ) -> tuple[Path, str]:
        arbre = self._dossier(etape_id)
        if arbre.exists():
            return arbre, await self._git("rev-parse", "HEAD", cwd=arbre)
        if sha is not None and not _SHA.fullmatch(sha):
            raise ErreurDepot("SHA invalide")
        clone = self.racine / "depots" / f"{projet_id}.git"
        async with self._verrous.setdefault(projet_id, asyncio.Lock()):
            if not clone.exists():
                clone.parent.mkdir(parents=True, exist_ok=True)
                try:
                    await self._git(
                        "clone", "--bare", "--", depot_url, str(clone), delai=120, distant=True
                    )
                except BaseException:
                    shutil.rmtree(clone, ignore_errors=True)
                    raise
            await self._git(
                "fetch", "origin", "+refs/heads/*:refs/heads/*", "--prune",
                cwd=clone, delai=120, distant=True,
            )  # fmt: skip
            if sha is None:
                if branche_ref is None:
                    ref = await self._git("symbolic-ref", "HEAD", cwd=clone)
                    branche_ref = ref.removeprefix("refs/heads/")
                sha = await self._resoudre(clone, f"refs/heads/{branche_ref}", branche_ref)
            else:
                sha = await self._resoudre(clone, sha, sha, "commit")
            arbre.parent.mkdir(parents=True, exist_ok=True)
            await self._git(
                "-c", "core.hooksPath=/dev/null",
                "worktree", "add", "--detach", "--", str(arbre), sha,
                cwd=clone,
            )  # fmt: skip
        return arbre, sha

    async def _resoudre(self, clone: Path, ref: str, nom: str, genre: str = "branche") -> str:
        if ref.startswith("refs/heads/") and not (
            _BRANCHE.fullmatch(nom) and not nom.startswith("-") and ".." not in nom
        ):
            raise ErreurDepot(f"branche {nom} introuvable dans le dépôt")
        try:
            return await self._git(
                "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", cwd=clone
            )
        except ErreurDepot:
            raise ErreurDepot(f"{genre} {nom} introuvable dans le dépôt") from None

    async def liberer(self, etape_id: int) -> None:
        arbre = self._dossier(etape_id)
        if not arbre.exists():
            return
        commun = None
        try:
            commun = await self._git(
                "rev-parse", "--path-format=absolute", "--git-common-dir", cwd=arbre
            )
            await self._git("worktree", "remove", "--force", str(arbre), cwd=Path(commun))
        except ErreurDepot:
            pass
        shutil.rmtree(arbre, ignore_errors=True)
        if commun:
            try:
                await self._git("worktree", "prune", cwd=Path(commun))
            except ErreurDepot:
                pass

    async def nettoyer(self, garder: set[int]) -> None:
        arbres = self.racine / "arbres"
        if arbres.is_dir():
            for p in arbres.iterdir():
                if p.name.isdigit() and int(p.name) not in garder:
                    await self.liberer(int(p.name))
        for clone in (self.racine / "depots").glob("*.git"):
            await self._git("worktree", "prune", cwd=clone)
