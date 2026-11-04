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
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import service
from app.billing.models import Invoice, Subscription
from app.billing.permissions import BILLING_INVOICE_READ
from app.billing.schemas import InvoiceResponse
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
