"""Listes filtrées des objets de support (BE-131, lecture seule).

Intention : la console de support lit, pour une organisation, les cinq familles
d'objets qu'un agent doit consulter avant d'agir : abonnements, factures,
paiements, droits (entitlements) et incidents. Aucune table propre : chaque liste
lit les tables des objets de PH-07 à PH-10 et l'incident de BE-247.

Registre (`REGISTRE_LISTES`) : une entrée par liste, qui fixe le modèle lu, la
clause qui rattache une ligne à l'organisation, les colonnes de statut, de date et
d'identifiant utilisées par les filtres, et la projection renvoyée. Le registre est
la source de vérité : la route de chaque liste n'est qu'un branchement sur lui
(test de couverture de BE-131 CA-1).

Règles (définition BE-131) :
- CA-1 : les cinq listes couvrent les objets de support du périmètre ; chaque
  ligne renvoyée est rattachée à l'organisation demandée.
- CA-2 : seuls `status`, `dateFrom`, `dateTo` et `id` filtrent une liste. Tout
  autre paramètre de requête est refusé en 422 (`filtre_non_autorise`) ; une
  période inversée (`dateFrom` > `dateTo`) est refusée en 422 aussi.
- CA-3 : la portée `tenant:<uuid>` ne lit que son propre tenant (contrôle de cible
  par `exiger_portee_sur_tenant`) ; un autre tenant reçoit 403 et le refus est
  journalisé. La portée plateforme lit les quatre listes de facturation et de
  droits, comme la vue d'abonnement de BE-031 (`plateforme_couvre_tenant`).
- CA-4 : la garde `require_admin_scope` (BE-120) refuse tout sujet sans autorité
  plateforme avec 403, avant toute lecture. La liste des incidents n'est servie
  qu'en portée plateforme : une portée tenant reçoit 403 (BE-247 CA-3).

Écarts consignés (recommandation appliquée, pas de QE tranchée) :
- Projection par rôle : la spécification demande une projection selon le rôle.
  Seul l'opérateur plateforme passe la garde ; la projection est donc la même pour
  toutes les portées. Les champs de paiement `checkoutUrl`, `idempotencyKey` et
  `providerReference` ne sortent jamais par cette route.
- Champs indisponibles : tous les champs demandés existent dans les tables lues ;
  aucun n'est renseigné `N/A`.
- Taille de page : NON DÉFINIE (QE-ADM-16). `PaginationParams` (défaut 20, maximum
  100) s'applique.
- Paiements rattachés à l'organisation : par la facture (abonnement) ou par le
  checkout (devis, `beneficiaryTenantId`). Une tentative sans facture ni checkout
  n'est dans aucune liste.
- Incidents : rattachés par `tenantId`. Un incident de plateforme (`tenantId` nul)
  n'apparaît dans aucune liste d'organisation.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import Checkout, Invoice, PaymentAttempt, Quote, Subscription, SubscriptionEntitlement
from app.core.errors import AppError
from app.operator.incidents_models import Incident
from app.operator.scope import AdminScope
from app.operator.tenant_guard import exiger_portee_sur_tenant, journaliser_refus_cross_tenant

FILTRES_AUTORISES = ("status", "dateFrom", "dateTo", "id")


def _iso(valeur: datetime | None) -> str | None:
    """Date en texte ISO 8601, ou None si la date est absente."""
    return valeur.isoformat() if valeur is not None else None


def _entier(valeur: Any) -> int | None:
    """Montant en entier (les colonnes `Numeric` reviennent en `Decimal`)."""
    return int(valeur) if valeur is not None else None


@dataclass(frozen=True)
class ObjetSupport:
    """Une liste du registre BE-131 : modèle, rattachement, filtres et projection.

    `requete` renvoie la requête des lignes de l'organisation (sans filtre).
    `colonne_statut`, `colonne_date` et `modele.id` sont les colonnes filtrées.
    `plateforme_seule` vaut vrai pour une liste qui n'est jamais servie en portée
    tenant (incidents, BE-247 CA-3).
    """

    nom: str
    modele: Any
    requete: Callable[[uuid.UUID], Select]
    colonne_statut: Any
    colonne_date: Any
    projeter: Callable[[Any], dict]
    plateforme_seule: bool = False


def _requete_abonnements(organisation_id: uuid.UUID) -> Select:
    return select(Subscription).where(Subscription.organizationId == organisation_id)


def _requete_factures(organisation_id: uuid.UUID) -> Select:
    return (
        select(Invoice)
        .join(Subscription, Invoice.subscriptionId == Subscription.id)
        .where(Subscription.organizationId == organisation_id)
    )


def _requete_paiements(organisation_id: uuid.UUID) -> Select:
    """Tentatives de paiement rattachées par la facture (abonnement) ou par le devis du checkout."""
    return (
        select(PaymentAttempt)
        .outerjoin(Invoice, PaymentAttempt.invoiceId == Invoice.id)
        .outerjoin(Subscription, Invoice.subscriptionId == Subscription.id)
        .outerjoin(Checkout, PaymentAttempt.checkoutId == Checkout.id)
        .outerjoin(Quote, Checkout.quoteId == Quote.id)
        .where(or_(Subscription.organizationId == organisation_id, Quote.beneficiaryTenantId == organisation_id))
    )


def _requete_droits(organisation_id: uuid.UUID) -> Select:
    return select(SubscriptionEntitlement).where(SubscriptionEntitlement.organizationId == organisation_id)


def _requete_incidents(organisation_id: uuid.UUID) -> Select:
    return select(Incident).where(Incident.tenantId == organisation_id)


def _projection_abonnement(ligne: Subscription) -> dict:
    return {
        "id": str(ligne.id),
        "planId": str(ligne.planId),
        "status": ligne.status,
        "lifecycleStatus": ligne.lifecycleStatus,
        "financialStatus": ligne.financialStatus,
        "incidentStatus": ligne.incidentStatus,
        "startDate": _iso(ligne.startDate),
        "endDate": _iso(ligne.endDate),
    }


def _projection_facture(ligne: Invoice) -> dict:
    return {
        "id": str(ligne.id),
        "subscriptionId": str(ligne.subscriptionId),
        "status": ligne.status,
        "amountCents": _entier(ligne.amountCents),
        "currency": ligne.currency,
        "total": _entier(ligne.total),
        "issuedAt": _iso(ligne.issuedAt),
        "paidAt": _iso(ligne.paidAt),
    }


def _projection_paiement(ligne: PaymentAttempt) -> dict:
    return {
        "id": str(ligne.id),
        "invoiceId": str(ligne.invoiceId) if ligne.invoiceId else None,
        "checkoutId": str(ligne.checkoutId) if ligne.checkoutId else None,
        "provider": ligne.provider,
        "status": ligne.status,
        "amountMinor": _entier(ligne.amountMinor),
        "currency": ligne.currency,
        "requestedAt": _iso(ligne.requestedAt),
        "submittedAt": _iso(ligne.submittedAt),
    }


def _projection_droit(ligne: SubscriptionEntitlement) -> dict:
    return {
        "id": str(ligne.id),
        "subscriptionId": str(ligne.subscriptionId),
        "moduleCode": ligne.moduleCode,
        "entitlementCode": ligne.entitlementCode,
        "status": ligne.status,
        "startsAt": _iso(ligne.startsAt),
        "endsAt": _iso(ligne.endsAt),
        "sourceAttribution": ligne.sourceAttribution,
        "quotaLimite": ligne.quotaLimite,
    }


def _projection_incident(ligne: Incident) -> dict:
    return {
        "id": str(ligne.id),
        "severity": ligne.severity,
        "owner": ligne.owner,
        "state": ligne.state,
        "occurredAt": _iso(ligne.occurredAt),
        "tenantId": str(ligne.tenantId) if ligne.tenantId else None,
    }


REGISTRE_LISTES: dict[str, ObjetSupport] = {
    "subscriptions": ObjetSupport(
        nom="subscriptions",
        modele=Subscription,
        requete=_requete_abonnements,
        colonne_statut=Subscription.status,
        colonne_date=Subscription.startDate,
        projeter=_projection_abonnement,
    ),
    "invoices": ObjetSupport(
        nom="invoices",
        modele=Invoice,
        requete=_requete_factures,
        colonne_statut=Invoice.status,
        colonne_date=Invoice.issuedAt,
        projeter=_projection_facture,
    ),
    "payments": ObjetSupport(
        nom="payments",
        modele=PaymentAttempt,
        requete=_requete_paiements,
        colonne_statut=PaymentAttempt.status,
        colonne_date=PaymentAttempt.requestedAt,
        projeter=_projection_paiement,
    ),
    "entitlements": ObjetSupport(
        nom="entitlements",
        modele=SubscriptionEntitlement,
        requete=_requete_droits,
        colonne_statut=SubscriptionEntitlement.status,
        colonne_date=SubscriptionEntitlement.startsAt,
        projeter=_projection_droit,
    ),
    "incidents": ObjetSupport(
        nom="incidents",
        modele=Incident,
        requete=_requete_incidents,
        colonne_statut=Incident.state,
        colonne_date=Incident.occurredAt,
        projeter=_projection_incident,
        plateforme_seule=True,
    ),
}


def _invalide(code: str, message: str, champ: str, detail: str) -> AppError:
    return AppError(code=code, message=message, status_code=422, field_errors={champ: [detail]})


def normaliser_periode(date_debut: datetime | None, date_fin: datetime | None) -> tuple[datetime | None, datetime | None]:
    """Dates ramenées en UTC si elles sont naïves ; période inversée refusée en 422 (CA-2)."""
    def utc(valeur: datetime | None) -> datetime | None:
        if valeur is None or valeur.tzinfo is not None:
            return valeur
        return valeur.replace(tzinfo=timezone.utc)

    debut, fin = utc(date_debut), utc(date_fin)
    if debut is not None and fin is not None and debut > fin:
        raise _invalide("periode_invalide", "La date de début suit la date de fin.", "dateFrom", "dateFrom doit précéder dateTo")
    return debut, fin


async def exiger_lecture(
    db: AsyncSession, *, acteur_id: uuid.UUID, scope: AdminScope, organisation_id: uuid.UUID, objet: ObjetSupport
) -> None:
    """Lève 403 si la portée ne permet pas de lire cette liste pour cette organisation (CA-3, CA-4).

    Une liste réservée à la plateforme refusée en portée tenant est journalisée comme
    un refus cross-tenant, comme les autres refus de portée (BE-147 CA-4).
    """
    if objet.plateforme_seule and not scope.is_platform:
        await journaliser_refus_cross_tenant(
            db,
            acteur_id=acteur_id,
            organization_id=organisation_id,
            portee=f"tenant:{scope.organization_id} (liste réservée à la plateforme)",
        )
        raise AppError(code="admin_scope_denied", message="Accès d'administration refusé pour cette portée.", status_code=403)
    await exiger_portee_sur_tenant(
        db,
        acteur_id=acteur_id,
        portee_platforme=scope.is_platform,
        portee_organisation=scope.organization_id,
        organization_id=organisation_id,
        plateforme_couvre_tenant=True,
    )


async def lister_objets(
    db: AsyncSession,
    objet: ObjetSupport,
    *,
    organisation_id: uuid.UUID,
    statut: str | None,
    date_debut: datetime | None,
    date_fin: datetime | None,
    identifiant: uuid.UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[dict], int]:
    """Page de lignes filtrées de `objet` pour l'organisation, et total des lignes filtrées.

    Tri : date la plus récente d'abord, puis identifiant (ordre stable pour la pagination).
    Les filtres absents ne restreignent pas la liste.
    """
    stmt = objet.requete(organisation_id)
    if statut is not None:
        stmt = stmt.where(objet.colonne_statut == statut)
    if date_debut is not None:
        stmt = stmt.where(objet.colonne_date >= date_debut)
    if date_fin is not None:
        stmt = stmt.where(objet.colonne_date <= date_fin)
    if identifiant is not None:
        stmt = stmt.where(objet.modele.id == identifiant)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    lignes = (
        await db.execute(stmt.order_by(objet.colonne_date.desc(), objet.modele.id).limit(limit).offset(offset))
    ).scalars().all()
    return [objet.projeter(ligne) for ligne in lignes], total
