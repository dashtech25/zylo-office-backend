"""Route des tentatives de paiement d'un checkout (BE-082).

- `POST /api/v1/billing/checkouts/{checkoutId}/payment-attempts` : soumet le checkout au fournisseur.
  En-tête `Idempotency-Key` obligatoire (16 à 120 caractères, BE-072). Corps ignoré : aucune donnée
  de carte n'est reçue ni transmise (CA-5). Réponses :
  - 201 : tentative `pending` (débit accepté, confirmation par webhook à venir) ;
  - 202 : tentative `unknown` (délai dépassé, CA-2) ;
  - 402 `PAYMENT_DECLINED`, 403 `FORBIDDEN`, 404 `checkout_not_found`, 409 `INVALID_TRANSITION`,
    503 `PROVIDER_UNAVAILABLE`.

La décision est dans app/billing/payment_attempts/service.py ; la route ne fait que relayer.
L'adaptateur fournisseur est fourni par `obtenir_fournisseur` : le stub sandbox (BE-028) par défaut.
Un test le remplace par `app.dependency_overrides[obtenir_fournisseur]`.
"""

import uuid

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import PaymentAttempt
from app.billing.payment_attempts.service import soumettre_tentative
from app.billing.payment_provider import FlutterwaveTestProvider, PaymentProvider
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.guards import get_current_organization_id

router = APIRouter()


def obtenir_fournisseur() -> PaymentProvider:
    """Adaptateur fournisseur utilisé par la route. Stub sandbox BE-028 tant qu'aucun PSP n'est choisi (QE-FAC-11)."""
    return FlutterwaveTestProvider()


class TentativeReponse(BaseModel):
    """Représentation d'une tentative : identifiant, checkout, état, version, date de soumission."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    checkoutId: uuid.UUID | None
    status: str
    version: int
    submittedAt: str | None


def _reponse(tentative: PaymentAttempt) -> TentativeReponse:
    return TentativeReponse(
        id=tentative.id,
        checkoutId=tentative.checkoutId,
        status=tentative.status,
        version=tentative.version,
        submittedAt=tentative.submittedAt.isoformat() if tentative.submittedAt else None,
    )


@router.post(
    "/checkouts/{checkout_id}/payment-attempts",
    response_model=TentativeReponse,
    status_code=status.HTTP_201_CREATED,
    summary="Soumettre un checkout au fournisseur de paiement (BE-082)",
)
async def soumettre(
    checkout_id: uuid.UUID,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=120),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    fournisseur: PaymentProvider = Depends(obtenir_fournisseur),
) -> TentativeReponse:
    """Soumet le checkout. Une issue inconnue (délai) répond 202 avec `status: unknown`."""
    tentative = await soumettre_tentative(
        db,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        checkout_id=checkout_id,
        idempotency_key=idempotency_key,
        fournisseur=fournisseur,
    )
    if tentative.status == "unknown":
        response.status_code = status.HTTP_202_ACCEPTED
    return _reponse(tentative)
