"""tache.relance_le (relance des blocages passagers)

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"


def upgrade() -> None:
    op.add_column("tache", sa.Column("relance_le", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("tache", "relance_le")
