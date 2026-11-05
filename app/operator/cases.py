"""Cas d'intervention (ticket de support) : modèle et règles de domaine (BE-123).

Table `intervention_case` : un ticket ouvert par un agent support (L1 ou L2) pour
une organisation (`tenantId`) ou pour la plateforme (`tenantId` NULL). Le cycle de
vie : `ouvert` -> `affecte` -> `cloture`, avec un passage possible par `escalade`
(BE-142) ; une escalade ouverte met le cas à `escalade`. Chaque transition produit une
entrée d'audit dans `audit_event` (BE-007, écrite par `app.audit.admin_audit`).

Droits (définition BE-123) :
- ouverture : rôle `agent_support_l1` ou `agent_support_l2` dans la portée du cas ;
- affectation et clôture : rôle de gestion (`ROLES_GESTION`), c'est-à-dire le
  responsable d'escalade. Hypothèse consignée (QE-ADM-86) : ce responsable porte le
  rôle `securite_incident_commander`, seul rôle candidat de BE-121 qui convient ;
  la permission `admin.cases.manage` est proposée mais n'a pas encore de registre ;
- lecture : tout détenteur d'un rôle de la portée du cas. Un agent L1 ou L2 ne lit
  que les cas qu'il a ouverts ou qui lui sont affectés ; le responsable de gestion
  lit tous les cas de sa portée.

Portée : la portée d'un cas est `platform` (cas sans tenant) ou `tenant:<uuid>`,
au même format que les affectations de BE-121. Une affectation de portée
`platform` ne couvre jamais un cas de tenant (BE-120 CA-2).

Clôture et vérification : une clôture exige une vérification enregistrée, c'est-à-dire
une entrée d'audit d'action `admin.case.verification` portant ce cas. Sans elle :
409. L'enregistrement de la vérification n'a pas de route dans BE-123 ; seule sa
présence est contrôlée ici (QE-ADM-87).

Ce module ne dépend d'aucun module métier : il n'importe que le socle (`core`,
`shared`, `identity`, `rbac`, `audit`).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, or_, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.audit.models import AuditEvent
from app.core.database import Base
from app.core.errors import AppError
from app.rbac.role_assignments import AdminRoleAssignment
from app.shared.models import UUIDPrimaryKeyMixin

PRIORITES = ("basse", "normale", "haute")
ETATS = ("ouvert", "affecte", "escalade", "cloture")
# Ouvrir une escalade fait passer le cas à `escalade` (BE-142 CA-2).
ETAT_ESCALADE = "escalade"

ROLES_OUVERTURE = frozenset({"agent_support_l1", "agent_support_l2"})
ROLES_GESTION = frozenset({"securite_incident_commander"})

ACTION_OUVERTURE = "admin.case.open"
ACTION_AFFECTATION = "admin.case.assign"
ACTION_CLOTURE = "admin.case.close"
ACTION_VERIFICATION = "admin.case.verification"
TYPE_ENTITE_CAS = "InterventionCase"


class InterventionCase(UUIDPrimaryKeyMixin, Base):
    """Un cas d'intervention (ticket de support).

    `tenantId` vaut NULL pour un cas de plateforme. `assigneeId` est renseigné à
    l'affectation. `consentRef` reste NULL tant que le consentement n'est pas
    modélisé (QE-ADM-88). `closedAtUtc` et `closureReason` ne sont renseignés qu'à
    la clôture. Aucune ligne n'est supprimée."""

    __tablename__ = "intervention_case"
    __table_args__ = (
        CheckConstraint("priority IN ('basse', 'normale', 'haute')", name="ck_intervention_case_priority"),
        CheckConstraint("status IN ('ouvert', 'affecte', 'escalade', 'cloture')", name="ck_intervention_case_status"),
        {"comment": "Cas d'intervention de support, ouvert et clos par les agents administratifs (BE-123)."},
    )

    tenantId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=True, index=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ouvert", server_default="ouvert")
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    qualification: Mapped[str] = mapped_column(String(200), nullable=False)
    openedBy: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)
    assigneeId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id"), nullable=True, index=True,
    )
    consentRef: Mapped[str | None] = mapped_column(String(120), nullable=True)
    openedAtUtc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closedAtUtc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closureReason: Mapped[str | None] = mapped_column(String(500), nullable=True)


def portee_du_cas(tenant_id: uuid.UUID | None) -> str:
    """Forme de portée d'un cas : `platform` ou `tenant:<uuid canonique>`."""
    return "platform" if tenant_id is None else f"tenant:{tenant_id}"


def erreur_refus() -> AppError:
    """403 uniforme de la portée d'administration (BE-120)."""
    return AppError(
        code="admin_scope_denied",
        message="Accès d'administration refusé pour cette portée.",
        status_code=403,
    )


def erreur_introuvable() -> AppError:
    return AppError(code="case_not_found", message="Cas d'intervention introuvable.", status_code=404)


async def roles_actifs_sur_portee(db: AsyncSession, user_id: uuid.UUID, scope: str) -> set[str]:
    """Rôles d'administration actifs du compte, sur exactement cette portée.

    Actif : non révoqué et sans échéance échue (même règle que BE-121). Une
    affectation `platform` ne se propage pas à un cas de tenant : la comparaison
    est une égalité de portée."""
    maintenant = datetime.now(timezone.utc)
    stmt = select(AdminRoleAssignment.roleCode).where(
        AdminRoleAssignment.actorId == user_id,
        AdminRoleAssignment.scope == scope,
        AdminRoleAssignment.revokedAt.is_(None),
        or_(AdminRoleAssignment.expiresAt.is_(None), AdminRoleAssignment.expiresAt > maintenant),
    )
    return set((await db.execute(stmt)).scalars().all())


async def charger_cas(db: AsyncSession, case_id: uuid.UUID) -> InterventionCase:
    """Le cas, ou 404 s'il n'existe pas."""
    cas = await db.get(InterventionCase, case_id)
    if cas is None:
        raise erreur_introuvable()
    return cas


async def exiger_ouverture(db: AsyncSession, user_id: uuid.UUID, tenant_id: uuid.UUID | None) -> None:
    """403 sauf si le compte a un rôle d'ouverture (L1 ou L2) sur la portée du cas."""
    if not await roles_actifs_sur_portee(db, user_id, portee_du_cas(tenant_id)) & ROLES_OUVERTURE:
        raise erreur_refus()


async def exiger_gestion(db: AsyncSession, user_id: uuid.UUID, cas: InterventionCase) -> None:
    """403 sauf si le compte est responsable de gestion sur la portée du cas."""
    if not await roles_actifs_sur_portee(db, user_id, portee_du_cas(cas.tenantId)) & ROLES_GESTION:
        raise erreur_refus()


async def exiger_lecture(db: AsyncSession, user_id: uuid.UUID, cas: InterventionCase) -> None:
    """Lecture limitée : gestion sur la portée, ou ouvreur, ou agent affecté.

    Un agent L1 ou L2 sans lien avec le cas reçoit 403, même avec une affectation
    de la même portée. Un compte sans rôle sur la portée reçoit 403 (CA-3)."""
    roles = await roles_actifs_sur_portee(db, user_id, portee_du_cas(cas.tenantId))
    if roles & ROLES_GESTION:
        return
    if not roles & ROLES_OUVERTURE:
        raise erreur_refus()
    if user_id not in (cas.openedBy, cas.assigneeId):
        raise erreur_refus()


async def verification_enregistree(db: AsyncSession, case_id: uuid.UUID) -> bool:
    """Vrai si une entrée d'audit `admin.case.verification` porte ce cas (CA-4)."""
    stmt = (
        select(AuditEvent.id)
        .where(
            AuditEvent.action == ACTION_VERIFICATION,
            AuditEvent.entityType == TYPE_ENTITE_CAS,
            AuditEvent.entityId == case_id,
        )
        .limit(1)
    )
    return (await db.execute(stmt)).first() is not None
