"""Troisième protection : les commits de l'agent de code ne touchent jamais aux tests."""

import configparser
import json
import tomllib
from posixpath import basename

from portail.espace import Espace
from portail.execution import ConfigExecution, correspond

COURRIEL_CODE = "agent-code@portail.local"


class _Illisible(Exception):
    pass


def _sections(nom: str, texte: str | None) -> dict[str, object]:
    """Sections de tests d'un manifeste ; un fichier absent n'en a aucune."""
    if texte is None:
        return {}
    try:
        if nom == "package.json":
            d = json.loads(texte)
            if not isinstance(d, dict):
                raise _Illisible
            s = {k: d[k] for k in ("jest", "vitest", "mocha", "ava", "c8", "nyc") if k in d}
            if "scripts" in d:  # un script de test peut en appeler un autre : tout est protégé
                s["scripts"] = d["scripts"]
            return s
        if nom == "setup.cfg":
            c = configparser.ConfigParser(interpolation=None)
            c.read_string(texte)
            return {"tool:pytest": dict(c["tool:pytest"])} if c.has_section("tool:pytest") else {}
        d = tomllib.loads(texte)
    except (ValueError, configparser.Error, RecursionError) as e:
        raise _Illisible from e
    if nom == "pyproject.toml":
        s = {}
        outil = d.get("tool")
        for cle in ("pytest", "coverage"):
            v = outil.get(cle, {}) if isinstance(outil, dict) else {}
            if isinstance(v, dict):
                s.update({f"tool.{cle}.{k}": x for k, x in v.items()})
            else:
                s[f"tool.{cle}"] = v
        projet = d.get("project")
        ep = projet.get("entry-points") if isinstance(projet, dict) else None
        if isinstance(ep, dict) and "pytest11" in ep:
            s["project.entry-points.pytest11"] = ep["pytest11"]
        return s

    # Cargo.toml : `_` et `-` sont équivalents pour cargo ; chaque graphie est sa propre
    # section (les fusionner laisserait l'une des deux changer sans être vue)
    dev = ("dev-dependencies", "dev_dependencies")
    s = {k: d[k] for k in (*dev, "test") if k in d}
    if isinstance(d.get("profile"), dict) and "test" in d["profile"]:
        s["profile.test"] = d["profile"]["test"]
    cibles = d.get("target", {})
    if isinstance(cibles, dict):
        for cible, v in cibles.items():
            if isinstance(v, dict):
                s.update({f"target.{cible}.{k}": v[k] for k in dev if k in v})
    return s


MANIFESTES = ("pyproject.toml", "package.json", "Cargo.toml", "setup.cfg")


async def verifier_commits_code(espace: Espace, depuis: str, cfg: ConfigExecution) -> list[str]:
    """Violations (texte lisible) dans les commits de l'agent de code depuis `depuis`."""
    violations: list[str] = []
    for sha, auteur, fichiers in await espace.commits(depuis):
        if auteur != COURRIEL_CODE:
            continue
        for f in fichiers:
            if correspond(f, cfg.protege):
                violations.append(f"{f} (fichier de tests)")
            nom = basename(f)
            if nom not in MANIFESTES:
                continue
            try:
                avant = _sections(nom, await espace.fichier_a(f"{sha}^", f))
                apres = _sections(nom, await espace.fichier_a(sha, f))
            except _Illisible:
                violations.append(f"{f} (illisible)")
                continue
            for cle in sorted(avant.keys() | apres.keys()):
                if avant.get(cle) != apres.get(cle):
                    violations.append(f"{f} (section {cle})")
    return violations
