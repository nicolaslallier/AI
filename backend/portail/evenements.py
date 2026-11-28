"""Bus d'événements en mémoire : les écritures en base y déposent des signaux d'invalidation,
diffusés en SSE aux vues kanban, pipelines et bureau (le sondage du front reste le filet de sécurité)."""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Literal

from sqlalchemy import event
from sqlalchemy.orm import Session

from portail.chat import _sse
from portail.db import (
    ActionConversation,
    AppelLLM,
    Avis,
    CarteDoc,
    Conversation,
    Etape,
    ExecutionDev,
    Pipeline,
    Proposition,
    Tache,
)

logger = logging.getLogger(__name__)

Signal = tuple[Literal["kanban", "pipelines", "bureau", "docs", "theme"], int | None | dict]


class Bus:
    def __init__(self) -> None:
        self.abonnes: set[asyncio.Queue[Signal]] = set()

    def abonner(self) -> asyncio.Queue[Signal]:
        file: asyncio.Queue[Signal] = asyncio.Queue(maxsize=100)
        self.abonnes.add(file)
        return file

    def desabonner(self, file: asyncio.Queue[Signal]) -> None:
        self.abonnes.discard(file)

    def publier(self, signal: Signal) -> None:
        for file in list(self.abonnes):
            try:
                file.put_nowait(signal)
            except asyncio.QueueFull:
                pass  # abonné à la traîne : le sondage de secours le rattrapera

    def emettre(self, type_: str, payload: dict) -> None:
        self.publier((type_, payload))


bus = Bus()

_PIPELINES = (Pipeline, Etape, ExecutionDev)
# ce que le bureau affiche et que les signaux ci-dessus ne couvrent pas ; le signal ne porte rien
_BUREAU = (Conversation, ActionConversation, Avis, AppelLLM)


def _signal(objet: object) -> Signal | None:
    if isinstance(objet, Tache | Proposition):
        return ("kanban", objet.projet_id)
    if isinstance(objet, _PIPELINES):
        return ("pipelines", None)
    if isinstance(objet, CarteDoc):
        return ("docs", None)
    if isinstance(objet, _BUREAU):
        return ("bureau", None)
    return None


@event.listens_for(Session, "after_flush")
def _apres_flush(session: Session, _contexte) -> None:
    signaux = session.info.setdefault("signaux", set())
    for objet in (*session.new, *session.dirty, *session.deleted):
        if (s := _signal(objet)) is not None:
            signaux.add(s)


@event.listens_for(Session, "do_orm_execute")
def _avant_execution(etat) -> None:
    if not (etat.is_update or etat.is_delete) or etat.bind_mapper is None:
        return
    classe = etat.bind_mapper.class_
    if classe is Tache:
        s: Signal | None = ("kanban", None)
    elif classe in _PIPELINES:
        s = ("pipelines", None)
    elif classe is CarteDoc:
        s = ("docs", None)
    elif classe in _BUREAU:
        s = ("bureau", None)
    else:
        return
    etat.session.info.setdefault("signaux", set()).add(s)


@event.listens_for(Session, "after_commit")
def _apres_commit(session: Session) -> None:
    for s in session.info.pop("signaux", ()):
        bus.publier(s)


@event.listens_for(Session, "after_rollback")
def _apres_rollback(session: Session) -> None:
    session.info.pop("signaux", None)


async def flux(bus: Bus, ping_s: float = 25) -> AsyncIterator[str]:
    file = bus.abonner()
    try:
        while True:
            try:
                type_, charge = await asyncio.wait_for(file.get(), ping_s)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            if type_ == "kanban":
                yield _sse(type_, {"projet_id": charge})
            else:
                yield _sse(type_, charge or {})
    finally:
        bus.desabonner(file)
