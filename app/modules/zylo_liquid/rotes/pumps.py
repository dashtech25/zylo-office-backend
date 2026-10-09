"""Routes des pompes : création en lot (A1), affectation des pompistes (B4), index de fermeture (D1), « mon affectation » du pompiste."""

import uuid

from fastapi import APIRouter, Depends
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.modules.zylo_liquid.permissions import PUMP_ASSIGNMENT_MANAGE, PUMP_ASSIGNMENT_READ, PUMP_CLOSING_MANAGE, PUMP_CLOSING_READ, PUMP_MANAGE
from app.modules.zylo_liquid.exploitation.schemas_pompes import BulkCreatePumpsRequest, BulkCreatePumpsResponse, ClosingIndexesResponse, MyShiftAssignmentResponse, PumpAssignmentResponse, SaveClosingIndexesRequest, SavePumpAssignmentRequest
from app.rbac.service import get_current_organization_id, require_permission_any_scope, require_permission_scoped_via
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.zylo_liquid.exploitation import pumps_affectation as pumps_affectation
from app.modules.zylo_liquid.exploitation import pumps_fermeture as pumps_fermeture
from app.modules.zylo_liquid.exploitation import pumps_service as pumps_service
from app.modules.zylo_liquid.scopes import _pump_assignment_report_scope, _shift_report_station_scope, _station_id_body_scope, require_permission_scoped_via_body

router = APIRouter()


@router.post(
    "/pumps/bulk",
    response_model=BulkCreatePumpsResponse,
    status_code=201,
    dependencies=[Depends(require_permission_scoped_via_body(PUMP_MANAGE, _station_id_body_scope))],
    summary="Créer des pompes en lot (tout-ou-rien)",
    description=(
        "Valide toutes les lignes puis écrit en une transaction. Si une ligne est invalide : 422 "
        "`pump_bulk_invalid` avec `details=[{rowNumber, field, code, message}]` et rien n'est écrit."
    ),
)
async def bulk_create_pumps(
    data: BulkCreatePumpsRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BulkCreatePumpsResponse:
    return await pumps_service.bulk_create_pumps(db, organization_id, current_user.id, data)



@router.get(
    "/shift-reports/{report_id}/assignments",
    response_model=PumpAssignmentResponse,
    dependencies=[Depends(require_permission_scoped_via(PUMP_ASSIGNMENT_READ, _pump_assignment_report_scope))],
    summary="Lire l'affectation des pompistes aux pompes d'un tour (prévu / réel)",
    description=(
        "Une ligne par pompe du rapport : pompiste prévu (planning A5), pompiste affecté, écart calculé par le serveur "
        "(jamais bloquant), observation ; pompistes et chefs d'équipe éligibles (nom seulement), pompistes prévus sans pompe, "
        "récapitulatif par pompiste, accès en écriture. Tant que rien n'est confirmé : brouillon prérempli depuis le planning "
        "(`assignmentVersion` = 0, rien de stocké)."
    ),
)
async def get_pump_assignment(
    report_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PumpAssignmentResponse:
    return await pumps_affectation.get_pump_assignment(db, organization_id, current_user.id, report_id)



@router.put(
    "/shift-reports/{report_id}/assignments",
    response_model=PumpAssignmentResponse,
    dependencies=[Depends(require_permission_scoped_via(PUMP_ASSIGNMENT_MANAGE, _pump_assignment_report_scope))],
    summary="Enregistrer tout = confirmer l'affectation de départ (état final, tout-ou-rien)",
    description=(
        "Corps `{assignmentVersion, decidedByUserId?, rows:[{pumpId, userId?, closedForShift?, note?}]}`. Une cellule invalide : "
        "422 `pump_assignment_invalid` avec `details=[{rowNumber, rowKey: \"pump:<id>\", field, code, message}]`, rien n'est écrit. "
        "409 `assignment_locked` (déjà confirmée), `assignment_changed` (modifiée entre-temps), `shift_not_open`."
    ),
)
async def save_pump_assignment(
    report_id: uuid.UUID,
    data: SavePumpAssignmentRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PumpAssignmentResponse:
    return await pumps_affectation.save_pump_assignment(db, organization_id, current_user.id, report_id, data)



@router.post(
    "/shift-reports/{report_id}/assignments/reset-to-planning",
    response_model=PumpAssignmentResponse,
    dependencies=[Depends(require_permission_scoped_via(PUMP_ASSIGNMENT_MANAGE, _pump_assignment_report_scope))],
    summary="Reprendre le planning (brouillon = planning, avant confirmation)",
    description="Renvoie le brouillon prérempli depuis le planning A5 (rien n'est écrit : le brouillon n'est jamais stocké). 409 `assignment_locked` si déjà confirmée.",
)
async def reset_pump_assignment_to_planning(
    report_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PumpAssignmentResponse:
    return await pumps_affectation.reset_pump_assignment_to_planning(db, organization_id, current_user.id, report_id)



@router.get(
    "/my-shift-assignment",
    response_model=MyShiftAssignmentResponse,
    dependencies=[Depends(require_permission_any_scope(PUMP_ASSIGNMENT_READ))],
    summary="Mon affectation du tour (pompiste connecté, lecture seule)",
    description=(
        "Pompes tenues par l'utilisateur connecté dans les tours OUVERTS dont l'affectation est confirmée ; liste vide sinon. "
        "Le service ne renvoie que SES segments, sur les stations où il a `pumpAssignment.read` (portée vérifiée par station)."
    ),
)
async def get_my_shift_assignment(
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MyShiftAssignmentResponse:
    return await pumps_affectation.get_my_shift_assignment(db, organization_id, current_user.id)



@router.get(
    "/shift-reports/{report_id}/closing-indexes",
    response_model=ClosingIndexesResponse,
    dependencies=[Depends(require_permission_scoped_via(PUMP_CLOSING_READ, _shift_report_station_scope))],
    summary="Index de fermeture des pompes d'un tour : lignes, prix, ratures, totaux par produit",
    description=(
        "Tout ce que la section « 1. Index de fermeture des pompes » affiche : une ligne par pompe (ouverture verrouillée, saisies existantes, "
        "personnes proposées pour « Lu à deux avec », prix résolu à l'ouverture du tour, historique des ratures, avertissements ambre), "
        "récapitulatif par produit (TOTAL 1/2/3) et CUMUL P.B., `closingVersion` à renvoyer à l'enregistrement. Noms seulement, jamais d'e-mail."
    ),
)
async def get_closing_indexes(
    report_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ClosingIndexesResponse:
    return await pumps_fermeture.get_closing_indexes(db, organization_id, report_id)



@router.put(
    "/shift-reports/{report_id}/closing-indexes",
    response_model=ClosingIndexesResponse,
    dependencies=[Depends(require_permission_scoped_via(PUMP_CLOSING_MANAGE, _shift_report_station_scope))],
    summary="Enregistrer TOUS les index de fermeture (tout-ou-rien), ou un brouillon",
    description=(
        "Corps `{closingVersion, lines:[{pumpLineId, closingIndex, readWithUserId, exitsLiters?, tankReturnLiters?, exitsNote?, counterEvent?, "
        "counterEventNote?, replacedOldFinalIndex?, replacedNewStartIndex?, rature?:{reasonCode, reasonNote?, initialedByUserId}}], "
        "confirmedZeroSale:[pumpLineId], draft?}`. Une cellule invalide : 422 `pump_closing_invalid` avec `details=[{cell: \"pump:<id>\", rowNumber, "
        "field, code, message}]`, rien n'est écrit. 409 `closing_version_changed`, `report_not_open`, `draft_after_recording`. Le tour reste `opened` : "
        "le rapport passe seulement en phase `ready_to_close` (hors brouillon). Renvoie la même vue que le GET."
    ),
)
async def save_closing_indexes(
    report_id: uuid.UUID,
    data: SaveClosingIndexesRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClosingIndexesResponse:
    return await pumps_fermeture.save_closing_indexes(db, organization_id, current_user.id, report_id, data)
