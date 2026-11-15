"""Troisième protection : les commits de l'agent de code ne touchent jamais aux tests."""

import configparser
import json
import re
import tomllib
from posixpath import basename

from portail.espace import Espace
from portail.execution import ConfigExecution, correspond

COURRIEL_CODE = "agent-code@portail.local"
COURRIEL_DOC = "agent-doc@portail.local"


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
            # `options` (entry_points, `file:`…) et `options.entry_points` peuvent déclarer un
            # plugin pytest11 chargé à chaque lancement : protégés en entier
            sections = ("tool:pytest", "options", "options.entry_points")
            return {k: dict(c[k]) for k in sections if c.has_section(k)}
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
        # ponytail: entry points, champs dynamiques (`file:`) et config du backend de build
        # protégés en entier — l'agent de code n'y touche presque jamais
        if isinstance(outil, dict) and "setuptools" in outil:
            s["tool.setuptools"] = outil["setuptools"]
        if "build-system" in d:
            s["build-system"] = d["build-system"]
        projet = d.get("project")
        if isinstance(projet, dict):
            for cle in ("entry-points", "dynamic"):
                if cle in projet:
                    s[f"project.{cle}"] = projet[cle]
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

# sections protégées de `_sections`, vues comme en-têtes TOML ou INI
_EN_TETES_DE_TEST = (
    "tool.pytest*", "tool.coverage*", "tool.setuptools*", "build-system", "project.entry-points*",
    "dev-dependencies", "dev_dependencies", "test", "profile.test", "target.*.dev-dependencies",
    "target.*.dev_dependencies", "tool:pytest", "options*",
)  # fmt: skip
_CLES_JSON_DE_TEST = {"scripts", "jest", "vitest", "mocha", "ava", "c8", "nyc"}
_EN_TETE = re.compile(r"\s*\[\[?\s*([^\]]+?)\s*\]")
_DEUX_POINTS = re.compile(r"\s*:")


def _cle_json(texte: str, ligne: int) -> str | None:
    """Clé de premier niveau dont la valeur contient `ligne` (1 = première ligne)."""
    cle, profondeur, n, i, debut = None, 0, 1, 0, None
    while i < len(texte):
        c = texte[i]
        if debut is not None:  # dans une chaîne (jamais de saut de ligne brut en JSON)
            if c == "\\":
                i += 1
            elif c == '"':
                if profondeur == 1 and _DEUX_POINTS.match(texte, i + 1):
                    if n > ligne:
                        break
                    cle = texte[debut + 1 : i]  # brute : les clés cherchées sont sans échappement
                debut = None
        elif c == '"':
            debut = i
        elif c in "{[":
            profondeur += 1
        elif c in "}]":
            profondeur -= 1
        elif c == "\n":
            n += 1
        i += 1
    return cle


def section_de_test(nom: str, texte: str, ligne: int) -> bool:
    """La ligne `ligne` d'un manifeste est-elle dans une section de tests protégée ?"""
    # ponytail: repérage par en-têtes ; une section manquée est quand même refusée par la
    # troisième protection (échec de la reprise)
    if nom == "package.json":
        return _cle_json(texte, ligne) in _CLES_JSON_DE_TEST
    section = None
    for brute in texte.splitlines()[:ligne]:
        if m := _EN_TETE.match(brute):
            section = m.group(1)
    return section is not None and correspond(section, _EN_TETES_DE_TEST)


async def verifier_commits_code(espace: Espace, depuis: str, cfg: ConfigExecution) -> list[str]:
    """Violations (texte lisible) dans les commits de l'agent de code depuis `depuis`."""
    violations: list[str] = []
    for sha, auteur, fichiers in await espace.commits(depuis):
        if auteur == COURRIEL_DOC:
            violations += [
                f"{f} (hors des chemins de doc)"
                for f in fichiers
                if not correspond(f, cfg.chemins_doc) or correspond(f, cfg.protege)
            ]
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
