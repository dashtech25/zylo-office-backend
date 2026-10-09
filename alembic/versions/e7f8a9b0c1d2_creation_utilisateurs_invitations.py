"""creation d'utilisateurs : table userInvitation et permission identity.user.manage (T-021, T-049)

Revision ID: e7f8a9b0c1d2
Revises: a9b8c7d6e5f4
Create Date: 2026-10-09

Migration additive : une nouvelle table (jetons d'activation, seule l'empreinte
SHA-256 est stockée) et une permission accordée explicitement aux rôles
« owner » existants. Pas de backfill au démarrage : la fonction ci-dessous est
rejouable (second passage sans effet) et n'est appelée que par cette migration.
Retour arrière : suppression de la table ; la permission et ses liaisons
restent en base (sans effet sans la route qui la contrôle).
"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "b4e1c7d2a9f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISSION_CODE = "identity.user.manage"
PERMISSION_MODULE = "identity"
PERMISSION_DESCRIPTION = "Créer des utilisateurs, réémettre une invitation, suspendre et réactiver un membre."


def accorde_permission_aux_proprietaires(bind) -> None:
    """Crée la permission si absente, puis la lie à chaque rôle `owner` qui ne l'a pas.
    Idempotent : un second passage n'ajoute aucune ligne."""
    permission_id = bind.execute(
        sa.text("SELECT id FROM permission WHERE code = :code"), {"code": PERMISSION_CODE}
    ).scalar()
    if permission_id is None:
        permission_id = uuid.uuid4()
        bind.execute(
            sa.text(
                'INSERT INTO permission (id, code, "moduleCode", description) '
                "VALUES (:id, :code, :module, :description)"
            ),
            {"id": permission_id, "code": PERMISSION_CODE, "module": PERMISSION_MODULE, "description": PERMISSION_DESCRIPTION},
        )
    proprietaires = bind.execute(sa.text("SELECT id FROM role WHERE code = 'owner'")).scalars().all()
    for role_id in proprietaires:
        bind.execute(
            sa.text(
                'INSERT INTO "rolePermission" (id, "roleId", "permissionId") '
                "SELECT :id, :role, :permission WHERE NOT EXISTS ("
                '  SELECT 1 FROM "rolePermission" WHERE "roleId" = :role AND "permissionId" = :permission'
                ")"
            ),
            {"id": uuid.uuid4(), "role": role_id, "permission": permission_id},
        )


def upgrade() -> None:
    op.create_table(
        "userInvitation",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organizationId", postgresql.UUID(as_uuid=True), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("userId", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("createdByUserId", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("tokenHash", sa.String(length=64), nullable=False, unique=True, comment="Empreinte SHA-256 du jeton d'activation"),
        sa.Column("expiresAt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usedAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revokedAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="Jeton d'activation à usage unique d'un compte créé par une organisation (haché, à durée limitée).",
    )
    op.create_index(op.f("ix_userInvitation_organizationId"), "userInvitation", ["organizationId"], unique=False)
    op.create_index(op.f("ix_userInvitation_userId"), "userInvitation", ["userId"], unique=False)
    op.create_index(
        "uq_userInvitation_open_per_user",
        "userInvitation",
        ["userId"],
        unique=True,
        postgresql_where=sa.text('"usedAt" IS NULL AND "revokedAt" IS NULL'),
    )
    accorde_permission_aux_proprietaires(op.get_bind())


def downgrade() -> None:
    op.drop_index("uq_userInvitation_open_per_user", table_name="userInvitation")
    op.drop_index(op.f("ix_userInvitation_userId"), table_name="userInvitation")
    op.drop_index(op.f("ix_userInvitation_organizationId"), table_name="userInvitation")
    op.drop_table("userInvitation")
