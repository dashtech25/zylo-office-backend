"""Routeur pour BE-209 : Webhook PSP entrant"""

from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.billing.webhook_service import PSPWebhookService

router = APIRouter()


@router.post("/webhooks/psp/{provider}", status_code=status.HTTP_202_ACCEPTED)
async def receive_psp_webhook(
    provider: str,
    request: Request,
    signature: str = Header(..., alias="X-Signature"),
    timestamp: str = Header(..., alias="X-Timestamp"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reçoit un webhook d'événement de paiement du fournisseur PSP.

    CA-1: signature invalide → 401 sans effet
    CA-2: doublon d'événement → pas d'effet
    CA-3: événement hors ordre → traité en ordre par le dispatcher (BE-193)
    CA-4: rejeu hors fenêtre → 401
    CA-5: tenant inconnu → quarantaine via BE-193

    Dépendances : BE-193, BE-206
    """

    # Récupérer le payload brut
    payload = await request.json()

    # Traiter le webhook via le service
    result = await PSPWebhookService.receive_webhook(
        db=db,
        provider=provider,
        payload=payload,
        signature=signature,
        timestamp=timestamp,
    )

    return result
