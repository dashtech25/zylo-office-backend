"""Routes des liens d'intégrations externes (BE-239).

Trois routes, toutes sous le tenant courant (`X-Organization-Id`, BE-010) :
- `GET /api/v1/integrations` : liste des liens du tenant, exige `integrations.read` ;
- `POST /api/v1/integrations/{provider}/connect` : crée un lien, exige `integrations.manage` ;
- `POST /api/v1/integrations/{id}/disconnect` : déconnecte un lien, exige `integrations.manage`.

Les contrôles de droits et de tenant vivent dans `app/integrations/liens.py` : les routes ne
font que traduire le corps HTTP. Une réponse n'expose jamais de valeur de secret (CA-1 de
BE-161) ; le corps de connexion porte la valeur une seule fois, et elle ne revient pas.
Le coffre est celui de `webhooks.get_coffre` (surchargeable en test).
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
from app.integrations.liens import (
    connecter_integration,
    deconnecter_integration,
    lister_integrations,
)
from app.integrations.models import IntegrationLink
from app.integrations.webhooks import get_coffre
from app.core.secrets import SecretStore
from app.rbac.guards import get_current_organization_id

router = APIRouter()


class ConnexionDemande(BaseModel):
    """Corps de `POST /integrations/{provider}/connect`.

    `remoteKey` doit être composée `fournisseur/compte/ressource` (CA-1). `secretValue` est
    déposée dans le coffre et n'est jamais relue. `extra="forbid"` : aucun `organizationId`
    dans le corps, le tenant vient de l'en-tête validé (CA-3).
    """

    model_config = ConfigDict(extra="forbid")

    externalAccount: str = Field(min_length=1, max_length=128)
    remoteKey: str = Field(min_length=1, max_length=512)
    secretValue: str = Field(min_length=1, max_length=4096)
    expireAt: datetime | None = None


class LienReponse(BaseModel):
    """Forme publique d'un lien. Aucune valeur de secret, aucun identifiant interne de coffre."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    externalAccount: str
    remoteKey: str
    statut: str
    curseurSync: str | None
    derniereReconciliation: datetime | None
    statutReconciliation: str | None
    createdAt: datetime
    updatedAt: datetime


def _identite(current_user: User, organization_id: uuid.UUID) -> IdentiteEmettrice:
    return IdentiteEmettrice(user_id=current_user.id, organization_id=organization_id)


@router.get(
    "/integrations",
    response_model=list[LienReponse],
    summary="Lister les liens d'intégrations de l'organisation courante",
)
async def lister(
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[IntegrationLink]:
    """Liste les liens du tenant courant. 403 sans `integrations.read`."""
    liens = await lister_integrations(db, _identite(current_user, organization_id), organization_id)
    return list(liens)


@router.post(
    "/integrations/{provider}/connect",
    response_model=LienReponse,
    status_code=201,
    summary="Connecter un compte externe à l'organisation courante",
)
async def connecter(
    provider: str,
    corps: ConnexionDemande,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
    store: SecretStore = Depends(get_coffre),
) -> IntegrationLink:
    """Crée le lien et dépose le secret dans le coffre. 403 sans `integrations.manage`, 422 si la clé n'est pas composée."""
    lien = await connecter_integration(
        db,
        store,
        _identite(current_user, organization_id),
        provider,
        corps.externalAccount,
        corps.remoteKey,
        corps.secretValue,
        expire_at=corps.expireAt,
    )
    await db.commit()
    return lien


@router.post(
    "/integrations/{lien_id}/disconnect",
    response_model=LienReponse,
    summary="Déconnecter un lien d'intégration et retirer son secret",
)
async def deconnecter(
    lien_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
    store: SecretStore = Depends(get_coffre),
) -> IntegrationLink:
    """Déconnecte le lien ; 404 pour un lien d'un autre tenant (CA-3), 403 sans `integrations.manage`."""
    lien = await deconnecter_integration(db, store, _identite(current_user, organization_id), lien_id)
    await db.commit()
    return lien
