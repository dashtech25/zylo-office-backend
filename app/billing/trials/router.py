"""Route de démarrage d'essai (BE-080).

Route : `POST /api/v1/billing/subscriptions/trials`, montée sous `/billing`
(app/api/v1/router.py).

Corps :
- `subscriptionId` : abonnement à mettre en essai ;
- `trialEnd` : fin d'essai, obligatoire, avec fuseau (QE-FAC-05) ;
- `consent` : optionnel, `{consentTextVersion, scope}` ; enregistré via BE-076 avant le
  contrôle de consentement.

Contrat :
- Tenant courant : en-tête `X-Organization-Id` (`get_current_organization_id`).
- Permission : `billing.subscription.manage` (SUBSCRIPTION_MANAGE). Sans elle : 403
  `FORBIDDEN`, et l'abonnement n'est pas touché. Le contrôle précède la lecture de
  l'abonnement, pour ne pas sonder son existence.
- Abonnement hors tenant ou inexistant : 404 `subscription_not_found`.
- Pas de consentement enregistré pour le compte : 422 `CONSENT_REQUIRED`.
- Abonnement qui ne peut pas passer en essai : 409 `INVALID_TRANSITION`.
- Succès : 200 avec l'agrégat abonnement (SubscriptionEtatResponse, BE-079).

La logique est dans app/billing/trials/service.py.
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.errors import BillingErrorCode, billing_error
from app.billing.permissions import SUBSCRIPTION_MANAGE
from app.billing.subscriptions.router import SubscriptionEtatResponse
from app.billing.trials.service import demarrer_essai
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.guards import get_current_organization_id
from app.rbac.service import user_has_permission

router = APIRouter()


class ConsentementEssai(BaseModel):
    """Consentement fourni avec la demande d'essai ; enregistré tel quel (BE-076)."""

    consentTextVersion: str = Field(min_length=1, max_length=64)
    scope: Literal["payeur", "tenant", "beneficiaire"]


class DemarrageEssaiRequete(BaseModel):
    """Corps de la demande d'essai. `trialEnd` doit porter un fuseau (QE-FAC-05)."""

    subscriptionId: uuid.UUID
    trialEnd: datetime
    consent: ConsentementEssai | None = None

    @field_validator("trialEnd")
    @classmethod
    def _exiger_fuseau(cls, valeur: datetime) -> datetime:
        """Refuse une fin d'essai naïve : elle serait interprétée selon le fuseau du serveur."""
        if valeur.tzinfo is None or valeur.utcoffset() is None:
            raise ValueError("trialEnd doit porter un fuseau horaire")
        return valeur


@router.post(
    "/subscriptions/trials",
    response_model=SubscriptionEtatResponse,
    summary="Démarrer l'essai d'un abonnement (BE-080)",
)
async def demarrer_essai_abonnement(
    payload: DemarrageEssaiRequete,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionEtatResponse:
    """Met l'abonnement en `trialing` si le consentement est enregistré ; sinon refuse sans écrire."""
    if not await user_has_permission(db, current_user.id, organization_id, SUBSCRIPTION_MANAGE):
        raise billing_error(BillingErrorCode.FORBIDDEN)
    consentement = payload.consent.model_dump() if payload.consent is not None else None
    abonnement = await demarrer_essai(
        db,
        subscription_id=payload.subscriptionId,
        tenant_id=organization_id,
        actor_id=current_user.id,
        trial_end=payload.trialEnd,
        consent=consentement,
    )
    return SubscriptionEtatResponse.model_validate(abonnement)
