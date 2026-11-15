"""Pile Portainer, secrets d'agents et vhost : un conteneur par agent, isolé, sans fuite."""

import json
import os
import re
import stat
import subprocess
from pathlib import Path

import yaml

from portail.agents import charger_catalogue

RACINE = Path(__file__).parents[2]
PILE = yaml.safe_load((RACINE / "deploy" / "portainer-stack.yml").read_text())
VAULT = RACINE / "scripts" / "vault-render-env.sh"
NOMS = list(charger_catalogue(RACINE / "agents.yaml").agents)


def _secret(nom: str) -> str:
    return "PORTAIL_AGENT_SECRET_" + nom.upper().replace("-", "_")


def _agents() -> dict[str, dict]:
    return {n: s for n, s in PILE["services"].items() if n.startswith("agent-")}


def test_un_service_par_agent():
    assert set(_agents()) == {f"agent-{n}" for n in NOMS}
    for n in NOMS:
        assert _agents()[f"agent-{n}"]["entrypoint"] == [n]


def test_agent_isole():
    for nom, s in _agents().items():
        n = nom.removeprefix("agent-")
        assert s["networks"] == ["portail-agents"], nom
        assert "volumes" not in s and "ports" not in s, nom
        assert s["read_only"] is True and s["cap_drop"] == ["ALL"], nom
        assert s["security_opt"] == ["no-new-privileges:true"], nom
        assert re.fullmatch(
            r"ghcr\.io/nicolaslallier/ai-agents:\$\{IMAGE_TAG:-latest\}@\$\{AGENTS_DIGEST:\?\}",
            s["image"],
        ), nom
        assert s["environment"] == {
            "AGENT_SECRET": f"${{{_secret(n)}:?}}",
            "AGENT_PORTAIL_URL": "http://portail:8000",
            "AGENT_VERSION": "${IMAGE_TAG:-latest}",
        }, nom


def test_reseau_agents_interne():
    assert PILE["networks"]["portail-agents"]["internal"] is True
    membres = {n for n, s in PILE["services"].items() if "portail-agents" in s.get("networks", [])}
    assert membres == {"portail", *_agents()}


def test_portail_recoit_chaque_secret():
    env = PILE["services"]["portail"]["environment"]
    for n in NOMS:
        assert env[_secret(n)] == f"${{{_secret(n)}:?}}"


def test_coffre_rend_chaque_secret():
    texte = VAULT.read_text()
    carte = re.search(r'^MAP="([^"]*)"', texte, re.MULTILINE).group(1).split()
    facultatives = re.search(r'^FACULTATIVES="([^"]*)"', texte, re.MULTILINE).group(1).split()
    for n in NOMS:
        assert f"{_secret(n)}={_secret(n)}" in carte
        assert _secret(n) not in facultatives


def _lancer_coffre(tmp_path: Path, court: bool) -> subprocess.CompletedProcess:
    secrets = {
        k: "v" * 40
        for k in (
            "PORTAIL_DB_PASSWORD",
            "PORTAIL_LITELLM_CLE",
            "PORTAIL_GITHUB_JETON",
            "PORTAIL_LANCEUR_SECRET",
            *(_secret(n) for n in NOMS),
        )
    }
    if court:
        secrets[_secret(NOMS[0])] = "court-" + "9" * 25  # 31 caractères
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    reponse = tmp_path / "reponse.json"
    reponse.write_text(json.dumps({"data": {"data": secrets}}))
    faux = bin_ / "curl"
    faux.write_text(f'#!/bin/sh\ncase " $* " in *" -o "*) exit 0;; esac\ncat {reponse}\n')
    faux.chmod(faux.stat().st_mode | stat.S_IXUSR)
    ca = tmp_path / "ca.crt"
    ca.write_text("x")
    env = {
        **os.environ,
        "PATH": f"{bin_}:{os.environ['PATH']}",
        "BAO_TOKEN": "jeton",
        "VAULT_CA_CERT": str(ca),
        "PORTAIL_STACK_ENV": str(tmp_path / "pile.env"),
    }
    return subprocess.run([str(VAULT)], check=False, env=env, capture_output=True, text=True)


def test_secret_court_refuse(tmp_path):
    r = _lancer_coffre(tmp_path, court=True)
    assert r.returncode != 0
    assert "trop court" in r.stderr
    assert "9" * 25 not in r.stdout + r.stderr


def test_secrets_longs_acceptes(tmp_path):
    r = _lancer_coffre(tmp_path, court=False)
    assert r.returncode == 0, r.stderr
    assert "v" * 40 not in r.stdout + r.stderr


def test_vhost_ne_sert_pas_interne():
    conf = (RACINE / "deploy" / "nginx" / "portail.conf").read_text()
    assert re.search(r"location\s+\^~\s+/interne/\s*\{\s*return\s+404;\s*\}", conf)
