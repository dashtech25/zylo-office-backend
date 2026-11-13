"""Routes BE-204 : Facture (Invoice) — API de documents financiers.

Routes :
- `GET /api/v1/invoices` : liste paginée des factures du tenant courant (permission `billing.documents.read`)
- `GET /api/v1/invoices/{invoice_id}` : une facture du tenant courant (permission `billing.documents.read`)
- `POST /api/v1/invoices/{invoice_id}/finalize` : finalise un brouillon (permission `billing.operate`)
- `POST /api/v1/invoices/{invoice_id}/void` : annule une facture (permission `billing.operate`)

L'organisation courante vient de l'en-tête `X-Organization-Id`.
La logique métier vit dans app/billing/invoices_be204.py.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.permissions import BILLING_DOCUMENTS_READ, BILLING_OPERATE
from app.billing import invoices_be204
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.guards import get_current_organization_id
from app.rbac.service import user_has_permission
from app.core.errors import AppError

router = APIRouter(tags=["invoices"])


class FinalizeInvoiceRequest(BaseModel):
    """Corps de finalisation d'une facture."""
    reason: str


class VoidInvoiceRequest(BaseModel):
    """Corps d'annulation d'une facture."""
    reason: str | None = None


class InvoiceResponse(BaseModel):
    """Représentation d'une facture."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenantId: uuid.UUID
    payerId: uuid.UUID
    issuer: str
    number: str | None
    state: str  # draft | finalized | void
    snapshot: dict | None
    issuedAt: datetime
    version: int


class InvoicesListResponse(BaseModel):
    """Réponse paginée de la liste des factures."""

    model_config = ConfigDict(from_attributes=True)

    data: list[InvoiceResponse]
    cursor: str | None
    limit: int


async def _require_permission(
    db: AsyncSession, user: User, organization_id: uuid.UUID, permission_code: str
) -> None:
    """Lève 403 si l'utilisateur n'a pas la permission requise."""
    if not await user_has_permission(db, user.id, organization_id, permission_code):
        raise AppError(
            code="FORBIDDEN",
            message="Vous n'avez pas les permissions requises pour cette action.",
            status_code=403,
        )


@router.get("")
async def list_invoices(
    cursor: str | None = Query(None),
    limit: int = Query(default=20, ge=1, le=100),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InvoicesListResponse:
    """Liste les factures du tenant courant avec pagination.

    Permissions : `billing.documents.read`.
    """
    await _require_permission(db, user, organization_id, BILLING_DOCUMENTS_READ)

    invoices, next_cursor = await invoices_be204.list_invoices(
        db=db,
        organization_id=organization_id,
        cursor=cursor,
        limit=limit,
    )

    return InvoicesListResponse(
        data=[InvoiceResponse.model_validate(inv) for inv in invoices],
        cursor=next_cursor,
        limit=limit,
    )


@router.get("/{invoice_id}")
async def get_invoice(
    invoice_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InvoiceResponse:
    """Récupère une facture du tenant courant.

    Permissions : `billing.documents.read`.
    Isolation : une facture d'un autre tenant renvoie 404.
    """
    await _require_permission(db, user, organization_id, BILLING_DOCUMENTS_READ)

    invoice = await invoices_be204.get_invoice(
        db=db,
        organization_id=organization_id,
        invoice_id=invoice_id,
    )

    return InvoiceResponse.model_validate(invoice)


@router.post("/{invoice_id}/finalize")
async def finalize_invoice(
    invoice_id: uuid.UUID,
    data: FinalizeInvoiceRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InvoiceResponse:
    """Finalise une facture brouillon.

    Permissions : `billing.operate`.
    Transition : draft → finalized.
    Fige le snapshot et enregistre l'audit.
    """
    await _require_permission(db, user, organization_id, BILLING_OPERATE)

    invoice = await invoices_be204.finalize_invoice(
        db=db,
        organization_id=organization_id,
        user_id=user.id,
        invoice_id=invoice_id,
        reason=data.reason,
    )

    await db.commit()

    return InvoiceResponse.model_validate(invoice)


@router.post("/{invoice_id}/void")
async def void_invoice(
    invoice_id: uuid.UUID,
    data: VoidInvoiceRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InvoiceResponse:
    """Annule une facture (passe l'état à `void`).

    Permissions : `billing.operate`.
    La facture reste en base, queryable avec state='void'.
    """
    await _require_permission(db, user, organization_id, BILLING_OPERATE)

    invoice = await invoices_be204.void_invoice(
        db=db,
        organization_id=organization_id,
        user_id=user.id,
        invoice_id=invoice_id,
        reason=data.reason,
    )

    await db.commit()

    return InvoiceResponse.model_validate(invoice)
