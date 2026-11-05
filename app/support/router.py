"""Routes de l'accès support (BE-262), montées sous `/api/v1/organizations`.

- `POST /{organization_id}/acces-support` : octroi d'un accès (201) ;
- `GET /{organization_id}/acces-support/courant` : lecture de l'accès actif du
  membre connecté sur cette organisation, avec audit de la lecture.

Chemins et noms NON DÉFINIS dans la source ; recommandation appliquée (BE-262).
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.support import service
from app.support.schemas import AccesSupportCreate, AccesSupportResponse

router = APIRouter()


@router.post(
    "/{organization_id}/acces-support",
    response_model=AccesSupportResponse,
    status_code=201,
    summary="Octroyer un accès support en lecture seule par défaut (BE-262)",
)
async def creer_acces_support(
    organization_id: uuid.UUID,
    corps: AccesSupportCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Crée l'accès, journalise l'octroi et renvoie l'accès créé.

    Le droit `rbac.grant.manage` de l'auteur est exigé dans l'organisation du
    chemin (contrôlé par le service)."""
    return await service.creer_acces(
        db,
        organization_id,
        current_user.id,
        corps.supportUserId,
        corps.justification,
        mode=corps.mode,
        fin_utc=corps.finUtc,
    )


@router.get(
    "/{organization_id}/acces-support/courant",
    response_model=AccesSupportResponse,
    summary="Lire l'accès support actif sur l'organisation (BE-262)",
)
async def lire_acces_support_courant(
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Renvoie l'accès actif du membre connecté ; 403 si aucun accès n'est valide."""
    return await service.obtenir_acces_courant(db, organization_id, current_user.id)
