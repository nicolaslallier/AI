"""Contrat `v1` entre le portail et les agents en conteneur (voir docs/agents-contrat-v1.md).

Les demandes venues d'un agent sont en `extra="forbid"` : le portail n'y lit que ce qu'il
autorise (messages, drapeau `outils`, `response_format`, `flux`, nom et arguments d'un outil).
"""

import asyncio
import secrets
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Annotated, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from portail import journal
from portail.agents import Agent, Catalogue, CatalogueInvalide
from portail.boucle import ErreurOutils

CONTRAT = "v1"


class _Forbid(BaseModel):
    model_config = ConfigDict(extra="forbid")


MESSAGES_MAX = 2000
CONTENU_MAX = 500_000


class MessageLLM(_Forbid):
    """Un message de la conversation : champs explicites, rien d'inventé ne passe au modèle."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = Field(default=None, max_length=CONTENU_MAX)
    tool_calls: list[dict] | None = Field(default=None, max_length=64)
    tool_call_id: str | None = Field(default=None, max_length=200)
    name: str | None = Field(default=None, max_length=200)


class ParametresAgent(BaseModel):
    modele: str
    temperature: float | None = None
    contexte_max: int
    tours_max: int
    produit: str
    role: str | None = None


class DemandeMission(BaseModel):
    contrat: Literal["v1"]
    mission: str
    agent: str
    jeton: str = Field(repr=False)
    messages: list[MessageLLM] = Field(max_length=MESSAGES_MAX)
    outils: list[dict]
    parametres: ParametresAgent
    response_format: dict | None = None
    flux: bool = False


class LigneTexte(BaseModel):
    type: Literal["texte"]
    texte: str


class LigneFin(BaseModel):
    type: Literal["fin"]
    texte: str
    messages: list[MessageLLM] = Field(max_length=MESSAGES_MAX)
    limite_atteinte: bool


class LigneErreur(BaseModel):
    type: Literal["erreur"]
    erreur: str


LigneMission = Annotated[LigneTexte | LigneFin | LigneErreur, Field(discriminator="type")]


class LigneFluxTexte(BaseModel):
    type: Literal["texte"]
    texte: str


class LigneFluxFin(BaseModel):
    type: Literal["fin"]
    message: MessageLLM


LigneFluxMission = Annotated[
    LigneFluxTexte | LigneFluxFin | LigneErreur, Field(discriminator="type")
]


class ReponseErreur(BaseModel):
    erreur: str


class DemandeModele(_Forbid):
    messages: list[MessageLLM] = Field(max_length=MESSAGES_MAX)
    outils: bool = False
    response_format: dict | None = None
    flux: bool = False


class ReponseModele(BaseModel):
    message: MessageLLM


class DemandeOutil(_Forbid):
    nom: str = Field(max_length=128)
    arguments: str = Field(max_length=200_000)  # JSON en chaîne, comme OpenAI


class ReponseOutil(BaseModel):
    resultat: str
    arret: bool = False


class Sante(BaseModel):
    contrat: str
    agent: str
    version: str


class ErreurMission(ErreurOutils):
    """Mission qui ne se termine pas proprement (agent injoignable, contrat, flux coupé, durée)."""


@dataclass(eq=False)
class Mission:
    id: str
    jeton: str = field(repr=False)
    agent: Agent
    llm: object
    outils: object | None
    schemas: list[dict]
    sur_appel: Callable[[str, str], Awaitable[None]]
    echeance: float
    version: str
    contexte: dict
    appels_modele: int = 0
    appels_tour: int = 0
    mal_formes: int = 0
    limite_atteinte: bool = False
    fermee: bool = False
    erreur: Exception | None = None
    tache: asyncio.Task | None = None  # lecture du flux de l'agent
    verrou: asyncio.Lock = field(default_factory=asyncio.Lock)  # une demande /interne/ à la fois
    en_vol: set[asyncio.Task] = field(default_factory=set)

    @property
    def noms(self) -> set[str]:
        return {s["function"]["name"] for s in self.schemas}


class Missions:
    """Registre en mémoire des missions en cours, retrouvées par leur jeton."""

    def __init__(
        self,
        secrets: dict[str, str],
        duree_s: int,
        transport: httpx.AsyncBaseTransport | None = None,
        horloge: Callable[[], float] = time.monotonic,
    ):
        self.secrets, self.duree_s, self.transport, self.horloge = (
            secrets,
            duree_s,
            transport,
            horloge,
        )
        self._en_cours: list[Mission] = []

    def ouvrir(self, llm, agent: Agent, outils, sur_appel, version: str) -> Mission:
        self._en_cours = [x for x in self._en_cours if self.horloge() <= x.echeance]
        contexte = dict(journal.contexte.get())
        offerts = {s["function"]["name"]: s for s in outils.schemas()} if outils else {}
        m = Mission(
            id=contexte.get("mission") or uuid.uuid4().hex[:12],
            jeton=secrets.token_urlsafe(32),
            agent=agent,
            llm=llm,
            outils=outils,
            schemas=[offerts[n] for n in agent.outils if n in offerts],
            sur_appel=sur_appel,
            echeance=self.horloge() + self.duree_s,
            version=version,
            contexte=contexte,
        )
        self._en_cours.append(m)
        return m

    def trouver(self, autorisation: str | None) -> Mission | None:
        schema, _, jeton = (autorisation or "").partition(" ")
        if schema != "Bearer" or not jeton:
            return None
        trouvee = None
        for m in self._en_cours:  # pas de sortie anticipée : temps indépendant du rang
            if secrets.compare_digest(m.jeton.encode(), jeton.encode()):
                trouvee = m
        if trouvee is None or self.horloge() > trouvee.echeance:
            return None
        return trouvee

    async def fermer(self, m: Mission) -> None:
        m.fermee = True  # avant d'annuler : plus aucun appel ne peut démarrer
        if m in self._en_cours:
            self._en_cours.remove(m)
        taches = list(m.en_vol)
        for t in taches:
            t.cancel()
        await asyncio.gather(*taches, return_exceptions=True)

    async def en_vol[T](self, m: Mission, attente: Awaitable[T]) -> T:
        """Exécute un appel comme tâche de la mission : annulé à sa fermeture, refusé après."""
        if m.fermee:
            if hasattr(attente, "close"):
                attente.close()  # coroutine jamais démarrée
            raise ErreurMission("mission arrêtée")
        tache = asyncio.ensure_future(attente)
        m.en_vol.add(tache)
        tache.add_done_callback(m.en_vol.discard)
        try:
            return await tache
        except asyncio.CancelledError:
            # annulé par `fermer`, pas la requête elle-même : l'appelant apprend l'arrêt
            if m.fermee and asyncio.current_task().cancelling() == 0:
                raise ErreurMission("mission arrêtée") from None
            raise


def lire_secrets(catalogue: Catalogue, environ: Mapping[str, str]) -> dict[str, str]:
    """Le secret de chaque agent à `service:` ; le message nomme la variable, jamais la valeur."""
    resultat, variables = {}, set()
    for nom, agent in catalogue.agents.items():
        if agent.service is None:
            continue
        variable = "PORTAIL_AGENT_SECRET_" + nom.upper().replace("-", "_")
        if variable in variables:
            raise CatalogueInvalide(
                f"agent « {nom} » : {variable} est partagée avec un autre agent"
            )
        variables.add(variable)
        valeur = environ.get(variable, "").strip()
        if len(valeur) < 32:
            raise CatalogueInvalide(
                f"agent « {nom} » : {variable} doit faire au moins 32 caractères"
            )
        resultat[nom] = valeur
    return resultat
