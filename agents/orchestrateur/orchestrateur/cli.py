"""Point d'entrée : `uv run orchestrateur "demande" --depot CHEMIN`."""

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultError,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from orchestrateur import definitions, depot, issue
from orchestrateur.etat import OUTILS_ETAT, Etat, serveur_mcp

MODELE_DEFAUT = "claude-opus-5-5"
# CA locale de l'Infra, copiée dans le dépôt : sert si NODE_EXTRA_CA_CERTS n'est pas défini.
CA_INFRA = Path(__file__).resolve().parents[3] / "certs" / "infra-ca.crt"

# Ce que les agents peuvent faire sans demander. Tout le reste est refusé (mode dontAsk) :
# personne n'est là pour approuver pendant une exécution.
OUTILS_AUTORISES = [
    "Agent",
    "Task",  # ancien nom de l'outil Agent
    "Read",
    "Grep",
    "Glob",
    "Edit",
    "Write",
    "Bash(git status:*)",
    "Bash(git diff:*)",
    "Bash(git log:*)",
    "Bash(git show:*)",
    "Bash(git add:*)",
    "Bash(git commit:*)",
    "Bash(uv sync:*)",
    "Bash(uv run:*)",
    "Bash(npm test:*)",
    "Bash(npm run:*)",
    "Bash(pytest:*)",
    *OUTILS_ETAT,
]
# Refusés même si une autre règle (réglages du dépôt) les autorisait.
OUTILS_INTERDITS = [
    "Bash(git push:*)",
    "Bash(git checkout:*)",
    "Bash(git switch:*)",
    "Bash(git reset:*)",
    "Bash(git rebase:*)",
    "Bash(git merge:*)",
    "Bash(gh:*)",
    "WebFetch",
    "WebSearch",
]


@dataclass
class Parametres:
    modele: str = MODELE_DEFAUT
    max_tours: int = 150
    budget_usd: float = 10.0
    autoriser: tuple[str, ...] = ()


def contexte(etat: Etat) -> str:
    return (
        "\n\n## Cette exécution\n\n"
        f"- Dépôt : `{etat.depot}`\n"
        f"- Branche de travail (déjà créée, tu es dessus) : `{etat.branche}`\n"
        f"- Branche de départ (à donner au relecteur) : `{etat.branche_depart}`\n"
        f"- Identifiant d'exécution : `{etat.id}`\n"
        "- Les outils `plan_definir`, `tache_maj` et `etat_lire` sont disponibles : utilise-les.\n"
    )


def env_claude_code() -> dict[str, str]:
    """Variables ajoutées pour Claude Code (Node) : la CA de l'Infra, pour joindre LiteLLM en HTTPS."""
    if os.environ.get("NODE_EXTRA_CA_CERTS") or not CA_INFRA.is_file():
        return {}
    return {"NODE_EXTRA_CA_CERTS": str(CA_INFRA)}


def construire_options(etat: Etat, p: Parametres, dossier_agents: Path = definitions.DOSSIER_AGENTS) -> ClaudeAgentOptions:
    orch, sous_agents = definitions.charger(dossier_agents)
    return ClaudeAgentOptions(
        cwd=etat.depot,
        model=p.modele or orch.modele,
        system_prompt={"type": "preset", "preset": "claude_code", "append": orch.prompt + contexte(etat)},
        agents={nom: d.vers_sdk() for nom, d in sous_agents.items()},
        mcp_servers={"etat": serveur_mcp(etat)},
        allowed_tools=[*OUTILS_AUTORISES, *p.autoriser],
        disallowed_tools=OUTILS_INTERDITS,
        permission_mode="dontAsk",
        setting_sources=["project"],  # CLAUDE.md et réglages du dépôt cible, pas ceux de ~/.claude
        max_turns=p.max_tours,
        max_budget_usd=p.budget_usd,
        resume=etat.session_id,
        env=env_claude_code(),
    )


def afficher(texte: str) -> None:
    print(texte, flush=True)


async def executer(etat: Etat, demande: str, options: ClaudeAgentOptions) -> ResultMessage | None:
    resultat: ResultMessage | None = None
    try:
        async for msg in query(prompt=demande, options=options):
            if isinstance(msg, SystemMessage) and msg.subtype == "init":
                etat.session_id = msg.data.get("session_id", etat.session_id)
                etat.sauver()
            elif isinstance(msg, AssistantMessage) and msg.parent_tool_use_id is None:
                for bloc in msg.content:
                    if isinstance(bloc, TextBlock) and bloc.text.strip():
                        afficher(f"\n[orchestrateur] {bloc.text.strip()}")
                    elif isinstance(bloc, ToolUseBlock) and bloc.name in ("Agent", "Task"):
                        agent = bloc.input.get("subagent_type", "?")
                        afficher(f"  → {agent} : {bloc.input.get('description', '')}")
                        etat.noter(f"délégué à {agent} : {bloc.input.get('description', '')}")
            elif isinstance(msg, ResultMessage):
                resultat = msg
                etat.session_id = msg.session_id
    except ResultError:
        # Le SDK lève cette erreur après avoir transmis le ResultMessage en erreur
        # (max_turns, budget, API injoignable) : le résultat suffit à conclure.
        if resultat is None:
            raise
    return resultat


def _analyser_arguments(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="orchestrateur",
        description="Découpe une demande de développement et la fait réaliser par des sous-agents.",
    )
    ap.add_argument("demande", nargs="?", help="la demande, en texte libre")
    ap.add_argument("--issue", help="lire la demande dans une issue GitHub (proprio/depot#12 ou URL)")
    ap.add_argument("--depot", type=Path, default=Path.cwd(), help="dépôt git cible (défaut : dossier courant)")
    ap.add_argument("--reprendre", metavar="ID", help="reprendre une exécution interrompue")
    ap.add_argument("--modele", default=os.environ.get("ORCHESTRATEUR_MODELE", MODELE_DEFAUT))
    ap.add_argument("--max-tours", type=int, default=150)
    ap.add_argument("--budget-usd", type=float, default=10.0, help="plafond de dépense de l'exécution")
    ap.add_argument(
        "--autoriser",
        action="append",
        default=[],
        metavar="REGLE",
        help='outil supplémentaire autorisé, ex. "Bash(make test:*)" (répétable)',
    )
    ap.add_argument("--pr", action="store_true", help="à la fin, pousser la branche et ouvrir une PR en brouillon (gh)")
    ap.add_argument("--a-blanc", action="store_true", help="tout préparer et afficher, sans toucher au dépôt ni appeler de modèle")
    ap.add_argument("--liste", action="store_true", help="lister les exécutions de ce dépôt")
    args = ap.parse_args(argv)
    if not (args.liste or args.reprendre) and bool(args.demande) == bool(args.issue):
        ap.error("donne une demande en texte ou --issue (l'un des deux)")
    return args


def _lister(racine: Path) -> int:
    dossier = Etat.dossier(racine)
    fichiers = sorted(dossier.glob("*.json")) if dossier.is_dir() else []
    if not fichiers:
        afficher("Aucune exécution dans ce dépôt.")
    for f in fichiers:
        e = Etat.charger(racine, f.stem)
        afficher(f"{e.id}  {e.statut:<11} {e.branche}  {e.demande.splitlines()[0][:70]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _analyser_arguments(argv)
    try:
        racine = depot.racine(args.depot)
    except depot.ErreurDepot as e:
        sys.exit(str(e))
    if args.liste:
        return _lister(racine)
    p = Parametres(modele=args.modele, max_tours=args.max_tours, budget_usd=args.budget_usd, autoriser=tuple(args.autoriser))

    if args.reprendre:
        try:
            etat = Etat.charger(racine, args.reprendre)
        except FileNotFoundError:
            sys.exit(f"Exécution {args.reprendre} introuvable dans {Etat.dossier(racine)}")
        if depot.branche_courante(racine) != etat.branche:
            sys.exit(f"Place-toi d'abord sur la branche {etat.branche} (git switch {etat.branche})")
        demande = "Reprends l'exécution là où elle s'est arrêtée. État enregistré :\n\n" + etat.resume()
    else:
        demande = args.demande
        if args.issue:
            try:
                demande = issue.lire(issue.analyser(args.issue))
            except Exception as e:  # noqa: BLE001 — réseau, 404, référence invalide : on s'arrête net
                sys.exit(f"Lecture de l'issue impossible : {e}")
        id_ = Etat.nouvel_id()
        etat = Etat(
            id=id_,
            demande=demande,
            depot=str(racine),
            branche=f"orchestrateur/{id_}",
            branche_depart=depot.branche_courante(racine),
        )

    options = construire_options(etat, p)

    if args.a_blanc:
        orch, sous_agents = definitions.charger()
        afficher(f"Dépôt          : {etat.depot}")
        afficher(f"Branche        : {etat.branche} (depuis {etat.branche_depart})")
        afficher(f"Orchestrateur  : {options.model}, {p.max_tours} tours max, {p.budget_usd} $ max")
        for nom, d in sous_agents.items():
            afficher(f"Sous-agent     : {nom:<12} {d.modele or 'hérité'}  outils : {', '.join(d.outils or ['tous'])}")
        afficher(f"Autorisés      : {', '.join(options.allowed_tools)}")
        afficher(f"Interdits      : {', '.join(options.disallowed_tools)}")
        afficher(f"API            : {os.environ.get('ANTHROPIC_BASE_URL', 'api.anthropic.com (ANTHROPIC_BASE_URL non défini)')}")
        afficher(f"CA             : {os.environ.get('NODE_EXTRA_CA_CERTS') or options.env.get('NODE_EXTRA_CA_CERTS', 'aucune')}")
        afficher(f"\nDemande :\n{demande}")
        return 0

    if not args.reprendre:
        try:
            etat.branche_depart = depot.preparer_branche(racine, etat.branche)
        except depot.ErreurDepot as e:
            sys.exit(str(e))
        etat.noter("exécution démarrée")
        etat.sauver()
    afficher(f"Exécution {etat.id} sur {etat.branche} (état : {etat.chemin()})")

    try:
        resultat = asyncio.run(executer(etat, demande, options))
    except KeyboardInterrupt:
        etat.statut = "interrompue"
        etat.noter("interrompue au clavier")
        etat.sauver()
        afficher(f"\nInterrompue. Pour reprendre : orchestrateur --reprendre {etat.id}")
        return 130
    except Exception as e:
        etat.statut = "erreur"
        etat.noter(f"erreur : {e}")
        etat.sauver()
        raise

    if resultat is None or resultat.is_error:
        etat.statut = "interrompue" if resultat and resultat.terminal_reason == "max_turns" else "erreur"
        raison = (resultat.terminal_reason or resultat.subtype) if resultat else "aucun résultat"
        etat.noter(f"fin anormale : {raison}")
    else:
        etat.statut = "terminee"
        etat.noter("terminée")
    if resultat:
        etat.cout_usd += resultat.total_cost_usd or 0.0
        etat.rapport = resultat.result or ""
    etat.sauver()

    commits = depot.commits_depuis(racine, etat.branche_depart)
    afficher(f"\n{etat.rapport}\n\n{etat.resume()}")
    afficher(f"\n{len(commits)} commit(s) sur {etat.branche}, coût {etat.cout_usd:.2f} $, statut {etat.statut}")
    if etat.statut != "terminee":
        afficher(f"Pour reprendre : orchestrateur --reprendre {etat.id}")

    if args.pr and etat.statut == "terminee" and commits:
        titre = etat.demande.splitlines()[0][:72]
        try:
            url = depot.ouvrir_pr(racine, etat.branche, etat.branche_depart, titre, etat.rapport)
        except depot.ErreurDepot as e:
            afficher(f"PR non ouverte : {e}")
            return 1
        etat.noter(f"PR ouverte : {url}")
        etat.sauver()
        afficher(f"PR en brouillon : {url}")
    return 0 if etat.statut == "terminee" else 1


if __name__ == "__main__":
    sys.exit(main())
