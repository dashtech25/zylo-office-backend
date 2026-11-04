"""BE-046 : allocation des entitlements aux utilisateurs (sièges).

Revision ID: b046a1e2c3d4
Revises: f668520e8d62

Crée la table `entitlement_allocations` :
- `entitlementId` (FK vers `subscription_entitlement`), `organizationId` (FK vers
  `organization`), `userId` (FK vers `user`), `grantedBy` (FK vers `user`), `grantedAt` ;
- `revokedAt` nullable : une révocation renseigne la date, la ligne reste (aucune suppression) ;
- index unique partiel `uq_entitlement_allocations_active` sur (entitlementId, userId)
  WHERE revokedAt IS NULL : un seul siège actif par couple, une révocation libère le couple.

Index de lecture : `entitlementId`, `organizationId`, `userId` (index déclarés dans le modèle).

Retour arrière : supprime la table entière. Les attributions de sièges sont perdues : à
n'utiliser qu'en développement ou sur une base sans sièges réels.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b046a1e2c3d4"
down_revision: Union[str, None] = "f668520e8d62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entitlement_allocations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("entitlementId", sa.Uuid(as_uuid=True), sa.ForeignKey("subscription_entitlement.id"), nullable=False),
        sa.Column("organizationId", sa.Uuid(as_uuid=True), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("userId", sa.Uuid(as_uuid=True), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("grantedBy", sa.Uuid(as_uuid=True), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("grantedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revokedAt", sa.DateTime(timezone=True), nullable=True),
        comment="Sièges d'entitlement attribués aux membres (BE-046). Révocation par revokedAt, sans suppression.",
    )
    op.create_index("ix_entitlement_allocations_entitlementId", "entitlement_allocations", ["entitlementId"])
    op.create_index("ix_entitlement_allocations_organizationId", "entitlement_allocations", ["organizationId"])
    op.create_index("ix_entitlement_allocations_userId", "entitlement_allocations", ["userId"])
    op.create_index(
        "uq_entitlement_allocations_active",
        "entitlement_allocations",
        ["entitlementId", "userId"],
        unique=True,
        postgresql_where=sa.text('"revokedAt" IS NULL'),
    )


def downgrade() -> None:
    op.drop_index("uq_entitlement_allocations_active", table_name="entitlement_allocations")
    op.drop_index("ix_entitlement_allocations_userId", table_name="entitlement_allocations")
    op.drop_index("ix_entitlement_allocations_organizationId", table_name="entitlement_allocations")
    op.drop_index("ix_entitlement_allocations_entitlementId", table_name="entitlement_allocations")
    op.drop_table("entitlement_allocations")
