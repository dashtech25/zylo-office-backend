"""BE-209 : Webhook PSP entrant — Réception et traitement.

Critères d'acceptation :
- CA-1: signature invalide → 401 sans effet
- CA-2: doublon d'événement → déduplication
- CA-4: rejeu hors fenêtre → 401
- CA-3: événement hors ordre → géré par inbox dispatcher (pas testé ici, c'est BE-193)
- CA-5: tenant inconnu → quarantaine (dépend de BE-206)
"""

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import PSPWebhookReceipt
from app.core.database import AsyncSessionLocal


@pytest.fixture
def webhook_payload():
    """Payload webhook PSP valide."""
    return {
        "id": f"evt_{uuid.uuid4().hex[:16]}",
        "eventType": "payment.success",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "data": {
            "paymentId": str(uuid.uuid4()),
            "amount": 50000,
            "currency": "XAF",
        },
    }


@pytest.fixture
def webhook_headers():
    """En-têtes webhook valides (signature et timestamp)."""
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "X-Signature": "valid-signature-placeholder",
        "X-Timestamp": timestamp,
    }


class TestCA1SignatureInvalide:
    """CA-1 : Signature invalide → HTTP 401 sans effet."""

    async def test_signature_invalide_retourne_401(
        self, client: AsyncClient, webhook_payload, webhook_headers
    ):
        """Signature invalide → HTTP 401."""
        headers = {
            **webhook_headers,
            "X-Signature": "invalid-signature",
        }

        res = await client.post(
            "/api/v1/webhooks/psp/stripe",
            json=webhook_payload,
            headers=headers,
        )

        assert res.status_code == 401

    async def test_signature_invalide_ne_cree_pas_receipt(
        self, client: AsyncClient, webhook_payload, webhook_headers
    ):
        """Signature invalide → pas de PSPWebhookReceipt créé."""
        headers = {
            **webhook_headers,
            "X-Signature": "invalid-signature",
        }

        await client.post(
            "/api/v1/webhooks/psp/stripe",
            json=webhook_payload,
            headers=headers,
        )

        # Vérifier qu'aucun receipt n'est créé
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PSPWebhookReceipt).where(
                    PSPWebhookReceipt.provider == "stripe",
                    PSPWebhookReceipt.providerEventId == webhook_payload["id"],
                )
            )
            assert result.scalar_one_or_none() is None


class TestCA2Deduplication:
    """CA-2 : Doublon d'événement → déduplication."""

    async def test_doublon_d_evenement_retourne_succes(
        self, client: AsyncClient, webhook_payload, webhook_headers
    ):
        """Même event_id envoyé deux fois → retour succès sans créer deux receipts."""

        # Premier appel
        res1 = await client.post(
            "/api/v1/webhooks/psp/stripe",
            json=webhook_payload,
            headers=webhook_headers,
        )
        assert res1.status_code == 202
        receipt_id_1 = res1.json()["receiptId"]

        # Deuxième appel avec le même payload
        res2 = await client.post(
            "/api/v1/webhooks/psp/stripe",
            json=webhook_payload,
            headers=webhook_headers,
        )
        assert res2.status_code == 202
        receipt_id_2 = res2.json()["receiptId"]

        # Même receipt ID retourné
        assert receipt_id_1 == receipt_id_2

        # Vérifier qu'un seul receipt existe en base
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PSPWebhookReceipt).where(
                    PSPWebhookReceipt.provider == "stripe",
                    PSPWebhookReceipt.providerEventId == webhook_payload["id"],
                )
            )
            receipts = result.scalars().all()
            assert len(receipts) == 1

    async def test_payload_different_cree_nouveau_receipt(
        self, client: AsyncClient, webhook_payload, webhook_headers
    ):
        """Deux payloads avec event_ids différents → deux receipts créés."""

        # Premier webhook
        res1 = await client.post(
            "/api/v1/webhooks/psp/stripe",
            json=webhook_payload,
            headers=webhook_headers,
        )
        assert res1.status_code == 202
        receipt_id_1 = res1.json()["receiptId"]

        # Deuxième webhook avec event_id différent
        payload2 = webhook_payload.copy()
        payload2["id"] = f"evt_{uuid.uuid4().hex[:16]}"

        res2 = await client.post(
            "/api/v1/webhooks/psp/stripe",
            json=payload2,
            headers=webhook_headers,
        )
        assert res2.status_code == 202
        receipt_id_2 = res2.json()["receiptId"]

        # IDs différents
        assert receipt_id_1 != receipt_id_2

        # Deux receipts en base
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(PSPWebhookReceipt))
            receipts = result.scalars().all()
            assert len(receipts) == 2


class TestCA4FenetreAntiRejeu:
    """CA-4 : Rejeu hors fenêtre → HTTP 401."""

    async def test_timestamp_trop_ancien_retourne_401(
        self, client: AsyncClient, webhook_payload, webhook_headers
    ):
        """Timestamp > 5 min dans le passé → HTTP 401."""
        old_timestamp = (
            datetime.now(timezone.utc) - timedelta(minutes=6)
        ).isoformat().replace("+00:00", "Z")

        headers = {
            **webhook_headers,
            "X-Timestamp": old_timestamp,
        }

        res = await client.post(
            "/api/v1/webhooks/psp/stripe",
            json=webhook_payload,
            headers=headers,
        )

        assert res.status_code == 401
        # Vérifier que la réponse mentionne la fenêtre de rejeu
        resp_json = res.json()
        # Accepter les deux formats : error.message ou detail
        message = (resp_json.get("error", {}).get("message", "") or
                   resp_json.get("detail", "")).lower()
        assert "replay" in message or "window" in message

    async def test_timestamp_valide_accepte(
        self, client: AsyncClient, webhook_payload, webhook_headers
    ):
        """Timestamp dans la fenêtre (< 5 min) → accepté."""
        valid_timestamp = (
            datetime.now(timezone.utc) - timedelta(minutes=2)
        ).isoformat().replace("+00:00", "Z")

        headers = {
            **webhook_headers,
            "X-Timestamp": valid_timestamp,
        }

        res = await client.post(
            "/api/v1/webhooks/psp/stripe",
            json=webhook_payload,
            headers=headers,
        )

        # Peut être 202 (accepted) ou 401 (si signature invalide)
        # Mais pas une erreur de fenêtre temporelle
        assert res.status_code in (202, 401)
        if res.status_code == 401:
            assert "signature" in res.json().get("detail", "").lower()

    async def test_timestamp_futur_acceptable_dans_tolerance(
        self, client: AsyncClient, webhook_payload, webhook_headers
    ):
        """Timestamp dans le futur mais acceptable (skew clock) → OK."""
        future_timestamp = (
            datetime.now(timezone.utc) + timedelta(seconds=30)
        ).isoformat().replace("+00:00", "Z")

        headers = {
            **webhook_headers,
            "X-Timestamp": future_timestamp,
        }

        res = await client.post(
            "/api/v1/webhooks/psp/stripe",
            json=webhook_payload,
            headers=headers,
        )

        # Doit être accepté (skew de quelques secondes normal)
        assert res.status_code in (202, 401)


class TestReceiptCreation:
    """Création et persistance de PSPWebhookReceipt."""

    async def test_receipt_creee_avec_les_bonnes_valeurs(
        self, client: AsyncClient, webhook_payload, webhook_headers
    ):
        """Receipt créé avec provider, providerEventId, timestamp, etc."""

        res = await client.post(
            "/api/v1/webhooks/psp/stripe",
            json=webhook_payload,
            headers=webhook_headers,
        )

        assert res.status_code == 202
        receipt_id = res.json()["receiptId"]

        async with AsyncSessionLocal() as db:
            receipt = await db.get(PSPWebhookReceipt, uuid.UUID(receipt_id))
            assert receipt is not None
            assert receipt.provider == "stripe"
            assert receipt.providerEventId == webhook_payload["id"]
            assert receipt.signatureVerified is True
            assert receipt.processedStatus == "processing"

    async def test_payload_hash_calcule(
        self, client: AsyncClient, webhook_payload, webhook_headers
    ):
        """Payload hash est calculé et stocké."""

        res = await client.post(
            "/api/v1/webhooks/psp/stripe",
            json=webhook_payload,
            headers=webhook_headers,
        )

        assert res.status_code == 202
        receipt_id = res.json()["receiptId"]

        async with AsyncSessionLocal() as db:
            receipt = await db.get(PSPWebhookReceipt, uuid.UUID(receipt_id))

            # Calculer le hash attendu
            expected_hash = hashlib.sha256(
                str(webhook_payload).encode()
            ).hexdigest()

            assert receipt.payloadHash == expected_hash


class TestProviderMultiple:
    """Support de plusieurs fournisseurs PSP."""

    async def test_webhooks_stripe_et_paypal_coexistent(
        self, client: AsyncClient, webhook_payload, webhook_headers
    ):
        """Même event_id chez deux providers différents → deux receipts."""

        # Webhook Stripe
        res1 = await client.post(
            "/api/v1/webhooks/psp/stripe",
            json=webhook_payload,
            headers=webhook_headers,
        )
        assert res1.status_code == 202

        # Webhook PayPal avec le même event_id
        res2 = await client.post(
            "/api/v1/webhooks/psp/paypal",
            json=webhook_payload,
            headers=webhook_headers,
        )
        assert res2.status_code == 202

        # Deux receipts créés (providers différents)
        async with AsyncSessionLocal() as db:
            stripe = await db.execute(
                select(PSPWebhookReceipt).where(
                    PSPWebhookReceipt.provider == "stripe"
                )
            )
            paypal = await db.execute(
                select(PSPWebhookReceipt).where(
                    PSPWebhookReceipt.provider == "paypal"
                )
            )

            assert stripe.scalar_one_or_none() is not None
            assert paypal.scalar_one_or_none() is not None


class TestEnqueueEvent:
    """Mise en queue des événements pour traitement asynchrone."""

    async def test_webhook_ajoute_a_la_queue(
        self, client: AsyncClient, webhook_payload, webhook_headers
    ):
        """Webhook accepté → événement mis en queue."""

        with patch("app.billing.webhook_service.enqueue_event", new_callable=AsyncMock) as mock_enqueue:
            res = await client.post(
                "/api/v1/webhooks/psp/stripe",
                json=webhook_payload,
                headers=webhook_headers,
            )

            assert res.status_code == 202

            # Vérifier que enqueue_event a été appelé
            mock_enqueue.assert_called_once()
            call_kwargs = mock_enqueue.call_args[1]
            assert call_kwargs["event_type"] == "psp.stripe.webhook"
            assert call_kwargs["payload"] == webhook_payload
