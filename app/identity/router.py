import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import UserResponse
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity import service
from app.identity.models import Organization, User
from app.identity.permissions import ORGANIZATION_MANAGE
from app.identity.schemas import CreateOrganizationRequest, OrganizationResponse, UpdateOrganizationRequest, UpdateUserProfileRequest
from app.rbac.service import require_permission

router = APIRouter()

# Router séparé (préfixe /users) monté dans app/main.py à côté du router
# /organizations — un même module `identity` peut exposer plusieurs préfixes,
# jamais un nouveau module pour une seule route.
users_router = APIRouter()


@users_router.patch("/{user_id}", response_model=UserResponse)
async def update_user_profile(
    user_id: uuid.UUID,
    data: UpdateUserProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Périmètre volontairement restreint à `photoStorageReference` pour
    l'instant (voir UpdateUserProfileRequest) — self-service ou owner de
    l'organisation de la cible, contrôlé dans `service.update_user_profile`."""
    return await service.update_user_profile(db, user_id, current_user, data)


@router.get("", response_model=list[OrganizationResponse])
async def list_my_organizations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Organization]:
    return await service.list_user_organizations(db, current_user.id)


@router.post("", response_model=OrganizationResponse, status_code=201)
async def create_organization(
    data: CreateOrganizationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    return await service.create_organization(db, current_user, data)


@router.patch("/{organization_id}", response_model=OrganizationResponse)
async def update_organization(
    organization_id: str,
    data: UpdateOrganizationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_permission(ORGANIZATION_MANAGE)),
) -> Organization:
    return await service.update_organization(db, organization_id, current_user.id, data)


@router.get("/{organization_id}/protected-demo")
async def protected_demo(
    organization_id: str,
    _: None = Depends(require_permission(ORGANIZATION_MANAGE)),
) -> dict[str, str]:
    """Endpoint de démonstration Phase 5+6 — prouve qu'un accès est bien refusé
    sans la permission identity.organization.manage et accordé avec elle."""
    return {"status": "accès autorisé", "permission": ORGANIZATION_MANAGE}
