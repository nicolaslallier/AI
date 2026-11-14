"""Suivi d'état d'une exécution : un fichier JSON par exécution.

Le fichier vit dans `<dépôt>/.git/orchestrateur/<id>.json` : hors de l'arbre de travail,
donc jamais committé, et propre à chaque clone. L'orchestrateur le met à jour par les
outils MCP `plan_definir` et `tache_maj`, servis en mémoire par ce programme.
"""

import json
import secrets
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server, tool

Statut = Literal["a_faire", "en_cours", "faite", "echec"]
STATUTS: tuple[str, ...] = ("a_faire", "en_cours", "faite", "echec")


def maintenant() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Tache:
    id: int
    titre: str
    agent: str = "codeur"
    statut: Statut = "a_faire"
    resultat: str = ""
    essais: int = 0


@dataclass
class Etat:
    id: str
    demande: str
    depot: str
    branche: str
    branche_depart: str
    statut: Literal["en_cours", "terminee", "interrompue", "erreur"] = "en_cours"
    session_id: str | None = None
    taches: list[Tache] = field(default_factory=list)
    journal: list[str] = field(default_factory=list)
    cout_usd: float = 0.0
    rapport: str = ""
    cree_le: str = field(default_factory=maintenant)
    maj_le: str = field(default_factory=maintenant)

    @staticmethod
    def nouvel_id() -> str:
        return datetime.now(UTC).strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)

    @staticmethod
    def dossier(depot: Path) -> Path:
        return depot / ".git" / "orchestrateur"

    def chemin(self) -> Path:
        return self.dossier(Path(self.depot)) / f"{self.id}.json"

    def noter(self, texte: str) -> None:
        self.journal.append(f"{maintenant()} {texte}")

    def sauver(self) -> Path:
        self.maj_le = maintenant()
        chemin = self.chemin()
        chemin.parent.mkdir(parents=True, exist_ok=True)
        tmp = chemin.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(chemin)  # écriture atomique : un arrêt brutal ne laisse pas un JSON coupé
        return chemin

    @classmethod
    def charger(cls, depot: Path, id_: str) -> "Etat":
        donnees = json.loads((cls.dossier(depot) / f"{id_}.json").read_text(encoding="utf-8"))
        donnees["taches"] = [Tache(**t) for t in donnees.get("taches", [])]
        return cls(**donnees)

    def resume(self) -> str:
        if not self.taches:
            return "Aucun plan enregistré."
        return "\n".join(
            f"{t.id}. [{t.statut}] {t.titre} ({t.agent}, {t.essais} essai(s))"
            + (f" : {t.resultat}" if t.resultat else "")
            for t in self.taches
        )

    # --- opérations appelées par les outils MCP ---

    def definir_plan(self, taches: list[dict[str, Any]]) -> str:
        if not taches:
            raise ValueError("le plan doit contenir au moins une tâche")
        if len(taches) > 12:
            raise ValueError("12 tâches au plus : découpe moins finement")
        nouvelles = []
        for i, t in enumerate(taches, start=1):
            titre = str(t.get("titre", "")).strip()
            if not titre:
                raise ValueError(f"tâche {i} : titre vide")
            nouvelles.append(Tache(id=i, titre=titre, agent=str(t.get("agent") or "codeur")))
        self.taches = nouvelles
        self.noter(f"plan défini : {len(nouvelles)} tâche(s)")
        self.sauver()
        return self.resume()

    def maj_tache(self, id_: int, statut: str, resultat: str = "") -> str:
        if statut not in STATUTS:
            raise ValueError(f"statut inconnu {statut!r} (attendu : {', '.join(STATUTS)})")
        tache = next((t for t in self.taches if t.id == id_), None)
        if tache is None:
            raise ValueError(f"tâche {id_} inconnue : définis d'abord le plan avec plan_definir")
        if statut == "en_cours":
            tache.essais += 1
        tache.statut = statut  # type: ignore[assignment]
        if resultat:
            tache.resultat = resultat.strip()[:500]
        self.noter(f"tâche {id_} → {statut}")
        self.sauver()
        return self.resume()


def _texte(contenu: str, erreur: bool = False) -> dict[str, Any]:
    reponse: dict[str, Any] = {"content": [{"type": "text", "text": contenu}]}
    if erreur:
        reponse["is_error"] = True
    return reponse


NOM_SERVEUR = "etat"
OUTILS_ETAT = [f"mcp__{NOM_SERVEUR}__{n}" for n in ("plan_definir", "tache_maj", "etat_lire")]


def outils(etat: Etat) -> list[SdkMcpTool[Any]]:
    """Les outils MCP qui exposent l'état à l'orchestrateur."""

    @tool(
        "plan_definir",
        "Enregistre le plan : la liste ordonnée des tâches (remplace le plan précédent). "
        "Écrit dans le fichier d'état de l'exécution, rien dans le dépôt.",
        {
            "type": "object",
            "properties": {
                "taches": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "titre": {"type": "string", "description": "ce que la tâche doit accomplir"},
                            "agent": {"type": "string", "description": "sous-agent principal (défaut : codeur)"},
                        },
                        "required": ["titre"],
                    },
                }
            },
            "required": ["taches"],
        },
    )
    async def plan_definir(args: dict[str, Any]) -> dict[str, Any]:
        try:
            return _texte(etat.definir_plan(args["taches"]))
        except (ValueError, KeyError, TypeError) as e:
            return _texte(f"Plan refusé : {e}", erreur=True)

    @tool(
        "tache_maj",
        "Change l'état d'une tâche du plan (a_faire, en_cours, faite, echec) avec un résumé "
        "d'une ligne du résultat. Passer à en_cours compte un essai. "
        "Écrit dans le fichier d'état de l'exécution, rien dans le dépôt.",
        {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "statut": {"type": "string", "enum": list(STATUTS)},
                "resultat": {"type": "string"},
            },
            "required": ["id", "statut"],
        },
    )
    async def tache_maj(args: dict[str, Any]) -> dict[str, Any]:
        try:
            return _texte(etat.maj_tache(int(args["id"]), args["statut"], args.get("resultat", "")))
        except (ValueError, KeyError, TypeError) as e:
            return _texte(f"Mise à jour refusée : {e}", erreur=True)

    @tool(
        "etat_lire",
        "Lecture seule. Renvoie le plan et l'état de chaque tâche.",
        {"type": "object", "properties": {}},
    )
    async def etat_lire(args: dict[str, Any]) -> dict[str, Any]:
        return _texte(etat.resume())

    return [plan_definir, tache_maj, etat_lire]


def serveur_mcp(etat: Etat):
    """Serveur MCP en mémoire, à passer dans `ClaudeAgentOptions.mcp_servers`."""
    return create_sdk_mcp_server(NOM_SERVEUR, tools=outils(etat))
