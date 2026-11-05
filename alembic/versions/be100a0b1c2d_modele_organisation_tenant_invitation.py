"""modèle organisation : table tenant, table invitation, statut d'appartenance (BE-100)

Revision ID: be100a0b1c2d
Revises: 343483f94352
Create Date: 2026-11-05

Migration additive, avec deux renommages :
- `organizationUser` devient `organization_user` (décision QE-POR-30 : tables en
  snake_case) ; ses index suivent le même nom. La contrainte d'unicité garde son
  nom d'origine, que le modèle déclare toujours.
- la colonne `status` (défaut `active`) porte le statut d'appartenance.

Tables créées :
- `tenant` : un seul tenant par organisation (unicité sur `organizationId`) ;
- `invitation` : destinataire identifié (`recipientUserId`, QE-POR-24), rôle
  facultatif, statut borné à pending / accepted / expired / revoked.

La table `organization` (BE-002) n'est pas modifiée. Retour arrière : suppression
des deux tables, retrait de la colonne, puis retour aux noms d'origine.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "be100a0b1c2d"
down_revision: Union[str, None] = "343483f94352"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table("organizationUser", "organization_user")
    op.execute('ALTER INDEX "ix_organizationUser_organizationId" RENAME TO "ix_organization_user_organizationId"')
    op.execute('ALTER INDEX "ix_organizationUser_userId" RENAME TO "ix_organization_user_userId"')
    op.add_column(
        "organization_user",
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active", comment="Statut de l'appartenance (BE-100)"),
    )

    op.create_table(
        "tenant",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organizationId", postgresql.UUID(as_uuid=True), sa.ForeignKey("organization.id"), nullable=False, unique=True, comment="Organisation du tenant : un seul tenant par organisation"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="Tenant d'une organisation (BE-100) : un seul par organisation.",
    )

    op.create_table(
        "invitation",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organizationId", postgresql.UUID(as_uuid=True), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("recipientUserId", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=False, comment="Identité invitée : seule elle peut accepter (QE-POR-24)"),
        sa.Column("roleId", postgresql.UUID(as_uuid=True), sa.ForeignKey("role.id"), nullable=True, comment="Rôle proposé (facultatif)"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("expiresAt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("createdByUserId", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'accepted', 'expired', 'revoked')", name="ck_invitation_status"),
        comment="Invitation du portail d'organisation : destinataire identifié, rôle proposé, statut borné.",
    )
    op.create_index(op.f("ix_invitation_organizationId"), "invitation", ["organizationId"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_invitation_organizationId"), table_name="invitation")
    op.drop_table("invitation")
    op.drop_table("tenant")
    op.drop_column("organization_user", "status")
    op.execute('ALTER INDEX "ix_organization_user_userId" RENAME TO "ix_organizationUser_userId"')
    op.execute('ALTER INDEX "ix_organization_user_organizationId" RENAME TO "ix_organizationUser_organizationId"')
    op.rename_table("organization_user", "organizationUser")
