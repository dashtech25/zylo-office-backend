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
- `GET /organizations/{organization_id}/entitlements` : liste des entitlements avec source,
  niveau, état calculé, période, limite et unité de quota. Le chemin porte l'organisation ;
  l'en-tête `X-Organization-Id` doit être identique (sinon 404, garde `organisation_cible`).
- Non-membre ou autre tenant : 404 `organization_not_found`, sans aucune donnée.
- Permission : `organization.entitlement.read` (QE-MOD-16). Membre sans elle : 403.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import entitlements as calcul_entitlements
from app.billing import service
from app.billing.models import Invoice, Subscription
from app.billing.permissions import BILLING_INVOICE_READ, ORGANIZATION_ENTITLEMENT_READ
from app.billing.schemas import InvoiceResponse, OrganizationEntitlementResponse
from app.core.database import get_db
from app.rbac.guards import get_current_organization_id
from app.rbac.service import require_permission
from app.shared.pagination import PaginationParams, paginate
from app.shared.schemas import Page

router = APIRouter()


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
    response_model=list[OrganizationEntitlementResponse],
    dependencies=[Depends(require_permission(ORGANIZATION_ENTITLEMENT_READ))],
    summary="Lister les entitlements d'une organisation (BE-045)",
)
async def list_organization_entitlements(
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[OrganizationEntitlementResponse]:
    """Entitlements de l'organisation du chemin, état calculé à la lecture.

    La garde (`get_current_organization_id`) refuse d'abord une organisation étrangère ou
    sans appartenance active par un 404 uniforme ; la permission est ensuite exigée (403).
    Seules les lignes de cette organisation sont lues (isolation). `quotaUnit` est nul quand
    la capacité ne porte pas d'unité.
    """
    calcules = await calcul_entitlements.calculer_entitlements(db, organization_id)
    return [
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
