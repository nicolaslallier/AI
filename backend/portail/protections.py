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
            s = {k: d[k] for k in ("jest", "vitest") if k in d}
            scripts = d.get("scripts", {})
            if not isinstance(scripts, dict):
                raise _Illisible
            s.update({f"scripts.{k}": v for k, v in scripts.items() if "test" in k})
            return s
        if nom == "setup.cfg":
            c = configparser.ConfigParser(interpolation=None)
            c.read_string(texte)
            return {"tool:pytest": dict(c["tool:pytest"])} if c.has_section("tool:pytest") else {}
        d = tomllib.loads(texte)
    except (ValueError, configparser.Error, RecursionError) as e:
        raise _Illisible from e
    if nom == "pyproject.toml":
        p = d.get("tool", {}).get("pytest", {}) if isinstance(d.get("tool"), dict) else {}
        if not isinstance(p, dict):
            return {"tool.pytest": p}
        return {f"tool.pytest.{k}": v for k, v in p.items()}
    # Cargo.toml
    s = {k: d[k] for k in ("dev-dependencies", "test") if k in d}
    cibles = d.get("target", {})
    if isinstance(cibles, dict):
        for cible, v in cibles.items():
            if isinstance(v, dict) and "dev-dependencies" in v:
                s[f"target.{cible}.dev-dependencies"] = v["dev-dependencies"]
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
