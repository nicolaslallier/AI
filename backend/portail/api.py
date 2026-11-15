import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from portail.agents import Catalogue, charger_catalogue
from portail.chat import Diffuseur, ServiceChat, annexes
from portail.config import Reglages
from portail.contexte import construire, jauge
from portail.conversations import ServiceConversation
from portail.db import (
    CommandeLancee,
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
from portail.moteur import Refus, creer_pipeline, recuperer_interrompues, spec_courante
from portail.notifications import Notifieur
from portail.ordonnanceur import Ordonnanceur, reprendre_interrompues
from portail.propositions import accepter, fermer_si_fini, rejeter
from portail.schemas import (
    Acceptation,
    CommandeVue,
    ConversationDetail,
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
    ProjetDetail,
    ProjetIn,
    ProjetOut,
    ProjetPatch,
    ProjetRef,
    PropositionVue,
    SpecCourante,
    TacheVue,
    verifier_depot,
)
from portail.suivi_pr import SuiviPR
from portail.taches import (
    creer_tache,
    deplacer_tache,
    modifier_tache,
    supprimer_tache,
)

logger = logging.getLogger(__name__)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessions() as session:
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]


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
    etapes = []
    for e in pipeline.etapes:
        agent = catalogue.agents.get(e.agent)
        j = None
        if agent:
            a = await annexes(session, agent, e, pipeline.projet_id)
            j = jauge(agent, construire(agent, e.messages, e.document, annexes=a))
        etapes.append(
            EtapeOut.model_validate(
                {
                    **{
                        k: getattr(e, k)
                        for k in ("id", "ordre", "agent", "etat", "erreur", "action", "sha")
                    },
                    "produit": agent.produit if agent else None,
                    "messages": e.messages,
                    "document": e.document,
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
    return PipelineDetail(
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
    for tid, url in (
        await session.execute(
            select(ExecutionDev.tache_id, ExecutionDev.pr_url)
            .where(ExecutionDev.tache_id.in_(ids))
            .order_by(ExecutionDev.n, ExecutionDev.id)
        )
    ).all():
        prs[tid] = url
    return [
        TacheVue.model_validate(t, from_attributes=True).model_copy(
            update={
                "pr_url": prs.get(t.id),
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


def _orchestrateur(r: Reglages, sessions, catalogue, llm) -> Orchestrateur | None:
    """Seulement si l'App GitHub et le lanceur sont configurés ; sinon rien, sans erreur."""
    if not (r.github_app_id and r.github_app_cle and r.lanceur_secret):
        return None
    try:
        github = GitHubApp(r.github_app_id, r.github_app_cle)
    except ErreurGitHub:
        logger.exception("App GitHub mal configurée : pas d'ordonnanceur")
        return None
    lanceur = ClientLanceur(r.lanceur_url, r.lanceur_secret)
    notifieur = Notifieur(r.ntfy_url, r.ntfy_sujet, r.ntfy_jeton)
    return Orchestrateur(sessions, catalogue, llm, lanceur, github, r, notifieur=notifieur)


def create_app(
    reglages: Reglages | None = None,
    llm: ClientLLM | None = None,
    catalogue: Catalogue | None = None,
    orchestrateur: Orchestrateur | None = None,
) -> FastAPI:
    r = reglages or Reglages()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.reglages = r
        app.state.catalogue = catalogue or charger_catalogue(r.agents_fichier)
        app.state.llm = llm or ClientLLM(r.litellm_url, r.litellm_cle)
        moteur = creer_moteur(r.database_url)
        app.state.sessions = fabrique_sessions(moteur)
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
            logger.exception("nettoyage des arbres de travail incomplet")
        app.state.diffuseur = Diffuseur()
        app.state.chat = ServiceChat(
            app.state.sessions, app.state.catalogue, app.state.llm, app.state.diffuseur, depots
        )

        async def annuler_tache(tache_id: int) -> None:
            async with app.state.sessions() as s:
                await _annuler_tache(app.state, s, tache_id)

        app.state.conversations = ServiceConversation(
            app.state.sessions,
            app.state.catalogue,
            app.state.llm,
            Diffuseur(),
            app.state.chat,
            annuler_tache,
            lambda: _reveiller(app.state),
        )
        async with app.state.sessions() as s:
            await app.state.conversations.recuperer_interrompues(s)
            await s.commit()
        orch = orchestrateur or _orchestrateur(
            r, app.state.sessions, app.state.catalogue, app.state.llm
        )
        app.state.orchestrateur, app.state.ordonnanceur, boucles = orch, None, []
        if orch:
            app.state.ordonnanceur = Ordonnanceur(app.state.sessions, orch, r.paralleles_max)
            await reprendre_interrompues(app.state.sessions, orch, app.state.ordonnanceur.lancer)
            suivi = SuiviPR(
                app.state.sessions, orch._github, orch, app.state.ordonnanceur,
                proprietaire=r.github_proprietaire, delai_s=r.delai_commentaires_s,
            )  # fmt: skip
            boucles = [
                asyncio.create_task(app.state.ordonnanceur.tourner()),
                asyncio.create_task(suivi.tourner()),
            ]
        yield
        taches = [*app.state.chat.taches.values(), *app.state.conversations.taches.values()]
        if orch:
            taches += [*boucles, *orch.taches.values()]
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
        return await call_next(request)

    @app.get("/api/sante")
    async def sante():
        return {"ok": True}

    @app.get("/api/projets", response_model=list[ProjetOut])
    async def lister_projets(s: Session):
        return (await s.scalars(select(Projet).order_by(Projet.nom))).all()

    @app.post("/api/projets", status_code=201, response_model=ProjetOut)
    async def creer_projet(corps: ProjetIn, s: Session):
        verifier_depot(corps.depot_url)
        projet = Projet(**corps.model_dump())
        s.add(projet)
        await s.commit()
        await s.refresh(projet)
        return projet

    @app.patch("/api/projets/{projet_id}", response_model=ProjetOut)
    async def modifier_projet(projet_id: int, corps: ProjetPatch, s: Session):
        projet = await s.get(Projet, projet_id)
        if projet is None:
            raise Refus(404, "projet introuvable")
        verifier_depot(corps.depot_url)
        for champ in corps.model_fields_set:
            setattr(projet, champ, getattr(corps, champ))
        await s.commit()
        await s.refresh(projet)
        return projet

    @app.put("/api/projets/{projet_id}/execution", response_model=ProjetOut)
    async def definir_execution(projet_id: int, corps: ExecutionIn, s: Session):
        projet = await s.get(Projet, projet_id)
        if projet is None:
            raise Refus(404, "projet introuvable")
        if corps.yaml.strip():
            lire_config(corps.yaml)
            projet.config_execution = corps.yaml
        else:
            projet.config_execution = None
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
        await s.commit()
        if a_lancer:
            request.app.state.chat.lancer(a_lancer.id)
        return await _detail(s, cat, pipeline.id)

    @app.get("/api/pipelines/{pipeline_id}", response_model=PipelineDetail)
    async def lire_pipeline(pipeline_id: int, request: Request, s: Session):
        return await _detail(s, request.app.state.catalogue, pipeline_id)

    @app.post("/api/pipelines/{pipeline_id}/annuler", response_model=PipelineDetail)
    async def annuler(pipeline_id: int, request: Request, s: Session):
        await _annuler(request.app.state, s, pipeline_id, clos=True)
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
        await _fermer(request, s, p.etape_id)
        _reveiller(request.app.state)
        return await _kanban(s, p.projet_id)

    @app.post("/api/propositions/{proposition_id}/rejeter", response_model=Kanban)
    async def rejeter_proposition(proposition_id: int, request: Request, s: Session):
        p = await _proposition(s, proposition_id)
        await rejeter(s, p)
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
        ids = (
            await s.scalars(
                select(Proposition.id)
                .where(Proposition.etape_id == etape_id, Proposition.etat == "ouverte")
                .order_by(Proposition.id)
            )
        ).all()
        perimees = 0
        for i in ids:
            p = await s.get(Proposition, i)
            try:
                await accepter(s, p, None)
            except Refus:
                if p.etat != "perimee":
                    raise
                perimees += 1
        await _fermer(request, s, etape_id)
        _reveiller(request.app.state)
        k = await _kanban(s, projet_id)
        return KanbanToutAccepte(**k.model_dump(), perimees=perimees)

    @app.post("/api/projets/{projet_id}/taches", status_code=201, response_model=TacheVue)
    async def ajouter_tache(projet_id: int, corps: DonneesTache, request: Request, s: Session):
        t = await creer_tache(s, projet_id, corps, "nicolas")
        await s.commit()
        _reveiller(request.app.state)
        return await _vue(s, t.id)

    @app.patch("/api/taches/{tache_id}", response_model=TacheVue)
    async def modifier(tache_id: int, corps: DonneesTachePartielles, request: Request, s: Session):
        t = await _tache(s, tache_id)
        await modifier_tache(s, t, corps, "nicolas")
        await s.commit()
        _reveiller(request.app.state)
        return await _vue(s, tache_id)

    @app.post("/api/taches/{tache_id}/deplacer", response_model=TacheVue)
    async def deplacer(tache_id: int, corps: Deplacement, request: Request, s: Session):
        t = await _tache(s, tache_id)
        await deplacer_tache(s, t, corps.colonne, corps.avant_id, "nicolas")
        await s.commit()
        _reveiller(request.app.state)
        return await _vue(s, tache_id)

    @app.delete("/api/taches/{tache_id}", status_code=204)
    async def supprimer(tache_id: int, s: Session):
        t = await _tache(s, tache_id)
        await supprimer_tache(s, t, "nicolas")
        await s.commit()

    @app.post("/api/taches/{tache_id}/annuler", response_model=TacheVue)
    async def annuler_tache(tache_id: int, request: Request, s: Session):
        await _annuler_tache(request.app.state, s, tache_id)
        return await _vue(s, tache_id)

    class MessageIn(BaseModel):
        contenu: str

    @app.post("/api/etapes/{etape_id}/messages", status_code=202)
    async def envoyer_message(etape_id: int, corps: MessageIn, request: Request):
        await request.app.state.chat.envoyer(etape_id, corps.contenu)
        return {}

    @app.post("/api/etapes/{etape_id}/rediger", status_code=202)
    async def rediger(etape_id: int, request: Request):
        await request.app.state.chat.rediger(etape_id)
        return {}

    @app.post("/api/etapes/{etape_id}/reessayer", status_code=202)
    async def reessayer(etape_id: int, request: Request):
        await request.app.state.chat.reessayer(etape_id)
        return {}

    class DocumentIn(BaseModel):
        contenu: str

    @app.put("/api/etapes/{etape_id}/document", response_model=DocumentOut)
    async def corriger_document(etape_id: int, corps: DocumentIn, request: Request):
        return await request.app.state.chat.corriger(etape_id, corps.contenu)

    @app.post("/api/etapes/{etape_id}/valider", response_model=PipelineDetail)
    async def valider(etape_id: int, request: Request, s: Session):
        pipeline_id = await request.app.state.chat.valider(etape_id)
        return await _detail(s, request.app.state.catalogue, pipeline_id)

    @app.get("/api/etapes/{etape_id}/flux")
    async def flux(etape_id: int, request: Request):
        chat = request.app.state.chat
        await chat.etat(etape_id)  # 404 avant de commencer le flux
        return StreamingResponse(chat.flux(etape_id), media_type="text/event-stream")

    @app.get("/api/conversations", response_model=list[ConversationResume])
    async def lister_conversations(request: Request):
        return await request.app.state.conversations.lister()

    @app.post("/api/conversations", status_code=201, response_model=ConversationDetail)
    async def creer_conversation(request: Request):
        service = request.app.state.conversations
        return await service.detail((await service.creer()).id)

    @app.get("/api/conversations/{conversation_id}", response_model=ConversationDetail)
    async def lire_conversation(conversation_id: int, request: Request):
        return await request.app.state.conversations.detail(conversation_id)

    @app.patch("/api/conversations/{conversation_id}", response_model=ConversationDetail)
    async def renommer_conversation(
        conversation_id: int, corps: ConversationPatch, request: Request
    ):
        service = request.app.state.conversations
        await service.renommer(conversation_id, corps.titre)
        return await service.detail(conversation_id)

    @app.delete("/api/conversations/{conversation_id}", status_code=204)
    async def supprimer_conversation(conversation_id: int, request: Request):
        await request.app.state.conversations.supprimer(conversation_id)

    @app.post("/api/conversations/{conversation_id}/messages", status_code=202)
    async def envoyer_conversation(conversation_id: int, corps: MessageIn, request: Request):
        await request.app.state.conversations.envoyer(conversation_id, corps.contenu)
        return {}

    @app.post("/api/conversations/{conversation_id}/reessayer", status_code=202)
    async def reessayer_conversation(conversation_id: int, request: Request):
        await request.app.state.conversations.reessayer(conversation_id)
        return {}

    @app.post("/api/actions/{action_id}/confirmer", status_code=202)
    async def confirmer_action(action_id: int, request: Request):
        await request.app.state.conversations.confirmer(action_id)
        return {}

    @app.post("/api/actions/{action_id}/refuser", status_code=202)
    async def refuser_action(action_id: int, request: Request):
        await request.app.state.conversations.refuser(action_id)
        return {}

    @app.get("/api/conversations/{conversation_id}/flux")
    async def flux_conversation(conversation_id: int, request: Request):
        service = request.app.state.conversations
        await service.etat(conversation_id)  # 404 avant de commencer le flux
        return StreamingResponse(service.flux(conversation_id), media_type="text/event-stream")

    @app.get("/api/evenements")
    async def evenements():
        return StreamingResponse(
            flux_evenements(bus),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

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
