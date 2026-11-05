"""Route de lecture des litiges fournisseur (BE-094).

- `GET /api/v1/billing/disputes/{disputeId}` : lit un litige de l'organisation courante
  (en-tête `X-Organization-Id`). Réponses : 200 ; 403 `FORBIDDEN` sans permission
  `billing.dispute.read` ; 404 `dispute_not_found` pour un litige absent ou d'un autre tenant.

Aucune route d'écriture : l'ouverture et la clôture passent uniquement par l'évènement fournisseur
(BE-083). La décision est dans app/billing/disputes/service.py ; la route ne fait que relayer.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.disputes.service import lire_litige
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.guards import get_current_organization_id

router = APIRouter()


class LitigeReponse(BaseModel):
    """Représentation d'un litige fournisseur."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    paymentAttemptId: uuid.UUID
    status: str
    providerRef: str
    openedAt: datetime
    resolvedAt: datetime | None


@router.get(
    "/disputes/{dispute_id}",
    response_model=LitigeReponse,
    summary="Lire un litige fournisseur de l'organisation courante (BE-094)",
)
async def lire(
    dispute_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Relaie la lecture au service, qui contrôle la permission puis le périmètre du tenant."""
    return await lire_litige(
        db, demandeur_id=current_user.id, organization_id=organization_id, dispute_id=dispute_id,
    )
