"""file de lettres mortes d'intégration (BE-165)

Revision ID: c165a0b1d2e3
Revises: 7b3cdbc1efc8
Create Date: 2026-11-05 14:00:00.000000

Table `lettreMorte` : une ligne par tentative définitivement échouée, avec les champs de la
reprise manuelle (`operateur`, `motif`, `reprisAt`). Unicité sur `tentativeId` (une lettre par
tentative). Downgrade : suppression de la table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c165a0b1d2e3"
down_revision: Union[str, None] = "7b3cdbc1efc8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lettreMorte",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tentativeId", postgresql.UUID(as_uuid=True), sa.ForeignKey("tentativeIntegration.id"), nullable=False),
        sa.Column("organizationId", postgresql.UUID(as_uuid=True), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("originalId", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("motif", sa.String(length=500), nullable=True),
        sa.Column("operateur", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("reprisAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("motif IS NULL OR length(btrim(motif)) > 0", name="ck_lettreMorte_motif_non_vide"),
        sa.UniqueConstraint("tentativeId", name="uq_lettreMorte_tentativeId"),
        comment="Lettres mortes d'intégration et reprises manuelles tracées (BE-165).",
    )
    op.create_index(
        "ix_lettreMorte_organizationId_createdAt", "lettreMorte", ["organizationId", "createdAt"]
    )


def downgrade() -> None:
    op.drop_index("ix_lettreMorte_organizationId_createdAt", table_name="lettreMorte")
    op.drop_table("lettreMorte")
