"""BE-202 : devis, checkout et consentement.

Étend la table `quote` (bénéficiaire et indicateur d'essai) et crée la table `consent`
(consentement explicite d'un payeur). La table `checkout` n'a pas besoin de changer : son
état `open` et son verrou `version` suffisent à la route BE-202.

Downgrade : supprime la table `consent` et les deux colonnes ajoutées à `quote`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "be202d3e4f5a"
down_revision: Union[str, None] = "2402c108f2e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "quote",
        sa.Column("beneficiaryId", sa.UUID(as_uuid=True), nullable=True,
                  comment="Bénéficiaire du devis, distinct du payeur et du tenant (BE-202) ; NULL si c'est le tenant."),
    )
    op.add_column(
        "quote",
        sa.Column("isTrial", sa.Boolean(), nullable=False, server_default=sa.text("false"),
                  comment="Devis d'essai : le checkout exige un consentement d'essai explicite (BE-202)."),
    )
    op.create_table(
        "consent",
        sa.Column("consentId", sa.UUID(as_uuid=True), primary_key=True, comment="Identifiant du consentement."),
        sa.Column("payerId", sa.UUID(as_uuid=True), sa.ForeignKey("billing_payer.id"), nullable=False,
                  comment="Compte payeur qui consent."),
        sa.Column("kind", sa.String(length=30), nullable=False,
                  comment="Nature du consentement ; `trial` pour l'essai (BE-202)."),
        sa.Column("recordedAt", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(),
                  comment="Heure d'enregistrement serveur."),
        comment="Consentement explicite d'un payeur (BE-202). Append-only.",
    )
    op.create_index("ix_consent_payerId", "consent", ["payerId"])


def downgrade() -> None:
    op.drop_index("ix_consent_payerId", table_name="consent")
    op.drop_table("consent")
    op.drop_column("quote", "isTrial")
    op.drop_column("quote", "beneficiaryId")
