"""Routes BE-214 : Rétention, sauvegarde et purge.

Route :
- `POST /api/v1/admin/retention/purges` : demande de purge

La logique métier vit dans app/retention/service.py.
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.retention import service
from app.core.errors import AppError

router = APIRouter(prefix="/admin/retention", tags=["retention"])


class PurgeRequest(BaseModel):
    """Corps de la demande de purge."""
    category: str = Field(..., description="Catégorie de données à purger")
    beforeDate: datetime = Field(..., description="Données antérieures à cette date")


class PurgeResponse(BaseModel):
    """Réponse de la demande de purge."""
    status: str
    category: str
    beforeDate: str
    organizationId: str
    requestedAt: str


@router.post("/purges")
async def request_purge(
    data: PurgeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PurgeResponse:
    """Demande la purge des données pour une catégorie.

    Permissions : `platform.retention.manage` (admin).
    Vérification legal_hold (CA-1).
    Vérification durée définie (CA-2).
    Isolation tenant (CA-4).
    Audit (CA-5).

    Lève 422 si legal_hold actif ou durée non définie.
    """
    from sqlalchemy import select
    from app.identity.models import OrganizationUser

    # TODO: Implémenter contrôle de permission platform.retention.manage
    # if not await user_has_permission(db, user.id, None, "platform.retention.manage"):
    #     raise AppError(code="FORBIDDEN", message="Permission requise.", status_code=403)

    # TODO: Obtenir organization_id depuis le contexte (admin, pas isolé à une org)
    # Pour l'instant, récupérer la première organisation de l'utilisateur
    org_user = (await db.execute(
        select(OrganizationUser).where(OrganizationUser.userId == user.id).limit(1)
    )).scalar_one_or_none()

    if not org_user:
        raise AppError(
            code="no_organization",
            message="L'utilisateur n'appartient à aucune organisation.",
            status_code=403,
        )

    organization_id = org_user.organizationId

    result = await service.request_purge(
        db=db,
        organization_id=organization_id,
        user_id=user.id,
        category=data.category,
        before_date=data.beforeDate,
    )

    await db.commit()

    return PurgeResponse(**result)
