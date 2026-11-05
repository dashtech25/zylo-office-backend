"""journal des tentatives d'intégration (BE-164)

Revision ID: 9b164a0c164e
Revises: 5e31981cf46c
Create Date: 2026-11-05 12:00:00.000000

Table `tentativeIntegration` : une ligne par tentative d'effet d'intégration, sans payload.
Index unique partiel sur (connecteurId, eventId) pour `issue = 'succes'` : une clé d'effet
ne peut avoir qu'un seul succès (CA-3). Downgrade : suppression de la table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "9b164a0c164e"
down_revision: Union[str, None] = "5e31981cf46c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tentativeIntegration",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("connecteurId", postgresql.UUID(as_uuid=True), sa.ForeignKey("connecteur.id"), nullable=False),
        sa.Column("organizationId", postgresql.UUID(as_uuid=True), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("correlationId", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("eventId", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issue", sa.String(length=16), nullable=False),
        sa.Column("codeErreur", sa.String(length=64), nullable=True),
        sa.Column("dureeMs", sa.Integer(), nullable=False),
        sa.Column("tentativeNo", sa.Integer(), nullable=False),
        sa.Column("prochaineTentativeAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("issue IN ('succes', 'echec')", name="ck_tentativeIntegration_issue"),
        sa.CheckConstraint('"dureeMs" >= 0', name="ck_tentativeIntegration_duree_positive"),
        sa.CheckConstraint('"tentativeNo" >= 1', name="ck_tentativeIntegration_tentative_positive"),
        comment="Journal des tentatives d'intégration : métadonnées sans payload (BE-164).",
    )
    op.create_index(
        "uq_tentativeIntegration_effet_succes",
        "tentativeIntegration",
        ["connecteurId", "eventId"],
        unique=True,
        postgresql_where=sa.text("issue = 'succes'"),
    )
    op.create_index(
        "ix_tentativeIntegration_organizationId_createdAt",
        "tentativeIntegration",
        ["organizationId", "createdAt"],
    )


def downgrade() -> None:
    op.drop_index("ix_tentativeIntegration_organizationId_createdAt", table_name="tentativeIntegration")
    op.drop_index("uq_tentativeIntegration_effet_succes", table_name="tentativeIntegration")
    op.drop_table("tentativeIntegration")
