"""Routes des tours : modèles, planning, pointage, passation, ouverture et rapport de tour, mouvements de personnel (B1-B5, A2, A5). Chaque route porte sa garde de permission (`require_permission_scoped_via*`)."""

import uuid

from fastapi import APIRouter, Depends
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.modules.zylo_liquid.permissions import SHIFT_ATTENDANCE_MANAGE, SHIFT_ATTENDANCE_READ, SHIFT_DEFINITION_MANAGE, SHIFT_HANDOVER_MANAGE, SHIFT_HANDOVER_READ, SHIFT_PLANNING_MANAGE, SHIFT_PLANNING_READ, SHIFT_REPLACEMENT_MANAGE, SHIFT_REPLACEMENT_READ, SHIFT_REPORT_MANAGE, SHIFT_REPORT_READ
from app.modules.zylo_liquid.exploitation.schemas_tours import AddPumpLineRequest, BulkSaveShiftAttendanceRequest, BulkSaveShiftHandoverRequest, BulkSaveShiftPlanningRequest, BulkSaveShiftPlanningResponse, BulkUpsertShiftDefinitionsRequest, BulkUpsertShiftDefinitionsResponse, CancelStaffMovementRequest, CloseHandoverIssueRequest, CloseHandoverIssueResponse, CorrectPumpOpeningRequest, OpenShiftRequest, ReceiveShiftHandoverRequest, ReceiveShiftHandoverResponse, RecordStaffMovementRequest, ShiftAttendanceResponse, ShiftAttendanceSummaryResponse, ShiftDefinitionResponse, ShiftHandoverContextResponse, ShiftHandoverSummaryResponse, ShiftOpeningContextResponse, ShiftPlanningResponse, ShiftReportResponse, StaffMovementsResponse
from app.rbac.service import get_current_organization_id, require_permission_scoped_via
from app.shared.pagination import PaginationParams
from app.shared.schemas import Page
from datetime import date
from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.zylo_liquid.exploitation import shifts_attendance as shifts_attendance
from app.modules.zylo_liquid.exploitation import shifts_definitions as shifts_definitions
from app.modules.zylo_liquid.exploitation import pumps_mouvements as shifts_mouvements
from app.modules.zylo_liquid.exploitation import shifts_passation as shifts_passation
from app.modules.zylo_liquid.exploitation import shifts_planning as shifts_planning
from app.modules.zylo_liquid.exploitation import shifts_rapport as shifts_rapport
from app.modules.zylo_liquid.scopes import _handover_item_station_scope, _handover_station_scope, _occurrence_id_body_scope, _occurrence_id_query_scope, _pump_assignment_report_scope, _shift_report_station_scope, _station_id_body_scope, _station_id_query_scope, require_permission_scoped_via_body, require_permission_scoped_via_query

from app.modules.zylo_liquid.permissions import SHIFT_DEFINITION_READ
router = APIRouter()


@router.post(
    "/shift-definitions/bulk",
    response_model=BulkUpsertShiftDefinitionsResponse,
    dependencies=[Depends(require_permission_scoped_via_body(SHIFT_DEFINITION_MANAGE, _station_id_body_scope))],
    summary="Définir les tours d'une station en lot (tout-ou-rien)",
    description=(
        "Upsert : ligne sans `id` = création, avec `id` = modification (dont activation/désactivation). "
        "Validation sur l'état final ; si une ligne est invalide : 422 `shift_definition_bulk_invalid` avec "
        "`details=[{rowNumber, field, code, message}]` et rien n'est écrit."
    ),
)
async def bulk_upsert_shift_definitions(
    data: BulkUpsertShiftDefinitionsRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BulkUpsertShiftDefinitionsResponse:
    return await shifts_definitions.bulk_upsert_shift_definitions(db, organization_id, current_user.id, data)



@router.get(
    "/shift-definitions",
    response_model=Page[ShiftDefinitionResponse],
    dependencies=[Depends(require_permission_scoped_via_query(SHIFT_DEFINITION_READ, _station_id_query_scope))],
    summary="Lister les tours",
    description="Liste paginée des tours, triée par numéro, filtrable par station et par statut actif/inactif.",
)
async def list_shift_definitions(
    pagination: PaginationParams = Depends(),
    stationId: uuid.UUID | None = None,
    active: bool | None = None,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await shifts_definitions.list_shift_definitions(db, organization_id, current_user.id, pagination, stationId, active)



@router.get(
    "/shift-planning",
    response_model=ShiftPlanningResponse,
    dependencies=[Depends(require_permission_scoped_via_query(SHIFT_PLANNING_READ, _station_id_query_scope))],
    summary="Lire la grille du planning d'une période (31 jours max)",
    description=(
        "Renvoie tout ce que la grille affiche : tours, pompes, personnel éligible par rôle (nom seulement), "
        "occurrences + affectations, trous (`gaps`), avertissements non bloquants (`warnings`), jours fermés et jeton `version`."
    ),
)
async def get_shift_planning(
    stationId: uuid.UUID,
    from_: date = Query(alias="from"),
    to: date = Query(),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ShiftPlanningResponse:
    return await shifts_planning.get_shift_planning(db, organization_id, stationId, from_, to)



@router.put(
    "/shift-planning/bulk",
    response_model=BulkSaveShiftPlanningResponse,
    dependencies=[Depends(require_permission_scoped_via_body(SHIFT_PLANNING_MANAGE, _station_id_body_scope))],
    summary="Enregistrer le planning d'une période (état final, tout-ou-rien)",
    description=(
        "Corps = état final de la période. Si une case est invalide : 422 `shift_planning_invalid` avec "
        "`details=[{cell, field, code, message}]` et rien n'est écrit ; 409 `planning_changed` si la période a changé depuis le chargement."
    ),
)
async def bulk_save_shift_planning(
    data: BulkSaveShiftPlanningRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BulkSaveShiftPlanningResponse:
    return await shifts_planning.bulk_save_shift_planning(db, organization_id, current_user.id, data)



@router.get(
    "/shift-attendance",
    response_model=ShiftAttendanceResponse,
    dependencies=[Depends(require_permission_scoped_via_query(SHIFT_ATTENDANCE_READ, _occurrence_id_query_scope))],
    summary="Lire le pointage d'un tour (pré-rempli depuis le planning)",
    description=(
        "Renvoie la feuille de pointage du tour OU les lignes virtuelles pré-remplies depuis le planning (statut « à pointer », "
        "jamais « présent » par défaut), la version, la signature, l'accès en écriture (fenêtre de saisie), les personnes "
        "éligibles (nom seulement) et les avertissements non bloquants."
    ),
)
async def get_shift_attendance(
    occurrenceId: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ShiftAttendanceResponse:
    return await shifts_attendance.get_shift_attendance(db, organization_id, current_user.id, occurrenceId)



@router.put(
    "/shift-attendance/bulk",
    response_model=ShiftAttendanceResponse,
    dependencies=[Depends(require_permission_scoped_via_body(SHIFT_ATTENDANCE_MANAGE, _occurrence_id_body_scope))],
    summary="Enregistrer le pointage d'un tour (état final, tout-ou-rien)",
    description=(
        "Corps = état final de la feuille. Si une cellule est invalide : 422 `shift_attendance_invalid` avec "
        "`details=[{rowNumber, lineKey, field, code, message}]` et rien n'est écrit ; 409 `attendance_changed` si la feuille a changé ; "
        "422 `attendance_too_early` / `attendance_window_closed`, 409 `attendance_locked` selon la fenêtre de saisie."
    ),
)
async def bulk_save_shift_attendance(
    data: BulkSaveShiftAttendanceRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ShiftAttendanceResponse:
    return await shifts_attendance.bulk_save_shift_attendance(db, organization_id, current_user.id, data)



@router.get(
    "/shift-attendance/summary",
    response_model=ShiftAttendanceSummaryResponse,
    dependencies=[Depends(require_permission_scoped_via_query(SHIFT_ATTENDANCE_READ, _station_id_query_scope))],
    summary="Pastilles de pointage de la grille du planning",
    description="Par tour de la période (31 jours max) : lignes pointées / à pointer, présents, retards, absents, remplacés. Calculé, jamais saisi.",
)
async def get_shift_attendance_summary(
    stationId: uuid.UUID,
    from_: date = Query(alias="from"),
    to: date = Query(),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ShiftAttendanceSummaryResponse:
    return await shifts_attendance.get_shift_attendance_summary(db, organization_id, stationId, from_, to)



@router.get(
    "/shift-handover/context",
    response_model=ShiftHandoverContextResponse,
    dependencies=[Depends(require_permission_scoped_via_query(SHIFT_HANDOVER_READ, _occurrence_id_query_scope))],
    summary="Lire tout ce que le pop-up « Passation » affiche",
    description=(
        "Partie A (tour précédent et sa passation, état calculé de la station avec « non disponible » explicite, anomalies en cours "
        "de la station, prise de connaissance) et partie B (ce que ce tour laisse au suivant : lignes, version, signature)."
    ),
)
async def get_shift_handover_context(
    occurrenceId: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ShiftHandoverContextResponse:
    return await shifts_passation.get_shift_handover_context(db, organization_id, current_user.id, occurrenceId)



@router.put(
    "/shift-handover/bulk",
    response_model=ShiftHandoverContextResponse,
    dependencies=[Depends(require_permission_scoped_via_body(SHIFT_HANDOVER_MANAGE, _occurrence_id_body_scope))],
    summary="Enregistrer la passation d'un tour (partie B, état final, tout-ou-rien)",
    description=(
        "Si une cellule est invalide : 422 `shift_handover_invalid` avec `details=[{rowNumber, itemKey, field, code, message}]` et rien n'est "
        "écrit ; 409 `handover_changed` si la passation a changé ; 422 `handover_not_started` / `handover_window_closed` / `handover_locked`."
    ),
)
async def bulk_save_shift_handover(
    data: BulkSaveShiftHandoverRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ShiftHandoverContextResponse:
    return await shifts_passation.bulk_save_shift_handover(db, organization_id, current_user.id, data)



@router.get(
    "/shift-handover/summary",
    response_model=ShiftHandoverSummaryResponse,
    dependencies=[Depends(require_permission_scoped_via_query(SHIFT_HANDOVER_READ, _station_id_query_scope))],
    summary="Pastilles de passation de la grille du planning",
    description="Par tour de la période (31 jours max) : passation écrite / reçue, plus le nombre d'anomalies en cours de la station.",
)
async def get_shift_handover_summary(
    stationId: uuid.UUID,
    from_: date = Query(alias="from"),
    to: date = Query(),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ShiftHandoverSummaryResponse:
    return await shifts_passation.get_shift_handover_summary(db, organization_id, stationId, from_, to)



@router.post(
    "/shift-handover/{handover_id}/receive",
    response_model=ReceiveShiftHandoverResponse,
    dependencies=[Depends(require_permission_scoped_via(SHIFT_HANDOVER_MANAGE, _handover_station_scope))],
    summary="Prendre connaissance de la passation du tour précédent",
    description="Action atomique, hors du lot : enregistre la personne et l'heure (non bloquant pour la suite). 422 `no_following_shift` sans tour entrant ; 409 `already_received`.",
)
async def receive_shift_handover(
    handover_id: uuid.UUID,
    data: ReceiveShiftHandoverRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReceiveShiftHandoverResponse:
    return await shifts_passation.receive_shift_handover(db, organization_id, current_user.id, handover_id, data)



@router.post(
    "/shift-handover/items/{item_id}/close",
    response_model=CloseHandoverIssueResponse,
    dependencies=[Depends(require_permission_scoped_via(SHIFT_HANDOVER_MANAGE, _handover_item_station_scope))],
    summary="Régler une anomalie en cours",
    description="Action atomique, hors du lot : résolution obligatoire ; 409 `issue_already_closed` si elle vient d'être réglée par quelqu'un d'autre.",
)
async def close_handover_issue(
    item_id: uuid.UUID,
    data: CloseHandoverIssueRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CloseHandoverIssueResponse:
    return await shifts_passation.close_handover_issue(db, organization_id, current_user.id, item_id, data)



@router.get(
    "/shift-opening/context",
    response_model=ShiftOpeningContextResponse,
    dependencies=[Depends(require_permission_scoped_via_query(SHIFT_REPORT_READ, _station_id_query_scope))],
    summary="Lire tout ce que l'onglet « Tour du jour » affiche",
    description=(
        "Tours du jour (planifiés puis hors planning) avec leur fenêtre d'ouverture, tour ouvert éventuel, responsables de tour éligibles "
        "(nom + téléphone, jamais l'e-mail), et pour chaque pompe/cuve active la valeur à reporter calculée par le serveur."
    ),
)
async def get_shift_opening_context(
    stationId: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ShiftOpeningContextResponse:
    return await shifts_rapport.get_shift_opening_context(db, organization_id, stationId)



@router.post(
    "/shift-opening",
    response_model=ShiftReportResponse,
    status_code=201,
    dependencies=[Depends(require_permission_scoped_via_body(SHIFT_REPORT_MANAGE, _station_id_body_scope))],
    summary="Ouvrir le tour (tout-ou-rien) et créer le rapport de tour",
    description=(
        "Si une cellule est invalide : 422 `shift_opening_invalid` avec `details=[{cell, kind, id, rowNumber, field, code, message}]` et rien n'est créé ; "
        "409 `shift_already_open` / `opening_index_changed` / `opening_stock_changed` ; 422 `shift_too_early` / `shift_window_over` / `no_active_pump` / `no_active_tank`."
    ),
)
async def open_shift(
    data: OpenShiftRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ShiftReportResponse:
    return await shifts_rapport.open_shift(db, organization_id, current_user.id, data)



@router.get(
    "/shift-reports/current",
    response_model=ShiftReportResponse,
    dependencies=[Depends(require_permission_scoped_via_query(SHIFT_REPORT_READ, _station_id_query_scope))],
    summary="Tour ouvert de la station (rapport de tour)",
    description="404 `no_open_shift` si aucun tour n'est ouvert sur la station.",
)
async def get_current_shift_report(
    stationId: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ShiftReportResponse:
    return await shifts_rapport.get_current_shift_report(db, organization_id, stationId)



@router.get(
    "/shift-reports/{report_id}",
    response_model=ShiftReportResponse,
    dependencies=[Depends(require_permission_scoped_via(SHIFT_REPORT_READ, _shift_report_station_scope))],
    summary="Rapport de tour (en-tête, lignes de pompe, lignes de cuve)",
)
async def get_shift_report(
    report_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ShiftReportResponse:
    return await shifts_rapport.get_shift_report(db, organization_id, report_id)



@router.patch(
    "/shift-reports/{report_id}/pump-lines/{line_id}/opening",
    response_model=ShiftReportResponse,
    dependencies=[Depends(require_permission_scoped_via(SHIFT_REPORT_MANAGE, _shift_report_station_scope))],
    summary="Corriger l'index d'ouverture d'une ligne « initial » ou « écart » tant que le tour est ouvert",
    description="409 `shift_not_open` si le tour est clos ; 422 `line_not_correctable` pour une ligne reportée ; 422 `shift_opening_invalid` pour une valeur invalide.",
)
async def correct_pump_opening(
    report_id: uuid.UUID,
    line_id: uuid.UUID,
    data: CorrectPumpOpeningRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ShiftReportResponse:
    return await shifts_rapport.correct_pump_opening(db, organization_id, current_user.id, report_id, line_id, data)



@router.post(
    "/shift-reports/{report_id}/pump-lines",
    response_model=ShiftReportResponse,
    status_code=201,
    dependencies=[Depends(require_permission_scoped_via(SHIFT_REPORT_MANAGE, _shift_report_station_scope))],
    summary="Ajouter une pompe au tour ouvert (ligne explicite)",
    description="Pompe active absente du rapport (activée ou créée après l'ouverture) ; mêmes contrôles que l'ouverture.",
)
async def add_pump_line(
    report_id: uuid.UUID,
    data: AddPumpLineRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ShiftReportResponse:
    return await shifts_rapport.add_pump_line(db, organization_id, current_user.id, report_id, data)



@router.get(
    "/shift-reports/{report_id}/movements",
    response_model=StaffMovementsResponse,
    dependencies=[Depends(require_permission_scoped_via(SHIFT_REPLACEMENT_READ, _pump_assignment_report_scope))],
    summary="Mouvements de personnel d'un tour : journal et état courant par pompe",
    description=(
        "Journal (le plus récent en haut), titulaire actuel et chronologie de chaque pompe (litres par segment seulement si les index "
        "au changement sont connus), pauses en cours (durée écoulée, sans seuil), pompes sans pompiste, pompistes et chefs d'équipe "
        "proposables comme remplaçants (nom seulement), `assignmentVersion` à renvoyer à l'enregistrement et accès en écriture."
    ),
)
async def get_staff_movements(
    report_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StaffMovementsResponse:
    return await shifts_mouvements.get_staff_movements(db, organization_id, current_user.id, report_id)



@router.post(
    "/shift-reports/{report_id}/movements",
    response_model=StaffMovementsResponse,
    status_code=201,
    dependencies=[Depends(require_permission_scoped_via(SHIFT_REPLACEMENT_MANAGE, _pump_assignment_report_scope))],
    summary="Enregistrer un mouvement de personnel (pause, retour, remplacement, réaffectation), tout-ou-rien",
    description=(
        "Corps `{kind, occurredAt?, subjectUserId?, reason?, note?, breakStartMovementId?, rows:[{pumpId, coverUserId?, closedForBreak?, "
        "changeIndex?}], assignmentVersion?}`. Une cellule invalide : 422 `shift_replacement_invalid` avec "
        "`details=[{rowNumber, rowKey: \"pump:<id>\"|\"movement\", field, code, message}]`, rien n'est écrit. 409 `shift_not_open`, "
        "`assignment_not_confirmed`, `movement_conflict`. Renvoie la même vue que le GET."
    ),
)
async def record_staff_movement(
    report_id: uuid.UUID,
    data: RecordStaffMovementRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StaffMovementsResponse:
    return await shifts_mouvements.record_staff_movement(db, organization_id, current_user.id, report_id, data)



@router.post(
    "/shift-reports/{report_id}/movements/{movement_id}/cancel",
    response_model=StaffMovementsResponse,
    dependencies=[Depends(require_permission_scoped_via(SHIFT_REPLACEMENT_MANAGE, _pump_assignment_report_scope))],
    summary="Annuler le dernier mouvement de personnel (motif obligatoire, rien n'est supprimé)",
    description="Corps `{reason, assignmentVersion?}`. 422 `cancel_not_last` si d'autres mouvements ont suivi ; 409 `movement_already_cancelled`, `movement_conflict`.",
)
async def cancel_staff_movement(
    report_id: uuid.UUID,
    movement_id: uuid.UUID,
    data: CancelStaffMovementRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StaffMovementsResponse:
    return await shifts_mouvements.cancel_staff_movement(db, organization_id, current_user.id, report_id, movement_id, data)
