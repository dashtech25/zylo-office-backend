"""Table restore_drills : exercices de restauration vérifiée (BE-245).

Revision ID: e245a1b2c3d4
Revises: f9d7ef17ec72
Create Date: 2026-11-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "e245a1b2c3d4"
down_revision: Union[str, None] = "f9d7ef17ec72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "restore_drills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("horodatage", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sauvegarde_id", sa.Uuid(), nullable=False),
        sa.Column("acteur_user_id", sa.Uuid(), nullable=False),
        sa.Column("environnement", sa.String(length=120), nullable=False),
        sa.Column("invariants", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("durees", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("resultat", sa.String(length=20), nullable=False),
        sa.CheckConstraint("resultat IN ('reussie','echec')", name="ck_restore_drills_resultat"),
        sa.ForeignKeyConstraint(["sauvegarde_id"], ["backup_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="Exercices de restauration vérifiée sur base jetable, avec invariants et durées (BE-245).",
    )


def downgrade() -> None:
    op.drop_table("restore_drills")
