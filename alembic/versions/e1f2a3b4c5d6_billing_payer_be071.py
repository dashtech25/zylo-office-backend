"""payeur, tenant bénéficiaire et administrateur d'abonnement : table billing_payer et colonnes subscription (BE-071)

Revision ID: e1f2a3b4c5d6
Revises: d4e5f6a7b8c9
Create Date: 2026-11-04

Migration additive. Elle crée la table `billing_payer` (payeur d'un abonnement),
puis ajoute à `subscription` trois colonnes nullables : `payerId`,
`beneficiaryTenantId` et `adminUserId`. La table `subscription` appartient à
BE-023 et n'est pas recréée ici.

Backfill : `beneficiaryTenantId` reçoit `organizationId` pour les lignes existantes,
car le tenant bénéficiaire d'un abonnement antérieur est son organisation. Le
backfill ne touche que les lignes où la colonne est encore nulle : un second
passage est sans effet. `payerId` et `adminUserId` restent nuls pour l'historique,
faute de donnée fiable (aucun payeur ni administrateur n'a jamais été enregistré).

Retour arrière : suppression des trois colonnes et de leurs index, puis de la table
`billing_payer`. Les lignes de `subscription` gardent `organizationId`, qui n'a jamais
été modifié, donc aucune donnée d'origine n'est perdue.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "billing_payer",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("payerKind", sa.String(length=30), nullable=False),
        sa.Column("accountRef", sa.String(length=255), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="Payeur d'un abonnement, distinct du tenant bénéficiaire et de l'administrateur (BE-071).",
    )

    op.add_column("subscription", sa.Column("payerId", sa.UUID(as_uuid=True), nullable=True,
                                            comment="Payeur de l'abonnement (BE-071)."))
    op.add_column("subscription", sa.Column("beneficiaryTenantId", sa.UUID(as_uuid=True), nullable=True,
                                            comment="Tenant bénéficiaire, périmètre d'accès (BE-071)."))
    op.add_column("subscription", sa.Column("adminUserId", sa.UUID(as_uuid=True), nullable=True,
                                            comment="Administrateur du tenant bénéficiaire (BE-071)."))

    op.create_foreign_key("fk_subscription_payerId_billing_payer", "subscription", "billing_payer",
                          ["payerId"], ["id"])
    op.create_foreign_key("fk_subscription_beneficiaryTenantId_organization", "subscription", "organization",
                          ["beneficiaryTenantId"], ["id"])
    op.create_foreign_key("fk_subscription_adminUserId_user", "subscription", "user",
                          ["adminUserId"], ["id"])

    op.create_index("ix_subscription_payerId", "subscription", ["payerId"])
    op.create_index("ix_subscription_beneficiaryTenantId", "subscription", ["beneficiaryTenantId"])
    op.create_index("ix_subscription_adminUserId", "subscription", ["adminUserId"])

    # Backfill idempotent : seules les lignes sans tenant bénéficiaire sont touchées.
    op.execute(
        'UPDATE subscription SET "beneficiaryTenantId" = "organizationId" '
        'WHERE "beneficiaryTenantId" IS NULL'
    )


def downgrade() -> None:
    op.drop_index("ix_subscription_adminUserId", table_name="subscription")
    op.drop_index("ix_subscription_beneficiaryTenantId", table_name="subscription")
    op.drop_index("ix_subscription_payerId", table_name="subscription")

    op.drop_constraint("fk_subscription_adminUserId_user", "subscription", type_="foreignkey")
    op.drop_constraint("fk_subscription_beneficiaryTenantId_organization", "subscription", type_="foreignkey")
    op.drop_constraint("fk_subscription_payerId_billing_payer", "subscription", type_="foreignkey")

    op.drop_column("subscription", "adminUserId")
    op.drop_column("subscription", "beneficiaryTenantId")
    op.drop_column("subscription", "payerId")

    op.drop_table("billing_payer")
