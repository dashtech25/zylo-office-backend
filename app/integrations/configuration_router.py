"""Routes de configuration d'intégration, montées sous `/api/v1/integrations` (BE-210).

- `POST /integrations` : crée une configuration à l'état `configured`, `201` ;
- `GET /integrations/{integration_id}` : lit la configuration, sans aucun secret (CA-1) ;
- `POST /integrations/{integration_id}/rotate` : ajoute une version de secret, `200` (CA-4) ;
- `POST /integrations/{integration_id}/revoke` : révoque l'intégration, `200` (CA-3).

Droit : `integrations.manage` sur les quatre routes (la définition parle de `integration.manage`,
code déjà déclaré par `app/integrations/permissions.py`). Refus : `403` `PERMISSION_DENIED`.
Tenant : toujours celui de `X-Organization-Id` (`get_current_organization_id`), jamais du corps.
Une intégration d'un autre tenant répond `404` (CA-6).

Aucune réponse ne contient de secret ni de référence de coffre : seuls l'identifiant, le
fournisseur, l'usage, les portées, la version de configuration et l'état sortent.
La logique est dans `app/integrations/configuration.py`.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.ecriture import IdentiteEmettrice
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.integrations import configuration
from app.integrations.permissions import INTEGRATIONS_MANAGE
from app.integrations.router import exiger_permission
from app.rbac.guards import get_current_organization_id

router = APIRouter()


class IntegrationCreation(BaseModel):
    """Corps de `POST /integrations`. Le secret n'est accepté qu'à la création et à la rotation."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=32)
    purpose: str = Field(min_length=1, max_length=64)
    scopes: list[str] = Field(default_factory=list, max_length=50)
    configSchemaVersion: int = Field(ge=1)
    secret: str = Field(min_length=1, max_length=4096)


class RotationDemande(BaseModel):
    """Corps de `POST /integrations/{id}/rotate` : la nouvelle valeur du secret."""

    model_config = ConfigDict(extra="forbid")

    secret: str = Field(min_length=1, max_length=4096)


class IntegrationReponse(BaseModel):
    """Forme publique d'une intégration. Aucun champ de secret ni de référence de coffre (CA-1)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    purpose: str
    scopes: list[str]
    configSchemaVersion: int
    state: str
    createdAt: datetime
    updatedAt: datetime


def _identite(current_user: User, organization_id: uuid.UUID) -> IdentiteEmettrice:
    return IdentiteEmettrice(user_id=current_user.id, organization_id=organization_id)


@router.post(
    "",
    response_model=IntegrationReponse,
    status_code=201,
    dependencies=[Depends(exiger_permission(INTEGRATIONS_MANAGE))],
    summary="Créer la configuration d'une intégration",
)
async def creer_integration(
    corps: IntegrationCreation,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Crée l'intégration à l'état `configured` et range le secret dans le coffre (CA-1, CA-2).

    Refus : `403` sans `integrations.manage` (CA-5) ; `409` si le couple fournisseur et usage existe déjà.
    """
    integration = await configuration.creer_integration(
        db,
        _identite(current_user, organization_id),
        provider=corps.provider,
        purpose=corps.purpose,
        scopes=corps.scopes,
        config_schema_version=corps.configSchemaVersion,
        secret=corps.secret,
    )
    await db.commit()
    await db.refresh(integration)
    return integration


@router.get(
    "/{integration_id}",
    response_model=IntegrationReponse,
    dependencies=[Depends(exiger_permission(INTEGRATIONS_MANAGE))],
    summary="Lire la configuration d'une intégration, sans secret",
)
async def lire_integration(
    integration_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Renvoie l'intégration du tenant courant. `404` si elle est absente ou d'un autre tenant (CA-6)."""
    return await configuration.lire_integration(db, organization_id, integration_id)


@router.post(
    "/{integration_id}/rotate",
    response_model=IntegrationReponse,
    dependencies=[Depends(exiger_permission(INTEGRATIONS_MANAGE))],
    summary="Ajouter une version de secret à une intégration",
)
async def rotater_secret(
    integration_id: uuid.UUID,
    corps: RotationDemande,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Ajoute une version ; l'ancienne reste valide jusqu'à la révocation (CA-4)."""
    integration = await configuration.rotater_secret(
        db,
        _identite(current_user, organization_id),
        integration_id,
        secret=corps.secret,
    )
    await db.commit()
    await db.refresh(integration)
    return integration


@router.post(
    "/{integration_id}/revoke",
    response_model=IntegrationReponse,
    dependencies=[Depends(exiger_permission(INTEGRATIONS_MANAGE))],
    summary="Révoquer une intégration et ses secrets",
)
async def revoquer_integration(
    integration_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Passe l'intégration à `revoked` ; toute résolution de ses références est refusée (CA-3)."""
    integration = await configuration.revoquer_integration(
        db,
        _identite(current_user, organization_id),
        integration_id,
    )
    await db.commit()
    await db.refresh(integration)
    return integration
