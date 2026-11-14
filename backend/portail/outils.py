"""Outils en lecture seule confinés à l'arbre d'une étape, et aperçu du dépôt pour l'agent."""

import asyncio
import contextlib
import fnmatch
import inspect
import json
import os
from pathlib import Path

from portail.contexte import estimer_jetons

_SECRETS = [".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*"]
_MAX_ENTREES = 300
_MAX_LIGNES = 2000
_MAX_OCTETS = 100_000
_MAX_RESULTATS = 100
_MAX_LIGNE_RESULTAT = 500
_DELAI_GREP = 30
_MAX_SORTIE_GREP = 1_000_000
_MARGE_COMPTE = 900  # lignes lues au-delà de 100 pour estimer le total
_LECTURE_MAX = 2_000_000  # ponytail: au-delà, lire/apercu ne voient que ce début de fichier


def _secret(nom: str) -> bool:
    nom = nom.casefold()
    return any(fnmatch.fnmatchcase(nom, p) for p in _SECRETS)


def _secret_chemin(parties: tuple[str, ...]) -> bool:
    return any(_secret(p) for p in parties)


def _est_git(parties: tuple[str, ...]) -> bool:
    return any(p.casefold() == ".git" for p in parties)


class _Interdit(Exception):
    pass


def _debut_fichier(fichier: Path, n: int) -> tuple[bytes, bool]:
    """Au plus n premiers octets, et True si le fichier est plus long."""
    with fichier.open("rb") as f:
        octets = f.read(n + 1)
    return octets[:n], len(octets) > n


def _fonction(nom: str, description: str, proprietes: dict, requis: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": nom,
            "description": description,
            "parameters": {"type": "object", "properties": proprietes, "required": requis},
        },
    }


SCHEMAS_OUTILS: dict[str, dict] = {
    "lister": _fonction(
        "lister",
        "Liste les fichiers et dossiers du dépôt sur deux niveaux (300 entrées au plus).",
        {
            "chemin": {
                "type": "string",
                "description": "Dossier relatif à la racine, « . » par défaut.",
            }
        },
        [],
    ),
    "lire": _fonction(
        "lire",
        "Lit un fichier texte du dépôt (2000 lignes au plus). Utiliser debut et fin (numéros de "
        "ligne, à partir de 1) pour lire une plage.",
        {
            "chemin": {"type": "string", "description": "Fichier relatif à la racine."},
            "debut": {"type": "integer", "description": "Première ligne à lire."},
            "fin": {"type": "integer", "description": "Dernière ligne à lire."},
        },
        ["chemin"],
    ),
    "chercher": _fonction(
        "chercher",
        "Cherche une expression régulière étendue dans les fichiers texte du dépôt "
        "(100 résultats au plus, au format fichier:ligne:texte).",
        {
            "motif": {"type": "string", "description": "Expression régulière (POSIX étendue)."},
            "chemin": {"type": "string", "description": "Dossier ou fichier où chercher."},
        },
        ["motif"],
    ),
}


class OutilsDepot:
    def __init__(self, racine: Path):
        self.racine = Path(racine).resolve()

    def _resoudre(self, chemin: str) -> Path:
        if not isinstance(chemin, str):
            raise _Interdit
        brut = Path(chemin)
        if brut.is_absolute() or _est_git(brut.parts):
            raise _Interdit
        try:
            resolu = (self.racine / brut).resolve()
        except (ValueError, OSError):
            raise _Interdit from None
        try:
            rel = resolu.relative_to(self.racine)
        except ValueError:
            raise _Interdit from None
        if _est_git(rel.parts):
            raise _Interdit
        return resolu

    def lister(self, chemin: str = ".") -> str:
        try:
            base = self._resoudre(chemin)
        except _Interdit:
            return "erreur : chemin interdit"
        if _secret_chemin(base.relative_to(self.racine).parts):
            return "erreur : fichier secret refusé"
        if not base.is_dir():
            return "erreur : dossier introuvable"
        entrees: list[str] = []

        def parcourir(dossier: Path, profondeur: int) -> bool:
            for e in sorted(os.scandir(dossier), key=lambda e: e.name):
                if e.name.casefold() == ".git" or _secret(e.name):
                    continue
                if len(entrees) >= _MAX_ENTREES:
                    return False
                est_dossier = e.is_dir(follow_symlinks=False)
                rel = Path(e.path).relative_to(self.racine).as_posix()
                entrees.append(rel + "/" if est_dossier else rel)
                if est_dossier and profondeur < 2 and not parcourir(Path(e.path), profondeur + 1):
                    return False
            return True

        complet = parcourir(base, 1)
        texte = "\n".join(entrees) or "(vide)"
        if not complet:
            texte += f"\n[… liste tronquée à {_MAX_ENTREES} entrées]"
        return texte

    def lire(self, chemin: str, debut: int | None = None, fin: int | None = None) -> str:
        try:
            fichier = self._resoudre(chemin)
        except _Interdit:
            return "erreur : chemin interdit"
        if _secret_chemin(fichier.relative_to(self.racine).parts):
            return "erreur : fichier secret refusé"
        if not fichier.is_file():
            return "erreur : fichier introuvable"
        for v in (debut, fin):
            if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
                return "erreur : debut et fin doivent être des entiers"
        octets, partiel = _debut_fichier(fichier, _LECTURE_MAX)
        if b"\0" in octets[:8192]:
            return "erreur : fichier binaire"
        lignes = octets.decode(errors="replace").split("\n")
        if lignes[-1] == "" and not partiel:
            lignes.pop()
        total = len(lignes)
        a = max(debut or 1, 1) - 1
        b = fin if fin is not None else total
        choisies = lignes[a:b]
        tronque = len(choisies) > _MAX_LIGNES or partiel
        corps = "\n".join(choisies[:_MAX_LIGNES])
        marqueur = f"[… tronqué : {'au moins ' if partiel else ''}{total} lignes au total]"
        reserve = len(marqueur.encode()) + 1
        if len(corps.encode()) + (reserve if tronque else 0) > _MAX_OCTETS:
            tronque = True
            corps = corps.encode()[: _MAX_OCTETS - reserve].decode(errors="ignore")
        return corps + ("\n" + marqueur if tronque else "")

    async def chercher(self, motif: str, chemin: str | None = None) -> str:
        if not isinstance(motif, str):
            return "erreur : motif invalide : du texte est attendu"
        try:
            cible = self._resoudre(chemin or ".")
        except _Interdit:
            return "erreur : chemin interdit"
        rel = cible.relative_to(self.racine).as_posix()
        spec = "." if rel == "." else f":(literal){rel}"
        exclusions = [
            f":(exclude,glob,icase)**/{p}{suffixe}" for p in _SECRETS for suffixe in ("", "/**")
        ]
        env = {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
        }
        proc = await asyncio.create_subprocess_exec(
            "git", "grep", "-n", "-I", "-E", "--no-color", "-e", motif, "--", spec, *exclusions,
            cwd=self.racine,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=_MAX_SORTIE_GREP,
        )  # fmt: skip

        tache_err = asyncio.ensure_future(proc.stderr.read())

        async def lire_sortie() -> tuple[list[bytes], bool, bytes]:
            lignes: list[bytes] = []
            octets = 0
            while True:
                try:
                    ligne = await proc.stdout.readline()
                except ValueError:  # ligne de plus de 1 Mo
                    return lignes, True, b""
                if not ligne:
                    break
                lignes.append(ligne)
                octets += len(ligne)
                if len(lignes) > _MAX_RESULTATS + _MARGE_COMPTE or octets > _MAX_SORTIE_GREP:
                    return lignes, True, b""
            await proc.wait()
            return lignes, False, await tache_err

        try:
            brutes, coupe, err = await asyncio.wait_for(lire_sortie(), _DELAI_GREP)
        except TimeoutError:
            return f"erreur : recherche trop longue (délai de {_DELAI_GREP} s dépassé)"
        finally:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
            tache_err.cancel()
        if not coupe and proc.returncode == 1:
            return "aucun résultat"
        if not coupe and proc.returncode != 0:
            msg = err.decode(errors="replace").strip()[:300]
            if proc.returncode == 128 and ("command line" in msg or "-e option" in msg):
                return "erreur : motif invalide : " + msg
            return "erreur : git grep : " + msg
        lignes = [b.decode(errors="replace").rstrip("\n") for b in brutes]
        gardees = [ligne[:_MAX_LIGNE_RESULTAT] for ligne in lignes[:_MAX_RESULTATS]]
        if coupe:
            gardees.append(
                f"[… plus de {len(lignes)} résultats]" if lignes else "[… résultats tronqués]"
            )
        elif len(lignes) > _MAX_RESULTATS:
            gardees.append(f"[… {len(lignes)} résultats au total]")
        return "\n".join(gardees)

    async def executer(self, nom: str, arguments: str) -> tuple[str, bool]:
        try:
            args = json.loads(arguments or "{}")
        except (ValueError, RecursionError):
            return "erreur : arguments JSON invalides", True
        if nom not in SCHEMAS_OUTILS or not isinstance(args, dict):
            return f"erreur : outil inconnu ou arguments invalides : {nom}", True
        fn = getattr(self, nom)
        try:
            inspect.signature(fn).bind(**args)
        except TypeError:
            return f"erreur : arguments manquants ou inattendus pour {nom}", True
        try:
            if nom == "chercher":
                return await self.chercher(**args), False
            return getattr(self, nom)(**args), False
        except (ValueError, OSError) as e:
            return f"erreur : {e}", False


def apercu(racine: Path, budget_jetons: int) -> str:
    racine = Path(racine)
    blocs = [("## Arborescence", OutilsDepot(racine).lister("."))]
    noms = sorted(p.name for p in racine.glob("README*"))
    noms += ["CLAUDE.md", "AGENTS.md", "pyproject.toml", "package.json", "Cargo.toml"]
    for nom in noms:
        f = racine / nom
        if f.is_file() and not f.is_symlink():
            octets, _ = _debut_fichier(f, budget_jetons * 4)
            blocs.append((f"### {nom}", octets.decode(errors="replace")))
    texte = ""
    marqueur = "\n[… tronqué]"
    for titre, contenu in blocs:
        sep = "\n\n" if texte else ""
        bloc = f"{titre}\n{contenu}"
        if estimer_jetons([{"content": texte + sep + bloc}]) <= budget_jetons:
            texte += sep + bloc
            continue
        # len // 4 + 4 <= budget  <=>  len <= (budget - 4) * 4 + 3
        place = (budget_jetons - 4) * 4 + 3 - len(texte + sep) - len(marqueur)
        if place > len(titre) + 1:
            texte += sep + bloc[:place] + marqueur
        break
    return texte
