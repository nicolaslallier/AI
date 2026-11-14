"""boucle de dev : config d'exécution, exécutions, commandes lancées

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op


def _ts(nom):
    return sa.Column(nom, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _fk(nom, cible):
    return sa.Column(
        nom, sa.Integer, sa.ForeignKey(f"{cible}.id", ondelete="CASCADE"), nullable=False
    )


revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.add_column("projet", sa.Column("config_execution", sa.Text))
    op.add_column("tache", sa.Column("resume_blocage", sa.Text))
    op.create_table(
        "execution_dev",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "pipeline_id",
            sa.Integer,
            sa.ForeignKey("pipeline.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        _fk("tache_id", "tache"),
        sa.Column("n", sa.Integer, nullable=False),
        sa.Column("branche", sa.String, nullable=False),
        sa.Column("espace", sa.String, nullable=False),
        sa.Column("base", sa.String, nullable=False),
        sa.Column("base_sha", sa.String, nullable=False),
        sa.Column("phase", sa.String, nullable=False),
        sa.Column("renvois", sa.Integer, nullable=False, server_default="0"),
        sa.Column("interruptions", sa.Integer, nullable=False, server_default="0"),
        sa.Column("remarques", sa.JSON, nullable=False),
        sa.Column("fichiers_tests", sa.JSON, nullable=False),
        sa.Column("sortie_rouge", sa.Text),
        sa.Column("pr_numero", sa.Integer),
        sa.Column("pr_url", sa.String),
        _ts("debut"),
    )
    op.create_table(
        "commande_lancee",
        sa.Column("id", sa.Integer, primary_key=True),
        _fk("pipeline_id", "pipeline"),
        _fk("etape_id", "etape"),
        sa.Column("nom", sa.String, nullable=False),
        sa.Column("code", sa.Integer),
        sa.Column("delai_depasse", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("sortie", sa.Text, nullable=False, server_default=""),
        _ts("debut"),
        _ts("fin"),
    )


def downgrade() -> None:
    op.drop_table("commande_lancee")
    op.drop_table("execution_dev")
    op.drop_column("tache", "resume_blocage")
    op.drop_column("projet", "config_execution")
