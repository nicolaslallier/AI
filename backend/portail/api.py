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
from portail.db import (
    Etape,
    Pipeline,
    Projet,
    Proposition,
    Tache,
    TacheDependance,
    creer_moteur,
    fabrique_sessions,
)
from portail.depots import Depots, ErreurDepot
from portail.etats import Etat
from portail.llm import ClientLLM
from portail.moteur import Refus, creer_pipeline, recuperer_interrompues, spec_courante
from portail.schemas import (
    DEPOT_RE,
    Deplacement,
    DocumentOut,
    DonneesTache,
    DonneesTachePartielles,
    EtapeOut,
    Kanban,
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
)
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
                        for k in ("id", "ordre", "agent", "etat", "erreur", "action")
                    },
                    "messages": e.messages,
                    "document": e.document,
                    "jauge": j,
                },
                from_attributes=True,
            )
        )
    return PipelineDetail(
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
    return [
        TacheVue.model_validate(t, from_attributes=True).model_copy(
            update={
                "depend_de": deps.get(t.id, []),
                "dependances_non_terminees": [
                    d for d in deps.get(t.id, []) if colonnes[d] != "terminee"
                ],
            }
        )
        for t in taches
    ]


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


def _verifier_depot(url: str | None) -> None:
    if url is not None and not DEPOT_RE.fullmatch(url):
        raise Refus(422, "URL de dépôt GitHub invalide")


def _resume(p: Pipeline, nom: str) -> PipelineResume:
    return PipelineResume(
        id=p.id, projet_id=p.projet_id, projet_nom=nom, type=p.type, etat=p.etat, maj_le=p.maj_le
    )


def create_app(
    reglages: Reglages | None = None,
    llm: ClientLLM | None = None,
    catalogue: Catalogue | None = None,
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
        yield
        taches = list(app.state.chat.taches.values())
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
        _verifier_depot(corps.depot_url)
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
        _verifier_depot(corps.depot_url)
        for champ in corps.model_fields_set:
            setattr(projet, champ, getattr(corps, champ))
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
        await request.app.state.chat.annuler(pipeline_id)
        return await _detail(s, request.app.state.catalogue, pipeline_id)

    @app.get("/api/projets/{projet_id}/kanban", response_model=Kanban)
    async def kanban(projet_id: int, s: Session):
        if await s.get(Projet, projet_id) is None:
            raise Refus(404, "projet introuvable")
        taches = (
            await s.scalars(
                select(Tache)
                .where(Tache.projet_id == projet_id)
                .order_by(Tache.colonne, Tache.rang, Tache.id)
            )
        ).all()
        props = (
            await s.scalars(
                select(Proposition)
                .where(Proposition.projet_id == projet_id, Proposition.etat == "ouverte")
                .order_by(Proposition.id)
            )
        ).all()
        return Kanban(
            taches=await _vues(s, list(taches)),
            propositions=[PropositionVue.model_validate(p, from_attributes=True) for p in props],
        )

    @app.post("/api/projets/{projet_id}/taches", status_code=201, response_model=TacheVue)
    async def ajouter_tache(projet_id: int, corps: DonneesTache, s: Session):
        t = await creer_tache(s, projet_id, corps, "nicolas")
        await s.commit()
        return await _vue(s, t.id)

    @app.patch("/api/taches/{tache_id}", response_model=TacheVue)
    async def modifier(tache_id: int, corps: DonneesTachePartielles, s: Session):
        t = await _tache(s, tache_id)
        await modifier_tache(s, t, corps, "nicolas")
        await s.commit()
        return await _vue(s, tache_id)

    @app.post("/api/taches/{tache_id}/deplacer", response_model=TacheVue)
    async def deplacer(tache_id: int, corps: Deplacement, s: Session):
        t = await _tache(s, tache_id)
        await deplacer_tache(s, t, corps.colonne, corps.avant_id, "nicolas")
        await s.commit()
        return await _vue(s, tache_id)

    @app.delete("/api/taches/{tache_id}", status_code=204)
    async def supprimer(tache_id: int, s: Session):
        t = await _tache(s, tache_id)
        await supprimer_tache(s, t, "nicolas")
        await s.commit()

    @app.post("/api/taches/{tache_id}/annuler", response_model=TacheVue)
    async def annuler_tache(tache_id: int, request: Request, s: Session):
        t = await _tache(s, tache_id)
        verrou, projet_id = t.verrou, t.projet_id
        if verrou is None:
            raise Refus(409, "rien à annuler")
        etat = await s.scalar(select(Pipeline.etat).where(Pipeline.id == verrou))
        await s.rollback()  # libère la transaction avant que le service ouvre la sienne
        if etat is not None and etat not in (Etat.TERMINEE, Etat.ECHOUEE):
            await request.app.state.chat.annuler(verrou)  # même chemin que /pipelines/{id}/annuler
        # ordre des verrous : projet d'abord, comme partout ailleurs
        await s.scalar(select(Projet.id).where(Projet.id == projet_id).with_for_update())
        t = await s.scalar(
            select(Tache)
            .where(Tache.id == tache_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        t.verrou = None
        await deplacer_tache(s, t, "a_faire", None, "nicolas")
        await s.commit()
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
