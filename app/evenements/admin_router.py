"""Console plateforme du catalogue d'événements (BE-176), montée sous `/api/v1/admin`.

Routes :
- `GET /evenements/types` : catalogue des types d'événements et de leurs versions de schéma,
  droit plateforme `evenements.read` (allowlist `PLATFORM_EVENEMENTS_READ_USER_IDS`), 200.

Refus par défaut : sans droit plateforme, `PERMISSION_DENIED` (403) avant toute lecture. Le droit
est de portée plateforme, donc hors `rbac.service.user_has_permission` (voir
`app.modules_registry.platform_rights`). Le moteur unique de BE-226 n'est pas encore en place.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.evenements.schemas import lister_types
from app.identity.models import User
from app.modules_registry.platform_rights import exiger_droit_plateforme

router = APIRouter(prefix="/evenements", tags=["admin-evenements"])

DROIT_EVENEMENTS_READ = "evenements.read"


@router.get("/types", summary="Catalogue des types d'événements et de leurs versions (plateforme)")
async def lister_types_evenements(
    db: AsyncSession = Depends(get_db),
    utilisateur: User = Depends(get_current_user),
) -> list[dict]:
    exiger_droit_plateforme(utilisateur.id, DROIT_EVENEMENTS_READ)
    return await lister_types(db)
