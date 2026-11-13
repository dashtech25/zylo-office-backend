"""Route des remboursements (BE-093).

- `POST /api/v1/billing/payments/{paymentId}/refunds` : demande un remboursement d'un paiement
  réussi. En-tête `Idempotency-Key` obligatoire (16 à 120 caractères, BE-072). Corps :
  `{"amount": int > 0, "reason": str, "approverId": uuid | null}`. Réponses :
  - 201 : remboursement `succeeded` ou `failed` ;
  - 202 : remboursement `pending` (issue inconnue, à réconcilier, BE-095) ;
  - 403 `FORBIDDEN`, 404 `payment_not_found`, 409 `APPROVAL_REQUIRED` / `INVALID_TRANSITION` /
    `DUPLICATE`, 422 `REFUND_LIMIT_EXCEEDED`.

La décision est dans app/billing/refunds/service.py ; la route ne fait que relayer. L'adaptateur
est fourni par `obtenir_fournisseur_remboursement`, remplaçable par `app.dependency_overrides` en test.
"""

import uuid

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import Refund
from app.billing.payment_provider import FlutterwaveTestProvider, PaymentProvider
from app.billing.refunds.service import demander_remboursement
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.guards import get_current_organization_id

router = APIRouter()


def obtenir_fournisseur_remboursement() -> PaymentProvider:
    """Adaptateur de remboursement. Stub sandbox (BE-028 / QE-FAC-11) tant qu'aucun PSP n'est choisi."""
    return FlutterwaveTestProvider()


class DemandeRemboursement(BaseModel):
    """Corps de la demande : montant en unités mineures (> 0), motif obligatoire, approbateur humain."""

    amount: int = Field(gt=0)
    reason: str
    approverId: uuid.UUID | None = None


class RemboursementReponse(BaseModel):
    """Représentation d'un remboursement."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    paymentAttemptId: uuid.UUID
    amount: int
    currency: str
    status: str
    approverId: uuid.UUID | None
    reason: str


@router.post(
    "/payments/{payment_id}/refunds",
    response_model=RemboursementReponse,
    status_code=status.HTTP_201_CREATED,
    summary="Demander le remboursement d'un paiement réussi, avec approbation humaine (BE-093)",
)
async def rembourser(
    payment_id: uuid.UUID,
    data: DemandeRemboursement,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=120),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    fournisseur: PaymentProvider = Depends(obtenir_fournisseur_remboursement),
) -> Refund:
    """Relaie la demande au service ; une issue inconnue répond 202 avec `status: pending`."""
    remboursement = await demander_remboursement(
        db,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        payment_id=payment_id,
        idempotency_key=idempotency_key,
        amount=data.amount,
        reason=data.reason,
        approver_id=data.approverId,
        fournisseur=fournisseur,
    )
    if remboursement.status == "pending":
        response.status_code = status.HTTP_202_ACCEPTED
    return remboursement
