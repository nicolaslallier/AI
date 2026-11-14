from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _horodatage(**kw):
    return mapped_column(DateTime(timezone=True), server_default=func.now(), **kw)


class Projet(Base):
    __tablename__ = "projet"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    cree_le: Mapped[datetime] = _horodatage()


class Pipeline(Base):
    __tablename__ = "pipeline"

    id: Mapped[int] = mapped_column(primary_key=True)
    projet_id: Mapped[int] = mapped_column(ForeignKey("projet.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String)
    etat: Mapped[str] = mapped_column(String, default="en_cours", server_default="en_cours")
    cree_le: Mapped[datetime] = _horodatage()
    maj_le: Mapped[datetime] = _horodatage(onupdate=func.now())

    etapes: Mapped[list["Etape"]] = relationship(order_by="Etape.ordre", back_populates="pipeline")


class Etape(Base):
    __tablename__ = "etape"

    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipeline.id", ondelete="CASCADE"))
    ordre: Mapped[int]
    agent: Mapped[str] = mapped_column(String)
    etat: Mapped[str] = mapped_column(String, default="a_faire", server_default="a_faire")
    erreur: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str | None] = mapped_column(String)  # "repondre" | "rediger"

    pipeline: Mapped[Pipeline] = relationship(back_populates="etapes")
    messages: Mapped[list["Message"]] = relationship(order_by="Message.id", back_populates="etape")
    document: Mapped["Document | None"] = relationship(back_populates="etape")


class Message(Base):
    __tablename__ = "message"

    id: Mapped[int] = mapped_column(primary_key=True)
    etape_id: Mapped[int] = mapped_column(ForeignKey("etape.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String)  # user | assistant | system
    contenu: Mapped[str] = mapped_column(Text)
    cree_le: Mapped[datetime] = _horodatage()

    etape: Mapped[Etape] = relationship(back_populates="messages")


class Document(Base):
    __tablename__ = "document"

    id: Mapped[int] = mapped_column(primary_key=True)
    projet_id: Mapped[int] = mapped_column(ForeignKey("projet.id", ondelete="CASCADE"))
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipeline.id", ondelete="CASCADE"))
    etape_id: Mapped[int] = mapped_column(ForeignKey("etape.id", ondelete="CASCADE"), unique=True)
    type: Mapped[str] = mapped_column(String)
    contenu: Mapped[str] = mapped_column(Text, default="", server_default="")
    etat: Mapped[str] = mapped_column(String, default="brouillon", server_default="brouillon")
    dernier_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("message.id", ondelete="SET NULL")
    )
    maj_le: Mapped[datetime] = _horodatage(onupdate=func.now())

    etape: Mapped[Etape] = relationship(back_populates="document")


def creer_moteur(url: str) -> AsyncEngine:
    return create_async_engine(url)


def fabrique_sessions(moteur: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(moteur, expire_on_commit=False)
