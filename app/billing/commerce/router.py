"""Routes BE-202 : devis, checkout et consentement, à la racine de `/api/v1`.

- `POST /api/v1/quotes` : crée un devis `created` (corps : `planVersionId`, `payerId`,
  `beneficiaryId` optionnel, `trial`). 201.
- `POST /api/v1/checkouts` : ouvre un checkout `open` depuis un devis (corps : `quoteId`). 201.
- `POST /api/v1/consents` : enregistre un consentement `trial` d'un payeur (corps : `payerId`,
  `kind`). 201.

Les trois routes exigent les en-têtes `X-Organization-Id` (tenant courant) et `Idempotency-Key`
(rejeu sans second effet, BE-072). Toute la décision est dans app/billing/commerce/service.py.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.commerce.service import creer_devis, enregistrer_consentement, ouvrir_checkout
from app.billing.models import Checkout, Consent, Quote
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.guards import get_current_organization_id

router = APIRouter()


def _cle_idempotence(idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=120)) -> str:
    """En-tête `Idempotency-Key` obligatoire (BE-072)."""
    return idempotency_key


class CreerDevisRequete(BaseModel):
    """Corps du devis : version de plan publiée, payeur, bénéficiaire optionnel, indicateur d'essai."""

    planVersionId: uuid.UUID
    payerId: uuid.UUID
    beneficiaryId: uuid.UUID | None = None
    trial: bool = False


class DevisReponse(BaseModel):
    """Devis BE-202. `planVersionSnapshotId` est l'instantané de l'offre figé au devis (BE-075)."""

    model_config = ConfigDict(from_attributes=True)

    quoteId: uuid.UUID
    tenantId: uuid.UUID
    payerId: uuid.UUID
    beneficiaryId: uuid.UUID | None
    planVersionSnapshotId: uuid.UUID
    state: str
    version: int
    trial: bool


class CreerCheckoutRequete(BaseModel):
    """Corps du checkout : devis à payer."""

    quoteId: uuid.UUID


class CheckoutReponse(BaseModel):
    """Checkout BE-202 : identifiant, devis, état et version."""

    checkoutId: uuid.UUID
    quoteId: uuid.UUID
    state: str
    version: int


class CreerConsentementRequete(BaseModel):
    """Corps du consentement : payeur et nature du consentement (`trial`)."""

    payerId: uuid.UUID
    kind: Literal["trial"]


class ConsentementReponse(BaseModel):
    """Consentement BE-202."""

    consentId: uuid.UUID
    payerId: uuid.UUID
    kind: str
    recordedAt: str


@router.post("/quotes", response_model=DevisReponse, status_code=status.HTTP_201_CREATED, summary="Créer un devis (BE-202)")
async def creer_devis_route(
    requete: CreerDevisRequete,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    idempotency_key: str = Depends(_cle_idempotence),
) -> DevisReponse:
    """Crée un devis `created`. Refus : 403 sans `billing.operate` ; 404 `payer_not_found` ou
    `plan_version_not_found` ; 422 `PLAN_VERSION_NOT_PUBLISHED` si la version n'est pas publiée."""
    devis: Quote = await creer_devis(
        db,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        plan_version_id=requete.planVersionId,
        payer_id=requete.payerId,
        beneficiary_id=requete.beneficiaryId,
        trial=requete.trial,
        idempotency_key=idempotency_key,
    )
    return DevisReponse(
        quoteId=devis.id,
        tenantId=devis.beneficiaryTenantId,
        payerId=devis.payerId,
        beneficiaryId=devis.beneficiaryId,
        planVersionSnapshotId=devis.planVersionSnapshotId,
        state=devis.status,
        version=devis.version,
        trial=devis.isTrial,
    )


@router.post("/checkouts", response_model=CheckoutReponse, status_code=status.HTTP_201_CREATED, summary="Ouvrir un checkout (BE-202)")
async def ouvrir_checkout_route(
    requete: CreerCheckoutRequete,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    idempotency_key: str = Depends(_cle_idempotence),
) -> CheckoutReponse:
    """Ouvre un checkout `open`. Refus : 403 sans `billing.operate` ; 404 `quote_not_found` (hors
    tenant ou inconnu) ; 422 `QUOTE_EXPIRED` ou `TRIAL_CONSENT_REQUIRED` ; 409 `INVALID_TRANSITION`."""
    checkout: Checkout = await ouvrir_checkout(
        db,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        quote_id=requete.quoteId,
        idempotency_key=idempotency_key,
    )
    return CheckoutReponse(
        checkoutId=checkout.id,
        quoteId=checkout.quoteId,
        state=checkout.status,
        version=checkout.version,
    )


@router.post("/consents", response_model=ConsentementReponse, status_code=status.HTTP_201_CREATED, summary="Enregistrer un consentement (BE-202)")
async def enregistrer_consentement_route(
    requete: CreerConsentementRequete,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    idempotency_key: str = Depends(_cle_idempotence),
) -> ConsentementReponse:
    """Enregistre un consentement `trial`. Refus : 403 sans `billing.operate` ; 404 `payer_not_found`."""
    consentement: Consent = await enregistrer_consentement(
        db,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        payer_id=requete.payerId,
        kind=requete.kind,
        idempotency_key=idempotency_key,
    )
    return ConsentementReponse(
        consentId=consentement.consentId,
        payerId=consentement.payerId,
        kind=consentement.kind,
        recordedAt=consentement.recordedAt.isoformat(),
    )
