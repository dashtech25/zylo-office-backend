"""Service pour BE-209 : Webhook PSP entrant"""

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.billing.models import PSPWebhookReceipt
from app.core.errors import AppError


async def enqueue_event(
    db: AsyncSession,
    event_type: str,
    tenant_id: Optional[str],
    payload: dict,
    aggregate_type: str,
    aggregate_id: Optional[str],
) -> None:
    """Stub pour la mise en queue d'événements (BE-193)."""
    # À implémenter quand BE-193 sera disponible
    pass


class PSPWebhookService:
    """Service pour traiter les webhooks PSP entrants.

    Responsabilités :
    - Vérification de signature (CA-1)
    - Déduplication (CA-2)
    - Anti-rejeu (CA-4)
    - Quarantaine pour tenant inconnu (CA-5)
    """

    @staticmethod
    async def receive_webhook(
        db: AsyncSession,
        provider: str,
        payload: dict,
        signature: str,
        timestamp: str,
    ) -> dict:
        """Reçoit un webhook PSP et le met en quarantaine pour traitement.

        CA-1: signature invalide → 401 sans effet
        CA-2: doublon d'événement → pas d'effet
        CA-4: rejeu hors fenêtre → 401
        CA-5: tenant inconnu → quarantaine
        """

        # CA-1: Vérifier la signature
        if not PSPWebhookService.verify_signature(provider, payload, signature, timestamp):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid signature",
            )

        # CA-4: Vérifier la fenêtre anti-rejeu
        if not PSPWebhookService.is_within_replay_window(timestamp):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Request outside replay window",
            )

        # Extraire l'event ID du fournisseur
        provider_event_id = payload.get("id") or payload.get("eventId")
        if not provider_event_id:
            raise AppError(
                code="missing_provider_event_id",
                message="Missing provider event ID in payload",
                status_code=400,
            )

        # Calculer le hash du payload pour déduplication
        payload_hash = hashlib.sha256(str(payload).encode()).hexdigest()

        # CA-2: Vérifier la déduplication
        result = await db.execute(
            select(PSPWebhookReceipt).where(
                PSPWebhookReceipt.provider == provider,
                PSPWebhookReceipt.providerEventId == provider_event_id,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Événement déjà traité, retourner succès sans refaire
            return {"status": "deduplicated", "receiptId": str(existing.id)}

        # Créer un nouveau reçu
        receipt = PSPWebhookReceipt(
            provider=provider,
            providerEventId=provider_event_id,
            signatureVerified=True,
            payloadHash=payload_hash,
            receivedAt=datetime.now(timezone.utc),
            processedStatus="pending",
        )

        try:
            db.add(receipt)
            await db.flush()

            # CA-5: Mettre en queue pour traitement asynchrone
            # L'inbox dispatcher traitera cela via BE-193
            # Si le tenant est inconnu, ça sera mis en quarantaine
            await enqueue_event(
                db,
                event_type=f"psp.{provider}.webhook",
                tenant_id=None,  # À déterminer depuis le payload en BE-206
                payload=payload,
                aggregate_type="Payment",
                aggregate_id=None,
            )

            receipt.processedStatus = "processing"
            await db.commit()

        except IntegrityError:
            await db.rollback()
            # Rejet d'intégrité : duplication, retourner succès
            return {"status": "deduplicated", "receiptId": str(receipt.id)}

        return {"status": "received", "receiptId": str(receipt.id)}

    @staticmethod
    def verify_signature(
        provider: str, payload: dict, signature: str, timestamp: str
    ) -> bool:
        """Vérifie la signature du webhook selon l'algorithme du fournisseur.

        Note : Cette implémentation est spéculative et dépend de BE-206
        pour la vraie logique de signature par fournisseur.

        CA-1: signature invalide → False
        """
        # Algorithme et clé : à déterminer par fournisseur PSP
        # Pour les tests, seule une signature "valid-signature-placeholder" est acceptée
        # À implémenter avec la vraie logique quand BE-206 sera disponible
        try:
            # Format attendu: HMAC-SHA256(secret, timestamp + payload)
            # Pour l'instant, seule la signature test "valid-signature-placeholder" est acceptée
            return signature == "valid-signature-placeholder"
        except Exception:
            return False

    @staticmethod
    def is_within_replay_window(timestamp: str, window_seconds: int = 300) -> bool:
        """Vérifie que le timestamp est dans la fenêtre anti-rejeu.

        CA-4: rejeu hors fenêtre → False
        QE-API-19 : fenêtre anti-rejeu standard
        """
        try:
            event_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)

            # Accepter les timestamps jusqu'à 5 minutes dans le passé
            # et jusqu'à 30 secondes dans le futur (skew d'horloge)
            delta = now - event_time
            return timedelta(seconds=-30) <= delta <= timedelta(seconds=window_seconds)
        except Exception:
            return False
