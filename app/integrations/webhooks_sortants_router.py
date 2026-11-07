"""Routes du webhook sortant, montées sous `/api/v1` (BE-211).

- `POST /webhook-endpoints` : crée un endpoint, `201`, et renvoie son secret une seule fois (CA-6) ;
- `POST /webhook-endpoints/{endpoint_id}/rotate-secret` : nouveau secret, `200`, ancien valide pendant
  l'overlap (CA-4) ;
- `GET /webhook-deliveries/{delivery_id}` : statut d'une livraison, `200`, sans contenu du corps.

Droits : création et rotation exigent `integrations.manage` (refus `403` `PERMISSION_DENIED`) ; la
lecture d'une livraison exige `integrations.read`. Le tenant vient toujours de `X-Organization-Id`. Une
ressource d'un autre tenant répond `404` (CA-3). La logique est dans `app/integrations/webhooks_sortants.py`.
"""

import datetime as dt
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.ecriture import IdentiteEmettrice
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.integrations import webhooks_sortants
from app.integrations.permissions import INTEGRATIONS_MANAGE, INTEGRATIONS_READ
from app.integrations.router import exiger_permission
from app.rbac.guards import get_current_organization_id

router = APIRouter()


class EndpointCreation(BaseModel):
    """Corps de `POST /webhook-endpoints`. Seule une URL HTTPS est acceptée."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=12, max_length=2048, pattern=r"^https://\S+$")


class EndpointReponse(BaseModel):
    """Forme publique d'un endpoint. Aucun secret ni référence de coffre."""

    id: uuid.UUID
    url: str
    state: str
    createdAt: dt.datetime
    updatedAt: dt.datetime


class EndpointAvecSecret(EndpointReponse):
    """Réponse de création et de rotation : la valeur du secret, une seule fois.

    `overlapJusquA` n'est renseigné qu'après une rotation : jusqu'à cet instant, l'ancien secret est
    encore accepté par les récepteurs.
    """

    secret: str
    overlapJusquA: dt.datetime | None = None


class LivraisonReponse(BaseModel):
    """Statut d'une livraison. Le corps envoyé n'est jamais exposé."""

    id: uuid.UUID
    endpointId: uuid.UUID
    eventId: uuid.UUID
    attempts: int
    status: str
    nextAttemptAt: dt.datetime
    createdAt: dt.datetime


def _identite(current_user: User, organization_id: uuid.UUID) -> IdentiteEmettrice:
    return IdentiteEmettrice(user_id=current_user.id, organization_id=organization_id)


def _avec_secret(endpoint, valeur: str) -> EndpointAvecSecret:
    return EndpointAvecSecret(
        id=endpoint.id,
        url=endpoint.url,
        state=endpoint.state,
        createdAt=endpoint.createdAt,
        updatedAt=endpoint.updatedAt,
        secret=valeur,
        overlapJusquA=endpoint.overlapJusquA,
    )


@router.post(
    "/webhook-endpoints",
    response_model=EndpointAvecSecret,
    status_code=201,
    dependencies=[Depends(exiger_permission(INTEGRATIONS_MANAGE))],
    summary="Créer un endpoint de webhook sortant",
)
async def creer_endpoint(
    corps: EndpointCreation,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Crée l'endpoint actif et renvoie son secret de signature, une seule fois. `403` sans `integrations.manage`."""
    endpoint, valeur = await webhooks_sortants.creer_endpoint(
        db, _identite(current_user, organization_id), url=corps.url
    )
    await db.commit()
    await db.refresh(endpoint)
    return _avec_secret(endpoint, valeur)


@router.post(
    "/webhook-endpoints/{endpoint_id}/rotate-secret",
    response_model=EndpointAvecSecret,
    dependencies=[Depends(exiger_permission(INTEGRATIONS_MANAGE))],
    summary="Faire tourner le secret d'un endpoint de webhook sortant",
)
async def faire_tourner_secret(
    endpoint_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Renvoie le nouveau secret ; l'ancien reste accepté jusqu'à `overlapJusquA`. `404` hors tenant."""
    endpoint, valeur = await webhooks_sortants.faire_tourner_secret(
        db, _identite(current_user, organization_id), endpoint_id
    )
    await db.commit()
    await db.refresh(endpoint)
    return _avec_secret(endpoint, valeur)


@router.get(
    "/webhook-deliveries/{delivery_id}",
    response_model=LivraisonReponse,
    dependencies=[Depends(exiger_permission(INTEGRATIONS_READ))],
    summary="Lire le statut d'une livraison de webhook sortant",
)
async def lire_livraison(
    delivery_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Statut, tentatives et prochaine tentative. `404` si la livraison est d'un autre tenant (CA-3)."""
    return await webhooks_sortants.lire_livraison(db, organization_id, delivery_id)
