"""Routes du personnel de station : création en lot et réactivation (A4)."""

import uuid

from fastapi import APIRouter, Depends
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.modules.zylo_liquid.permissions import STATION_STAFF_MANAGE
from app.modules.zylo_liquid.exploitation.schemas_personnel import BulkCreateStationStaffRequest, BulkCreateStationStaffResponse
from app.modules.zylo_liquid.schemas import StationStaffResponse
from app.rbac.service import get_current_organization_id
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.zylo_liquid.exploitation import personnel_service as personnel_service
from app.modules.zylo_liquid.scopes import _station_id_body_scope, require_permission_scoped_via_body

from app.modules.zylo_liquid.scopes import _staff_user_station_scope
from app.rbac.service import require_permission_scoped_via
router = APIRouter()


@router.post(
    "/station-staff/bulk",
    response_model=BulkCreateStationStaffResponse,
    status_code=201,
    dependencies=[Depends(require_permission_scoped_via_body(STATION_STAFF_MANAGE, _station_id_body_scope))],
    summary="Créer du personnel en lot (tout-ou-rien)",
    description=(
        "Compte + fiche de poste + rôle scopé station pour chaque ligne, dans UNE transaction (50 lignes max). "
        "Mot de passe temporaire généré par le serveur, renvoyé une seule fois. Si une ligne est invalide : 422 "
        "`staff_bulk_invalid` avec `details=[{rowNumber, field, code, message}]` et rien n'est écrit."
    ),
)
async def bulk_create_station_staff(
    data: BulkCreateStationStaffRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> BulkCreateStationStaffResponse:
    return await personnel_service.bulk_create_station_staff(db, organization_id, current_user.id, data)



@router.post(
    "/station-staff/{user_id}/reactivate",
    response_model=StationStaffResponse,
    dependencies=[Depends(require_permission_scoped_via(STATION_STAFF_MANAGE, _staff_user_station_scope))],
)
async def reactivate_station_staff_member(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> StationStaffResponse:
    return await personnel_service.reactivate_station_staff_access(db, organization_id, current_user.id, user_id)
