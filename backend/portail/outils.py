"""Outils en lecture seule confinés à l'arbre d'une étape, et aperçu du dépôt pour l'agent."""

import asyncio
import contextlib
import fnmatch
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


def _secret(nom: str) -> bool:
    return any(fnmatch.fnmatchcase(nom, p) for p in _SECRETS)


class _Interdit(Exception):
    pass


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
        brut = Path(chemin)
        if brut.is_absolute() or ".git" in brut.parts:
            raise _Interdit
        resolu = (self.racine / brut).resolve()
        try:
            rel = resolu.relative_to(self.racine)
        except ValueError:
            raise _Interdit from None
        if ".git" in rel.parts:
            raise _Interdit
        return resolu

    def lister(self, chemin: str = ".") -> str:
        try:
            base = self._resoudre(chemin)
        except _Interdit:
            return "erreur : chemin interdit"
        if not base.is_dir():
            return "erreur : dossier introuvable"
        entrees: list[str] = []

        def parcourir(dossier: Path, profondeur: int) -> bool:
            for e in sorted(os.scandir(dossier), key=lambda e: e.name):
                if e.name == ".git" or _secret(e.name):
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
        if _secret(fichier.name):
            return "erreur : fichier secret refusé"
        if not fichier.is_file():
            return "erreur : fichier introuvable"
        octets = fichier.read_bytes()
        if b"\0" in octets[:8192]:
            return "erreur : fichier binaire"
        lignes = octets.decode(errors="replace").splitlines()
        total = len(lignes)
        a = max(debut or 1, 1) - 1
        b = fin if fin is not None else total
        choisies = lignes[a:b]
        tronque = len(choisies) > _MAX_LIGNES
        corps = "\n".join(choisies[:_MAX_LIGNES])
        marqueur = f"[… tronqué : {total} lignes au total]"
        reserve = len(marqueur.encode()) + 1
        if len(corps.encode()) + (reserve if tronque else 0) > _MAX_OCTETS:
            tronque = True
            corps = corps.encode()[: _MAX_OCTETS - reserve].decode(errors="ignore")
        return corps + ("\n" + marqueur if tronque else "")

    async def chercher(self, motif: str, chemin: str | None = None) -> str:
        try:
            cible = self._resoudre(chemin or ".")
        except _Interdit:
            return "erreur : chemin interdit"
        rel = cible.relative_to(self.racine).as_posix()
        exclusions = [f":(exclude,glob)**/{p}" for p in _SECRETS]
        env = {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
        }
        proc = await asyncio.create_subprocess_exec(
            "git", "grep", "-n", "-I", "-E", "--no-color", "-e", motif, "--", rel, *exclusions,
            cwd=self.racine,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )  # fmt: skip
        try:
            out, err = await asyncio.wait_for(proc.communicate(), _DELAI_GREP)
        except BaseException as e:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
            if isinstance(e, TimeoutError):
                return f"erreur : recherche trop longue (délai de {_DELAI_GREP} s dépassé)"
            raise
        if proc.returncode == 1:
            return "aucun résultat"
        if proc.returncode != 0:
            return "erreur : motif invalide : " + err.decode(errors="replace").strip()
        lignes = out.decode(errors="replace").splitlines()
        gardees = [ligne[:_MAX_LIGNE_RESULTAT] for ligne in lignes[:_MAX_RESULTATS]]
        if len(lignes) > _MAX_RESULTATS:
            gardees.append(f"[… {len(lignes)} résultats au total]")
        return "\n".join(gardees)

    async def executer(self, nom: str, arguments: str) -> tuple[str, bool]:
        try:
            args = json.loads(arguments or "{}")
        except ValueError:
            return "erreur : arguments JSON invalides", True
        if nom not in SCHEMAS_OUTILS or not isinstance(args, dict):
            return f"erreur : outil inconnu ou arguments invalides : {nom}", True
        try:
            if nom == "chercher":
                return await self.chercher(**args), False
            return getattr(self, nom)(**args), False
        except TypeError:
            return f"erreur : arguments manquants ou inattendus pour {nom}", True


def apercu(racine: Path, budget_jetons: int) -> str:
    racine = Path(racine)
    blocs = [("## Arborescence", OutilsDepot(racine).lister("."))]
    noms = sorted(p.name for p in racine.glob("README*"))
    noms += ["CLAUDE.md", "AGENTS.md", "pyproject.toml", "package.json", "Cargo.toml"]
    for nom in noms:
        f = racine / nom
        if f.is_file() and not f.is_symlink():
            blocs.append((f"### {nom}", f.read_text(errors="replace")))
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
