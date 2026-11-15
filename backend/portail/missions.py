"""Contrat `v1` entre le portail et les agents en conteneur (voir docs/agents-contrat-v1.md).

Les demandes venues d'un agent sont en `extra="forbid"` : le portail n'y lit que ce qu'il
autorise (messages, drapeau `outils`, `response_format`, `flux`, nom et arguments d'un outil).
"""

import asyncio
import json
import logging
import secrets
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from portail import journal
from portail.agents import Agent, Catalogue, CatalogueInvalide
from portail.boucle import (
    _IGNORE,
    _MAL_FORMES_MAX,
    _MAX_APPELS_PAR_TOUR,
    ErreurOutils,
    _libelle,
    _outil_mesure,
)
from portail.llm import ErreurLLM, FiltreReflexion, retirer_reflexion

logger = logging.getLogger(__name__)

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


# --- routes /interne/ : appelées par les agents en conteneur, authentifiées par le jeton de mission

ROUTEUR_INTERNE = APIRouter(prefix="/interne", include_in_schema=False)
CORPS_MAX = 4_000_000  # octets


def _erreur(code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"erreur": message})


def _arretee() -> JSONResponse:
    return _erreur(409, "mission arrêtée")


def _mission(request: Request) -> Mission | None:
    return request.app.state.missions.trouver(request.headers.get("Authorization"))


async def lire_corps[T: BaseModel](request: Request, modele: type[T]) -> T | JSONResponse:
    """Lit et valide à la main : le 422 par défaut de FastAPI recopierait le contenu reçu."""
    if int(request.headers.get("content-length") or 0) > CORPS_MAX:
        return _erreur(413, "demande trop grande")
    corps = b""
    async for morceau in request.stream():
        corps += morceau
        if len(corps) > CORPS_MAX:
            return _erreur(413, "demande trop grande")
    try:
        return modele.model_validate_json(corps)
    except ValueError:  # JSON illisible, champ inconnu, borne dépassée : refus sans détail
        return _erreur(422, "demande invalide")


def _jetons(messages: list[dict]) -> int:
    """Même estimation que `contexte.estimer_jetons`, sur le message entier (pas `content` seul)."""
    return sum(len(json.dumps(m, ensure_ascii=False)) // 4 + 4 for m in messages)


def _noter_erreur(m: Mission, e: Exception) -> None:
    if m.erreur is None:
        m.erreur = e


def _contexte_journal(m: Mission) -> None:
    # la requête tourne dans une autre tâche que l'appelant : on repose son contexte
    journal.commencer(**m.contexte, lieu="conteneur", version_image=m.version)


def _ligne(objet: dict) -> bytes:
    return (json.dumps(objet, ensure_ascii=False) + "\n").encode()


def _message_rendu(message: dict) -> dict:
    """Ce que l'agent reçoit : role, content (sans réflexion) et tool_calls, rien d'autre."""
    rendu = {"role": "assistant", "content": message.get("content")}
    if isinstance(rendu["content"], str):
        rendu["content"] = retirer_reflexion(rendu["content"])
    if message.get("tool_calls"):
        rendu["tool_calls"] = message["tool_calls"]
    return rendu


async def _pomper(m: Mission, messages: list[dict], file: asyncio.Queue) -> None:
    try:
        async for morceau in m.llm.flux(m.agent.modele, messages, m.agent.temperature):
            await file.put(morceau)
    except ErreurLLM as e:
        _noter_erreur(m, e)
        await file.put(e)


async def _flux_modele(missions: Missions, m: Mission, messages: list[dict]):
    async with m.verrou:  # tenu pendant tout le flux
        if m.fermee or m.erreur is not None:
            yield _ligne({"type": "erreur", "erreur": "mission arrêtée"})
            return
        _contexte_journal(m)
        file: asyncio.Queue = asyncio.Queue()
        # tâche en vol : `fermer` l'annule, et le flux se termine au lieu de tenir le verrou
        tache = asyncio.ensure_future(missions.en_vol(m, _pomper(m, messages, file)))
        tache.add_done_callback(lambda _: file.put_nowait(None))
        filtre, brut = FiltreReflexion(), ""
        try:
            while (morceau := await file.get()) is not None:
                if isinstance(morceau, ErreurLLM):
                    yield _ligne({"type": "erreur", "erreur": "modèle indisponible"})
                    return
                brut += morceau
                if part := filtre.envoyer(morceau):
                    yield _ligne({"type": "texte", "texte": part})
            try:
                await tache
            except ErreurMission:
                yield _ligne({"type": "erreur", "erreur": "mission arrêtée"})
                return
            fin = {"role": "assistant", "content": retirer_reflexion(brut).strip()}
            yield _ligne({"type": "fin", "message": fin})
        finally:
            tache.cancel()  # connexion coupée par l'agent : l'appel au modèle s'arrête


@ROUTEUR_INTERNE.post("/modele")
async def modele(request: Request):
    missions: Missions = request.app.state.missions
    m = _mission(request)
    if m is None:
        return _erreur(401, "jeton de mission invalide")
    d = await lire_corps(request, DemandeModele)
    if isinstance(d, JSONResponse):
        return d
    if d.flux and d.outils:
        return _erreur(422, "flux permis seulement sans outils")
    messages = [x.model_dump(exclude_unset=True) for x in d.messages]
    agent = m.agent
    if _jetons(messages) > agent.contexte_max:  # l'élagage est l'affaire de l'agent
        return _erreur(413, "contexte dépassé")
    async with m.verrou:
        if m.fermee or m.erreur is not None:
            return _arretee()
        if m.appels_modele >= agent.tours_max + 1:
            m.limite_atteinte = True
            return _erreur(429, "limite d'appels au modèle atteinte")
        m.appels_modele += 1
        m.appels_tour = 0
        arret = getattr(m.outils, "arret", False)  # une action proposée : on conclut sans outils
        offerts = m.schemas if d.outils and m.schemas and not arret else None
        if d.flux:
            return StreamingResponse(
                _flux_modele(missions, m, messages), media_type="application/x-ndjson"
            )
        _contexte_journal(m)
        try:
            message = await missions.en_vol(
                m,
                m.llm.completer(
                    agent.modele,
                    messages,
                    agent.temperature,
                    outils=offerts,
                    response_format=d.response_format,
                ),
            )
        except ErreurMission:
            return _arretee()
        except ErreurLLM as e:  # le texte de LiteLLM ne part pas vers l'agent
            _noter_erreur(m, e)
            return _erreur(502, "modèle indisponible")
    return {"message": _message_rendu(message)}


def _compter(m: Mission, mal_forme: bool) -> JSONResponse | None:
    """Trois appels mal formés de suite arrêtent la mission, comme dans `boucle_outils`."""
    m.mal_formes = m.mal_formes + 1 if mal_forme else 0
    if m.mal_formes < _MAL_FORMES_MAX:
        return None
    _noter_erreur(
        m, ErreurOutils(f"le modèle {m.agent.modele} ne gère pas correctement les outils")
    )
    if m.tache is not None:
        m.tache.cancel()
    return _arretee()


@ROUTEUR_INTERNE.post("/outils")
async def outils(request: Request):
    missions: Missions = request.app.state.missions
    m = _mission(request)
    if m is None:
        return _erreur(401, "jeton de mission invalide")
    if m.fermee or m.erreur is not None:
        return _arretee()
    d = await lire_corps(request, DemandeOutil)
    async with m.verrou:
        if m.fermee or m.erreur is not None:
            return _arretee()
        if isinstance(d, JSONResponse):  # demande invalide : compte comme un appel mal formé
            if d.status_code == 422:
                _outil_mesure(None, m.agent, "", False)
                return _compter(m, True) or d
            return d
        if getattr(m.outils, "arret", False):  # une action est proposée : rien ne s'exécute
            return {"resultat": _IGNORE, "arret": True}
        m.appels_tour += 1
        if m.appels_tour > _MAX_APPELS_PAR_TOUR:
            return {"resultat": "erreur : trop d'appels dans un même tour, ignoré", "arret": False}
        if d.nom not in m.noms:  # pas offert à cette mission, même s'il est dans agent.outils
            resultat, mal_forme, libelle = f"erreur : outil non autorisé : {d.nom}", True, d.nom
        else:
            _contexte_journal(m)
            try:
                resultat, mal_forme = await missions.en_vol(
                    m, m.outils.executer(d.nom, d.arguments)
                )
            except ErreurMission:
                return _arretee()
            except Exception as e:  # noqa: BLE001 (un outil qui lève ne laisse pas de requête en 500)
                journal.erreur(logger, "outil %s en échec", d.nom)
                _noter_erreur(m, ErreurOutils(f"outil {d.nom} en échec ({type(e).__name__})"))
                if m.tache is not None:
                    m.tache.cancel()
                return _arretee()
            libelle = _libelle(d.nom, d.arguments)
        _outil_mesure(d.nom, m.agent, resultat, True)
        arret = _compter(m, mal_forme)
        try:
            await m.sur_appel(libelle, resultat)
        except Exception as e:  # noqa: BLE001 (l'appel n'a pas pu être enregistré : on s'arrête)
            journal.erreur(logger, "appel d'outil non enregistré")
            _noter_erreur(m, ErreurOutils(f"appel d'outil non enregistré ({type(e).__name__})"))
            if m.tache is not None:
                m.tache.cancel()
            return _arretee()
        return arret or {"resultat": resultat, "arret": getattr(m.outils, "arret", False)}
