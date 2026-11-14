import asyncio
import os
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text

from portail.agents import Agent, Catalogue
from portail.api import create_app
from portail.config import Reglages
from portail.db import Base, creer_moteur, fabrique_sessions
from portail.github import CommentaireGitHub
from portail.lanceur import Resultat

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

    async def flux(self, modele, messages, temperature):
        self.appels.append({"modele": modele, "messages": messages, "temperature": temperature})
        for m in self.morceaux:
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
        "a": _agent("a"),
        "b": _agent("b"),
        "petit": _agent("petit", contexte_max=50),
        "plan": _agent(
            "plan", consigne_redaction="Rédige le plan.", produit="plan", auto=True, outils=OUTILS
        ),
        "taches": _agent(
            "taches", consigne_redaction="Propose les tâches.", produit="taches", auto=True
        ),
    },
    pipelines={
        "spec": ["spec"],
        "double": ["a", "b"],
        "petit": ["petit"],
        "planification": ["plan", "taches"],
    },
)


@pytest.fixture
def reglages(schema, tmp_path):
    return Reglages(database_url=URL, donnees_dir=tmp_path / "donnees")


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

    async def lancer(self, espace, image, commande, delai_s, lecture_seule) -> Resultat:
        self.appels.append(
            {
                "route": "lancer", "espace": espace, "image": image, "commande": commande,
                "delai_s": delai_s, "lecture_seule": list(lecture_seule),
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
