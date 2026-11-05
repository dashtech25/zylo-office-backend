"""Modèle RBAC du socle : rôles, permissions, grants et affectations.

Tables (camelCase, migrations dans `alembic/versions/`) :
- `role` : gabarit de droits, scopé à une organisation (`Role`) ;
- `permission` : code global `domaine.entite.action`, déclaré par un module
  (`Permission`) ;
- `rolePermission` : contenu d'un rôle (`RolePermission`) ;
- `userRole` : attribution d'un rôle à un membre, éventuellement scopée à une
  ressource (`UserRole`) ;
- `userPermissionGrant` : grant ou refus individuel (`UserPermissionGrant`).

Ce module ne contient que la structure. La décision d'autorisation n'est jamais
prise ici : elle est rendue par `rbac/service.py::user_has_permission`, qui lit
ces tables. Un rôle n'est qu'un gabarit ; ce qui compte, c'est la résolution.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Rôle métier d'une organisation (ex. `owner`, `zylo_liquid_station_admin`).

    Un rôle est un ensemble de permissions (`RolePermission`). Son contenu ne
    dépend jamais de la ressource : la portée se règle sur l'attribution
    (`UserRole.resourceType/resourceId`). `code` est unique par organisation.
    Un rôle sans `moduleCode` est transverse au socle ; un rôle avec
    `moduleCode` est un rôle de module (voir plus bas)."""

    __tablename__ = "role"
    __table_args__ = (
        UniqueConstraint("organizationId", "code", name="uq_role_org_code"),
        # BE-182 : cible de la clé composite de userRole (le tenant suit la référence).
        UniqueConstraint("organizationId", "id", name="uq_role_org_id"),
        {"comment": "Rôle métier scopé à une organisation (ex: Admin, Comptable)."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # T-018 : rattachement du rôle à UN module. null = rôle transverse du socle
    # (ex. `owner`, rôles personnalisés existants). Non null = rôle de module :
    # il ne peut contenir que les permissions de son module ou du socle partagé
    # (voir rbac/module_policy.py). Un seul mécanisme : aucune portée module
    # n'est ajoutée sur userRole. Le rattachement des rôles déjà existants se
    # fait par backfill explicite (rbac/module_backfill.py), jamais au démarrage.
    moduleCode: Mapped[str | None] = mapped_column(
        String(100), ForeignKey("module.code"), nullable=True, index=True
    )


class Permission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Permission globale, unique par `code` (convention `domaine.entite.action`).

    `moduleCode` indique le module qui la déclare. Une permission n'a pas de
    portée propre : la portée vient de l'attribution ou du grant qui la porte."""

    __tablename__ = "permission"
    __table_args__ = {"comment": "Permission globale au système, déclarée par un module (convention: module.resource.action)."}

    code: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)
    moduleCode: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)


class RolePermission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Association many-to-many rôle <-> permission. Unicité du couple imposée
    par `uq_rolePermission_role_perm` (une permission ne figure qu'une fois
    dans un rôle)."""

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
    """Attribution d'un rôle à un utilisateur. `resourceType`/`resourceId`
    (null par défaut = organisation entière, comportement historique
    inchangé) permettent de rattacher cette attribution à une ressource
    précise — ex. ("station", "<uuid>") pour un gérant qui ne doit avoir les
    permissions de son rôle que sur SA station, jamais sur les autres.
    Même convention que `UserPermissionGrant.resourceType/resourceId` : le
    contenu du rôle (`RolePermission`) ne change pas, seule la portée de son
    application à cet utilisateur est restreinte (voir `processus-double-
    sources-verite/01-etat-actuel-zylo-liquid.md` §7 et
    `02-modele-double-source.md` §6, point bloquant résolu ici)."""

    __tablename__ = "userRole"
    __table_args__ = (
        UniqueConstraint(
            "userId", "organizationId", "roleId", "resourceType", "resourceId", name="uq_userRole_user_org_role_scope"
        ),
        # BE-182 (CA-2) : le rôle attribué appartient au même tenant que l'attribution.
        ForeignKeyConstraint(
            ["organizationId", "roleId"],
            ["role.organizationId", "role.id"],
            name="fk_userRole_org_role_tenant",
        ),
        {"comment": "Attribution d'un rôle à un utilisateur, scopée à une organisation et éventuellement à une ressource précise (station...)."},
    )

    userId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)
    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    roleId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("role.id"), nullable=False, index=True)

    resourceType: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resourceId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class UserPermissionGrant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Grant/deny individuel, indépendant du rôle affiché — modèle décrit dans
    « rôle et permissions global global et spécifique par module Zylo
    Office.md » §5.3, généralisation au noyau du `zylo.liquid.access.grant`
    de `formation/role_permission.md`. Un rôle (Role/RolePermission) n'est
    qu'un gabarit : c'est la résolution de CETTE table + des rôles actifs qui
    détermine l'autorisation réelle (voir `rbac/service.py::user_has_permission`).

    Règle non négociable (role_permission.md §0.2) : à portée égale ou plus
    large, un `effect="deny"` annule toujours un `effect="allow"` obtenu par
    ailleurs (rôle ou autre grant) — jamais l'inverse, contrairement au
    modèle "union pure" d'Odoo/Dolibarr (aucun refus explicite chez eux)."""

    __tablename__ = "userPermissionGrant"
    __table_args__ = {
        "comment": "Grant ou refus individuel d'une permission à un utilisateur, éventuellement scopé à une ressource précise et borné dans le temps (délégation)."
    }

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    userId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)
    permissionId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("permission.id"), nullable=False, index=True
    )
    effect: Mapped[str] = mapped_column(String(10), nullable=False)  # "allow" | "deny"

    # null = portée = toute l'organisation. Sinon une ressource précise, ex.
    # ("station", "<uuid>") — convention libre par module, jamais interprétée
    # par le moteur (qui ne fait qu'un test d'égalité stricte).
    resourceType: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resourceId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="direct")  # "direct" | "delegation"
    delegatedFromGrantId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("userPermissionGrant.id"), nullable=True, index=True
    )
    grantedByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)

    validFrom: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    validUntil: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revokedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    auditNote: Mapped[str | None] = mapped_column(String(500), nullable=True)
