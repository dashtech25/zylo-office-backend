"""Affectations globales et temporaires de rôle d'administration (BE-121).

Table `admin_role_assignment` : un rôle d'administration donné à un compte,
pour une portée (`platform` ou `tenant:<uuid canonique>`), avec une échéance
facultative et une date de révocation. Distincte de `userRole` (rôles
d'organisation, BE-008) : cette table ne touche jamais aux rôles d'organisation.

Règles (définition BE-121, recommandation QE-ADM-03) :
- un rôle marqué temporaire (`ROLES_TEMPORAIRES`) doit porter une échéance
  future (422 sinon) ;
- seule la portée plateforme peut attribuer une portée globale ; ce contrôle
  est fait par la route, pas ici (la route connaît la portée de la requête) ;
- une affectation active de rôle `ROLES_AUTORITE_PLATEFORME`, de portée
  `platform`, donne l'autorité plateforme (BE-120). Elle remplace la liste
  d'exploitation `OPERATOR_READ_USER_IDS` pour la portée d'administration. Une
  affectation est active si elle n'est ni révoquée ni échue.

Ce module ne dépend d'aucune capacité ni d'aucun module métier : il n'importe
que le socle (`core`, `shared`). La route est dans `role_assignments_router.py`.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, or_, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.errors import AppError
from app.shared.models import UUIDPrimaryKeyMixin

# Rôles candidats de la définition BE-121 (codes stables, en minuscules).
ROLES_CANDIDATS = frozenset({
    "agent_support_l1",
    "agent_support_l2",
    "finance_support",
    "operateur_plateforme",
    "securite_incident_commander",
    "approbateur_independant",
    "auditeur",
    "administrateur_client",
})

# Rôles marqués temporaires : une échéance est obligatoire. Hypothèse consignée
# (QE-ADM-03 et BE-121) : la sécurité / incident commander et l'approbateur
# indépendant sont les rôles d'élévation temporaire ; les autres sont permanents.
ROLES_TEMPORAIRES = frozenset({"securite_incident_commander", "approbateur_independant"})

# Rôles qui donnent l'autorité plateforme (BE-120) lorsqu'ils sont affectés en
# portée `platform`. Hypothèse consignée : seul l'opérateur plateforme amorce
# l'autorité ; l'élévation d'incident n'accorde pas, à elle seule, l'accès.
ROLES_AUTORITE_PLATEFORME = frozenset({"operateur_plateforme"})

PORTEE_PLATEFORME = "platform"


class AdminRoleAssignment(UUIDPrimaryKeyMixin, Base):
    """Une affectation de rôle d'administration à un compte, pour une portée.

    `scope` vaut `platform` ou `tenant:<uuid>` (même format que l'en-tête
    `X-Admin-Scope`, voir app/operator/scope.py). `grantedBy` est l'auteur de
    l'attribution, conservé pour la traçabilité. `revokedAt` est renseigné par
    la route `POST .../{assignment_id}/revoke` (BE-146) ; aucune ligne n'est
    jamais supprimée. `revokedBy` est l'administrateur qui a révoqué."""

    __tablename__ = "admin_role_assignment"
    __table_args__ = (
        {"comment": "Affectation de rôle d'administration globale ou temporaire (BE-121)."},
    )

    actorId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)
    roleCode: Mapped[str] = mapped_column(String(60), nullable=False)
    scope: Mapped[str] = mapped_column(String(120), nullable=False)
    grantedBy: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    grantedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expiresAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revokedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revokedBy: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=True)


def _refus(code: str, message: str, status_code: int = 422) -> AppError:
    return AppError(code=code, message=message, status_code=status_code)


def valider_attribution(role_code: str, expires_at: datetime | None, maintenant: datetime | None = None) -> None:
    """Contrôle le rôle et l'échéance d'une attribution avant écriture.

    Lève 422 si le rôle est inconnu, si un rôle temporaire n'a pas d'échéance
    (CA-2), ou si l'échéance est déjà passée. Ne touche pas à la base."""
    if role_code not in ROLES_CANDIDATS:
        raise _refus("admin_role_unknown", "Rôle d'administration inconnu.")
    if role_code in ROLES_TEMPORAIRES and expires_at is None:
        raise _refus(
            "admin_role_expiry_required",
            "Un rôle temporaire doit porter une échéance.",
        )
    if expires_at is not None:
        reference = maintenant or datetime.now(timezone.utc)
        if expires_at.tzinfo is None:
            raise _refus("admin_role_expiry_invalid", "L'échéance doit comporter un fuseau horaire.")
        if expires_at <= reference:
            raise _refus("admin_role_expiry_invalid", "L'échéance doit être dans le futur.")


async def creer_affectation(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID,
    role_code: str,
    scope: str,
    expires_at: datetime | None,
    granted_by: uuid.UUID,
) -> AdminRoleAssignment:
    """Ajoute une affectation dans la session, sans la valider ni la commiter.

    L'appelant gère la transaction : la même transaction porte l'entrée d'audit
    (CA-4). `scope` doit déjà être validé par l'appelant (`parse_admin_scope`)."""
    valider_attribution(role_code, expires_at)
    ligne = AdminRoleAssignment(
        actorId=actor_id,
        roleCode=role_code,
        scope=scope,
        grantedBy=granted_by,
        grantedAt=datetime.now(timezone.utc),
        expiresAt=expires_at,
        revokedAt=None,
    )
    db.add(ligne)
    await db.flush()
    return ligne


async def lister_affectations(db: AsyncSession, actor_id: uuid.UUID, scope: str | None = None) -> list[AdminRoleAssignment]:
    """Affectations d'un compte, les plus récentes d'abord.

    `scope` restreint à une portée exacte (portée tenant de la requête) ; `None`
    renvoie toutes les portées du compte (portée plateforme)."""
    stmt = select(AdminRoleAssignment).where(AdminRoleAssignment.actorId == actor_id)
    if scope is not None:
        stmt = stmt.where(AdminRoleAssignment.scope == scope)
    result = await db.execute(stmt.order_by(AdminRoleAssignment.grantedAt.desc()))
    return list(result.scalars().all())


async def has_platform_authority(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """Vrai si le compte détient une affectation active d'autorité plateforme.

    Active : portée `platform`, rôle dans `ROLES_AUTORITE_PLATEFORME`, non
    révoquée, et sans échéance échue. Refus fermé : sans ligne, faux."""
    maintenant = datetime.now(timezone.utc)
    stmt = (
        select(AdminRoleAssignment.id)
        .where(
            AdminRoleAssignment.actorId == user_id,
            AdminRoleAssignment.scope == PORTEE_PLATEFORME,
            AdminRoleAssignment.roleCode.in_(ROLES_AUTORITE_PLATEFORME),
            AdminRoleAssignment.revokedAt.is_(None),
            or_(AdminRoleAssignment.expiresAt.is_(None), AdminRoleAssignment.expiresAt > maintenant),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).first() is not None


class AffectationDejaRevoquee(AppError):
    """Révocation d'une affectation déjà révoquée (409, BE-146).

    Une seconde révocation ne réécrit jamais `revokedAt` ni `revokedBy` : la date
    de la première révocation reste la preuve de fin d'autorité."""

    def __init__(self) -> None:
        super().__init__(
            code="admin_role_assignment_already_revoked",
            message="Cette affectation est déjà révoquée.",
            status_code=409,
        )


async def revoquer_affectation(
    db: AsyncSession,
    ligne: AdminRoleAssignment,
    *,
    revoked_by: uuid.UUID,
) -> AdminRoleAssignment:
    """Marque l'affectation révoquée, sans la supprimer, sans la valider ni la commiter.

    BE-146 CA-4 : la ligne et ses colonnes d'origine (actorId, roleCode, scope,
    grantedAt, expiresAt) restent intactes ; seules `revokedAt` et `revokedBy`
    sont renseignées. Lève 409 si la ligne est déjà révoquée. L'appelant écrit
    l'entrée d'audit dans la même transaction et gère le commit.

    La fin d'autorité par échéance n'est pas une écriture : `has_platform_authority`
    compare `expiresAt` à l'horloge à chaque requête, sans action humaine (CA-1).
    """
    if ligne.revokedAt is not None:
        raise AffectationDejaRevoquee()
    ligne.revokedAt = datetime.now(timezone.utc)
    ligne.revokedBy = revoked_by
    await db.flush()
    return ligne
