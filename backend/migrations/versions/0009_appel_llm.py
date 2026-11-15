"""table appel_llm (mesure des appels au modèle, sans contenu)

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    op.create_table(
        "appel_llm",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "quand", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("agent", sa.String, nullable=False),
        sa.Column("modele", sa.String, nullable=False),
        sa.Column("lieu", sa.String, nullable=False, server_default="portail"),
        sa.Column("version_image", sa.String),
        sa.Column("mission", sa.String),
        sa.Column("pipeline_id", sa.Integer),
        sa.Column("etape_id", sa.Integer),
        sa.Column("tache_id", sa.Integer),
        sa.Column("conversation_id", sa.Integer),
        sa.Column("jetons_entree", sa.Integer),
        sa.Column("jetons_sortie", sa.Integer),
        sa.Column("duree_ms", sa.Integer, nullable=False),
        sa.Column("issue", sa.String, nullable=False),
    )
    op.create_index("ix_appel_llm_mission", "appel_llm", ["mission"])
    op.create_index("ix_appel_llm_agent_quand", "appel_llm", ["agent", "quand"])


def downgrade() -> None:
    op.drop_table("appel_llm")
