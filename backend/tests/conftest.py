import asyncio
import contextlib
import json
import os
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text

from portail import journal
from portail.agents import OUTILS_LECTURE_PORTAIL, OUTILS_PORTAIL, Agent, Catalogue
from portail.api import create_app
from portail.config import Reglages
from portail.db import Base, creer_moteur, fabrique_sessions
from portail.github import CommentaireGitHub
from portail.lanceur import Resultat
from portail.missions import ROUTEUR_INTERNE, DemandeMission, Missions

URL = os.environ.get(
    "PORTAIL_TEST_DATABASE_URL", "postgresql+psycopg://portail:portail@localhost:5433/portail_test"
)


@pytest.fixture(scope="session")
def schema():
    # moteur synchrone : un moteur async de session serait lié à une autre boucle d'événements
    m = create_engine(URL)
    Base.metadata.create_all(m)
    m.dispose()


@pytest_asyncio.fixture
async def moteur(schema):
    m = creer_moteur(URL)
    yield m
    async with m.begin() as c:
        tables = ", ".join(Base.metadata.tables)
        await c.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    await m.dispose()


@pytest.fixture
def sessions(moteur):
    return fabrique_sessions(moteur)


# --- API ---------------------------------------------------------------


class FauxLLM:
    """Même signature que ClientLLM.flux. `morceaux` est renvoyé, puis `exception` est levée."""

    def __init__(self):
        self.morceaux: list[str | asyncio.Event] = []  # un Event met le flux en pause
        self.exception: Exception | None = None
        self.appels: list[dict] = []  # {"modele", "messages", "temperature"}
        self.reponses: list[dict | asyncio.Event] = []  # renvoyés tour à tour par `completer`
        # morceaux propres à chaque appel de `flux`, tour à tour ; vide : `morceaux` à chaque appel
        self.file: list[list[str | asyncio.Event]] = []

    async def flux(self, modele, messages, temperature):
        self.appels.append(
            {
                "modele": modele,
                "messages": messages,
                "temperature": temperature,
                "contexte": dict(journal.contexte.get()),
            }
        )
        for m in self.file.pop(0) if self.file else self.morceaux:
            if isinstance(m, asyncio.Event):
                await m.wait()
            else:
                yield m
        if self.exception:
            raise self.exception

    async def completer(self, modele, messages, temperature, outils=None, response_format=None):
        self.appels.append(
            {
                "modele": modele,
                "messages": [dict(m) for m in messages],  # copie : la boucle ajoute ensuite
                "temperature": temperature,
                "outils": outils,
                "response_format": response_format,
                "contexte": dict(journal.contexte.get()),
            }
        )
        if self.exception:
            raise self.exception
        reponse = self.reponses.pop(0)
        if isinstance(reponse, asyncio.Event):  # un Event bloque l'appel jusqu'à son signal
            await reponse.wait()
            reponse = self.reponses.pop(0)
        return reponse


def _agent(nom, contexte_max=32768, **kw):
    return Agent(
        nom=nom, description=nom, modele="m", prompt_systeme=f"Tu es {nom}.",
        contexte_max=contexte_max, **kw,
    )  # fmt: skip


OUTILS = ["lister", "lire", "chercher"]

CATALOGUE_TEST = Catalogue(
    agents={
        "spec": _agent("spec", consigne_redaction="Rédige la spec.", outils=OUTILS),
        "orchestrateur": _agent("orchestrateur", outils=list(OUTILS_PORTAIL)),
        "pm": _agent("pm", outils=list(OUTILS_LECTURE_PORTAIL)),
        "a": _agent("a"),
        "b": _agent("b"),
        "petit": _agent("petit", contexte_max=50),
        "plan": _agent(
            "plan", consigne_redaction="Rédige le plan.", produit="plan", auto=True, outils=OUTILS
        ),
        "taches": _agent(
            "taches", consigne_redaction="Propose les tâches.", produit="taches", auto=True
        ),
        "vision": _agent(
            "vision", consigne_redaction="Rédige la vision.", produit="vision", prefixe="mot-"
        ),
        "volet": _agent(
            "volet",
            consigne_redaction="Rédige le volet.",
            produit="volet",
            prefixe="aff-",
            volet="affaires",
            auto=True,
            sans_validation=True,
        ),
        "synthese": _agent(
            "synthese",
            consigne_redaction="Rédige la synthèse.",
            produit="architecture",
            prefixe="ent-",
            auto=True,
        ),
    },
    pipelines={
        "spec": ["spec"],
        "double": ["a", "b"],
        "petit": ["petit"],
        "planification": ["plan", "taches"],
        "architecture": ["vision", "volet", "synthese"],
    },
)


@pytest.fixture
def reglages(schema, tmp_path):
    return Reglages(database_url=URL, donnees_dir=tmp_path / "donnees", resume_heure="")


@pytest.fixture
def faux_llm():
    return FauxLLM()


@pytest_asyncio.fixture
async def client(moteur, reglages, faux_llm):
    app = create_app(reglages=reglages, llm=faux_llm, catalogue=CATALOGUE_TEST)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://t") as c,
    ):
        yield c


@pytest_asyncio.fixture
async def client_conteneur(moteur, reglages, faux_llm):
    """Fabrique `(catalogue, faux_agent) -> client` : l'application tourne avec les missions du faux."""
    async with contextlib.AsyncExitStack() as pile:

        async def fabriquer(catalogue, faux):
            app = create_app(
                reglages=reglages, llm=faux_llm, catalogue=catalogue, missions=faux.registre
            )
            await pile.enter_async_context(LifespanManager(app))
            return await pile.enter_async_context(
                AsyncClient(transport=ASGITransport(app), base_url="http://t")
            )

        yield fabriquer


# --- routes /interne/ ----------------------------------------------------


class Horloge:
    """Horloge des tests : `t` avance quand le test le décide."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Interne:
    """Une `FastAPI` nue avec les routes `/interne/`, sans base ni lifespan."""

    def __init__(self, faux_llm):
        self.llm = faux_llm
        self.horloge = Horloge()
        self.missions = Missions({}, 60, horloge=self.horloge)
        app = FastAPI()
        app.state.missions = self.missions
        app.include_router(ROUTEUR_INTERNE)
        self.client = AsyncClient(transport=ASGITransport(app), base_url="http://t")

    def ouvrir(self, agent=None, outils=None, llm=None, sur_appel=None, version="v0"):
        async def rien(libelle, resultat):
            return None

        m = self.missions.ouvrir(
            llm or self.llm, agent or _agent("revue"), outils, sur_appel or rien, version
        )
        m.outils_ouverts = bool(outils)  # comme si un appel au modèle avait offert les outils
        return m

    async def post(self, chemin, m, corps, **kw):
        return await self.client.post(
            f"/interne/{chemin}", json=corps, headers={"Authorization": f"Bearer {m.jeton}"}, **kw
        )


@pytest_asyncio.fixture
async def interne(faux_llm):
    i = Interne(faux_llm)
    yield i
    await i.client.aclose()


# --- agent en conteneur ---------------------------------------------------


class _FluxAgent(httpx.AsyncByteStream):
    """Réponse de `/missions` : l'agent tourne dans sa propre tâche, comme dans son conteneur."""

    def __init__(self, faux, demande):
        self.faux, self.demande = faux, demande
        self.file: asyncio.Queue = asyncio.Queue()
        self.tache: asyncio.Task | None = None

    async def _jouer(self):
        try:
            async for ligne in self.faux.jouer(self.demande, self.faux.portail(self.demande.jeton)):
                await self.file.put(ligne)
        finally:
            await self.file.put(None)

    async def __aiter__(self):
        self.tache = asyncio.ensure_future(self._jouer())
        while (ligne := await self.file.get()) is not None:
            if isinstance(ligne, dict):
                ligne = json.dumps(ligne, ensure_ascii=False) + "\n"
            yield ligne.encode() if isinstance(ligne, str) else ligne

    async def aclose(self):
        self.faux.deconnecte.set()  # le portail a fermé le flux : l'agent voit la connexion coupée
        if self.tache:
            self.tache.cancel()
            await asyncio.gather(self.tache, return_exceptions=True)


class FauxAgent:
    """Un faux conteneur d'agent : `registre` est un `Missions` branché dessus.

    - `contrat`, `version`, `joignable`, `code` : ce que `/sante` et `/missions` répondent ;
    - `missions` : les requêtes reçues, `{"entetes", "corps"}` ;
    - `jouer(demande, portail)` : générateur de lignes (dict, ou texte brut pour une ligne
      illisible), remplacé par les tests qui trichent ; `portail(chemin, corps)` appelle `/interne/`
      avec le jeton de la mission ;
    - `deconnecte` : posé quand le portail ferme le flux.
    """

    SECRET = "s" * 32

    def __init__(self, agent="revue", duree_s=60):
        self.agent, self.contrat, self.version = agent, "v1", "sha-agent"
        self.joignable, self.code = True, 200
        self.missions: list[dict] = []
        self.sante: list[dict] = []
        self.deconnecte = asyncio.Event()
        self.registre = Missions(
            {agent: self.SECRET}, duree_s, transport=httpx.MockTransport(self.repondre)
        )
        app = FastAPI()
        app.state.missions = self.registre
        app.include_router(ROUTEUR_INTERNE)
        self.client = AsyncClient(transport=ASGITransport(app), base_url="http://t")

    def portail(self, jeton):
        async def appeler(chemin, corps):
            return await self.client.post(
                f"/interne/{chemin}", json=corps, headers={"Authorization": f"Bearer {jeton}"}
            )

        return appeler

    async def repondre(self, request: httpx.Request) -> httpx.Response:
        if not self.joignable:
            raise httpx.ConnectError("hors service")
        if request.url.path == "/sante":
            self.sante.append({"entetes": dict(request.headers)})
            return httpx.Response(
                200, json={"contrat": self.contrat, "agent": self.agent, "version": self.version}
            )
        corps = json.loads(request.content)
        self.missions.append({"entetes": dict(request.headers), "corps": corps})
        if self.code != 200:
            return httpx.Response(self.code)
        return httpx.Response(200, stream=_FluxAgent(self, DemandeMission.model_validate(corps)))

    async def jouer(self, demande, portail):
        """La boucle d'outils d'un agent honnête."""
        messages = [m.model_dump(exclude_none=True) for m in demande.messages]
        corps = {"outils": bool(demande.outils), "response_format": demande.response_format}
        while True:
            r = await portail("modele", {"messages": messages, **corps})
            if r.status_code != 200:
                yield {"type": "erreur", "erreur": "texte de l'agent"}
                return
            messages.append(r.json()["message"])
            appels = messages[-1].get("tool_calls") or []
            if not appels:
                yield {
                    "type": "fin", "texte": messages[-1]["content"] or "", "messages": messages,
                    "limite_atteinte": False,
                }  # fmt: skip
                return
            for a in appels:
                f = a["function"]
                r = await portail("outils", {"nom": f["name"], "arguments": f["arguments"]})
                resultat = r.json().get("resultat", "")
                messages.append({"role": "tool", "tool_call_id": a["id"], "content": resultat})


@pytest_asyncio.fixture
async def faux_agent():
    faux = FauxAgent()
    yield faux
    await faux.client.aclose()


# --- dépôt -------------------------------------------------------------


def git(cwd, *args: str) -> str:
    r = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    )  # fmt: skip
    return r.stdout.strip()


@pytest.fixture
def depot_origine(tmp_path):
    """Dépôt local avec un commit (README.md) sur main."""
    o = tmp_path / "origine"
    o.mkdir()
    git(o, "init", "-b", "main")
    (o / "README.md").write_text("# Projet\n")
    git(o, "add", "README.md")
    git(o, "commit", "-m", "init")
    return o


# --- lanceur -----------------------------------------------------------


class FauxLanceur:
    """Même interface que ClientLanceur. L'espace `e` est le dossier `dossier / e`."""

    def __init__(self, dossier: Path):
        self.dossier = Path(dossier)
        self.codes: dict[str, list[int]] = {}  # rendus tour à tour par commande exacte, 0 sinon
        self.effets: dict[str, Callable[[Path], None]] = {}  # appliqués au dossier de l'espace
        self.delais: set[str] = set()  # commandes exactes qui dépassent leur délai
        self.appels: list[dict] = []

    async def lancer(
        self, espace, image, commande, delai_s, lecture_seule, tout_lecture_seule=False
    ) -> Resultat:
        self.appels.append(
            {
                "route": "lancer", "espace": espace, "image": image, "commande": commande,
                "delai_s": delai_s, "lecture_seule": list(lecture_seule),
                "tout_lecture_seule": tout_lecture_seule,
            }
        )  # fmt: skip
        if commande in self.effets:
            self.effets[commande](self.dossier / espace)
        if commande in self.delais:
            sortie = f"sortie de {commande}\n[délai dépassé : {delai_s} s]"
            return Resultat(code=None, sortie=sortie, delai_depasse=True)
        codes = self.codes.get(commande)
        code = codes.pop(0) if codes else 0
        return Resultat(code=code, sortie=f"sortie de {commande}", delai_depasse=False)

    async def services(self, espace, services) -> None:
        self.appels.append({"route": "services", "espace": espace, "services": list(services)})

    async def arreter(self, espace) -> None:
        self.appels.append({"route": "arreter", "espace": espace})

    async def nettoyer(self, espace) -> None:
        self.appels.append({"route": "nettoyer", "espace": espace})


class FauxNotifieur:
    def __init__(self):
        self.envoyes: list[dict] = []

    async def envoyer(self, titre, message, lien=None) -> None:
        self.envoyes.append({"titre": titre, "message": message, "lien": lien})


@pytest.fixture
def faux_lanceur(tmp_path):
    return FauxLanceur(tmp_path / "espaces")


# --- GitHub ------------------------------------------------------------


def commentaire(
    type_, id_, texte="à revoir", auteur="nicolaslallier", cree_le=None, **kw
) -> CommentaireGitHub:
    return CommentaireGitHub(
        id=id_, type=type_, auteur=auteur, auteur_type=kw.pop("auteur_type", "User"),
        texte=texte, cree_le=cree_le or datetime.now(UTC), url=f"https://github.com/c/{id_}", **kw,
    )  # fmt: skip


class FauxGitHub:
    """Même interface async que GitHubApp, état en mémoire.

    - `branche_defaut_nom` : branche par défaut rendue (« main ») ;
    - `protegee` : ensemble des branches protégées (par défaut `{"main"}`) ;
    - `prs` : numéro -> {"branche", "base", "titre", "corps", "url"} (créées en brouillon) ;
    - `etats` : numéro -> "ouverte" | "fusionnee" | "fermee" (les tests le modifient) ;
    - `commentaires` : liste de (numéro, texte) ;
    - `lus` : numéro de PR -> commentaires lus (les trois lectures filtrent par `type`) ;
    - `reponses` : liste de (numéro, commentaire_id, texte) ;
    - `erreur` : si renseignée, toute méthode lève cette ErreurGitHub.
    """

    def __init__(self):
        self.branche_defaut_nom = "main"
        self.protegee: set[str] = {"main"}
        self.prs: dict[int, dict] = {}
        self.etats: dict[int, str] = {}
        self.commentaires: list[tuple[int, str]] = []
        self.lus: dict[int, list[CommentaireGitHub]] = {}
        self.reponses: list[tuple[int, int, str]] = []
        self.erreur: Exception | None = None

    def _verifier(self):
        if self.erreur:
            raise self.erreur

    async def jeton(self, depot) -> str:
        self._verifier()
        return ""

    async def branche_defaut(self, depot) -> str:
        self._verifier()
        return self.branche_defaut_nom

    async def branche_protegee(self, depot, branche) -> bool:
        self._verifier()
        return branche in self.protegee

    async def creer_pr(self, depot, branche, base, titre, corps) -> tuple[int, str]:
        self._verifier()
        n = len(self.prs) + 1
        url = f"https://github.com/{depot}/pull/{n}"
        self.prs[n] = {"branche": branche, "base": base, "titre": titre, "corps": corps, "url": url}
        self.etats[n] = "ouverte"
        return n, url

    async def etat_pr(self, depot, numero) -> str:
        self._verifier()
        return self.etats[numero]

    async def commenter(self, depot, numero, texte) -> None:
        self._verifier()
        self.commentaires.append((numero, texte))

    async def fermer_pr(self, depot, numero) -> None:
        self._verifier()
        self.etats[numero] = "fermee"

    def _lus(self, numero, type_) -> list[CommentaireGitHub]:
        self._verifier()
        return [c for c in self.lus.get(numero, []) if c.type == type_]

    async def revues(self, depot, numero) -> list[CommentaireGitHub]:
        return self._lus(numero, "revue")

    async def commentaires_ligne(self, depot, numero) -> list[CommentaireGitHub]:
        return self._lus(numero, "ligne")

    async def commentaires_conversation(self, depot, numero) -> list[CommentaireGitHub]:
        return self._lus(numero, "conversation")

    async def repondre_ligne(self, depot, numero, commentaire_id, texte) -> None:
        self._verifier()
        self.reponses.append((numero, commentaire_id, texte))


@pytest.fixture
def faux_github():
    return FauxGitHub()


# --- métriques ---------------------------------------------------------


def valeur(nom: str, /, **etiquettes: str) -> float:
    """Valeur courante d'un échantillon du registre ; les tests comparent avant et après."""
    from prometheus_client import REGISTRY

    return REGISTRY.get_sample_value(nom, etiquettes) or 0.0
