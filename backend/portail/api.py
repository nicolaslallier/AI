import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from portail.agents import Catalogue, charger_catalogue
from portail.chat import Diffuseur, ServiceChat
from portail.config import Reglages
from portail.contexte import construire, jauge
from portail.db import Document, Etape, Pipeline, Projet, creer_moteur, fabrique_sessions
from portail.llm import ClientLLM
from portail.moteur import Refus, creer_pipeline, recuperer_interrompues
from portail.schemas import (
    EtapeOut,
    PipelineDetail,
    PipelineIn,
    PipelineResume,
    ProjetDetail,
    ProjetIn,
    ProjetOut,
    ProjetRef,
    SpecCourante,
)


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
        llm = construire(catalogue.agents[e.agent], e.messages, e.document)
        etapes.append(
            EtapeOut.model_validate(
                {
                    **{
                        k: getattr(e, k)
                        for k in ("id", "ordre", "agent", "etat", "erreur", "action")
                    },
                    "messages": e.messages,
                    "document": e.document,
                    "jauge": jauge(catalogue.agents[e.agent], llm),
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


def _resume(p: Pipeline, nom: str) -> PipelineResume:
    return PipelineResume(
        id=p.id, projet_id=p.projet_id, projet_nom=nom, type=p.type, etat=p.etat, maj_le=p.maj_le
    )


def create_app(
    reglages: Reglages | None = None,
    llm: ClientLLM | None = None,
    catalogue: Catalogue | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        r = reglages or Reglages()
        app.state.reglages = r
        app.state.catalogue = catalogue or charger_catalogue(r.agents_fichier)
        app.state.llm = llm or ClientLLM(r.litellm_url, r.litellm_cle)
        moteur = creer_moteur(r.database_url)
        app.state.sessions = fabrique_sessions(moteur)
        async with app.state.sessions() as s:
            await recuperer_interrompues(s)
            await s.commit()
        app.state.diffuseur = Diffuseur()
        app.state.chat = ServiceChat(
            app.state.sessions, app.state.catalogue, app.state.llm, app.state.diffuseur
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
            and not chemin.startswith("/api/sante")
            and "X-Auth-Request-Email" not in request.headers
        ):
            return JSONResponse(status_code=401, content={"detail": "non authentifié"})
        return await call_next(request)

    @app.get("/api/sante")
    async def sante():
        return {"ok": True}

    @app.get("/api/projets", response_model=list[ProjetOut])
    async def lister_projets(s: Session):
        return (await s.scalars(select(Projet).order_by(Projet.nom))).all()

    @app.post("/api/projets", status_code=201, response_model=ProjetOut)
    async def creer_projet(corps: ProjetIn, s: Session):
        projet = Projet(nom=corps.nom, description=corps.description)
        s.add(projet)
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
        spec = await s.scalar(
            select(Document)
            .where(
                Document.projet_id == projet_id,
                Document.type == "spec",
                Document.etat == "validee",
            )
            .order_by(Document.maj_le.desc())
            .limit(1)
        )
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
        pipeline = await creer_pipeline(s, cat, corps.projet_id, corps.type)
        await s.commit()
        return await _detail(s, cat, pipeline.id)

    @app.get("/api/pipelines/{pipeline_id}", response_model=PipelineDetail)
    async def lire_pipeline(pipeline_id: int, request: Request, s: Session):
        return await _detail(s, request.app.state.catalogue, pipeline_id)

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

    @app.get("/api/etapes/{etape_id}/flux")
    async def flux(etape_id: int, request: Request):
        chat = request.app.state.chat
        await chat.etat(etape_id)  # 404 avant de commencer le flux
        return StreamingResponse(chat.flux(etape_id), media_type="text/event-stream")

    return app
