"""table carte_doc (kanban de documentation)

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"


def upgrade() -> None:
    op.create_table(
        "carte_doc",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "projet_id", sa.Integer, sa.ForeignKey("projet.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("titre", sa.String(200), nullable=False),
        sa.Column("genre", sa.String, nullable=False),
        sa.Column("consigne", sa.Text, nullable=False, server_default=""),
        sa.Column("colonne", sa.String, nullable=False, server_default="a_rediger"),
        sa.Column("chemin", sa.String, nullable=False, unique=True),
        sa.Column("contenu", sa.Text, nullable=False, server_default=""),
        sa.Column("remarques", sa.JSON, nullable=False),
        sa.Column("renvois", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sha", sa.String),
        sa.Column("pipeline_id", sa.Integer, sa.ForeignKey("pipeline.id", ondelete="SET NULL")),
        sa.Column("erreur", sa.Text),
        sa.Column("etag", sa.String),
        sa.Column("publie_le", sa.DateTime(timezone=True)),
        sa.Column(
            "cree_le", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "maj_le", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("carte_doc")
