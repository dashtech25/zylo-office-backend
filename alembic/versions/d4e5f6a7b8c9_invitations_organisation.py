"""invitations à rejoindre une organisation : table organizationInvitation et permission organization.members.invite (BE-012)

Revision ID: d4e5f6a7b8c9
Revises: 9fa8a14283b1
Create Date: 2026-11-03

Migration additive : une nouvelle table (destinataire, rôle proposé, état,
expiration ; seule l'empreinte SHA-256 du jeton est stockée) et une permission
accordée aux rôles « owner » existants. Pas de backfill au démarrage : la
fonction ci-dessous est rejouable (second passage sans effet).

La table n'est pas `userInvitation` : celle-ci active un compte déjà créé
(userId obligatoire), alors qu'une invitation vise une adresse qui n'a peut-être
pas de compte.

Retour arrière : suppression de la table. La permission et ses liaisons restent
en base, sans effet sans la route qui la contrôle (même politique que e7f8a9b0c1d2).
"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "9fa8a14283b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISSION_CODE = "organization.members.invite"
PERMISSION_MODULE = "identity"
PERMISSION_DESCRIPTION = "Inviter une personne à rejoindre l'organisation et consulter les invitations en attente."


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
        "organizationInvitation",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organizationId", postgresql.UUID(as_uuid=True), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False, comment="Adresse du destinataire, en minuscules"),
        sa.Column("roleId", postgresql.UUID(as_uuid=True), sa.ForeignKey("role.id"), nullable=True, comment="Rôle proposé (facultatif)"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending", comment="pending | revoked | accepted"),
        sa.Column("tokenHash", sa.String(length=64), nullable=False, unique=True, comment="Empreinte SHA-256 du jeton d'invitation"),
        sa.Column("expiresAt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("createdByUserId", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="Invitation à rejoindre une organisation : destinataire, rôle proposé, état, expiration (jeton haché).",
    )
    op.create_index(op.f("ix_organizationInvitation_organizationId"), "organizationInvitation", ["organizationId"], unique=False)
    op.create_index(
        "uq_organizationInvitation_pending_per_email",
        "organizationInvitation",
        ["organizationId", "email"],
        unique=True,
        postgresql_where=sa.text("\"status\" = 'pending'"),
    )
    accorde_permission_aux_proprietaires(op.get_bind())


def downgrade() -> None:
    op.drop_index("uq_organizationInvitation_pending_per_email", table_name="organizationInvitation")
    op.drop_index(op.f("ix_organizationInvitation_organizationId"), table_name="organizationInvitation")
    op.drop_table("organizationInvitation")
