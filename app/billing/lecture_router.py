"""Lecture des factures de l'organisation courante (BE-027).

Routes (domaine facturation, montées sous `/api/v1/organizations`) :
- `GET /organizations/current/invoices` : page des factures de l'organisation active ;
- `GET /organizations/current/invoices/{invoiceId}` : une facture de l'organisation active.

Contrat :
- L'organisation n'est jamais prise dans le chemin : elle vient de l'en-tête
  `X-Organization-Id`, validé par `get_current_organization_id` (appartenance active,
  sinon 404 `organization_not_found`).
- Permission : `billing.invoice.read` (app/billing/permissions.py). Un membre sans
  cette permission reçoit 403 `permission_denied`.
- Facture d'une autre organisation : 404 `invoice_not_found`, comme une facture absente.
- Le statut renvoyé est celui de la base serveur. Les routes sont en lecture seule :
  aucun corps ni paramètre de requête n'écrit ou ne redéfinit un statut.

Les anciennes routes `/api/v1/billing/organizations/{id}/invoices` restent en place
(app/billing/router.py) ; elles ne sont pas la surface de lecture de BE-027.

Entitlements d'une organisation désignée par son identifiant (BE-045) :
- `GET /organizations/{organization_id}/entitlements` : entitlements avec source, niveau, état
  calculé, période, limite et unité de quota, en deux groupes (BE-107) : `included` (source
  `offre`) et `addOns` (autres sources). Le chemin porte l'organisation ;
  l'en-tête `X-Organization-Id` doit être identique (sinon 404, garde `organisation_cible`).
- Non-membre ou autre tenant : 404 `organization_not_found`, sans aucune donnée.
- Permission : `organization.entitlement.read` (QE-MOD-16). Membre sans elle : 403.
- Lecture seule : POST, PATCH et DELETE sur ce chemin répondent 405.

Usage de l'organisation (BE-108) :
- `GET /organizations/{organization_id}/usage` : dernier snapshot d'usage publié (table
  `usage_snapshot`, écrite par PH-09). Portée `OrgScope` (BE-101) : le chemin seul fixe
  l'organisation ; hors appartenance ou identifiant mal formé : 404 ; sans
  `organization.usage.read` : 403 `permission_denied`. Sans snapshot : 200 avec valeurs vides.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import entitlements as calcul_entitlements
from app.billing import service
from app.billing.models import Invoice, Subscription, UsageSnapshot
from app.billing.permissions import BILLING_INVOICE_READ, ORGANIZATION_ENTITLEMENT_READ
from app.billing.schemas import (
    EntitlementsOrganisationResponse,
    InvoiceResponse,
    OrganizationEntitlementResponse,
    UsageOrganisationResponse,
)
from app.core.database import get_db
from app.rbac.guards import get_current_organization_id
from app.rbac.portee_organisation import OrgScope, exiger_action
from app.rbac.service import require_permission
from app.shared.pagination import PaginationParams, paginate
from app.shared.schemas import Page

router = APIRouter()

# Source d'un droit inclus dans l'offre (sourceAttribution) ; tout autre droit est un add-on (BE-107).
SOURCE_INCLUSE = "offre"


@router.get(
    "/current/invoices",
    response_model=Page[InvoiceResponse],
    dependencies=[Depends(require_permission(BILLING_INVOICE_READ))],
    summary="Lister les factures de l'organisation courante",
)
async def list_current_invoices(
    pagination: PaginationParams = Depends(),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Factures des abonnements de l'organisation active, les plus récentes d'abord."""
    stmt = select(Invoice).join(Subscription, Subscription.id == Invoice.subscriptionId).where(
        Subscription.organizationId == organization_id
    ).order_by(Invoice.issuedAt.desc())
    return await paginate(db, stmt, pagination, InvoiceResponse)


@router.get(
    "/current/invoices/{invoice_id}",
    response_model=InvoiceResponse,
    dependencies=[Depends(require_permission(BILLING_INVOICE_READ))],
    summary="Lire une facture de l'organisation courante",
)
async def get_current_invoice(
    invoice_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Invoice:
    """Une facture de l'organisation active ; 404 si elle appartient à une autre organisation."""
    return await service.get_organization_invoice(db, organization_id, invoice_id)


@router.get(
    "/{organization_id}/entitlements",
    response_model=EntitlementsOrganisationResponse,
    dependencies=[Depends(require_permission(ORGANIZATION_ENTITLEMENT_READ))],
    summary="Lister les entitlements d'une organisation, droits inclus et add-ons séparés (BE-045, BE-107)",
)
async def list_organization_entitlements(
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> EntitlementsOrganisationResponse:
    """Entitlements de l'organisation du chemin, état calculé à la lecture, en deux groupes.

    La garde (`get_current_organization_id`) refuse d'abord une organisation étrangère ou
    sans appartenance active par un 404 uniforme ; la permission est ensuite exigée (403).
    Seules les lignes de cette organisation sont lues (isolation). `quotaUnit` est nul quand
    la capacité ne porte pas d'unité.

    Séparation (BE-107) : `included` = source `offre` (droits du plan), `addOns` = toute
    autre source (achat additionnel, essai, allocation admin, usage réel). Les deux groupes
    ne se recouvrent jamais ; l'ordre de lecture est conservé dans chaque groupe.
    Lecture seule : la route n'expose aucune méthode d'écriture (POST/PATCH/DELETE = 405).
    """
    calcules = await calcul_entitlements.calculer_entitlements(db, organization_id)
    lignes = [
        OrganizationEntitlementResponse(
            id=entitlement.id,
            moduleCode=entitlement.moduleCode,
            entitlementCode=entitlement.entitlementCode,
            scope=entitlement.niveauApplication,
            source=entitlement.sourceAttribution,
            state=entitlement.etat,
            quotaLimit=entitlement.quotaLimite,
            quotaUnit=entitlement.quotaUnit,
            periodStart=entitlement.startsAt,
            periodEnd=entitlement.endsAt,
            stateVersion=entitlement.stateVersion,
        )
        for entitlement in calcules
    ]
    return EntitlementsOrganisationResponse(
        included=[ligne for ligne in lignes if ligne.source == SOURCE_INCLUSE],
        addOns=[ligne for ligne in lignes if ligne.source != SOURCE_INCLUSE],
    )


# Action du portail pour la lecture de l'usage ; sa permission est dans POLITIQUE_PORTAIL (BE-108).
USAGE_PORTAIL_ACTION = "portail.usage.lire"


@router.get(
    "/{organization_id}/usage",
    response_model=UsageOrganisationResponse,
    summary="Lire l'usage (agrégats et limites) de l'organisation (BE-108)",
)
async def get_organization_usage(
    scope: OrgScope = Depends(exiger_action(USAGE_PORTAIL_ACTION)),
    db: AsyncSession = Depends(get_db),
) -> UsageOrganisationResponse:
    """Dernier snapshot d'usage de l'organisation du chemin, ou valeurs vides s'il n'en existe pas.

    La portée et la permission sont vérifiées par `exiger_action` avant le corps de la route.
    Seules les lignes de `scope.organization_id` sont lues (isolation tenant, CA-4). La réponse
    ne reprend que date, granularité, agrégats et limites : aucune identité individuelle (CA-2).
    """
    stmt = (
        select(UsageSnapshot)
        .where(UsageSnapshot.organizationId == scope.organization_id)
        .order_by(UsageSnapshot.measuredAt.desc())
        .limit(1)
    )
    ligne = (await db.execute(stmt)).scalars().first()
    if ligne is None:
        return UsageOrganisationResponse(measuredAt=None, granularity=None, aggregates={}, limits={})
    return UsageOrganisationResponse(
        measuredAt=ligne.measuredAt,
        granularity=ligne.granularity,
        aggregates=ligne.aggregates,
        limits=ligne.limits,
    )
