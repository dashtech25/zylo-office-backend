"""Réconciliation des états incertains (BE-052) : table module_reconciliations.

Revision ID: b052c4e7a1f3
Revises: 041531056547
Create Date: 2026-11-04

Un cas est ouvert quand deux sources d'autorité se contredisent. La table n'est jamais mise à jour
pour changer l'état du sujet (CA-1). `idempotencyKey` est unique : un événement rejoué ne crée pas de
second cas (CA-2). Le downgrade supprime la table puis le type énuméré.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b052c4e7a1f3"
down_revision: Union[str, None] = "041531056547"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ETAT_RECONCILIATION = postgresql.ENUM("open", "resolved", "escalated", name="module_reconciliation_state", create_type=False)


def upgrade() -> None:
    ETAT_RECONCILIATION.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "module_reconciliations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subjectType", sa.String(length=50), nullable=False, comment="Type du sujet (ex. tenant_module)."),
        sa.Column("subjectId", postgresql.UUID(as_uuid=True), nullable=False, comment="Identifiant du sujet."),
        sa.Column(
            "organizationId",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization.id"),
            nullable=False,
            comment="Organisation concernée.",
        ),
        sa.Column(
            "state",
            ETAT_RECONCILIATION,
            nullable=False,
            server_default="open",
            comment="État du cas : open, resolved ou escalated.",
        ),
        sa.Column("sourceA", sa.String(length=100), nullable=False, comment="Valeur lue dans la première source."),
        sa.Column("sourceB", sa.String(length=100), nullable=False, comment="Valeur lue dans la seconde source."),
        sa.Column("idempotencyKey", sa.String(length=128), nullable=False, comment="Clé de l'événement qui a ouvert le cas (unique)."),
        sa.Column("openedAt", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolution", sa.String(length=30), nullable=True, comment="Décision de résolution."),
        sa.Column("resolvedBy", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True, comment="Compte qui a résolu le cas."),
        sa.Column("resolvedAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidenceReference", sa.String(length=255), nullable=True, comment="Référence de la preuve fournie à la résolution."),
        sa.UniqueConstraint("idempotencyKey", name="uq_module_reconciliations_idempotency_key"),
        comment="Cas de réconciliation des états incertains (BE-052). Le cas ne modifie pas le sujet.",
    )
    op.create_index("ix_module_reconciliations_organizationId", "module_reconciliations", ["organizationId"])
    op.create_index("ix_module_reconciliations_subject", "module_reconciliations", ["subjectType", "subjectId"])


def downgrade() -> None:
    op.drop_index("ix_module_reconciliations_subject", table_name="module_reconciliations")
    op.drop_index("ix_module_reconciliations_organizationId", table_name="module_reconciliations")
    op.drop_table("module_reconciliations")
    ETAT_RECONCILIATION.drop(op.get_bind(), checkfirst=True)
