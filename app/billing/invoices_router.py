"""Routes de la facture par identifiant : finalisation et lecture (BE-086).

- `POST /api/v1/billing/invoices/{invoiceId}/finalize` : finalise un brouillon (permission
  `billing.invoice.finalize`, ACTF-09). Corps : `{"reason": "..."}`, obligatoire (audit).
- `GET /api/v1/billing/invoices/{invoiceId}` : lit une facture de l'organisation courante
  (permission `billing.invoice.read`). Hors périmètre : 404 `invoice_not_found`.

L'organisation courante vient de l'en-tête `X-Organization-Id` (app/rbac/guards.py).
La logique vit dans app/billing/invoices.py.
"""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import invoices
from app.billing.errors import BillingErrorCode, billing_error
from app.billing.models import Invoice
from app.billing.permissions import BILLING_INVOICE_FINALIZE, BILLING_INVOICE_READ
from app.billing.schemas import InvoiceResponse
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.guards import get_current_organization_id
from app.rbac.service import user_has_permission

router = APIRouter()


async def _exiger_permission(db: AsyncSession, user: User, organization_id: uuid.UUID, code: str) -> None:
    """Refuse avec `FORBIDDEN` (catalogue billing, BE-070) si l'utilisateur n'a pas `code`.

    Contrôle fait ici et non par `require_permission` du socle, qui répond `permission_denied` :
    la définition de BE-086 impose le code `FORBIDDEN` pour ces deux routes. Le contrôle reste
    celui de `user_has_permission` (refus par défaut, rbac/service.py).
    """
    if not await user_has_permission(db, user.id, organization_id, code):
        raise billing_error(BillingErrorCode.FORBIDDEN)


class FinaliserFactureRequest(BaseModel):
    reason: str


@router.post(
    "/invoices/{invoice_id}/finalize",
    response_model=InvoiceResponse,
    summary="Finaliser une facture brouillon",
)
async def finalize_invoice(
    invoice_id: uuid.UUID,
    data: FinaliserFactureRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Invoice:
    """Passe la facture de `draft` à `finalized` ; voir app/billing/invoices.py pour les règles."""
    await _exiger_permission(db, user, organization_id, BILLING_INVOICE_FINALIZE)
    return await invoices.finaliser_facture(db, organization_id, user.id, invoice_id, data.reason)


@router.get(
    "/invoices/{invoice_id}",
    response_model=InvoiceResponse,
    summary="Lire une facture de l'organisation courante",
)
async def get_invoice(
    invoice_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Invoice:
    """Une facture de l'organisation courante ; 404 si elle appartient à un autre périmètre."""
    await _exiger_permission(db, user, organization_id, BILLING_INVOICE_READ)
    return await invoices.lire_facture(db, organization_id, invoice_id)
