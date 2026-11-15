"""journal d'audit

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    op.create_table(
        "audit",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "quand", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("auteur", sa.String, nullable=False),
        sa.Column("action", sa.String, nullable=False),
        sa.Column("objet", sa.String, nullable=False),
        sa.Column("objet_id", sa.Integer, nullable=False),
    )
    op.create_index("ix_audit_quand", "audit", ["quand"])


def downgrade() -> None:
    op.drop_table("audit")
