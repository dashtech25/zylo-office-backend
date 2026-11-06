"""BE-189 : verrou de version sur le membership (table `organization_user`).

Revision ID: b189c0de0189
Revises: 8a46d69b86bf
Create Date: 2026-11-06

Ajoute `organization_user.version` (entier, défaut 1, non nul) : compteur incrémenté à
chaque changement d'état d'un membership (app/identity/membership.py). Migration purement
additive : les lignes existantes reçoivent 1 par défaut.

Downgrade : suppression de la colonne. Seul le compteur de version disparaît.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b189c0de0189"
down_revision: Union[str, None] = "8a46d69b86bf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "organization_user",
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="Version du membership (BE-189) ; incrémentée à chaque changement d'état.",
        ),
    )


def downgrade() -> None:
    op.drop_column("organization_user", "version")
