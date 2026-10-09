"""Routes du jaugeage des cuves à la fermeture du tour (D2)."""

import uuid

from fastapi import APIRouter, Depends
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.modules.zylo_liquid.exploitation.schemas_jauge import SaveTankGaugingRequest, TankGaugingResponse
from app.modules.zylo_liquid.permissions import TANK_GAUGING_MANAGE, TANK_GAUGING_READ
from app.rbac.service import get_current_organization_id, require_permission_scoped_via
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.zylo_liquid.exploitation import jauge_service as jauge_service
from app.modules.zylo_liquid.scopes import _shift_report_station_scope

router = APIRouter()


@router.get(
    "/shift-reports/{report_id}/closing-gauging",
    response_model=TankGaugingResponse,
    dependencies=[Depends(require_permission_scoped_via(TANK_GAUGING_READ, _shift_report_station_scope))],
    summary="Lire le jaugeage de fermeture : mesure, contrôle du stock, comparaison télémétrie",
    description=(
        "Une ligne par cuve du rapport : ouverture, reçu (réceptions déclarées), ventes et sorties (D1), stock théorique, stock réel (hauteur convertie "
        "par la table de jaugeage ou litres de la table papier), écart de stock (réel - théorique), points de la table, historique des ratures, "
        "comparaison télémétrie (jamais fusionnée), totaux par produit, livraisons détectées non déclarées, `gaugingVersion`."
    ),
)
async def get_tank_gauging(
    report_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> TankGaugingResponse:
    return await jauge_service.get_tank_gauging(db, organization_id, report_id)



@router.put(
    "/shift-reports/{report_id}/closing-gauging",
    response_model=TankGaugingResponse,
    dependencies=[Depends(require_permission_scoped_via(TANK_GAUGING_MANAGE, _shift_report_station_scope))],
    summary="Enregistrer tout le jaugeage de fermeture (tout-ou-rien)",
    description=(
        "Corps `{gaugingVersion, lines:[{tankLineId, heightCm, gaugedAt?, method?, measuredByUserId?, assistedByUserId?, paperTable?:{liters, reference}, "
        "varianceNote?, rature?:{reasonCode, reasonNote?, initialedByUserId}}]}`. Une cellule invalide : 422 `tank_gauging_invalid` avec "
        "`details=[{cell: \"tank:<id>\", kind, id, rowNumber, field, code, message}]`, rien n'est créé. 409 `gauging_version_changed`, `shift_not_open`."
    ),
)
async def save_tank_gauging(
    report_id: uuid.UUID,
    data: SaveTankGaugingRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TankGaugingResponse:
    return await jauge_service.save_tank_gauging(db, organization_id, current_user.id, report_id, data)
