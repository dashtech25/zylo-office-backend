"""Routes du module opérations (BE-236).

- GET /api/v1/operations/{operation_id} : état d'une opération de l'organisation courante.

Garde : l'organisation courante est validée par `get_current_organization_id` (appartenance
active). Le contrôle de droit (initiateur, ou `OPERATION_READ`) est fait dans
`service.lire_operation`, car il dépend de la ressource et non seulement de l'organisation.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.operations import service
from app.operations.schemas import OperationResponse
from app.rbac.guards import get_current_organization_id

router = APIRouter()


@router.get("/{operation_id}", response_model=OperationResponse)
async def lire_operation(
    operation_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OperationResponse:
    """Renvoie l'état de l'opération. 404 si absente ou d'un autre tenant, 403 sans droit."""
    operation = await service.lire_operation(
        db, operation_id=operation_id, organization_id=organization_id, utilisateur_id=current_user.id
    )
    return service.serialiser_operation(operation)
