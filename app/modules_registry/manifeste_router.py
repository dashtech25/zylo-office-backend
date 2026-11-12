"""Route de publication d'un manifeste de module, par code (BE-195), montée sous `/api/v1/admin`.

- `POST /modules/by-code/{module_code}/versions` : valide le manifeste et crée la version en
  `draft`, 201. Le chemin porte le segment `by-code` : la route BE-042 `POST /modules/{module_id}/versions`
  prend un identifiant UUID et ne doit pas être masquée.

Droit : `platform.catalog.manage` (QE-API-27), vérifié avant la lecture du manifeste. Réponses :
201, 401 sans session, 403 sans droit (`PERMISSION_DENIED`), 404 module inconnu, 409 version déjà
enregistrée, 422 manifeste rejeté (voir `manifeste_publication`).
"""

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.modules_registry import manifeste_publication as service
from app.modules_registry.permissions import PLATFORM_CATALOG_MANAGE
from app.modules_registry.platform_rights import exiger_droit_plateforme
from app.modules_registry.schemas import ModuleVersionAdminResponse

router = APIRouter(prefix="/modules/by-code", tags=["admin-modules"])


@router.post(
    "/{module_code}/versions",
    response_model=ModuleVersionAdminResponse,
    status_code=201,
    summary="Publie le manifeste d'un module et crée la version (draft)",
)
async def publier_manifeste(
    module_code: str,
    corps: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    utilisateur: User = Depends(get_current_user),
) -> ModuleVersionAdminResponse:
    """Crée la version `draft` d'un module à partir de son manifeste validé.

    Le droit `platform.catalog.manage` est exigé avant toute validation : un compte sans droit
    reçoit 403 quel que soit le contenu du manifeste. Le corps est lu comme un objet libre pour que
    la validation (et son audit de rejet) reste dans le service, pas dans la validation de FastAPI.
    """
    exiger_droit_plateforme(utilisateur.id, PLATFORM_CATALOG_MANAGE)
    ligne = await service.publier_manifeste(db, module_code, corps, acteur_id=utilisateur.id)
    await db.commit()
    return ModuleVersionAdminResponse.model_validate(ligne)
