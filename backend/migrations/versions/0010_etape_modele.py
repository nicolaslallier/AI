"""colonne etape.modele (modèle choisi pour l'étape)

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"


def upgrade() -> None:
    op.add_column("etape", sa.Column("modele", sa.String))


def downgrade() -> None:
    op.drop_column("etape", "modele")
