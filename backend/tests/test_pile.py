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


def _lancer_coffre(tmp_path: Path, court: bool, **extra: str) -> subprocess.CompletedProcess:
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
    env.pop(
        "GITHUB_ACTIONS", None
    )  # sinon le script masque les valeurs : un autre test s'en charge
    env.update(extra)
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


def test_valeurs_seulement_dans_les_lignes_masquees(tmp_path):
    r = _lancer_coffre(tmp_path, court=False, GITHUB_ACTIONS="true")
    assert r.returncode == 0, r.stderr
    lignes = [x for x in (r.stdout + r.stderr).splitlines() if "v" * 40 in x]
    assert lignes and all(x.startswith("::add-mask::") for x in lignes)


def test_vhost_ne_sert_pas_interne():
    conf = (RACINE / "deploy" / "nginx" / "portail.conf").read_text()
    bloc = re.search(r"location\s+\^~\s+/interne\s*\{\s*return\s+404;\s*\}", conf)
    assert bloc and bloc.start() < conf.index("location / {")


def test_agent_aux_cles_connues():
    for nom, s in _agents().items():
        assert set(s) == {
            "image", "networks", "read_only", "cap_drop", "security_opt", "mem_limit",
            "pids_limit", "restart", "user", "cpus", "entrypoint", "environment",
        }, nom  # fmt: skip
        assert s["user"] == "65532:65532" and s["cpus"] == "0.5", nom


def test_lanceur_sans_secret_d_agent():
    env = json.dumps(PILE["services"]["lanceur"])
    assert "PORTAIL_AGENT_SECRET" not in env and "AGENT_SECRET" not in env


def test_reseau_des_agents_fixe_et_connu_du_portail():
    config = PILE["networks"]["portail-agents"]["ipam"]["config"]
    assert len(config) == 1
    assert (
        PILE["services"]["portail"]["environment"]["PORTAIL_RESEAU_AGENTS"] == config[0]["subnet"]
    )


def test_digests_verifies_au_deploiement():
    wf = (RACINE / ".github" / "workflows" / "deploy.yml").read_text()
    assert wf.count("sha256:[0-9a-f]{64}") == 1 and "for v in EXECUTION_DIGEST AGENTS_DIGEST" in wf


def _facultatives(rendu: str) -> str:
    return re.search(r'FACULTATIVES="([^"]*)"', rendu).group(1)


def test_service_ferme_sur_le_vhost_et_jeton_facultatif():
    conf = (RACINE / "deploy" / "nginx" / "portail.conf").read_text()
    assert re.search(r"location \^~ /service \{\s*return 404;\s*\}", conf)
    pile = (RACINE / "deploy" / "portainer-stack.yml").read_text()
    assert "PORTAIL_JETON_SERVICE: ${PORTAIL_JETON_SERVICE:-}" in pile
    rendu = VAULT.read_text()
    assert "PORTAIL_JETON_SERVICE=PORTAIL_JETON_SERVICE" in rendu
    assert " PORTAIL_JETON_SERVICE " in _facultatives(rendu)


def test_cle_des_agents_facultative_dans_la_pile():
    pile = (RACINE / "deploy" / "portainer-stack.yml").read_text()
    assert "PORTAIL_LITELLM_CLE_AGENTS: ${PORTAIL_LITELLM_CLE_AGENTS:-}" in pile
    rendu = VAULT.read_text()
    assert "PORTAIL_LITELLM_CLE_AGENTS=PORTAIL_LITELLM_CLE_AGENTS" in rendu
    assert " PORTAIL_LITELLM_CLE_AGENTS " in _facultatives(rendu)
