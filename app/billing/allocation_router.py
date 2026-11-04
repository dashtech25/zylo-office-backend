"""Allocation des sièges d'entitlement aux membres (BE-046).

Routes (domaine facturation, montées sous `/api/v1/organizations`) :
- `POST /organizations/{organization_id}/entitlements/{entitlement_id}/allocations` :
  attribue un siège à `userId` (corps `userId`, `stateVersion`) ; 201 avec le siège créé.
- `DELETE /organizations/{organization_id}/entitlements/{entitlement_id}/allocations/{user_id}` :
  révoque le siège actif de ce membre ; 200 avec le siège, `revokedAt` renseigné.

Contrat :
- Garde d'organisation : `get_current_organization_id` refuse par un 404 uniforme un chemin
  ou un en-tête étranger, ou un acteur non membre. Aucune donnée n'est lue avant ce contrôle.
- Permissions distinctes : `organization.entitlement.allocate` pour l'attribution,
  `organization.entitlement.revoke` pour la révocation (app/billing/permissions.py). Membre
  sans la permission : 403 `permission_denied`, rien n'est écrit.
- La logique métier (verrou, quota, version, audit) est dans app/billing/allocations.py.
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import allocations
from app.billing.permissions import ORGANIZATION_ENTITLEMENT_ALLOCATE, ORGANIZATION_ENTITLEMENT_REVOKE
from app.billing.schemas import AllocationCreate, AllocationResponse
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.guards import get_current_organization_id
from app.rbac.service import require_permission

router = APIRouter()


@router.post(
    "/{organization_id}/entitlements/{entitlement_id}/allocations",
    response_model=AllocationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(ORGANIZATION_ENTITLEMENT_ALLOCATE))],
    summary="Attribuer un siège d'entitlement à un membre (BE-046)",
)
async def attribuer_siege(
    entitlement_id: uuid.UUID,
    payload: AllocationCreate,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Attribue un siège. 404 entitlement hors organisation, 422 membre étranger,
    409 quota atteint (`ENTITLEMENT_SEAT_LIMIT_REACHED`), version périmée ou siège déjà actif."""
    return await allocations.attribuer_siege(
        db,
        actor_user_id=current_user.id,
        organization_id=organization_id,
        entitlement_id=entitlement_id,
        user_id=payload.userId,
        state_version=payload.stateVersion,
    )


@router.delete(
    "/{organization_id}/entitlements/{entitlement_id}/allocations/{user_id}",
    response_model=AllocationResponse,
    dependencies=[Depends(require_permission(ORGANIZATION_ENTITLEMENT_REVOKE))],
    summary="Révoquer le siège d'un membre sur un entitlement (BE-046)",
)
async def revoquer_siege(
    entitlement_id: uuid.UUID,
    user_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Révoque le siège actif : la ligne est conservée avec `revokedAt`. 404 si aucun siège actif."""
    return await allocations.revoquer_siege(
        db,
        actor_user_id=current_user.id,
        organization_id=organization_id,
        entitlement_id=entitlement_id,
        user_id=user_id,
    )
