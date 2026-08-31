import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "role"
    __table_args__ = (
        UniqueConstraint("organizationId", "code", name="uq_role_org_code"),
        {"comment": "Rôle métier scopé à une organisation (ex: Admin, Comptable)."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class Permission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "permission"
    __table_args__ = {"comment": "Permission globale au système, déclarée par un module (convention: module.resource.action)."}

    code: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)
    moduleCode: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)


class RolePermission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rolePermission"
    __table_args__ = (
        UniqueConstraint("roleId", "permissionId", name="uq_rolePermission_role_perm"),
        {"comment": "Association rôle <-> permission (many-to-many)."},
    )

    roleId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("role.id"), nullable=False, index=True)
    permissionId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("permission.id"), nullable=False, index=True
    )


class UserRole(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "userRole"
    __table_args__ = (
        UniqueConstraint("userId", "organizationId", "roleId", name="uq_userRole_user_org_role"),
        {"comment": "Attribution d'un rôle à un utilisateur, scopée à une organisation (un même user peut avoir un rôle différent selon l'organisation)."},
    )

    userId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)
    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    roleId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("role.id"), nullable=False, index=True)
