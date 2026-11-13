"""Routes de la facture par identifiant : finalisation et lecture (BE-086).

- `POST /api/v1/billing/invoices/{invoiceId}/finalize` : finalise un brouillon (permission
  `billing.invoice.finalize`, ACTF-09). Corps : `{"reason": "..."}`, obligatoire (audit).
- `GET /api/v1/billing/invoices/{invoiceId}` : lit une facture de l'organisation courante
  (permission `billing.invoice.read`). Hors périmètre : 404 `invoice_not_found`.
- `POST /api/v1/billing/invoices/{invoiceId}/credit-notes` : émet un avoir sur une facture
  finalisée (BE-087). Permission finance `billing.invoice.finalize` (ACTF-09, réutilisée :
  QE-SOC-06). Corps : `{"amount", "reason", "approverId"}`. Règles : app/billing/credit_notes/service.py.

L'organisation courante vient de l'en-tête `X-Organization-Id` (app/rbac/guards.py).
La logique vit dans app/billing/invoices.py.
"""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import invoices
from app.billing.credit_notes import service as avoirs
from app.billing.errors import BillingErrorCode, billing_error
from app.billing.models import CreditNote, Invoice
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


class EmettreAvoirRequest(BaseModel):
    """Corps de l'émission d'avoir (BE-087). `amount` en unités mineures, strictement positif."""

    amount: int = Field(gt=0)
    reason: str
    approverId: uuid.UUID | None = None


class AvoirResponse(BaseModel):
    """Représentation d'un avoir émis (BE-087)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoiceId: uuid.UUID
    amount: int
    currency: str
    reason: str
    status: str
    createdAt: datetime


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


@router.post(
    "/invoices/{invoice_id}/credit-notes",
    response_model=AvoirResponse,
    status_code=201,
    summary="Émettre un avoir sur une facture finalisée",
)
async def create_credit_note(
    invoice_id: uuid.UUID,
    data: EmettreAvoirRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CreditNote:
    """Crée un avoir lié à la facture ; la facture d'origine n'est pas modifiée (app/billing/credit_notes/service.py)."""
    await _exiger_permission(db, user, organization_id, BILLING_INVOICE_FINALIZE)
    return await avoirs.emettre_avoir(
        db, organization_id, user.id, invoice_id,
        amount=data.amount, reason=data.reason, approver_id=data.approverId,
    )
