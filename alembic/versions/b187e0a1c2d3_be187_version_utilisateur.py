"""BE-187 : verrou de version sur l'utilisateur (table `user`).

Revision ID: b187e0a1c2d3
Revises: 52e99f1b21b5
Create Date: 2026-11-05

Ajoute `user.version` (entier, défaut 1, non nul) : compteur incrémenté à chaque
transition de statut (app/identity/cycle_de_vie_utilisateur.py). Migration purement
additive : les lignes existantes reçoivent 1 par défaut.

Downgrade : suppression de la colonne. Aucune donnée métier n'est perdue, seul le
compteur de version disparaît.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b187e0a1c2d3"
down_revision: Union[str, None] = "52e99f1b21b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="Version de l'utilisateur (BE-187) ; incrémentée à chaque transition de statut.",
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "version")
