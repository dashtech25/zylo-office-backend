"""Routes des devis (BE-077), montées sous `/billing` (app/api/v1/router.py).

- `POST /api/v1/billing/quotes` : crée un devis. Corps : `planCode`, `scenario`,
  `payerId`. Réponse 201 avec le devis `priced`. Si le prix n'est pas configuré, la
  réponse est 422 (`PRICE_NOT_CONFIGURED`, ou `CURRENCY_NOT_CONFIGURED` /
  `TAX_NOT_CONFIGURED`) et `error.details[0].quoteId` désigne le devis resté `created`.
- `GET /api/v1/billing/quotes/{quoteId}` : lit un devis du tenant courant.
- `POST /api/v1/billing/quotes/{quoteId}/accept` : accepte un devis `priced`. Corps
  optionnel `expectedVersion` (verrou optimiste, BE-072).

Le tenant courant vient de l'en-tête `X-Organization-Id` (`get_current_organization_id`).
Toute la décision est dans app/billing/quotes/service.py ; la route ne fait que relayer.
"""

import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import Quote
from app.billing.quotes.service import accepter_devis, creer_devis, lire_devis
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.guards import get_current_organization_id

router = APIRouter()


class CreerDevisRequete(BaseModel):
    """Corps de la création : offre, scénario de tarification et compte payeur."""

    planCode: str
    scenario: str
    payerId: uuid.UUID


class AccepterDevisRequete(BaseModel):
    """Corps optionnel de l'acceptation : version attendue du devis (verrou optimiste)."""

    expectedVersion: int | None = None


class DevisReponse(BaseModel):
    """Représentation d'un devis. `pricingSnapshotJson` est nul avant l'état `priced`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    version: int
    payerId: uuid.UUID
    beneficiaryTenantId: uuid.UUID
    planVersionSnapshotId: uuid.UUID
    expiresAt: str | None = None
    createdAt: str
    pricingSnapshotJson: dict | None = None


def _reponse(devis: Quote) -> DevisReponse:
    return DevisReponse(
        id=devis.id,
        status=devis.status,
        version=devis.version,
        payerId=devis.payerId,
        beneficiaryTenantId=devis.beneficiaryTenantId,
        planVersionSnapshotId=devis.planVersionSnapshotId,
        expiresAt=devis.expiresAt.isoformat() if devis.expiresAt else None,
        createdAt=devis.createdAt.isoformat(),
        pricingSnapshotJson=devis.pricingSnapshotJson,
    )


@router.post("/quotes", response_model=DevisReponse, status_code=status.HTTP_201_CREATED, summary="Créer un devis (BE-077)")
async def creer(
    requete: CreerDevisRequete,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DevisReponse:
    """Crée le devis : permission `billing.subscription.manage`, puis prix (BE-078).

    Refus : 403 `FORBIDDEN` ; 404 `payer_not_found` ou `plan_not_found` ; 409
    `INVALID_TRANSITION` si l'offre est retirée ; 422 `PRICE_NOT_CONFIGURED` (le devis
    reste `created`, voir la docstring du module).
    """
    devis = await creer_devis(
        db,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        plan_code=requete.planCode,
        scenario=requete.scenario,
        payer_id=requete.payerId,
    )
    return _reponse(devis)


@router.get("/quotes/{quote_id}", response_model=DevisReponse, summary="Lire un devis (BE-077)")
async def lire(
    quote_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DevisReponse:
    """Lit un devis du tenant courant. 404 `quote_not_found` hors tenant ou inconnu ; 403 sans permission."""
    devis = await lire_devis(db, organization_id=organization_id, actor_user_id=current_user.id, quote_id=quote_id)
    return _reponse(devis)


@router.post("/quotes/{quote_id}/accept", response_model=DevisReponse, summary="Accepter un devis (BE-077)")
async def accepter(
    quote_id: uuid.UUID,
    requete: AccepterDevisRequete | None = None,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DevisReponse:
    """Accepte un devis `priced`. Refus : 403 `FORBIDDEN` ; 404 `quote_not_found` ; 409 `VERSION_CONFLICT`
    ou `INVALID_TRANSITION` ; 422 `QUOTE_EXPIRED` (le devis passe `expired`, aucune souscription)."""
    corps = requete or AccepterDevisRequete()
    devis = await accepter_devis(
        db,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        quote_id=quote_id,
        expected_version=corps.expectedVersion,
    )
    return _reponse(devis)
