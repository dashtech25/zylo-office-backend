"""BE-246 : tables de sortie de tenant et de holds juridiques.

Revision ID: a246c1d2e3f4
Revises: adce56acf5ff, f243a0b1c2d4
Create Date: 2026-11-05 22:00:00.000000

Crée `tenant_exit_requests` (demande de sortie, approbation, état, holds, étapes, attestation) et
`legal_holds` (holds posés sur un tenant). Cette révision réconcilie aussi les deux têtes présentes
sur develop (adce56acf5ff : BE-238 ; f243a0b1c2d4 : BE-243/BE-252/BE-258), pour qu'il n'en reste
qu'une seule après BE-246.

Downgrade : supprime les deux tables ; les révisions de fusion restent sans effet.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "a246c1d2e3f4"
down_revision: Union[str, Sequence[str], None] = ("adce56acf5ff", "f243a0b1c2d4")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenant_exit_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organizationId", postgresql.UUID(as_uuid=True), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("demandeur", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("approbateur", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("motif", sa.String(500), nullable=False),
        sa.Column("etat", sa.String(16), nullable=False),
        sa.Column("holds", sa.JSON(), nullable=False),
        sa.Column("etapes", sa.JSON(), nullable=False),
        sa.Column("attestation", sa.JSON(), nullable=False),
        sa.Column("decideLe", sa.DateTime(timezone=True), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("etat IN ('terminee', 'tenue')", name="ck_tenant_exit_requests_etat"),
        comment="Demande de sortie d'un tenant : approbation, holds, étapes et attestation (BE-246).",
    )
    op.create_index("ix_tenant_exit_requests_organizationId", "tenant_exit_requests", ["organizationId"])

    op.create_table(
        "legal_holds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organizationId", postgresql.UUID(as_uuid=True), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("motif", sa.String(500), nullable=False),
        sa.Column("decideur", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("poseLe", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="Holds juridiques posés sur un tenant ; un hold actif bloque la sortie (BE-246).",
    )
    op.create_index("ix_legal_holds_organizationId", "legal_holds", ["organizationId"])


def downgrade() -> None:
    op.drop_index("ix_legal_holds_organizationId", table_name="legal_holds")
    op.drop_table("legal_holds")
    op.drop_index("ix_tenant_exit_requests_organizationId", table_name="tenant_exit_requests")
    op.drop_table("tenant_exit_requests")
