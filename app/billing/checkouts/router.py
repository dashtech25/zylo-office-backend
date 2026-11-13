"""Routes des checkouts (BE-081), montées sous `/billing` (app/api/v1/router.py).

- `POST /api/v1/billing/checkouts` : ouvre un checkout `open` depuis un devis `accepted`.
  Corps : `quoteId`. Réponse 201. Un champ `status` dans le corps est ignoré : le client
  ne fixe jamais l'état (CA-2).
- `GET /api/v1/billing/checkouts/{checkoutId}` : lit un checkout du tenant courant.

Le tenant courant vient de l'en-tête `X-Organization-Id`. La décision est dans
app/billing/checkouts/service.py ; la route ne fait que relayer.
"""

import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.checkouts.service import creer_checkout, lire_checkout
from app.billing.models import Checkout
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.guards import get_current_organization_id

router = APIRouter()


class CreerCheckoutRequete(BaseModel):
    """Corps de la création : devis accepté à payer."""

    quoteId: uuid.UUID


class CheckoutReponse(BaseModel):
    """Représentation d'un checkout : identifiant, devis, état, version, date de création."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    quoteId: uuid.UUID
    status: str
    version: int
    createdAt: str


def _reponse(checkout: Checkout) -> CheckoutReponse:
    return CheckoutReponse(
        id=checkout.id,
        quoteId=checkout.quoteId,
        status=checkout.status,
        version=checkout.version,
        createdAt=checkout.createdAt.isoformat(),
    )


@router.post(
    "/checkouts",
    response_model=CheckoutReponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ouvrir un checkout depuis un devis accepté (BE-081)",
)
async def creer(
    requete: CreerCheckoutRequete,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CheckoutReponse:
    """Crée un checkout `open`. Refus : 403 `FORBIDDEN` ; 404 `quote_not_found` ; 422 `QUOTE_EXPIRED`
    ou `CONSENT_REQUIRED` ; 409 `INVALID_TRANSITION` si le devis n'est pas accepté."""
    checkout = await creer_checkout(
        db,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        quote_id=requete.quoteId,
    )
    return _reponse(checkout)


@router.get("/checkouts/{checkout_id}", response_model=CheckoutReponse, summary="Lire un checkout (BE-081)")
async def lire(
    checkout_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CheckoutReponse:
    """Lit un checkout du tenant courant. 404 `checkout_not_found` hors tenant ou inconnu ; 403 sans permission."""
    checkout = await lire_checkout(
        db,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        checkout_id=checkout_id,
    )
    return _reponse(checkout)
