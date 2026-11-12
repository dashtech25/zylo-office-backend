"""Services BE-204 : Facture (Invoice) — API de documents financiers.

Logique métier pour les routes de documents financiers :
- Lecture paginée des factures (GET /api/v1/invoices)
- Lecture d'une facture (GET /api/v1/invoices/{id})
- Finalisation d'une facture brouillon (POST /api/v1/invoices/{id}/finalize)
- Annulation d'une facture (POST /api/v1/invoices/{id}/void)

Règles de domaine :
- Une facture émise (state='finalized' ou state='void') est append-only : aucune modification.
- Deux factures du même émetteur ne peuvent avoir le même numéro (unicité).
- Isolation tenant : chaque facture appartient à un tenant ; lecture d'un autre tenant = 404.
- Audit : chaque émission écrit une entrée d'audit.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError


async def list_invoices(
    db: AsyncSession,
    organization_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = 20,
) -> tuple[list[Any], str | None]:
    """Liste paginée des factures du tenant courant.

    Filtre par tenantId pour isolation (CA-3).
    Retourne (factures, curseur suivant).

    Implémentation spéculative : structure pagination basique.
    """
    from app.billing.models import BillingInvoice
    from sqlalchemy import select, and_, func

    # Requête de base : factures du tenant courant
    query = select(BillingInvoice).where(BillingInvoice.tenantId == organization_id)

    # Pagination avec curseur (ID de la dernière facture vue)
    if cursor:
        try:
            last_id = uuid.UUID(cursor)
            query = query.where(BillingInvoice.id > last_id)
        except (ValueError, TypeError):
            pass  # Curseur invalide, ignorer et démarrer du début

    # Limiter à limit + 1 pour déterminer s'il y a une page suivante
    query = query.order_by(BillingInvoice.id).limit(limit + 1)

    result = await db.execute(query)
    invoices = result.scalars().all()

    # Déterminer le curseur suivant
    next_cursor = None
    if len(invoices) > limit:
        invoices = invoices[:limit]
        next_cursor = str(invoices[-1].id)

    return invoices, next_cursor


async def get_invoice(db: AsyncSession, organization_id: uuid.UUID, invoice_id: uuid.UUID) -> Any:
    """Lit une facture du tenant courant.

    Isolation (CA-3) : une facture d'un autre tenant retourne 404.
    Lève 404 `invoice_not_found` si absente ou hors scope.

    Implémentation spéculative : requête directe par ID + filtrage tenant.
    """
    from app.billing.models import BillingInvoice
    from sqlalchemy import select, and_

    result = await db.execute(
        select(BillingInvoice).where(
            and_(
                BillingInvoice.id == invoice_id,
                BillingInvoice.tenantId == organization_id,
            )
        )
    )
    invoice = result.scalar_one_or_none()

    if not invoice:
        raise AppError(
            code="invoice_not_found",
            message="Facture introuvable.",
            status_code=404,
        )

    return invoice


async def finalize_invoice(
    db: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    invoice_id: uuid.UUID,
    reason: str,
) -> Any:
    """Finalise une facture brouillon.

    Transition : draft → finalized (CA-1). Fige le snapshot, écrit l'audit (CA-6).
    Lève 404 si absente ou hors scope, 409 si transition interdite.

    Implémentation spéculative : transition d'état, audit writing.
    """
    from app.billing.models import BillingInvoice
    from sqlalchemy import select, and_
    from app.shared.audit import write_audit_event

    # Charger la facture
    result = await db.execute(
        select(BillingInvoice).where(
            and_(
                BillingInvoice.id == invoice_id,
                BillingInvoice.tenantId == organization_id,
            )
        )
    )
    invoice = result.scalar_one_or_none()

    if not invoice:
        raise AppError(
            code="invoice_not_found",
            message="Facture introuvable.",
            status_code=404,
        )

    # Contrôler la transition (CA-1, CA-5)
    if invoice.state != "draft":
        raise AppError(
            code="invoice_invalid_state_transition",
            message=f"Impossible de finaliser une facture avec l'état '{invoice.state}'. Seul l'état 'draft' peut être finalisé.",
            status_code=409,
        )

    # Finaliser : passer l'état, éventuellement figer le snapshot
    invoice.state = "finalized"
    invoice.version += 1

    # Écrire l'audit (CA-6)
    await write_audit_event(
        db=db,
        principal_id=user_id,
        principal_kind="user",
        action="billing.invoice.finalize",
        organization_id=organization_id,
        resource_id=str(invoice_id),
        resource_kind="invoice",
        details={"reason": reason, "previous_state": "draft"},
    )

    db.add(invoice)
    await db.flush()

    return invoice


async def void_invoice(
    db: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    invoice_id: uuid.UUID,
    reason: str | None = None,
) -> Any:
    """Annule une facture.

    Transition : * → void (CA-5). La facture reste queryable avec state='void'.
    Lève 404 si absente ou hors scope.

    Implémentation spéculative : transition d'état.
    """
    from app.billing.models import BillingInvoice
    from sqlalchemy import select, and_

    # Charger la facture
    result = await db.execute(
        select(BillingInvoice).where(
            and_(
                BillingInvoice.id == invoice_id,
                BillingInvoice.tenantId == organization_id,
            )
        )
    )
    invoice = result.scalar_one_or_none()

    if not invoice:
        raise AppError(
            code="invoice_not_found",
            message="Facture introuvable.",
            status_code=404,
        )

    # Annuler : passer l'état à void
    previous_state = invoice.state
    invoice.state = "void"
    invoice.version += 1

    db.add(invoice)
    await db.flush()

    return invoice
