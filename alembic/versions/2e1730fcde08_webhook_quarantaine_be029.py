"""BE-029 : quarantaine des évènements webhook de paiement.

Ajoute à `paymentWebhookEvent` les colonnes qui tracent un évènement contradictoire
reçu avec le même identifiant fournisseur : `quarantinedAt` (date de mise en quarantaine)
et `quarantineDigest` (empreinte du contenu contradictoire, jamais appliqué).

Revision ID: 2e1730fcde08
Revises: d4e5f6a7b8c9
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "2e1730fcde08"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "paymentWebhookEvent",
        sa.Column("quarantinedAt", sa.DateTime(timezone=True), nullable=True,
                  comment="Date de mise en quarantaine d'un évènement contradictoire (BE-029)."),
    )
    op.add_column(
        "paymentWebhookEvent",
        sa.Column("quarantineDigest", sa.String(64), nullable=True,
                  comment="SHA-256 du contenu contradictoire mis en quarantaine, jamais appliqué (BE-029)."),
    )


def downgrade() -> None:
    op.drop_column("paymentWebhookEvent", "quarantineDigest")
    op.drop_column("paymentWebhookEvent", "quarantinedAt")
