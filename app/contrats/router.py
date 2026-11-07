"""Lecture des versions d'un contrat (BE-215), montée sous `/api/v1`.

Route : `GET /contracts/{contract_name}/versions`, droit plateforme `platform.catalog.manage`
(allowlist `PLATFORM_CATALOG_MANAGE_USER_IDS`, QE-API-27). Sans droit : 403 `PERMISSION_DENIED`
avant toute lecture. Contrat sans version : 404 `CONTRACT_NOT_FOUND`.

Le droit est de portée plateforme : il passe par `app.modules_registry.platform_rights`, comme
les autres routes du catalogue, et non par `rbac.service.user_has_permission`.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.contrats.service import lister_versions
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user
from app.identity.models import User
from app.modules_registry.permissions import PLATFORM_CATALOG_MANAGE
from app.modules_registry.platform_rights import exiger_droit_plateforme

router = APIRouter(prefix="/contracts", tags=["contracts"])


@router.get("/{contract_name}/versions", summary="Versions d'un contrat (plateforme)")
async def lire_versions_contrat(
    contract_name: str,
    db: AsyncSession = Depends(get_db),
    utilisateur: User = Depends(get_current_user),
) -> list[dict]:
    exiger_droit_plateforme(utilisateur.id, PLATFORM_CATALOG_MANAGE)
    versions = await lister_versions(db, contract_name=contract_name)
    if not versions:
        raise AppError(code="CONTRACT_NOT_FOUND", message="Contrat inconnu.", status_code=404)
    return versions
