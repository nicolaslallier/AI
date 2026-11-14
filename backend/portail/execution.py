"""Configuration d'exécution d'un projet : image, commandes nommées, motifs protégés."""

import re
import shlex
from collections.abc import Sequence
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from portail.moteur import Refus

CONFIG_TESTS_DEFAUT = [
    "**/conftest.py",
    "pytest.ini",
    "**/pytest.ini",
    ".pytest.ini",
    "**/.pytest.ini",
    "tox.ini",
    "**/tox.ini",
    "jest.config.*",
    "**/jest.config.*",
    "vitest.config.*",
    "**/vitest.config.*",
    "vitest.workspace.*",
    "**/vitest.workspace.*",
    "vite.config.*",  # vitest y lit la section `test:` faute de vitest.config
    "**/vite.config.*",
    ".cargo/config.toml",
    # exécutés à l'installation ou au démarrage de Python : ils peuvent fausser la suite sans toucher un test
    "setup.py",
    "**/setup.py",
    "sitecustomize.py",
    "**/sitecustomize.py",
    "usercustomize.py",
    "**/usercustomize.py",
    "*.pth",
    "**/*.pth",
]
OBLIGATOIRES = ("installer", "tests", "tests_cibles")


class Service(BaseModel):
    nom: str = Field(pattern=r"^[a-z0-9-]{1,32}$")
    image: str
    env: dict[str, str] = {}


class ConfigExecution(BaseModel):
    image: str
    chemins_tests: list[str]
    config_tests: list[str] = list(CONFIG_TESTS_DEFAUT)
    commandes: dict[str, str]
    services: list[Service] = []

    @field_validator("chemins_tests")
    @classmethod
    def _chemins_tests(cls, v):
        if not v:
            raise ValueError("au moins un chemin de tests est obligatoire")
        return v

    @field_validator("commandes")
    @classmethod
    def _commandes(cls, v):
        for nom in OBLIGATOIRES:
            if nom not in v:
                raise ValueError(f"la commande « {nom} » est obligatoire")
        if "{fichiers}" not in v["tests_cibles"]:
            raise ValueError("la commande « tests_cibles » doit contenir {fichiers}")
        return v

    @model_validator(mode="after")
    def _noms_uniques(self):
        noms = [s.nom for s in self.services]
        if len(noms) != len(set(noms)):
            raise ValueError("les noms de services doivent être uniques")
        return self

    @property
    def protege(self) -> list[str]:
        return self.chemins_tests + self.config_tests


def lire_config(texte_yaml: str) -> ConfigExecution:
    try:
        brut = yaml.safe_load(texte_yaml)
    except yaml.YAMLError as e:
        raise Refus(422, f"YAML invalide : {e}") from None
    if not isinstance(brut, dict):
        raise Refus(422, "la configuration doit être un objet YAML")
    try:
        return ConfigExecution.model_validate(brut)
    except ValidationError as e:
        msgs = [
            f"{'.'.join(str(p) for p in err['loc'])} : {err['msg'].removeprefix('Value error, ')}"
            for err in e.errors()
        ]
        raise Refus(422, "configuration invalide — " + " ; ".join(msgs)) from None


def commande(cfg: ConfigExecution, nom: str, fichiers: Sequence[str] = ()) -> str:
    return cfg.commandes[nom].replace("{fichiers}", " ".join(shlex.quote(f) for f in fichiers))


def _regex(motif: str) -> re.Pattern[str]:
    sortie, i = "", 0
    while i < len(motif):
        if motif.startswith("**/", i):
            sortie += "(?:.*/)?"
            i += 3
        elif motif.startswith("/**", i) and i + 3 == len(motif):
            sortie += "/.*"
            i += 3
        elif motif.startswith("**", i):
            sortie += ".*"
            i += 2
        elif motif[i] == "*":
            sortie += "[^/]*"
            i += 1
        elif motif[i] == "?":
            sortie += "[^/]"
            i += 1
        else:
            sortie += re.escape(motif[i])
            i += 1
    return re.compile(sortie, re.DOTALL)


def correspond(chemin: str, motifs: Sequence[str]) -> bool:
    return any(_regex(m).fullmatch(chemin) for m in motifs)


def dossiers_lecture_seule(cfg: ConfigExecution, racine: Path) -> list[str]:
    """Dossiers protégés à monter en lecture seule : vrais dossiers, sans aucun lien sur le chemin."""
    if racine.is_symlink():
        return []
    trouves = []
    for motif in cfg.protege:
        dossier = motif.removesuffix("/**")
        if dossier == motif or re.search(r"[*?\[]", dossier):
            continue
        parties = dossier.split("/")
        if any(p in ("", ".", "..") for p in parties):
            continue
        courant, sain = racine, True
        for p in parties:
            courant = courant / p
            if courant.is_symlink():
                sain = False
                break
        if sain and courant.is_dir() and dossier not in trouves:
            trouves.append(dossier)
    return trouves
