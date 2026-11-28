import asyncio
import ipaddress
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from portail import architecture, bureau, journal, metriques, resume
from portail.agents import Catalogue, agent_effectif, charger_catalogue
from portail.arbitre import Arbitre, LLMArbitre
from portail.archimate import BlocInvalide, xml_echange
from portail.audit import auteur_de, inscrire
from portail.avis import ServiceAvis
from portail.chat import Diffuseur, ServiceChat, annexes
from portail.config import Reglages
from portail.contexte import construire, jauge
from portail.conversations import ServiceConversation
from portail.db import (
    Audit,
    Avis,
    CarteDoc,
    CommandeLancee,
    CommentairePris,
    Document,
    Etape,
    ExecutionDev,
    Pipeline,
    Projet,
    Proposition,
    Tache,
    TacheDependance,
    creer_moteur,
    fabrique_sessions,
)
from portail.depots import Depots, ErreurDepot
from portail.dev import Orchestrateur
from portail.etats import Etat
from portail.evenements import bus
from portail.evenements import flux as flux_evenements
from portail.execution import lire_config
from portail.github import ErreurGitHub, GitHubApp
from portail.lanceur import ClientLanceur
from portail.llm import ClientLLM
from portail.missions import ROUTEUR_INTERNE, Missions, lire_secrets
from portail.moteur import Refus, creer_pipeline, recuperer_interrompues, spec_courante
from portail.musique import ErreurMusique, demander
from portail.notifications import Notifieur
from portail.obsidian import Coffre, chemin_doc, creer_coffre, verifier_ecriture
from portail.ordonnanceur import Ordonnanceur, reprendre_interrompues
from portail.propositions import accepter, fermer_si_fini, rejeter
from portail.propositions import tout_accepter as accepter_tout
from portail.schemas import (
    Acceptation,
    AuditOut,
    AvisOut,
    Bureau,
    CarteDocIn,
    CarteDocPatch,
    CarteDocVue,
    CommandeVue,
    CommentaireVue,
    ConversationDetail,
    ConversationIn,
    ConversationPatch,
    ConversationResume,
    Deplacement,
    DocumentOut,
    DonneesTache,
    DonneesTachePartielles,
    EtapeOut,
    ExecutionIn,
    ExecutionVue,
    Kanban,
    KanbanToutAccepte,
    PipelineDetail,
    PipelineIn,
    PipelineResume,
    PosteDetail,
    ProjetDetail,
    ProjetIn,
    ProjetOut,
    ProjetPatch,
    ProjetRef,
    PropositionVue,
    Renvoi,
    SpecCourante,
    TacheVue,
    Validation,
    verifier_depot,
)
from portail.service import routeur_service
from portail.suivi_pr import SuiviPR
from portail.taches import (
    creer_tache,
    deplacer_tache,
    modifier_tache,
    supprimer_tache,
)
from portail.usine_doc import EN_COURS as DOC_EN_COURS
from portail.usine_doc import UsineDoc

logger = logging.getLogger(__name__)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessions() as session:
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]


_METHODES = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})


async def _compter(generateur, nom: str):
    """Compte le flux ouvert dès le premier morceau demandé ; `finally` couvre fermeture et annulation."""
    jauge_flux = metriques.FLUX_OUVERTS.labels(flux=nom)
    jauge_flux.inc()
    try:
        async with aclosing(generateur):  # ferme le générateur interne (son `finally` désabonne)
            async for morceau in generateur:
                yield morceau
    finally:
        jauge_flux.dec()


def _flux(generateur, nom: str) -> StreamingResponse:
    """Flux SSE : le proxy ne doit ni le mettre en tampon ni le mettre en cache."""
    return StreamingResponse(
        _compter(generateur, nom),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _tracer(s: AsyncSession, request: Request, action: str, objet: str, objet_id: int):
    """Ligne d'audit « au mieux », commitée après le service (qui a sa propre session) : elle peut
    manquer après un crash entre les deux commits. Un échec est journalisé, jamais relevé : l'action a eu lieu."""
    try:
        inscrire(s, auteur_de(request), action, objet, objet_id)
        await s.commit()
    except SQLAlchemyError:
        await s.rollback()  # sinon la lecture qui suit dans la route lève PendingRollbackError
        journal.erreur(logger, "audit non inscrit : %s %s", action, objet_id)


async def _avis(session: AsyncSession, docs: list[Document]) -> dict[int, list[AvisOut]]:
    """Avis visibles (hors abandonnés) de ces documents, par document."""
    par_id = {d.id: d for d in docs}
    sortie: dict[int, list[AvisOut]] = {}
    for a in await session.scalars(
        select(Avis).where(Avis.document_id.in_(par_id), Avis.etat != "abandonne").order_by(Avis.id)
    ):
        vue = AvisOut.model_validate(a, from_attributes=True)
        vue.ancienne = a.version < par_id[a.document_id].version
        sortie.setdefault(a.document_id, []).append(vue)
    return sortie


async def _detail(session: AsyncSession, catalogue: Catalogue, pipeline_id: int) -> PipelineDetail:
    pipeline = await session.scalar(
        select(Pipeline)
        .where(Pipeline.id == pipeline_id)
        .options(
            selectinload(Pipeline.etapes).selectinload(Etape.messages),
            selectinload(Pipeline.etapes).selectinload(Etape.document),
        )
        .execution_options(populate_existing=True)
    )
    if pipeline is None:
        raise Refus(404, "pipeline introuvable")
    projet = await session.get(Projet, pipeline.projet_id)
    avis_par_doc = await _avis(session, [e.document for e in pipeline.etapes if e.document])
    etapes = []
    for e in pipeline.etapes:
        agent = agent_effectif(catalogue, e.agent, e.modele)
        j = None
        if agent:
            a = await annexes(session, catalogue, agent, e, pipeline.projet_id)
            j = jauge(agent, construire(agent, e.messages, e.document, annexes=a))
        etapes.append(
            EtapeOut.model_validate(
                {
                    **{
                        k: getattr(e, k)
                        for k in ("id", "ordre", "agent", "etat", "erreur", "action", "sha")
                    },
                    "produit": agent.produit if agent else None,
                    "modele": agent.modele if agent else None,
                    "modele_fige": e.modele is not None,
                    "modeles": catalogue.modeles_permis
                    if agent and agent.produit == "spec"
                    else [],
                    "messages": e.messages,
                    "document": e.document
                    and {
                        **{
                            k: getattr(e.document, k)
                            for k in ("id", "contenu", "etat", "version", "maj_le")
                        },
                        "avis": avis_par_doc.get(e.document.id, []),
                    },
                    "jauge": j,
                },
                from_attributes=True,
            )
        )
    ex = await session.scalar(select(ExecutionDev).where(ExecutionDev.pipeline_id == pipeline_id))
    commandes = (
        await session.scalars(
            select(CommandeLancee)
            .where(CommandeLancee.pipeline_id == pipeline_id)
            .order_by(CommandeLancee.id)
        )
    ).all()
    commentaires = (
        (
            await session.scalars(
                select(CommentairePris)
                .where(CommentairePris.execution_id == ex.id)
                .order_by(CommentairePris.cree_le, CommentairePris.id)
            )
        ).all()
        if ex
        else []
    )
    return PipelineDetail(
        commentaires=[CommentaireVue.model_validate(c, from_attributes=True) for c in commentaires],
        execution=ExecutionVue.model_validate(ex, from_attributes=True) if ex else None,
        commandes=[CommandeVue.model_validate(c, from_attributes=True) for c in commandes],
        id=pipeline.id,
        projet=ProjetRef(id=projet.id, nom=projet.nom),
        type=pipeline.type,
        etat=pipeline.etat,
        maj_le=pipeline.maj_le,
        etapes=etapes,
    )


async def _vues(session: AsyncSession, taches: list[Tache]) -> list[TacheVue]:
    ids = [t.id for t in taches]
    deps: dict[int, list[int]] = {}
    for a, b in (
        await session.execute(
            select(TacheDependance.tache_id, TacheDependance.depend_de_id)
            .where(TacheDependance.tache_id.in_(ids))
            .order_by(TacheDependance.depend_de_id)
        )
    ).all():
        deps.setdefault(a, []).append(b)
    colonnes = dict(
        (
            await session.execute(
                select(Tache.id, Tache.colonne).where(
                    Tache.id.in_({d for v in deps.values() for d in v})
                )
            )
        ).all()
    )
    prs: dict[int, str | None] = {}  # la plus récente exécution de chaque tâche gagne
    modes: dict[int, str] = {}
    for tid, url, mode in (
        await session.execute(
            select(ExecutionDev.tache_id, ExecutionDev.pr_url, ExecutionDev.mode)
            .where(ExecutionDev.tache_id.in_(ids))
            .order_by(ExecutionDev.n, ExecutionDev.id)
        )
    ).all():
        prs[tid] = url
        modes[tid] = mode
    return [
        TacheVue.model_validate(t, from_attributes=True).model_copy(
            update={
                "pr_url": prs.get(t.id),
                "reprise": t.colonne == "en_cours" and modes.get(t.id) == "reprise",
                "depend_de": deps.get(t.id, []),
                "dependances_non_terminees": [
                    d for d in deps.get(t.id, []) if colonnes[d] != "terminee"
                ],
            }
        )
        for t in taches
    ]


async def _kanban(session: AsyncSession, projet_id: int) -> Kanban:
    taches = (
        await session.scalars(
            select(Tache)
            .where(Tache.projet_id == projet_id)
            .order_by(Tache.colonne, Tache.rang, Tache.id)
            .execution_options(populate_existing=True)
        )
    ).all()
    props = (
        await session.scalars(
            select(Proposition)
            .where(Proposition.projet_id == projet_id, Proposition.etat == "ouverte")
            .order_by(Proposition.id)
        )
    ).all()
    config = await session.scalar(select(Projet.config_execution).where(Projet.id == projet_id))
    return Kanban(
        config_execution=bool(config),
        taches=await _vues(session, list(taches)),
        propositions=[PropositionVue.model_validate(p, from_attributes=True) for p in props],
    )


async def _vue(session: AsyncSession, tache_id: int) -> TacheVue:
    t = await session.scalar(
        select(Tache).where(Tache.id == tache_id).execution_options(populate_existing=True)
    )
    return (await _vues(session, [t]))[0]


async def _tache(session: AsyncSession, tache_id: int) -> Tache:
    t = await session.get(Tache, tache_id)
    if t is None:
        raise Refus(404, "tâche introuvable")
    return t


def _resume(p: Pipeline, nom: str) -> PipelineResume:
    return PipelineResume(
        id=p.id, projet_id=p.projet_id, projet_nom=nom, type=p.type, etat=p.etat, maj_le=p.maj_le
    )


def _reveiller(state) -> None:
    if ordonnanceur := state.ordonnanceur:
        ordonnanceur.reveiller()


async def _annuler(state, s: AsyncSession, pipeline_id: int, clos: bool) -> None:
    """Un pipeline `dev` passe par l'orchestrateur (même terminé : nettoyage), les autres par le
    chat, qui refuse un pipeline clos (`clos` : le lui demander quand même). Libère la
    transaction de `s` avant que le service ouvre la sienne, puis la tâche que le pipeline
    verrouillait revient « à faire », sans verrou ; une reprise en cours la ramène *En revue*
    (la PR existe), verrou gardé."""
    p = await s.get(Pipeline, pipeline_id)
    if p is None:
        raise Refus(404, "pipeline introuvable")
    type_, etat = p.type, p.etat
    if type_ == "doc":  # mené par l'usine de doc : rien à annuler côté chat
        raise Refus(409, "un pipeline doc se gère depuis sa carte du kanban doc")
    mode = await s.scalar(select(ExecutionDev.mode).where(ExecutionDev.pipeline_id == pipeline_id))
    reprise = mode == "reprise" and etat == Etat.EN_COURS
    await s.rollback()
    orchestrateur = state.orchestrateur
    if type_ == "dev" and orchestrateur:
        await orchestrateur.annuler(pipeline_id)
    elif clos or etat not in (Etat.TERMINEE, Etat.ECHOUEE):
        await state.chat.annuler(pipeline_id)
    projet_id = await s.scalar(select(Tache.projet_id).where(Tache.verrou == pipeline_id))
    if projet_id is None:
        return
    # ordre des verrous : projet d'abord, comme partout ailleurs
    await s.scalar(select(Projet.id).where(Projet.id == projet_id).with_for_update())
    t = await s.scalar(
        select(Tache)
        .where(Tache.verrou == pipeline_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if t is not None:
        t.verrou = None
        await deplacer_tache(s, t, "en_revue" if reprise else "a_faire", None, "nicolas")
        if reprise:
            t.verrou = pipeline_id
    await s.commit()
    _reveiller(state)


async def _annuler_tache(state, s: AsyncSession, tache_id: int) -> None:
    t = await _tache(s, tache_id)
    verrou = t.verrou
    if verrou is None:
        raise Refus(409, "rien à annuler")
    await _annuler(state, s, verrou, clos=False)  # même chemin que /pipelines/{id}/annuler


def _orchestrateur(r: Reglages, sessions, catalogue, llm, missions) -> Orchestrateur | None:
    """Seulement si l'App GitHub et le lanceur sont configurés ; sinon un avertissement qui nomme
    les variables absentes (jamais leurs valeurs) et pas d'ordonnanceur."""
    manquantes = [
        nom
        for nom, valeur in (
            ("PORTAIL_GITHUB_APP_ID", r.github_app_id),
            ("PORTAIL_GITHUB_APP_CLE", r.github_app_cle),
            ("PORTAIL_LANCEUR_SECRET", r.lanceur_secret),
        )
        if not valeur
    ]
    if manquantes:
        logger.warning(
            "ordonnanceur éteint : %s absente%s",
            ", ".join(manquantes),
            "s" if len(manquantes) > 1 else "",
        )
        return None
    try:
        github = GitHubApp(r.github_app_id, r.github_app_cle)
    except ErreurGitHub:
        journal.erreur(logger, "App GitHub mal configurée : pas d'ordonnanceur")
        return None
    lanceur = ClientLanceur(r.lanceur_url, r.lanceur_secret)
    notifieur = Notifieur(r.ntfy_url, r.ntfy_sujet, r.ntfy_jeton)
    return Orchestrateur(
        sessions, catalogue, llm, lanceur, github, r, notifieur=notifieur, missions=missions
    )


def create_app(
    reglages: Reglages | None = None,
    llm: ClientLLM | None = None,
    catalogue: Catalogue | None = None,
    orchestrateur: Orchestrateur | None = None,
    missions: Missions | None = None,
    coffre: Coffre | None = None,
) -> FastAPI:
    r = reglages or Reglages()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.reglages = r
        app.state.coffre = coffre or creer_coffre(r)  # sans secret S3 : None, le Portail démarre
        app.state.reseau_agents = ipaddress.ip_network(r.reseau_agents) if r.reseau_agents else None
        metriques.initialiser(r)
        app.state.catalogue = catalogue or charger_catalogue(r.agents_fichier)
        # un agent à `service:` sans secret valide empêche le démarrage
        app.state.missions = missions or Missions(
            lire_secrets(app.state.catalogue, os.environ), r.duree_mission_s
        )
        moteur = creer_moteur(r.database_url)
        app.state.sessions = fabrique_sessions(moteur)
        app.state.llm = llm or ClientLLM(
            r.litellm_url,
            r.litellm_cle,
            sessions=app.state.sessions,
            version=r.version,
            delai_s=r.llm_delai_s,
        )
        async with app.state.sessions() as s:
            await recuperer_interrompues(s)
            await s.commit()
            en_attente = set(
                (await s.scalars(select(Etape.id).where(Etape.etat == Etat.EN_ATTENTE))).all()
            )
        depots = Depots(r.donnees_dir, r.github_jeton)
        try:
            # au démarrage, aucune étape n'est au milieu d'une préparation : nettoyer sans verrou
            await depots.nettoyer(garder=en_attente)
        except ErreurDepot:
            journal.erreur(logger, "nettoyage des arbres de travail incomplet")
        arbitre = Arbitre(r.appels_par_modele)
        interactif = LLMArbitre(app.state.llm, arbitre, "interactif")
        app.state.diffuseur = Diffuseur()
        app.state.avis = ServiceAvis(
            app.state.sessions, app.state.catalogue, interactif, depots, app.state.missions
        )
        app.state.chat = ServiceChat(
            app.state.sessions, app.state.catalogue, interactif, app.state.diffuseur, depots,
            app.state.avis, app.state.missions,
        )  # fmt: skip
        async with app.state.sessions() as s:
            await app.state.avis.recuperer_interrompues(s)
            await s.commit()

        async def annuler_tache(tache_id: int) -> None:
            async with app.state.sessions() as s:
                await _annuler_tache(app.state, s, tache_id)

        app.state.conversations = ServiceConversation(
            app.state.sessions,
            app.state.catalogue,
            interactif,
            Diffuseur(),
            app.state.chat,
            annuler_tache,
            lambda: _reveiller(app.state),
            app.state.missions,
        )
        async with app.state.sessions() as s:
            await app.state.conversations.recuperer_interrompues(s)
            await s.commit()
        boucles: list[asyncio.Task] = []
        if "pm" in app.state.catalogue.agents and r.resume_heure:
            boucles.append(
                asyncio.create_task(
                    resume.tourner(
                        app.state.sessions, app.state.conversations,
                        Notifieur(r.ntfy_url, r.ntfy_sujet, r.ntfy_jeton),
                        r.resume_heure, r.url_publique, lambda: datetime.now(UTC),
                    )
                )
            )  # fmt: skip
        orch = orchestrateur or _orchestrateur(
            r,
            app.state.sessions,
            app.state.catalogue,
            LLMArbitre(app.state.llm, arbitre, "fond"),
            app.state.missions,
        )
        app.state.orchestrateur, app.state.ordonnanceur = orch, None
        app.state.usine = None
        if "doc" in app.state.catalogue.pipelines:
            app.state.usine = UsineDoc(
                app.state.sessions, app.state.catalogue, LLMArbitre(app.state.llm, arbitre, "fond"),
                depots, app.state.coffre, r,
                Notifieur(r.ntfy_url, r.ntfy_sujet, r.ntfy_jeton), app.state.missions,
            )  # fmt: skip
            await app.state.usine.reprendre()
        if orch:  # ponytail: l'usine de doc tourne seulement avec l'ordonnanceur de dev
            app.state.ordonnanceur = Ordonnanceur(
                app.state.sessions, orch, r.paralleles_max, app.state.usine, r.relances_max
            )
            await reprendre_interrompues(app.state.sessions, orch, app.state.ordonnanceur.lancer)
            suivi = SuiviPR(
                app.state.sessions, orch._github, orch, app.state.ordonnanceur,
                proprietaire=r.github_proprietaire, delai_s=r.delai_commentaires_s,
            )  # fmt: skip
            boucles += [
                asyncio.create_task(app.state.ordonnanceur.tourner()),
                asyncio.create_task(suivi.tourner()),
            ]
        yield
        taches = [
            *app.state.chat.taches.values(),
            *app.state.conversations.taches.values(),
            *app.state.avis.taches.values(),
        ]
        taches += boucles
        if orch:
            taches += [*orch.taches.values()]
        if app.state.usine:
            taches += [*app.state.usine.taches.values()]
        for t in taches:
            t.cancel()
        await asyncio.gather(*taches, return_exceptions=True)
        await moteur.dispose()

    app = FastAPI(lifespan=lifespan)

    @app.exception_handler(Refus)
    async def _refus(_: Request, refus: Refus):
        return JSONResponse(status_code=refus.code, content={"detail": refus.message})

    @app.middleware("http")
    async def _utilisateur(request: Request, call_next):
        chemin = request.url.path
        if (
            request.app.state.reglages.exiger_utilisateur
            and chemin.startswith("/api/")
            and chemin != "/api/sante"
            and not request.headers.get("X-Auth-Request-Email")
        ):
            return JSONResponse(status_code=401, content={"detail": "non authentifié"})
        # Anti-CSRF : le cookie oauth2-proxy vaut pour tout .famillelallier.net,
        # donc une écriture doit venir du portail lui-même.
        if chemin.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            site = request.headers.get("Sec-Fetch-Site")
            origine = request.headers.get("Origin")
            if (site and site not in ("same-origin", "none")) or (
                not site and origine and urlsplit(origine).netloc != request.headers.get("Host")
            ):
                return JSONResponse(status_code=403, content={"detail": "requête d'un autre site"})
        try:
            return await call_next(request)
        except Exception:  # noqa: BLE001
            # Pas de gestionnaire `exception_handler(Exception)` : Starlette relève l'exception
            # après lui et uvicorn la journaliserait avec son message (jeton, sortie de commande).
            route = request.scope.get("route")  # le modèle (`/api/taches/{tache_id}`), pas l'URL
            journal.erreur(
                logger, "erreur interne sur %s %s", request.method, getattr(route, "path", "?")
            )
            return JSONResponse(status_code=500, content={"detail": "erreur interne"})

    @app.middleware("http")
    async def _mesurer(request: Request, call_next):
        # Déclaré après `_utilisateur` : extérieur, il voit aussi les 401 et 403.
        debut = time.perf_counter()
        code = "500"  # si call_next relève
        try:
            reponse = await call_next(request)
            code = str(reponse.status_code)
            return reponse
        finally:
            # Le modèle de route, jamais l'URL : sans route, une valeur fixe (cardinalité bornée).
            route = getattr(request.scope.get("route"), "path", "aucune")
            if route != "/metrics":
                # ensemble fixe : une méthode inventée par un client ne crée pas de série
                methode = request.method if request.method in _METHODES else "AUTRE"
                metriques.HTTP_REQUETES.labels(methode, route, code).inc()
                metriques.HTTP_DUREE.labels(methode, route).observe(time.perf_counter() - debut)

    @app.middleware("http")
    async def _reseau_agents(request: Request, call_next):
        # Déclaré en dernier : le plus extérieur, exécuté avant toute lecture d'en-tête. Le pair est
        # celui de la connexion (uvicorn sans --proxy-headers) : aucun en-tête ne le réécrit.
        reseau = request.app.state.reseau_agents
        if reseau is not None:
            try:
                pair = ipaddress.ip_address(request.client.host) if request.client else None
            except ValueError:
                pair = None
            pair = getattr(pair, "ipv4_mapped", None) or pair  # ::ffff:a.b.c.d est a.b.c.d
            chez_agents = pair is not None and pair in reseau
            if chez_agents != request.url.path.startswith("/interne/"):
                return Response(status_code=404)
            # un chemin non normalisé (`/interne/../x`, `%2e%2e`) ne sort pas de /interne/
            if chez_agents and "/.." in request.url.path:
                return Response(status_code=404)
        return await call_next(request)

    @app.get("/api/sante")
    async def sante():
        return {"ok": True}

    @app.get("/api/projets", response_model=list[ProjetOut])
    async def lister_projets(s: Session):
        return (await s.scalars(select(Projet).order_by(Projet.nom))).all()

    @app.post("/api/projets", status_code=201, response_model=ProjetOut)
    async def creer_projet(corps: ProjetIn, request: Request, s: Session):
        verifier_depot(corps.depot_url)
        projet = Projet(**corps.model_dump())
        s.add(projet)
        await s.flush()
        inscrire(s, auteur_de(request), "projet.creer", "projet", projet.id)
        await s.commit()
        await s.refresh(projet)
        return projet

    @app.patch("/api/projets/{projet_id}", response_model=ProjetOut)
    async def modifier_projet(projet_id: int, corps: ProjetPatch, request: Request, s: Session):
        projet = await s.get(Projet, projet_id)
        if projet is None:
            raise Refus(404, "projet introuvable")
        verifier_depot(corps.depot_url)
        for champ in corps.model_fields_set:
            setattr(projet, champ, getattr(corps, champ))
        inscrire(s, auteur_de(request), "projet.modifier", "projet", projet_id)
        await s.commit()
        await s.refresh(projet)
        return projet

    @app.put("/api/projets/{projet_id}/execution", response_model=ProjetOut)
    async def definir_execution(projet_id: int, corps: ExecutionIn, request: Request, s: Session):
        projet = await s.get(Projet, projet_id)
        if projet is None:
            raise Refus(404, "projet introuvable")
        if corps.yaml.strip():
            lire_config(corps.yaml)
            projet.config_execution = corps.yaml
        else:
            projet.config_execution = None
        inscrire(s, auteur_de(request), "projet.definir_execution", "projet", projet_id)
        await s.commit()
        await s.refresh(projet)
        return projet

    @app.get("/api/projets/{projet_id}", response_model=ProjetDetail)
    async def lire_projet(projet_id: int, s: Session):
        projet = await s.get(Projet, projet_id)
        if projet is None:
            raise Refus(404, "projet introuvable")
        pipelines = (
            await s.scalars(
                select(Pipeline)
                .where(Pipeline.projet_id == projet_id)
                .order_by(Pipeline.maj_le.desc())
            )
        ).all()
        spec = await spec_courante(s, projet_id)
        return ProjetDetail(
            **ProjetOut.model_validate(projet, from_attributes=True).model_dump(),
            config_execution=projet.config_execution,
            pipelines=[_resume(p, projet.nom) for p in pipelines],
            spec_courante=SpecCourante.model_validate(spec, from_attributes=True) if spec else None,
        )

    @app.get("/api/pipelines", response_model=list[PipelineResume])
    async def lister_pipelines(s: Session, etat: str | None = None):
        q = (
            select(Pipeline, Projet.nom)
            .join(Projet, Projet.id == Pipeline.projet_id)
            .order_by(Pipeline.maj_le.desc())
        )
        if etat:
            q = q.where(Pipeline.etat == etat)
        return [_resume(p, nom) for p, nom in (await s.execute(q)).all()]

    @app.post("/api/pipelines", status_code=201, response_model=PipelineDetail)
    async def ouvrir_pipeline(corps: PipelineIn, request: Request, s: Session):
        if await s.get(Projet, corps.projet_id) is None:
            raise Refus(404, "projet introuvable")
        cat = request.app.state.catalogue
        pipeline, a_lancer = await creer_pipeline(s, cat, corps.projet_id, corps.type)
        inscrire(s, auteur_de(request), "pipeline.lancer", "pipeline", pipeline.id)
        await s.commit()
        if a_lancer:
            request.app.state.chat.lancer(a_lancer.id)
        return await _detail(s, cat, pipeline.id)

    @app.get("/api/pipelines/{pipeline_id}", response_model=PipelineDetail)
    async def lire_pipeline(pipeline_id: int, request: Request, s: Session):
        return await _detail(s, request.app.state.catalogue, pipeline_id)

    @app.get("/api/pipelines/{pipeline_id}/architecture.md")
    async def architecture_md(pipeline_id: int, request: Request, s: Session):
        try:
            texte = await architecture.assembler(s, request.app.state.catalogue, pipeline_id)
        except BlocInvalide as e:
            raise Refus(409, str(e)) from e
        return Response(texte, media_type="text/markdown; charset=utf-8")

    @app.get("/api/pipelines/{pipeline_id}/architecture.xml")
    async def architecture_xml(pipeline_id: int, request: Request, s: Session):
        try:
            modele = await architecture.modele_fusionne(s, request.app.state.catalogue, pipeline_id)
        except BlocInvalide as e:
            raise Refus(409, str(e)) from e
        pipeline = await s.get(Pipeline, pipeline_id)
        projet = await s.get(Projet, pipeline.projet_id)
        return Response(
            xml_echange(modele, projet.nom),
            media_type="application/xml",
            headers={
                "Content-Disposition": f'attachment; filename="architecture-{pipeline_id}.xml"'
            },
        )

    @app.post("/api/pipelines/{pipeline_id}/annuler", response_model=PipelineDetail)
    async def annuler(pipeline_id: int, request: Request, s: Session):
        await _annuler(request.app.state, s, pipeline_id, clos=True)
        await _tracer(s, request, "pipeline.annuler", "pipeline", pipeline_id)
        return await _detail(s, request.app.state.catalogue, pipeline_id)

    @app.get("/api/projets/{projet_id}/kanban", response_model=Kanban)
    async def kanban(projet_id: int, s: Session):
        if await s.get(Projet, projet_id) is None:
            raise Refus(404, "projet introuvable")
        return await _kanban(s, projet_id)

    async def _proposition(s: AsyncSession, proposition_id: int) -> Proposition:
        p = await s.get(Proposition, proposition_id)
        if p is None:
            raise Refus(404, "proposition introuvable")
        return p

    async def _fermer(request: Request, s: AsyncSession, etape_id: int) -> None:
        """Commite ; termine l'étape si plus rien n'est ouvert et lance la suivante."""
        suivante = await fermer_si_fini(s, request.app.state.catalogue, etape_id)
        await s.commit()
        if suivante:
            request.app.state.chat.lancer(suivante.id)

    @app.post("/api/propositions/{proposition_id}/accepter", response_model=Kanban)
    async def accepter_proposition(
        proposition_id: int, request: Request, s: Session, corps: Acceptation | None = None
    ):
        p = await _proposition(s, proposition_id)
        try:
            await accepter(s, p, corps.donnees if corps else None)
        except Refus:
            if p.etat == "perimee":  # le marquage est gardé, même si l'acceptation échoue
                await _fermer(request, s, p.etape_id)
            raise
        inscrire(s, auteur_de(request), "proposition.accepter", "proposition", p.id)
        await _fermer(request, s, p.etape_id)
        _reveiller(request.app.state)
        return await _kanban(s, p.projet_id)

    @app.post("/api/propositions/{proposition_id}/rejeter", response_model=Kanban)
    async def rejeter_proposition(proposition_id: int, request: Request, s: Session):
        p = await _proposition(s, proposition_id)
        await rejeter(s, p)
        inscrire(s, auteur_de(request), "proposition.rejeter", "proposition", p.id)
        await _fermer(request, s, p.etape_id)
        return await _kanban(s, p.projet_id)

    @app.post("/api/etapes/{etape_id}/propositions/tout-accepter", response_model=KanbanToutAccepte)
    async def tout_accepter(etape_id: int, request: Request, s: Session):
        etape = await s.get(Etape, etape_id)
        if etape is None:
            raise Refus(404, "étape introuvable")
        projet_id = await s.scalar(
            select(Pipeline.projet_id).where(Pipeline.id == etape.pipeline_id)
        )
        perimees = await accepter_tout(s, etape_id)
        inscrire(s, auteur_de(request), "propositions.tout_accepter", "etape", etape_id)
        await _fermer(request, s, etape_id)
        _reveiller(request.app.state)
        k = await _kanban(s, projet_id)
        return KanbanToutAccepte(**k.model_dump(), perimees=perimees)

    @app.post("/api/projets/{projet_id}/taches", status_code=201, response_model=TacheVue)
    async def ajouter_tache(projet_id: int, corps: DonneesTache, request: Request, s: Session):
        t = await creer_tache(s, projet_id, corps, "nicolas")
        inscrire(s, auteur_de(request), "tache.creer", "tache", t.id)
        await s.commit()
        _reveiller(request.app.state)
        return await _vue(s, t.id)

    @app.patch("/api/taches/{tache_id}", response_model=TacheVue)
    async def modifier(tache_id: int, corps: DonneesTachePartielles, request: Request, s: Session):
        t = await _tache(s, tache_id)
        await modifier_tache(s, t, corps, "nicolas")
        inscrire(s, auteur_de(request), "tache.modifier", "tache", tache_id)
        await s.commit()
        _reveiller(request.app.state)
        return await _vue(s, tache_id)

    @app.post("/api/taches/{tache_id}/deplacer", response_model=TacheVue)
    async def deplacer(tache_id: int, corps: Deplacement, request: Request, s: Session):
        t = await _tache(s, tache_id)
        await deplacer_tache(s, t, corps.colonne, corps.avant_id, "nicolas")
        inscrire(s, auteur_de(request), "tache.deplacer", "tache", tache_id)
        await s.commit()
        _reveiller(request.app.state)
        return await _vue(s, tache_id)

    @app.delete("/api/taches/{tache_id}", status_code=204)
    async def supprimer(tache_id: int, request: Request, s: Session):
        t = await _tache(s, tache_id)
        await supprimer_tache(s, t, "nicolas")
        inscrire(s, auteur_de(request), "tache.supprimer", "tache", tache_id)
        await s.commit()

    @app.post("/api/taches/{tache_id}/annuler", response_model=TacheVue)
    async def annuler_tache(tache_id: int, request: Request, s: Session):
        await _annuler_tache(request.app.state, s, tache_id)
        await _tracer(s, request, "tache.annuler", "tache", tache_id)
        return await _vue(s, tache_id)

    # --- kanban doc -----------------------------------------------------------

    async def _carte(s: AsyncSession, carte_id: int, verrou: bool = False) -> CarteDoc:
        q = select(CarteDoc).where(CarteDoc.id == carte_id)
        carte = await s.scalar(q.with_for_update() if verrou else q)
        if carte is None:
            raise Refus(404, "carte introuvable")
        return carte

    async def _vues_doc(s: AsyncSession, *conditions) -> list[CarteDocVue]:
        lignes = await s.execute(
            select(CarteDoc, Projet.nom)
            .join(Projet, Projet.id == CarteDoc.projet_id)
            .where(*conditions)
            .order_by(CarteDoc.id)
            .execution_options(populate_existing=True)
        )
        return [
            CarteDocVue.model_validate(
                {**{k: getattr(c, k) for k in CarteDocVue.model_fields if k != "projet_nom"},
                 "projet_nom": nom}
            )
            for c, nom in lignes.all()
        ]  # fmt: skip

    async def _vue_doc(s: AsyncSession, carte_id: int) -> CarteDocVue:
        return (await _vues_doc(s, CarteDoc.id == carte_id))[0]

    async def _modifier_carte(
        s: AsyncSession, request: Request, carte_id: int, action: str, **champs
    ):
        """Hors rédaction et revue seulement : l'usine écrit la carte pendant ce temps."""
        carte = await _carte(s, carte_id, verrou=True)
        if carte.colonne in DOC_EN_COURS:
            raise Refus(409, "carte en cours de rédaction ou de revue")
        for k, v in champs.items():
            setattr(carte, k, v)
        inscrire(s, auteur_de(request), action, "carte_doc", carte_id)
        try:
            await s.commit()
        except IntegrityError as e:
            raise Refus(409, "ce chemin du coffre est déjà pris") from e
        _reveiller(request.app.state)
        return await _vue_doc(s, carte_id)

    @app.get("/api/docs/cartes", response_model=list[CarteDocVue])
    async def lister_cartes(s: Session, projet_id: int | None = None):
        return await _vues_doc(s, *([CarteDoc.projet_id == projet_id] if projet_id else []))

    @app.post("/api/docs/cartes", status_code=201, response_model=CarteDocVue)
    async def creer_carte(corps: CarteDocIn, request: Request, s: Session):
        projet = await s.get(Projet, corps.projet_id)
        if projet is None:
            raise Refus(404, "projet introuvable")
        try:
            chemin = chemin_doc(projet.nom, corps.titre)
        except ValueError as e:
            raise Refus(422, str(e)) from e
        carte = CarteDoc(**corps.model_dump(), chemin=chemin, remarques=[])
        s.add(carte)
        try:
            await s.flush()
        except IntegrityError as e:
            raise Refus(409, "ce chemin du coffre est déjà pris") from e
        inscrire(s, auteur_de(request), "carte_doc.creer", "carte_doc", carte.id)
        await s.commit()
        _reveiller(request.app.state)
        return await _vue_doc(s, carte.id)

    @app.patch("/api/docs/cartes/{carte_id}", response_model=CarteDocVue)
    async def modifier_carte(carte_id: int, corps: CarteDocPatch, request: Request, s: Session):
        champs = corps.model_dump(exclude_none=True)
        if "chemin" in champs:  # forme normalisée : l'unicité porte sur le chemin réellement écrit
            try:
                champs["chemin"] = verifier_ecriture(champs["chemin"])
            except ValueError as e:
                raise Refus(422, str(e)) from e
        return await _modifier_carte(s, request, carte_id, "carte_doc.modifier", **champs)

    @app.post("/api/docs/cartes/{carte_id}/valider", response_model=CarteDocVue)
    async def valider_carte(carte_id: int, corps: Validation, request: Request, s: Session):
        if request.app.state.usine is None:
            raise Refus(503, "usine de doc éteinte")
        await request.app.state.usine.valider(carte_id, corps.forcer)
        await _tracer(s, request, "carte_doc.valider", "carte_doc", carte_id)
        return await _vue_doc(s, carte_id)

    @app.post("/api/docs/cartes/{carte_id}/renvoyer", response_model=CarteDocVue)
    async def renvoyer_carte(carte_id: int, corps: Renvoi, request: Request, s: Session):
        return await _modifier_carte(
            s, request, carte_id, "carte_doc.renvoyer",
            remarques=corps.remarques, renvois=0, erreur=None, colonne="a_rediger",
        )  # fmt: skip

    @app.post("/api/docs/cartes/{carte_id}/relancer", response_model=CarteDocVue)
    async def relancer_carte(carte_id: int, request: Request, s: Session):
        return await _modifier_carte(
            s, request, carte_id, "carte_doc.relancer", erreur=None, colonne="a_rediger"
        )

    @app.delete("/api/docs/cartes/{carte_id}", status_code=204)
    async def supprimer_carte(carte_id: int, request: Request, s: Session):
        """La carte seulement : la note publiée reste dans le coffre."""
        carte = await _carte(s, carte_id, verrou=True)
        if carte.colonne in DOC_EN_COURS:
            raise Refus(409, "carte en cours de rédaction ou de revue")
        await s.delete(carte)
        inscrire(s, auteur_de(request), "carte_doc.supprimer", "carte_doc", carte_id)
        await s.commit()

    class MusiqueIn(BaseModel):
        texte: str = Field(min_length=1)
        context_id: str | None = None

    @app.post("/api/musique")
    async def musique(corps: MusiqueIn, request: Request):
        r = request.app.state.reglages
        try:
            return await demander(
                r.litellm_url,
                r.litellm_cle_agents or r.litellm_cle,
                corps.texte,
                corps.context_id,
                delai_s=r.llm_delai_s,
            )
        except ErreurMusique as e:
            raise HTTPException(502, str(e)) from e

    def _coffre(request: Request) -> Coffre:
        c = request.app.state.coffre
        if c is None:
            raise HTTPException(503, "coffre Obsidian non configuré")
        return c

    async def _lire_coffre(appel):
        try:
            return await appel
        except FileNotFoundError:
            raise HTTPException(404, "note introuvable") from None
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        except (BotoCoreError, ClientError) as e:
            code = (
                e.response.get("Error", {}).get("Code", "?") if isinstance(e, ClientError) else ""
            )
            journal.erreur(logger, "coffre Obsidian injoignable %s", code)
            raise HTTPException(502, "coffre Obsidian injoignable") from None

    @app.get("/api/coffre/arbre")
    async def coffre_arbre(request: Request, dossier: str = ""):
        return await _lire_coffre(_coffre(request).lister(dossier))

    @app.get("/api/coffre/note")
    async def coffre_note(request: Request, chemin: str):
        return {"chemin": chemin, "contenu": await _lire_coffre(_coffre(request).lire(chemin))}

    class MessageIn(BaseModel):
        contenu: str
        modele: str | None = None

    @app.post("/api/etapes/{etape_id}/messages", status_code=202)
    async def envoyer_message(etape_id: int, corps: MessageIn, request: Request, s: Session):
        await request.app.state.chat.envoyer(etape_id, corps.contenu, corps.modele)
        await _tracer(s, request, "etape.message", "etape", etape_id)
        return {}

    @app.post("/api/etapes/{etape_id}/rediger", status_code=202)
    async def rediger(etape_id: int, request: Request, s: Session):
        await request.app.state.chat.rediger(etape_id)
        await _tracer(s, request, "etape.rediger", "etape", etape_id)
        return {}

    @app.post("/api/etapes/{etape_id}/reessayer", status_code=202)
    async def reessayer(etape_id: int, request: Request, s: Session):
        await request.app.state.chat.reessayer(etape_id)
        await _tracer(s, request, "etape.reessayer", "etape", etape_id)
        return {}

    class DocumentIn(BaseModel):
        contenu: str

    @app.put("/api/etapes/{etape_id}/document", response_model=DocumentOut)
    async def corriger_document(etape_id: int, corps: DocumentIn, request: Request, s: Session):
        doc = await request.app.state.chat.corriger(etape_id, corps.contenu)
        await _tracer(s, request, "etape.corriger", "etape", etape_id)
        sortie = DocumentOut.model_validate(doc, from_attributes=True)
        sortie.avis = (await _avis(s, [doc])).get(doc.id, [])
        return sortie

    @app.post("/api/documents/{document_id}/avis", status_code=202)
    async def relancer_avis(document_id: int, request: Request, s: Session):
        doc = await s.get(Document, document_id)
        if doc is None:
            raise Refus(404, "document introuvable")
        if doc.etat != "brouillon":
            raise Refus(409, "document déjà validé")
        await request.app.state.avis.lancer(document_id)
        await _tracer(s, request, "avis.relancer", "document", document_id)

    class AvisPatch(BaseModel):
        etat: Literal["pris_en_compte", "ecarte", "ouvert"]

    @app.patch("/api/avis/{avis_id}", response_model=AvisOut)
    async def trier_avis(avis_id: int, corps: AvisPatch, request: Request, s: Session):
        avis = await s.get(Avis, avis_id)
        if avis is None:
            raise Refus(404, "avis introuvable")
        if avis.etat not in ("ouvert", "pris_en_compte", "ecarte"):
            raise Refus(409, "avis non tranchable : encore en cours ou abandonné")
        avis.etat = corps.etat
        doc = await s.get(Document, avis.document_id)
        inscrire(s, auteur_de(request), "avis.trier", "avis", avis_id)
        await s.commit()
        return AvisOut.model_validate(avis, from_attributes=True).model_copy(
            update={"ancienne": avis.version < doc.version}
        )

    @app.post("/api/etapes/{etape_id}/valider", response_model=PipelineDetail)
    async def valider(etape_id: int, request: Request, s: Session):
        pipeline_id = await request.app.state.chat.valider(etape_id)
        await _tracer(s, request, "etape.valider", "etape", etape_id)
        return await _detail(s, request.app.state.catalogue, pipeline_id)

    @app.get("/api/etapes/{etape_id}/flux")
    async def flux(etape_id: int, request: Request):
        chat = request.app.state.chat
        await chat.etat(etape_id)  # 404 avant de commencer le flux
        return _flux(chat.flux(etape_id), "etapes")

    @app.get("/api/conversations", response_model=list[ConversationResume])
    async def lister_conversations(request: Request):
        return await request.app.state.conversations.lister()

    @app.post("/api/conversations", status_code=201, response_model=ConversationDetail)
    async def creer_conversation(request: Request, s: Session, corps: ConversationIn | None = None):
        service = request.app.state.conversations
        cid = (await service.creer((corps or ConversationIn()).agent)).id
        await _tracer(s, request, "conversation.creer", "conversation", cid)
        return await service.detail(cid)

    @app.get("/api/conversations/{conversation_id}", response_model=ConversationDetail)
    async def lire_conversation(conversation_id: int, request: Request):
        return await request.app.state.conversations.detail(conversation_id)

    @app.patch("/api/conversations/{conversation_id}", response_model=ConversationDetail)
    async def renommer_conversation(
        conversation_id: int, corps: ConversationPatch, request: Request, s: Session
    ):
        service = request.app.state.conversations
        await service.renommer(conversation_id, corps.titre)
        await _tracer(s, request, "conversation.renommer", "conversation", conversation_id)
        return await service.detail(conversation_id)

    @app.delete("/api/conversations/{conversation_id}", status_code=204)
    async def supprimer_conversation(conversation_id: int, request: Request, s: Session):
        await request.app.state.conversations.supprimer(conversation_id)
        await _tracer(s, request, "conversation.supprimer", "conversation", conversation_id)

    @app.post("/api/conversations/{conversation_id}/messages", status_code=202)
    async def envoyer_conversation(
        conversation_id: int, corps: MessageIn, request: Request, s: Session
    ):
        await request.app.state.conversations.envoyer(conversation_id, corps.contenu)
        await _tracer(s, request, "conversation.message", "conversation", conversation_id)
        return {}

    @app.post("/api/conversations/{conversation_id}/reessayer", status_code=202)
    async def reessayer_conversation(conversation_id: int, request: Request, s: Session):
        await request.app.state.conversations.reessayer(conversation_id)
        await _tracer(s, request, "conversation.reessayer", "conversation", conversation_id)
        return {}

    @app.post("/api/actions/{action_id}/confirmer", status_code=202)
    async def confirmer_action(action_id: int, request: Request):
        await request.app.state.conversations.confirmer(action_id, auteur_de(request))
        return {}

    @app.post("/api/actions/{action_id}/refuser", status_code=202)
    async def refuser_action(action_id: int, request: Request):
        await request.app.state.conversations.refuser(action_id, auteur_de(request))
        return {}

    @app.get("/api/conversations/{conversation_id}/flux")
    async def flux_conversation(conversation_id: int, request: Request):
        service = request.app.state.conversations
        await service.etat(conversation_id)  # 404 avant de commencer le flux
        return _flux(service.flux(conversation_id), "conversations")

    @app.get("/api/audit", response_model=list[AuditOut])
    async def lire_audit(s: Session, limite: int = 100, avant: int | None = None):
        q = select(Audit).order_by(Audit.id.desc()).limit(max(1, min(limite, 500)))
        if avant is not None:
            q = q.where(Audit.id < avant)
        return (await s.scalars(q)).all()

    @app.get("/api/bureau", response_model=Bureau)
    async def lire_le_bureau(request: Request, s: Session):
        return await bureau.lire_bureau(
            s, request.app.state.catalogue, datetime.now(UTC), request.app.state.missions
        )

    @app.get("/api/bureau/{agent}", response_model=PosteDetail)
    async def lire_un_poste(agent: str, request: Request, s: Session):
        return await bureau.lire_poste(s, request.app.state.catalogue, agent)

    @app.get("/api/evenements")
    async def evenements():
        return _flux(flux_evenements(bus), "evenements")

    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request):
        await metriques.rafraichir(request.app.state.sessions)
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # Avant le repli SPA ; hors /api/ : le jeton de mission remplace l'en-tête d'utilisateur.
    app.include_router(ROUTEUR_INTERNE)
    # Hors /api/ et /interne/ : le jeton de service n'ouvre que cette route ; fermée sur le vhost.
    app.include_router(routeur_service(_reveiller))

    if r.static_dir:
        racine = r.static_dir.resolve()
        app.mount("/assets", StaticFiles(directory=racine / "assets"), name="assets")

        # Enregistrée en dernier : repli SPA, hors /api/. Les /api/ inconnus gardent leur 404 JSON.
        @app.get("/{chemin:path}", include_in_schema=False)
        async def spa(chemin: str):
            if chemin == "api" or chemin.startswith("api/"):
                raise Refus(404, "introuvable")
            try:
                fichier = (racine / chemin).resolve()
                if fichier.is_relative_to(racine) and fichier.is_file():
                    return FileResponse(fichier)
            except (OSError, ValueError):
                pass
            return FileResponse(racine / "index.html")

    return app
