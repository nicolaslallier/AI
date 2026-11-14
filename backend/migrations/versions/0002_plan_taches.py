"""kanban, propositions, dépôt du projet

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"


def _ts(nom):
    return sa.Column(nom, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.add_column("projet", sa.Column("depot_url", sa.String))
    op.add_column("projet", sa.Column("branche_ref", sa.String))
    op.add_column("etape", sa.Column("sha", sa.String))
    op.add_column("etape", sa.Column("apercu", sa.Text))
    op.add_column("message", sa.Column("outil", sa.String))

    op.create_table(
        "tache",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "projet_id", sa.Integer, sa.ForeignKey("projet.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("titre", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("criteres", sa.JSON, nullable=False),
        sa.Column("fichiers", sa.JSON, nullable=False),
        sa.Column("colonne", sa.String, nullable=False, server_default="a_faire"),
        sa.Column("rang", sa.Integer, nullable=False),
        sa.Column("origine", sa.String, nullable=False),
        sa.Column("document_id", sa.Integer, sa.ForeignKey("document.id", ondelete="SET NULL")),
        sa.Column("protegee", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("verrou", sa.Integer, sa.ForeignKey("pipeline.id", ondelete="SET NULL")),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        _ts("cree_le"),
        _ts("maj_le"),
    )
    op.create_index("ix_tache_projet_colonne_rang", "tache", ["projet_id", "colonne", "rang"])
    op.create_table(
        "tache_dependance",
        sa.Column(
            "tache_id",
            sa.Integer,
            sa.ForeignKey("tache.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "depend_de_id",
            sa.Integer,
            sa.ForeignKey("tache.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_table(
        "tache_evenement",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "projet_id", sa.Integer, sa.ForeignKey("projet.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("tache_id", sa.Integer, nullable=False),
        sa.Column("type", sa.String, nullable=False),
        sa.Column("auteur", sa.String, nullable=False),
        sa.Column("donnees", sa.JSON, nullable=False),
        _ts("cree_le"),
    )
    op.create_table(
        "proposition",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "pipeline_id",
            sa.Integer,
            sa.ForeignKey("pipeline.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "etape_id", sa.Integer, sa.ForeignKey("etape.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "projet_id", sa.Integer, sa.ForeignKey("projet.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("sorte", sa.String, nullable=False),
        sa.Column("cle", sa.String),
        sa.Column("tache_id", sa.Integer, sa.ForeignKey("tache.id", ondelete="SET NULL")),
        sa.Column("version_tache", sa.Integer),
        sa.Column("donnees", sa.JSON, nullable=False),
        sa.Column("etat", sa.String, nullable=False, server_default="ouverte"),
        sa.Column("tache_creee_id", sa.Integer, sa.ForeignKey("tache.id", ondelete="SET NULL")),
        _ts("cree_le"),
    )


def downgrade() -> None:
    for t in ("proposition", "tache_evenement", "tache_dependance"):
        op.drop_table(t)
    op.drop_index("ix_tache_projet_colonne_rang", "tache")
    op.drop_table("tache")
    op.drop_column("message", "outil")
    op.drop_column("etape", "apercu")
    op.drop_column("etape", "sha")
    op.drop_column("projet", "branche_ref")
    op.drop_column("projet", "depot_url")
