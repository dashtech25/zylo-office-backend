"""Synthèse des états d'un compte client pour la console de support (BE-130, lecture seule).

Intention : un agent de support voit, sur une seule vue, l'état d'une organisation
cliente : offre, abonnement, paiement, factures, droits, incidents et échéances.
Aucune table propre : la lecture porte sur `subscription`, `invoice`,
`paymentAttempt`, `subscription_entitlement` (BE-023, BE-024, BE-027, BE-028) et
`incidents` (BE-247).

Règles (définition BE-130) :
- CA-1 : les sept sections sont toujours présentes. Une section dont la source
  n'est pas encore définie (offre, PH-07) porte la mention `statut: N/A` avec sa
  raison. Une section sans donnée (pas d'abonnement) porte aussi `N/A`.
- CA-2 : la projection dépend des rôles actifs du compte. Les sections
  `paiement` et `factures` sont masquées (`{"statut": "masque"}`) sauf pour les
  rôles `ROLES_FINANCIERS`. Les autres sections sont visibles par tout
  détenteur de la route.
- CA-3 : la garde de portée (`require_admin_scope`, BE-120) et
  `assert_tenant_content_scope` refusent la synthèse d'un autre tenant. La
  portée plateforme ne couvre jamais le contenu d'un tenant.
- CA-4 : aucun champ santé ou réputation. Il n'est pas arbitré (PH-01A), donc
  absent de la réponse.

Écarts consignés (recommandation appliquée, pas de QE tranchée) :
- Offre : `N/A` explicite, car les états offre (PH-07) ne sont pas résolus
  (QE-ADM-22).
- Rôles financiers : `finance_support` et `agent_support_l2` voient les
  sections financières. La spécification ne nomme que L1 et finance ; L2 est
  traité comme non masqué, le même traitement que finance.
- Un compte sans rôle de support (opérateur seul) voit les sections financières
  masquées, comme L1 : l'opérateur ne lit pas de contenu client.
- Échéances : `finPeriode` (fin de période), `finGrace` (fin de la période de
  grâce, BE-091) et `effetResiliation` (date d'effet, BE-090) sont lus tels
  quels ; une date absente vaut `null`.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import Invoice, PaymentAttempt, Subscription, SubscriptionEntitlement
from app.operator.incidents_models import Incident
from app.rbac.role_assignments import AdminRoleAssignment

ROLES_FINANCIERS = frozenset({"finance_support", "agent_support_l2"})
SECTIONS = ("offre", "abonnement", "paiement", "factures", "droits", "incidents", "echeances")
MASQUE = {"statut": "masque"}


def _na(raison: str) -> dict:
    return {"statut": "N/A", "raison": raison}


def _iso(valeur: datetime | None) -> str | None:
    return valeur.isoformat() if valeur is not None else None


async def roles_actifs(db: AsyncSession, user_id: uuid.UUID, organization_id: uuid.UUID) -> set[str]:
    """Codes des rôles d'administration actifs du compte, en portée plateforme ou du tenant.

    Actif : non révoqué et sans échéance échue. Une affectation de rôle dans une
    autre portée n'entre pas dans la projection."""
    maintenant = datetime.now(timezone.utc)
    stmt = select(AdminRoleAssignment.roleCode).where(
        AdminRoleAssignment.actorId == user_id,
        AdminRoleAssignment.scope.in_(("platform", f"tenant:{organization_id}")),
        AdminRoleAssignment.revokedAt.is_(None),
        or_(AdminRoleAssignment.expiresAt.is_(None), AdminRoleAssignment.expiresAt > maintenant),
    )
    return set((await db.execute(stmt)).scalars().all())


async def _dernier_abonnement(db: AsyncSession, organization_id: uuid.UUID) -> Subscription | None:
    """Abonnement le plus récent du tenant, ou None."""
    stmt = (
        select(Subscription)
        .where(Subscription.organizationId == organization_id)
        .order_by(Subscription.startDate.desc(), Subscription.id)
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def _section_abonnement(abonnement: Subscription | None) -> dict:
    if abonnement is None:
        return _na("aucun abonnement pour ce compte")
    return {
        "statut": abonnement.status,
        "lifecycleStatus": abonnement.lifecycleStatus,
        "financialStatus": abonnement.financialStatus,
        "incidentStatus": abonnement.incidentStatus,
    }


async def _section_paiement(db: AsyncSession, organization_id: uuid.UUID) -> dict:
    """Dernière tentative de paiement et nombre de tentatives sur les factures du tenant."""
    jointure = (
        select(PaymentAttempt)
        .join(Invoice, PaymentAttempt.invoiceId == Invoice.id)
        .join(Subscription, Invoice.subscriptionId == Subscription.id)
        .where(Subscription.organizationId == organization_id)
    )
    nombre = (await db.execute(select(func.count()).select_from(jointure.subquery()))).scalar_one()
    derniere = (await db.execute(jointure.order_by(PaymentAttempt.requestedAt.desc()).limit(1))).scalar_one_or_none()
    return {
        "derniereTentative": derniere.status if derniere is not None else None,
        "nombreTentatives": nombre,
    }


async def _section_factures(db: AsyncSession, organization_id: uuid.UUID) -> dict:
    """Nombre de factures du tenant, ventilé par statut."""
    stmt = (
        select(Invoice.status, func.count())
        .join(Subscription, Invoice.subscriptionId == Subscription.id)
        .where(Subscription.organizationId == organization_id)
        .group_by(Invoice.status)
    )
    par_statut = {statut: total for statut, total in (await db.execute(stmt)).all()}
    return {"nombre": sum(par_statut.values()), "parStatut": par_statut}


async def _section_droits(db: AsyncSession, organization_id: uuid.UUID) -> dict:
    """Droits du tenant : total et nombre de droits actifs (BE-024)."""
    stmt = (
        select(SubscriptionEntitlement.status, func.count())
        .where(SubscriptionEntitlement.organizationId == organization_id)
        .group_by(SubscriptionEntitlement.status)
    )
    par_statut = {statut: total for statut, total in (await db.execute(stmt)).all()}
    return {"total": sum(par_statut.values()), "actifs": par_statut.get("active", 0)}


async def _section_incidents(db: AsyncSession, organization_id: uuid.UUID) -> dict:
    """Incidents d'exploitation rattachés au tenant, ventilés par état (BE-247)."""
    stmt = (
        select(Incident.state, func.count())
        .where(Incident.tenantId == organization_id)
        .group_by(Incident.state)
    )
    par_etat = {etat: total for etat, total in (await db.execute(stmt)).all()}
    return {"nombre": sum(par_etat.values()), "parEtat": par_etat}


def _section_echeances(abonnement: Subscription | None) -> dict:
    """Dates clés de l'abonnement : fin de période, fin de grâce, effet de résiliation."""
    if abonnement is None:
        return _na("aucun abonnement pour ce compte")
    return {
        "finPeriode": _iso(abonnement.endDate),
        "finGrace": _iso(abonnement.graceUntil),
        "effetResiliation": _iso(abonnement.cancelEffectiveAt),
    }


async def construire_synthese(db: AsyncSession, organization_id: uuid.UUID, roles: set[str]) -> dict:
    """Les sept sections de la synthèse, projetées selon les rôles du compte (BE-130 CA-1, CA-2).

    `roles` : codes des rôles actifs de l'appelant. Sans rôle financier, les
    sections `paiement` et `factures` sont masquées. Les autres sections ne
    dépendent pas du rôle."""
    financier = bool(roles & ROLES_FINANCIERS)
    abonnement = await _dernier_abonnement(db, organization_id)
    return {
        "organizationId": str(organization_id),
        "offre": _na("états offre non définis (PH-07, QE-ADM-22)"),
        "abonnement": _section_abonnement(abonnement),
        "paiement": await _section_paiement(db, organization_id) if financier else dict(MASQUE),
        "factures": await _section_factures(db, organization_id) if financier else dict(MASQUE),
        "droits": await _section_droits(db, organization_id),
        "incidents": await _section_incidents(db, organization_id),
        "echeances": _section_echeances(abonnement),
    }
