"""webhook entrant : table webhook_recu (BE-163)

Revision ID: 3c9e0b7f2a14
Revises: 290f30a9bcbf
Create Date: 2026-11-05 13:00:00.000000

Crée la table `webhook_recu` : un événement externe reçu par connecteur, avec la clé
d'idempotence `(connecteurId, idExterne)` (CA-2). Seul le routage minimal est stocké
(`payloadMinimal`), pas la charge utile complète.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3c9e0b7f2a14"
down_revision: Union[str, None] = "290f30a9bcbf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "webhook_recu",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("connecteurId", sa.UUID(as_uuid=True), sa.ForeignKey("connecteur.id"), nullable=False),
        sa.Column("idExterne", sa.String(length=255), nullable=False),
        sa.Column("organizationId", sa.UUID(as_uuid=True), sa.ForeignKey("organization.id"), nullable=True),
        sa.Column("payloadMinimal", postgresql.JSONB(), nullable=False),
        sa.Column("recuAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("statut", sa.String(length=16), server_default="recu", nullable=False),
        sa.CheckConstraint("statut IN ('recu')", name="ck_webhook_recu_statut"),
        sa.CheckConstraint("length(btrim(\"idExterne\")) > 0", name="ck_webhook_recu_id_externe_non_vide"),
        sa.UniqueConstraint("connecteurId", "idExterne", name="uq_webhook_recu_connecteur_id_externe"),
        comment="Événements externes reçus par webhook entrant, sans charge utile complète (BE-163).",
    )
    op.create_index("ix_webhook_recu_connecteurId", "webhook_recu", ["connecteurId"])
    op.create_index("ix_webhook_recu_organizationId", "webhook_recu", ["organizationId"])


def downgrade() -> None:
    op.drop_index("ix_webhook_recu_organizationId", table_name="webhook_recu")
    op.drop_index("ix_webhook_recu_connecteurId", table_name="webhook_recu")
    op.drop_table("webhook_recu")
