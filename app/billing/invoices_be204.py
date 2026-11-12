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

    Retourne (factures, curseur suivant) ou lève 404 si l'organisation n'existe pas.
    TODO: Implémenter.
    """
    # Placeholder
    return [], None


async def get_invoice(db: AsyncSession, organization_id: uuid.UUID, invoice_id: uuid.UUID) -> Any:
    """Lit une facture du tenant courant.

    Lève 404 `invoice_not_found` si absente ou hors scope.
    TODO: Implémenter.
    """
    raise AppError(
        code="invoice_not_found",
        message="Facture introuvable.",
        status_code=404,
    )


async def finalize_invoice(
    db: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    invoice_id: uuid.UUID,
    reason: str,
) -> Any:
    """Finalise une facture brouillon.

    Transition : draft → finalized. Fige le snapshot, écrit l'audit.
    Lève 404 si absente ou hors scope, 409 si transition interdite.
    TODO: Implémenter.
    """
    raise AppError(
        code="invoice_not_found",
        message="Facture introuvable.",
        status_code=404,
    )


async def void_invoice(
    db: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    invoice_id: uuid.UUID,
    reason: str | None = None,
) -> Any:
    """Annule une facture.

    Transition : * → void. La facture reste queryable avec state='void'.
    Lève 404 si absente ou hors scope.
    TODO: Implémenter.
    """
    raise AppError(
        code="invoice_not_found",
        message="Facture introuvable.",
        status_code=404,
    )
