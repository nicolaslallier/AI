from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    false,
    func,
)
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
    depot_url: Mapped[str | None] = mapped_column(String)
    branche_ref: Mapped[str | None] = mapped_column(String)  # nul : branche par défaut du dépôt
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
    sha: Mapped[str | None] = mapped_column(String)  # point de départ calculé une fois
    apercu: Mapped[str | None] = mapped_column(Text)

    pipeline: Mapped[Pipeline] = relationship(back_populates="etapes")
    messages: Mapped[list["Message"]] = relationship(order_by="Message.id", back_populates="etape")
    document: Mapped["Document | None"] = relationship(back_populates="etape")


class Message(Base):
    __tablename__ = "message"

    id: Mapped[int] = mapped_column(primary_key=True)
    etape_id: Mapped[int] = mapped_column(ForeignKey("etape.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String)  # user | assistant | system | tool
    contenu: Mapped[str] = mapped_column(Text)
    outil: Mapped[str | None] = mapped_column(String)  # libellé de l'appel, ex. lire(src/a.py)
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


class Tache(Base):
    __tablename__ = "tache"
    __table_args__ = (Index("ix_tache_projet_colonne_rang", "projet_id", "colonne", "rang"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    projet_id: Mapped[int] = mapped_column(ForeignKey("projet.id", ondelete="CASCADE"))
    titre: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    criteres: Mapped[list] = mapped_column(JSON, default=list)
    fichiers: Mapped[list] = mapped_column(JSON, default=list)
    colonne: Mapped[str] = mapped_column(String, default="a_faire", server_default="a_faire")
    rang: Mapped[int] = mapped_column(Integer)
    origine: Mapped[str] = mapped_column(String)  # "agent" | "manuel"
    document_id: Mapped[int | None] = mapped_column(ForeignKey("document.id", ondelete="SET NULL"))
    protegee: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    verrou: Mapped[int | None] = mapped_column(ForeignKey("pipeline.id", ondelete="SET NULL"))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    cree_le: Mapped[datetime] = _horodatage()
    maj_le: Mapped[datetime] = _horodatage(onupdate=func.now())


class TacheDependance(Base):
    __tablename__ = "tache_dependance"

    tache_id: Mapped[int] = mapped_column(
        ForeignKey("tache.id", ondelete="CASCADE"), primary_key=True
    )
    depend_de_id: Mapped[int] = mapped_column(
        ForeignKey("tache.id", ondelete="CASCADE"), primary_key=True
    )


class TacheEvenement(Base):
    __tablename__ = "tache_evenement"

    id: Mapped[int] = mapped_column(primary_key=True)
    projet_id: Mapped[int] = mapped_column(ForeignKey("projet.id", ondelete="CASCADE"))
    tache_id: Mapped[int] = mapped_column(Integer)  # sans clé étrangère : le journal survit
    type: Mapped[str] = mapped_column(String)  # creation | modification | deplacement | suppression
    auteur: Mapped[str] = mapped_column(String)  # "nicolas" | "agent:<nom>"
    donnees: Mapped[dict] = mapped_column(JSON, default=dict)
    cree_le: Mapped[datetime] = _horodatage()


class Proposition(Base):
    __tablename__ = "proposition"

    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipeline.id", ondelete="CASCADE"))
    etape_id: Mapped[int] = mapped_column(ForeignKey("etape.id", ondelete="CASCADE"))
    projet_id: Mapped[int] = mapped_column(ForeignKey("projet.id", ondelete="CASCADE"))
    sorte: Mapped[str] = mapped_column(String)  # nouvelle | modification | retrait
    cle: Mapped[str | None] = mapped_column(String)
    tache_id: Mapped[int | None] = mapped_column(ForeignKey("tache.id", ondelete="SET NULL"))
    version_tache: Mapped[int | None] = mapped_column(Integer)
    donnees: Mapped[dict] = mapped_column(JSON, default=dict)
    etat: Mapped[str] = mapped_column(String, default="ouverte", server_default="ouverte")
    tache_creee_id: Mapped[int | None] = mapped_column(ForeignKey("tache.id", ondelete="SET NULL"))
    cree_le: Mapped[datetime] = _horodatage()


def creer_moteur(url: str) -> AsyncEngine:
    return create_async_engine(url)


def fabrique_sessions(moteur: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(moteur, expire_on_commit=False)
