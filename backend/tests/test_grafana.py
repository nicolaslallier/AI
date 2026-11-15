"""Tableaux de bord et alertes du portail : chargeables, et ne citent que des métriques exposées."""

import json
import re
from pathlib import Path

import yaml
from prometheus_client import REGISTRY, generate_latest

import portail.metriques  # noqa: F401 (déclare les métriques dans le registre)

DOSSIER = Path(__file__).parents[2] / "deploy" / "grafana"
SUFFIXES = ("_total", "_bucket", "_sum", "_count", "_created")


def _racine(nom: str) -> str:
    for s in SUFFIXES:
        nom = nom.removesuffix(s)
    return nom


def _tableaux() -> list[dict]:
    return [json.loads(f.read_text()) for f in sorted(DOSSIER.glob("portail-*.json"))]


def _sources(panneau: dict):
    yield panneau.get("datasource")
    for c in panneau.get("targets", []):
        yield c.get("datasource")


def test_tableaux_valides():
    tableaux = _tableaux()
    assert len(tableaux) == 4
    assert len({t["uid"] for t in tableaux}) == 4
    for t in tableaux:
        assert t["title"].strip() and t["panels"], t["uid"]
        for p in t["panels"]:
            for ds in _sources(p):
                assert ds["uid"] in {"prometheus", "loki"} or ds["uid"].startswith("$"), p["title"]


def test_metriques_existantes():
    exposees = {
        _racine(m.group(1))
        for m in re.finditer(
            r"^# TYPE (portail_\w+) ", generate_latest(REGISTRY).decode(), re.MULTILINE
        )
    }
    fichiers = [*DOSSIER.glob("*.json"), *DOSSIER.glob("*.yml")]
    assert len(fichiers) >= 4
    cites = {_racine(m) for f in fichiers for m in re.findall(r"\bportail_\w+", f.read_text())}
    assert cites and cites <= exposees, cites - exposees


def test_alertes_valides():
    groupe = yaml.safe_load((DOSSIER / "alertes-portail.yml").read_text())["groups"][0]
    assert groupe["name"] == "portail" and groupe["interval"] == "1m"
    regles = {r["uid"]: r for r in groupe["rules"]}
    assert set(regles) == {
        "portail-erreurs-modele",
        "portail-tache-trop-longue",
        "portail-echecs-consecutifs",
        "portail-deploiement-ancien",
    }
    for r in regles.values():
        assert r["condition"] and "for" in r and r["noDataState"] == "OK", r["uid"]
        assert r["annotations"]["summary"].strip()
        for texte in r["annotations"].values():  # rien de variable dans la notification
            assert "$values" not in texte and "$labels" not in texte
