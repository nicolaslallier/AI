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
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from portail import journal, metriques
from portail.agents import Agent, Catalogue, CatalogueInvalide
from portail.boucle import (
    _IGNORE,
    _MAL_FORMES_MAX,
    _MAX_APPELS_PAR_TOUR,
    ErreurOutils,
    ResultatBoucle,
    _libelle,
    _outil_mesure,
    boucle_outils,
)
from portail.llm import ErreurLLM, FiltreReflexion, retirer_reflexion

logger = logging.getLogger(__name__)

CONTRAT = "v1"
LIGNE_MAX = 4_000_000  # octets, une ligne de la réponse d'un agent
LIGNES_MAX = 100_000  # lignes de la réponse d'un agent
TOTAL_MAX = 64_000_000  # octets de la réponse d'un agent, toutes lignes confondues
FORMAT_MAX = 32_000  # caractères du `response_format` demandé par un agent
SANTE_MAX = 4096  # octets


class _Forbid(BaseModel):
    model_config = ConfigDict(extra="forbid")


MESSAGES_MAX = 2000
CONTENU_MAX = 500_000


class _Fonction(_Forbid):
    name: str = Field(max_length=128)
    arguments: str = Field(max_length=200_000)


class AppelOutil(_Forbid):
    id: str = Field(max_length=200)
    type: Literal["function"]
    function: _Fonction


class MessageLLM(_Forbid):
    """Un message de la conversation : champs explicites, rien d'inventé ne passe au modèle."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = Field(default=None, max_length=CONTENU_MAX)
    tool_calls: list[AppelOutil] | None = Field(default=None, max_length=64)
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
    texte: str = Field(max_length=CONTENU_MAX)


class LigneFin(BaseModel):
    type: Literal["fin"]
    texte: str = Field(max_length=CONTENU_MAX)
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

    @field_validator("response_format")
    @classmethod
    def _format_permis(cls, v: dict | None) -> dict | None:
        """Seulement `json_object` ou `json_schema`, et petit : il est relayé au modèle tel quel."""
        if v is None:
            return v
        objet = v == {"type": "json_object"}
        schema = (
            v.get("type") == "json_schema"
            and set(v) == {"type", "json_schema"}
            and isinstance(v["json_schema"], dict)
        )
        if not (objet or schema) or len(json.dumps(v)) > FORMAT_MAX:
            raise ValueError("response_format refusé")
        return v


class ReponseModele(BaseModel):
    message: MessageLLM


class DemandeOutil(_Forbid):
    nom: str = Field(max_length=128)
    arguments: str = Field(max_length=200_000)  # JSON en chaîne, comme OpenAI


class ReponseOutil(BaseModel):
    resultat: str
    arret: bool = False


class Sante(BaseModel):
    """Réponse d'un conteneur non fiable : bornée, d'un jeu de caractères sûr, sinon écartée."""

    contrat: str = Field(max_length=16, pattern=r"^[\w.-]+$")
    agent: str = Field(max_length=64, pattern=r"^[\w-]+$")
    version: str = Field(max_length=64, pattern=r"^[\w.:@+-]+$")


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
    # ponytail: reste posé si une réponse en flux ne démarre jamais ; borné par l'échéance de la mission.
    occupee: bool = False  # une demande /interne/ à la fois : la suivante est refusée (429)
    outils_ouverts: bool = False  # le dernier appel au modèle a offert les outils
    en_vol: set[asyncio.Task] = field(default_factory=set)

    def prendre(self) -> bool:
        if self.occupee or self.fermee:
            return False
        self.occupee = True
        return True

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
        self.sondes: dict[str, tuple[float, Sante | None]] = {}  # cache du bureau, par agent

    def ouvrir(self, llm, agent: Agent, outils, sur_appel, version: str) -> Mission:
        for x in [x for x in self._en_cours if self.horloge() > x.echeance]:
            self._clore(x)
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

    def _clore(self, m: Mission) -> list[asyncio.Task]:
        """Ferme sans attendre : plus aucun appel ne démarre, les appels en vol sont annulés."""
        m.fermee, m.occupee = True, False  # avant d'annuler
        if m in self._en_cours:
            self._en_cours.remove(m)
        taches = list(m.en_vol)
        if m.tache is not None:  # le flux vers l'agent : sa connexion se coupe, l'agent annule
            taches.append(m.tache)
        for t in taches:
            t.cancel()
        return taches

    async def fermer(self, m: Mission) -> None:
        await asyncio.gather(*self._clore(m), return_exceptions=True)

    async def sante(self, agent: Agent, delai_s: float = 2) -> Sante | None:
        """`None` si l'agent est injoignable, trop lent, répond autre chose que 200 ou du n'importe quoi."""
        try:
            async with (
                asyncio.timeout(delai_s),  # le délai de httpx vaut par lecture : celui-ci, au total
                httpx.AsyncClient(transport=self.transport, timeout=delai_s) as client,
                client.stream("GET", f"{agent.service}/sante") as r,
            ):
                if r.status_code != 200:
                    return None
                corps = bytearray()
                async for morceau in r.aiter_bytes():
                    corps += morceau
                    if len(corps) > SANTE_MAX:
                        return None
            return Sante.model_validate_json(bytes(corps))
        except (httpx.HTTPError, ValueError, TimeoutError):
            return None

    async def faire_tourner(
        self,
        llm,
        agent: Agent,
        messages: list[dict],
        outils,
        sur_appel: Callable[[str, str], Awaitable[None]],
        *,
        sur_texte: Callable[[str], Awaitable[None]] | None = None,
        response_format: dict | None = None,
    ) -> ResultatBoucle:
        """Une mission dans le conteneur de l'agent. L'agent n'est pas fiable : seules les lignes
        du contrat sont lues, et l'erreur que le portail a vue passe avant celle de l'agent."""
        s = await self.sante(agent)
        if s is None:
            raise ErreurMission(f"agent « {agent.nom} » injoignable")
        if s.contrat != CONTRAT:
            raise ErreurMission(f"agent « {agent.nom} » : contrat incompatible")
        if s.agent != agent.nom:  # avant d'envoyer le secret : un `service:` mal configuré
            raise ErreurMission(f"agent « {agent.nom} » : agent inattendu")
        secret = self.secrets.get(agent.nom)
        if secret is None:
            raise ErreurMission(f"agent « {agent.nom} » : secret absent")
        m, fin, echec = None, None, None
        try:
            m = self.ouvrir(llm, agent, outils, sur_appel, s.version)
            try:
                demande = DemandeMission(
                    contrat=CONTRAT,
                    mission=m.id,
                    agent=agent.nom,
                    jeton=m.jeton,
                    messages=[MessageLLM.model_validate(x) for x in messages],
                    outils=m.schemas,
                    parametres=ParametresAgent(
                        modele=agent.modele,
                        temperature=agent.temperature,
                        contexte_max=agent.contexte_max,
                        tours_max=agent.tours_max,
                        produit=agent.produit,
                        role=agent.role,
                    ),
                    response_format=response_format,
                    flux=sur_texte is not None and not m.schemas,
                )
            except ValidationError:  # le détail reprendrait le contenu des messages
                raise ErreurMission(
                    f"agent « {agent.nom} » : messages refusés par le contrat"
                ) from None
            m.tache = asyncio.ensure_future(self._lire(agent, secret, demande, sur_texte))
            try:
                async with asyncio.timeout(max(m.echeance - self.horloge(), 0)):
                    await asyncio.wait({m.tache})
            except TimeoutError:
                echec = ErreurMission("durée de mission dépassée")
            else:
                if m.tache.cancelled():  # le portail a coupé le flux : `m.erreur` dira pourquoi
                    echec = ErreurMission(f"agent « {agent.nom} » : mission interrompue")
                else:
                    echec = m.tache.exception()
                    fin = None if echec else m.tache.result()
        finally:
            if m is not None:
                await self.fermer(m)
                if m.appels_modele:
                    try:
                        metriques.TOURS_MISSION.labels(agent=agent.nom).observe(m.appels_modele)
                    except Exception:  # noqa: BLE001 (une métrique ne masque ni l'erreur ni l'annulation)
                        journal.erreur(logger, "métrique des tours non enregistrée")
        if m.erreur is not None:  # ce que le portail a vu prime sur ce que l'agent raconte
            raise m.erreur
        if echec is not None:
            raise echec
        messages[:] = [x.model_dump(exclude_none=True) for x in fin.messages]
        return ResultatBoucle(texte=fin.texte, limite_atteinte=m.limite_atteinte)

    async def _lire(
        self, agent: Agent, secret: str, demande: DemandeMission, sur_texte
    ) -> LigneFin:
        interrompue = ErreurMission(f"agent « {agent.nom} » : mission interrompue")
        relaye = 0  # caractères de `texte` relayés : un flot de lignes courtes coûte aussi
        lignes = TypeAdapter(LigneMission)
        try:
            async with (
                httpx.AsyncClient(
                    transport=self.transport,
                    timeout=httpx.Timeout(self.duree_s, connect=10),
                    follow_redirects=False,
                ) as client,
                client.stream(
                    "POST",
                    f"{agent.service}/missions",
                    content=demande.model_dump_json(),  # le jeton est dans le corps, jamais journalisé
                    headers={
                        "Authorization": f"Bearer {secret}",
                        "Content-Type": "application/json",
                    },
                ) as r,
            ):
                if r.status_code != 200:
                    raise ErreurMission(
                        f"agent « {agent.nom} » a refusé la mission ({r.status_code})"
                    )
                async for brut in _lignes_bornees(r):
                    try:
                        ligne = lignes.validate_json(brut)
                    except ValidationError:  # le détail reprendrait la ligne de l'agent
                        raise interrompue from None
                    if isinstance(ligne, LigneTexte):
                        relaye += len(ligne.texte)
                        if relaye > CONTENU_MAX:
                            raise interrompue
                        if sur_texte is not None:
                            await sur_texte(ligne.texte)
                    elif isinstance(ligne, LigneFin):
                        return ligne
                    else:
                        # texte fixe : celui de l'agent finirait en base, en commentaire de PR
                        raise ErreurMission(f"agent « {agent.nom} » : mission en erreur")
        except (httpx.HTTPError, ValueError):  # réponse hors bornes, ou illisible
            raise interrompue from None
        raise interrompue  # flux fini sans ligne `fin`

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


async def _lignes_bornees(reponse: httpx.Response):
    """Les lignes non vides de la réponse d'un agent : nombre, taille et total bornés, lecture
    linéaire (un `\\n` n'est cherché que dans les octets nouveaux, les octets rendus sont retirés)."""
    tampon, total, n = bytearray(), 0, 0
    async for morceau in reponse.aiter_bytes():
        total += len(morceau)
        deja_vu = len(tampon)  # sans saut de ligne
        tampon += morceau
        debut = 0
        while (i := tampon.find(b"\n", max(debut, deja_vu))) >= 0:
            ligne, debut = tampon[debut:i], i + 1
            n += 1
            if n > LIGNES_MAX or len(ligne) > LIGNE_MAX or total > TOTAL_MAX:
                raise ValueError("réponse de l'agent hors bornes")
            if ligne.strip():
                yield bytes(ligne)
        del tampon[:debut]
        if len(tampon) > LIGNE_MAX or total > TOTAL_MAX:
            raise ValueError("réponse de l'agent hors bornes")
    if tampon.strip():
        yield bytes(tampon)


async def _rien(libelle: str, resultat: str) -> None:
    return None


async def tourner(llm, missions: Missions | None, agent: Agent, messages, outils, sur_appel):
    """`boucle_outils` dans le portail, ou une mission dans le conteneur si l'agent a un `service:`."""
    if agent.service is None:
        return await boucle_outils(llm, agent, messages, outils, sur_appel)
    if missions is None:
        raise ErreurMission("registre des missions absent")
    return await missions.faire_tourner(llm, agent, messages, outils, sur_appel)


async def streamer(llm, missions: Missions | None, agent: Agent, messages, sur_texte) -> str:
    """Le texte d'un agent à `service:` sans outils, relayé morceau par morceau à `sur_texte`."""
    if missions is None:
        raise ErreurMission("registre des missions absent")
    r = await missions.faire_tourner(llm, agent, messages, None, _rien, sur_texte=sur_texte)
    return r.texte.strip()


async def completer(
    llm, missions: Missions | None, agent: Agent, messages, response_format: dict | None
) -> str:
    """Une réponse structurée sans outils ; avec un `service:`, c'est une nouvelle mission."""
    if agent.service is None:
        reponse = await llm.completer(
            agent.modele,
            messages,
            agent.temperature,
            response_format=response_format,
            sortie_max=agent.sortie_max,
        )
        return retirer_reflexion(reponse.get("content") or "")
    if missions is None:
        raise ErreurMission("registre des missions absent")
    # copie : l'historique de l'appelant est le sien, comme avec l'appel direct
    r = await missions.faire_tourner(
        llm, agent, list(messages), None, _rien, response_format=response_format
    )
    return r.texte


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
    longueur = request.headers.get("content-length") or "0"
    if not longueur.isdigit() or int(longueur) > CORPS_MAX:
        return _erreur(413, "demande trop grande")
    corps = bytearray()
    async for morceau in request.stream():
        corps += morceau
        if len(corps) > CORPS_MAX:
            return _erreur(413, "demande trop grande")
    try:
        return modele.model_validate_json(bytes(corps))
    except ValueError:  # JSON illisible, champ inconnu, borne dépassée : refus sans détail
        return _erreur(422, "demande invalide")


def _jetons(messages: list[dict], response_format: dict | None = None) -> int:
    """Même estimation que `contexte.estimer_jetons`, sur le message entier (pas `content` seul),
    plus le format de réponse, relayé au modèle."""
    reste = json.dumps(response_format, ensure_ascii=False) if response_format else ""
    return sum(len(json.dumps(m, ensure_ascii=False)) // 4 + 4 for m in messages) + len(reste) // 4


def _noter_erreur(m: Mission, e: Exception) -> None:
    """Retient l'erreur que le portail a vue et coupe le flux vers l'agent."""
    if m.erreur is None:
        m.erreur = e
    if m.tache is not None:
        m.tache.cancel()


def _contexte_journal(m: Mission) -> None:
    # la requête tourne dans une autre tâche que l'appelant : on repose son contexte
    journal.commencer(**{**m.contexte, "lieu": "conteneur", "version_image": m.version})


def _ligne(objet: dict) -> bytes:
    return (json.dumps(objet, ensure_ascii=False) + "\n").encode()


def _appels_rendus(appels: list) -> list[dict]:
    """Des appels d'outils rejouables tels quels : id, type, nom et arguments en chaîne."""
    rendus = []
    for i, appel in enumerate(appels[:64]):
        appel = appel if isinstance(appel, dict) else {}
        fonction = appel.get("function")
        fonction = fonction if isinstance(fonction, dict) else {}
        arguments = fonction.get("arguments")
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments, default=str)
        nom, id_ = fonction.get("name"), appel.get("id")
        rendus.append(
            {
                "id": id_ if isinstance(id_, str) and id_ else f"appel_{i}",
                "type": "function",
                "function": {
                    "name": nom if isinstance(nom, str) else "inconnu",
                    "arguments": arguments,
                },
            }
        )
    return rendus


def _message_rendu(message: dict) -> dict:
    """Ce que l'agent reçoit : role, content (sans réflexion) et tool_calls, rien d'autre."""
    rendu = {"role": "assistant", "content": message.get("content")}
    if isinstance(rendu["content"], str):
        rendu["content"] = retirer_reflexion(rendu["content"])
    if isinstance(message.get("tool_calls"), list) and message["tool_calls"]:
        rendu["tool_calls"] = _appels_rendus(message["tool_calls"])
    return rendu


_MODELE_INDISPONIBLE = ErreurLLM("appel au modèle en échec")  # message fixe, jamais celui reçu


def _erreur_modele(m: Mission, e: Exception) -> ErreurLLM:
    """L'erreur retenue : celle du modèle, ou un message fixe pour toute autre exception."""
    if not isinstance(e, ErreurLLM):
        journal.erreur(logger, "appel au modèle en échec (%s)", type(e).__name__)
        e = ErreurLLM(str(_MODELE_INDISPONIBLE))
    _noter_erreur(m, e)
    return e


async def _pomper(m: Mission, messages: list[dict], file: asyncio.Queue) -> None:
    try:
        async for morceau in m.llm.flux(
            m.agent.modele, messages, m.agent.temperature, m.agent.sortie_max
        ):
            await file.put(morceau)  # file bornée : un agent qui ne lit plus ralentit le modèle
        await file.put(None)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001 (toute panne du modèle devient une ligne d'erreur fixe)
        await file.put(_erreur_modele(m, e))


def _vider(file: asyncio.Queue) -> None:
    while not file.empty():
        file.get_nowait()


async def _flux_modele(missions: Missions, m: Mission, messages: list[dict]):
    """Rend la main de la mission (`m.occupee`) à la fin du flux, quelle qu'en soit la cause."""
    tache = None
    try:
        if m.fermee or m.erreur is not None:
            yield _ligne({"type": "erreur", "erreur": "mission arrêtée"})
            return
        _contexte_journal(m)
        file: asyncio.Queue = asyncio.Queue(maxsize=64)
        # tâche en vol : `fermer` l'annule, et le flux se termine au lieu de tenir la mission
        tache = asyncio.ensure_future(missions.en_vol(m, _pomper(m, messages, file)))

        def _fini(t: asyncio.Task) -> None:
            if t.cancelled() or t.exception() is not None:
                _vider(file)  # flux abandonné : on réveille le lecteur sans rien garder
                file.put_nowait(None)

        tache.add_done_callback(_fini)
        filtre, brut = FiltreReflexion(), ""
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
        if tache is not None:
            tache.cancel()  # connexion coupée par l'agent : l'appel au modèle s'arrête
        if not m.fermee:  # après `fermer`, la mission n'est plus à personne
            m.occupee = False


@ROUTEUR_INTERNE.post("/modele")
async def modele(request: Request):
    missions: Missions = request.app.state.missions
    m = _mission(request)
    if m is None:
        return _erreur(401, "jeton de mission invalide")
    if m.fermee or m.erreur is not None:
        return _arretee()
    if not m.prendre():  # avant de lire le corps : une demande à la fois par mission
        return _erreur(429, "une demande est déjà en cours")
    garde = False  # le flux garde la mission jusqu'à sa fin
    try:
        try:
            d = await missions.en_vol(m, lire_corps(request, DemandeModele))
        except ErreurMission:
            return _arretee()
        if isinstance(d, JSONResponse):
            return d
        if m.fermee or m.erreur is not None or missions.horloge() > m.echeance:
            return _arretee()
        if d.flux and d.outils:
            return _erreur(422, "flux permis seulement sans outils")
        messages = [x.model_dump(exclude_unset=True) for x in d.messages]
        agent = m.agent
        if _jetons(messages, d.response_format) > agent.contexte_max:  # l'élagage est à l'agent
            return _erreur(413, "contexte dépassé")
        if m.appels_modele >= agent.tours_max + 1:
            m.limite_atteinte = True
            m.outils_ouverts = False
            return _erreur(429, "limite d'appels au modèle atteinte")
        m.appels_modele += 1
        m.appels_tour = 0
        arret = getattr(m.outils, "arret", False)  # une action proposée : on conclut sans outils
        dernier = (
            m.appels_modele > agent.tours_max
        )  # comme boucle.py : le dernier appel sans outils
        if dernier:
            m.limite_atteinte = True
        offerts = m.schemas if d.outils and m.schemas and not arret and not dernier else None
        m.outils_ouverts = offerts is not None
        if d.flux:
            garde = True
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
                    sortie_max=agent.sortie_max,
                ),
            )
        except ErreurMission:
            return _arretee()
        except Exception as e:  # noqa: BLE001 (le texte de LiteLLM ne part pas vers l'agent)
            _erreur_modele(m, e)
            return _erreur(502, "modèle indisponible")
        return {"message": _message_rendu(message)}
    finally:
        if not garde and not m.fermee:
            m.occupee = False


def _compter(m: Mission, mal_forme: bool) -> JSONResponse | None:
    """Trois appels mal formés de suite arrêtent la mission, comme dans `boucle_outils`."""
    m.mal_formes = m.mal_formes + 1 if mal_forme else 0
    if m.mal_formes < _MAL_FORMES_MAX:
        return None
    _noter_erreur(
        m, ErreurOutils(f"le modèle {m.agent.modele} ne gère pas correctement les outils")
    )
    return _arretee()


@ROUTEUR_INTERNE.post("/outils")
async def outils(request: Request):
    missions: Missions = request.app.state.missions
    m = _mission(request)
    if m is None:
        return _erreur(401, "jeton de mission invalide")
    if m.fermee or m.erreur is not None:
        return _arretee()
    if not m.prendre():
        return _erreur(429, "une demande est déjà en cours")
    try:
        try:
            d = await missions.en_vol(m, lire_corps(request, DemandeOutil))
        except ErreurMission:
            return _arretee()
        if m.fermee or m.erreur is not None or missions.horloge() > m.echeance:
            return _arretee()
        if not m.outils_ouverts:  # aucun appel au modèle ne les a offerts (ou plus)
            return _erreur(409, "outils non offerts")
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
                return _arretee()
            libelle = _libelle(d.nom, d.arguments)
        _outil_mesure(d.nom, m.agent, resultat, True)
        arret = _compter(m, mal_forme)
        try:
            await missions.en_vol(m, m.sur_appel(libelle, resultat))  # annulé à la fermeture
        except ErreurMission:
            return _arretee()
        except Exception as e:  # noqa: BLE001 (l'appel n'a pas pu être enregistré : on s'arrête)
            journal.erreur(logger, "appel d'outil non enregistré")
            _noter_erreur(m, ErreurOutils(f"appel d'outil non enregistré ({type(e).__name__})"))
            return _arretee()
        return arret or {"resultat": resultat, "arret": getattr(m.outils, "arret", False)}
    finally:
        if not m.fermee:
            m.occupee = False
