from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity import service
from app.identity.models import Organization, User
from app.identity.permissions import ORGANIZATION_MANAGE
from app.identity.schemas import CreateOrganizationRequest, OrganizationResponse
from app.rbac.service import require_permission

router = APIRouter()


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


@router.get("/{organization_id}/protected-demo")
async def protected_demo(
    organization_id: str,
    _: None = Depends(require_permission(ORGANIZATION_MANAGE)),
) -> dict[str, str]:
    """Endpoint de démonstration Phase 5+6 — prouve qu'un accès est bien refusé
    sans la permission identity.organization.manage et accordé avec elle."""
    return {"status": "accès autorisé", "permission": ORGANIZATION_MANAGE}
