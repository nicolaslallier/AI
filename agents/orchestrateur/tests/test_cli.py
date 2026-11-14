"""Exécutions complètes avec un faux `query` : aucun modèle appelé."""

from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, ResultError, ResultMessage, SystemMessage, TextBlock, ToolUseBlock

from orchestrateur import cli
from orchestrateur.etat import Etat
from tests.conftest import git


def resultat(**kw) -> ResultMessage:
    base = dict(
        subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=3,
        session_id="session-1", total_cost_usd=0.42, result="Rapport : tâche A faite.",
    )
    return ResultMessage(**{**base, **kw})


def faux_query(fin: ResultMessage, commit: bool = True, vus: list | None = None):
    async def query(*, prompt, options):
        if vus is not None:
            vus.append((prompt, options))
        yield SystemMessage(subtype="init", data={"session_id": "session-1"})
        yield AssistantMessage(
            content=[
                TextBlock("Je découpe la demande."),
                ToolUseBlock(id="t1", name="Agent", input={"subagent_type": "codeur", "description": "tâche A"}),
            ],
            model="claude-opus-5-5",
        )
        if commit:
            (Path(options.cwd) / "a.txt").write_text("a")
            git(options.cwd, "add", "a.txt")
            git(options.cwd, "commit", "-q", "-m", "ajoute a")
        yield fin
        if fin.is_error:  # comme le vrai SDK : l'erreur est levée après le résultat
            raise ResultError("Claude Code returned an error result")

    return query


def etats(depot):
    return [Etat.charger(depot, f.stem) for f in Etat.dossier(depot).glob("*.json")]


def test_options(depot_git):
    etat = Etat(id="x", demande="d", depot=str(depot_git), branche="orchestrateur/x", branche_depart="main", session_id="s0")
    o = cli.construire_options(etat, cli.Parametres(budget_usd=3, max_tours=20, autoriser=("Bash(make:*)",)))
    assert o.cwd == str(depot_git) and o.model == "claude-opus-5-5"
    assert o.permission_mode == "dontAsk" and o.setting_sources == ["project"]
    assert o.max_budget_usd == 3 and o.max_turns == 20 and o.resume == "s0"
    assert set(o.agents) == {"explorateur", "codeur", "testeur", "relecteur"}
    assert "Bash(make:*)" in o.allowed_tools and "mcp__etat__tache_maj" in o.allowed_tools
    assert "Bash(git push:*)" in o.disallowed_tools
    assert not set(o.allowed_tools) & set(o.disallowed_tools)
    assert "orchestrateur/x" in o.system_prompt["append"] and "Tu es l'orchestrateur" in o.system_prompt["append"]


def test_ca_infra_par_defaut(monkeypatch):
    assert cli.CA_INFRA.is_file() and "BEGIN CERTIFICATE" in cli.CA_INFRA.read_text()
    monkeypatch.delenv("NODE_EXTRA_CA_CERTS", raising=False)
    assert cli.env_claude_code() == {"NODE_EXTRA_CA_CERTS": str(cli.CA_INFRA)}
    monkeypatch.setenv("NODE_EXTRA_CA_CERTS", "/ailleurs.crt")
    assert cli.env_claude_code() == {}  # une valeur déjà définie l'emporte


def test_execution_complete(depot_git, monkeypatch, capsys):
    vus: list = []
    monkeypatch.setattr(cli, "query", faux_query(resultat(), vus=vus))
    assert cli.main(["Faire A", "--depot", str(depot_git)]) == 0
    [etat] = etats(depot_git)
    assert etat.statut == "terminee" and etat.session_id == "session-1"
    assert etat.cout_usd == pytest.approx(0.42) and etat.rapport.startswith("Rapport")
    assert any("délégué à codeur" in j for j in etat.journal)
    assert git(depot_git, "rev-parse", "--abbrev-ref", "HEAD") == etat.branche
    assert vus[0][0] == "Faire A"
    sortie = capsys.readouterr().out
    assert "→ codeur : tâche A" in sortie and "1 commit(s)" in sortie


def test_fin_sur_max_tours_puis_reprise(depot_git, monkeypatch, capsys):
    monkeypatch.setattr(cli, "query", faux_query(resultat(is_error=True, subtype="error_max_turns", terminal_reason="max_turns")))
    assert cli.main(["Faire A", "--depot", str(depot_git)]) == 1
    [etat] = etats(depot_git)
    assert etat.statut == "interrompue"
    assert f"--reprendre {etat.id}" in capsys.readouterr().out

    vus: list = []
    monkeypatch.setattr(cli, "query", faux_query(resultat(), commit=False, vus=vus))
    assert cli.main(["--reprendre", etat.id, "--depot", str(depot_git)]) == 0
    prompt, options = vus[0]
    assert options.resume == "session-1" and prompt.startswith("Reprends")
    assert Etat.charger(depot_git, etat.id).statut == "terminee"


def test_reprise_sur_mauvaise_branche(depot_git, monkeypatch):
    monkeypatch.setattr(cli, "query", faux_query(resultat(is_error=True, terminal_reason="max_turns")))
    cli.main(["Faire A", "--depot", str(depot_git)])
    [etat] = etats(depot_git)
    git(depot_git, "checkout", "-q", "main")
    with pytest.raises(SystemExit, match="Place-toi"):
        cli.main(["--reprendre", etat.id, "--depot", str(depot_git)])


def test_a_blanc_ne_touche_a_rien(depot_git, monkeypatch, capsys):
    monkeypatch.setattr(cli, "query", None)  # tout appel planterait
    assert cli.main(["--a-blanc", "Faire A", "--depot", str(depot_git)]) == 0
    assert git(depot_git, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert not Etat.dossier(depot_git).exists()
    assert "Sous-agent     : codeur" in capsys.readouterr().out


def test_arbre_modifie_refuse(depot_git, monkeypatch):
    monkeypatch.setattr(cli, "query", None)
    (depot_git / "README.md").write_text("modifié")
    with pytest.raises(SystemExit, match="non committées"):
        cli.main(["Faire A", "--depot", str(depot_git)])


def test_pr_ouverte_seulement_si_terminee_avec_commits(depot_git, monkeypatch):
    appels: list = []
    monkeypatch.setattr(cli.depot, "ouvrir_pr", lambda *a: appels.append(a) or "https://example.invalid/pr/1")
    monkeypatch.setattr(cli, "query", faux_query(resultat(), commit=False))
    cli.main(["Faire A", "--depot", str(depot_git), "--pr"])
    assert appels == []  # aucun commit
    git(depot_git, "checkout", "-q", "main")
    monkeypatch.setattr(cli, "query", faux_query(resultat()))
    assert cli.main(["Faire A", "--depot", str(depot_git), "--pr"]) == 0
    [(_, branche, depart, titre, corps)] = appels
    assert depart == "main" and titre == "Faire A" and corps.startswith("Rapport")


def test_liste(depot_git, monkeypatch, capsys):
    assert cli.main(["--liste", "--depot", str(depot_git)]) == 0
    assert "Aucune" in capsys.readouterr().out
    monkeypatch.setattr(cli, "query", faux_query(resultat()))
    cli.main(["Faire A", "--depot", str(depot_git)])
    cli.main(["--liste", "--depot", str(depot_git)])
    assert "Faire A" in capsys.readouterr().out


def test_erreur_sans_resultat_remonte(depot_git, monkeypatch):
    async def query(*, prompt, options):
        raise ResultError("CLI introuvable")
        yield

    monkeypatch.setattr(cli, "query", query)
    with pytest.raises(ResultError):
        cli.main(["Faire A", "--depot", str(depot_git)])
    [etat] = etats(depot_git)
    assert etat.statut == "erreur"


@pytest.mark.parametrize("argv", [[], ["texte", "--issue", "o/d#1"]])
def test_arguments_exclusifs(argv):
    with pytest.raises(SystemExit):
        cli.main(argv)
