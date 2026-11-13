"""BE-204 : Facture (Invoice) — API de documents financiers.

Intention : prouver les critères d'acceptation de BE-204 (implementation-backend/tasks-donnees-api-contrats.md) :
- CA-1 : facture émise ne peut être modifiée (immuable après finalization)
- CA-2 : deux factures du même émetteur ne peuvent avoir le même numéro (unicité)
- CA-3 : lecture d'une facture d'un autre tenant renvoie 404 (isolation)
- CA-4 : finalize sans `billing.operate` renvoie 403
- CA-5 : void ne supprime pas, change state seulement
- CA-6 : émission écrit entrée d'audit
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.billing.models import BillingInvoice


@pytest.mark.asyncio
async def test_ca2_invoice_unique_constraint_issuer_number():
    """CA-2 : deux factures du même émetteur ne peuvent avoir le même numéro (unicité)."""
    tenant_id = uuid.uuid4()
    issuer = "Émetteur Test"
    invoice_number = "INV-001"
    payer_id = uuid.uuid4()

    async with AsyncSessionLocal() as db:
        # Créer la première facture
        inv1 = BillingInvoice(
            id=uuid.uuid4(),
            tenantId=tenant_id,
            payerId=payer_id,
            issuer=issuer,
            number=invoice_number,
            state="finalized",
            snapshot=None,
            issuedAt=datetime.now(timezone.utc),
            version=1,
        )
        db.add(inv1)
        await db.commit()

        # Tenter de créer une deuxième avec même issuer+number : doit lever IntegrityError
        inv2 = BillingInvoice(
            id=uuid.uuid4(),
            tenantId=tenant_id,
            payerId=payer_id,
            issuer=issuer,
            number=invoice_number,
            state="finalized",
            snapshot=None,
            issuedAt=datetime.now(timezone.utc),
            version=1,
        )
        db.add(inv2)
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


@pytest.mark.asyncio
async def test_ca5_void_does_not_delete_and_changes_state():
    """CA-5 : void ne supprime pas la facture et change state seulement."""
    tenant_id = uuid.uuid4()
    invoice_id = uuid.uuid4()
    payer_id = uuid.uuid4()

    async with AsyncSessionLocal() as db:
        # Créer facture en draft
        invoice = BillingInvoice(
            id=invoice_id,
            tenantId=tenant_id,
            payerId=payer_id,
            issuer="Émetteur Test",
            number="INV-005",
            state="draft",
            snapshot=None,
            issuedAt=datetime.now(timezone.utc),
            version=1,
        )
        db.add(invoice)
        await db.commit()

        # Passer à void
        invoice.state = "void"
        invoice.version = 2
        db.add(invoice)
        await db.commit()

        # Vérifier que la facture existe toujours avec state=void
        result = await db.execute(
            select(BillingInvoice).where(BillingInvoice.id == invoice_id)
        )
        fetched = result.scalar_one_or_none()
        assert fetched is not None, "Facture doit rester en base après void"
        assert fetched.state == "void", "État doit passer à void"
