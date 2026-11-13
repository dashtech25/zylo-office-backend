"""Routes de la caisse par pompiste (D3) et du calcul de caisse A à H / NOTA (D5)."""

import uuid

from fastapi import APIRouter, Depends
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.modules.zylo_liquid.exploitation.schemas_caisse import CashSummaryReportResponse, ClosingCashResponse, SaveCashAdjustmentsRequest, SaveClosingCashRequest
from app.modules.zylo_liquid.permissions import CASH_COLLECTION_MANAGE, CASH_COLLECTION_READ, CASH_SUMMARY_MANAGE, CASH_SUMMARY_READ
from app.rbac.service import get_current_organization_id, require_permission_scoped_via
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.zylo_liquid.exploitation import caisse_calcul as caisse_calcul
from app.modules.zylo_liquid.exploitation import caisse_collecte as caisse_collecte
from app.modules.zylo_liquid.scopes import _pump_assignment_report_scope

router = APIRouter()


@router.get(
    "/shift-reports/{report_id}/closing-cash",
    response_model=ClosingCashResponse,
    dependencies=[Depends(require_permission_scoped_via(CASH_COLLECTION_READ, _pump_assignment_report_scope))],
    summary="Caisse par pompiste d'un tour : ventes attribuées, déductions, théorique, remis, écart signé, NOTA",
    description=(
        "Une ligne par personne ayant tenu au moins une pompe (pompes tenues, litres et valeur attribués, déductions, théorique, "
        "comptage pompiste et RT, remis, écart signé, état « à recalculer »), pompes partagées et leur répartition, `summary` "
        "(F = `totalRemitted`, somme des théoriques, NOTA et `notaSum`, écarts de groupe) et `cashVersion` à renvoyer à l'enregistrement. "
        "Un montant non calculable est nul (« non calculé »), jamais estimé."
    ),
)
async def get_closing_cash(
    report_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClosingCashResponse:
    return await caisse_collecte.get_closing_cash(db, organization_id, current_user.id, report_id)



@router.put(
    "/shift-reports/{report_id}/closing-cash",
    response_model=ClosingCashResponse,
    dependencies=[Depends(require_permission_scoped_via(CASH_COLLECTION_MANAGE, _pump_assignment_report_scope))],
    summary="Enregistrer tout = comptage et remise de caisse de tous les pompistes (état final, tout-ou-rien)",
    description=(
        "Corps `{cashVersion, lines:[{userId, creditVouchersAmount, mobilePaymentsAmount, otherDeductionsAmount, otherDeductionsNote?, "
        "attendantCountedAmount, managerRecountedAmount, documentsHandedOver, note?, rature?:{reasonCode, reasonNote?, initialedByUserId}}], "
        "pumpShares:[{pumpLineId, shares:[{userId, litersShare}], reason}], confirmedNoDeductions:[userId]}`. Une cellule invalide : 422 "
        "`cash_collection_invalid` avec `details=[{rowNumber, rowKey: \"user:<id>\"|\"pump:<lineId>\", field, code, message}]`, rien n'est écrit. "
        "409 `report_not_open`, `assignment_not_confirmed`, `closing_not_recorded`, `cash_version_changed`."
    ),
)
async def save_closing_cash(
    report_id: uuid.UUID,
    data: SaveClosingCashRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClosingCashResponse:
    return await caisse_collecte.save_closing_cash(db, organization_id, current_user.id, report_id, data)



@router.get(
    "/shift-reports/{report_id}/cash-summary",
    response_model=CashSummaryReportResponse,
    dependencies=[Depends(require_permission_scoped_via(CASH_SUMMARY_READ, _pump_assignment_report_scope))],
    summary="Caisse d'un tour : A à H, dépenses diverses, VAL/CCT, NOTA et comparaison à l'écart de caisse (recalculés à chaque lecture)",
    description=(
        "Le serveur recalcule tout à la demande (rien n'est stocké comme vérité) : A (rubriques 1 à 4), B (5 à 7), C = A − B, dépenses "
        "diverses, D (VAL/CCT), E = C − dépenses + D, F (espèces remises, D3), H = F − E, NOTA (écarts par pompiste D3) et sa différence "
        "avec H (tolérance 1,00 FCFA). Une valeur dont une source manque est nulle (« non disponible ») avec la cause. `assumptions` "
        "renvoie les formules et règles appliquées ; `inputsVersion` est à renvoyer à l'enregistrement."
    ),
)
async def get_cash_summary_endpoint(
    report_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CashSummaryReportResponse:
    return await caisse_calcul.get_cash_summary_view(db, organization_id, current_user.id, report_id)



@router.put(
    "/shift-reports/{report_id}/cash-adjustments",
    response_model=CashSummaryReportResponse,
    dependencies=[Depends(require_permission_scoped_via(CASH_SUMMARY_MANAGE, _pump_assignment_report_scope))],
    summary="Enregistrer tout = dépenses diverses, règlements VAL/CCT et règle de déduction (état final, tout-ou-rien)",
    description=(
        "Corps `{inputsVersion, deductRetainedSales, deductRetainedSalesNote?, expenses:[{label, amount, receiptReference?, note?}], "
        "settlements:[{commercialAccountId?, payerLabel?, amount, mode, reference, paymentId?}]}`. Le client n'envoie jamais A à H ni le NOTA "
        "(ignorés). Une cellule invalide : 422 `cash_summary_invalid` avec `details=[{rowNumber, rowKey, key, field, code, message}]`, rien n'est "
        "écrit. 409 `report_not_open`, `cash_inputs_version_changed`. Renvoie le calcul complet recalculé."
    ),
)
async def save_cash_adjustments_endpoint(
    report_id: uuid.UUID,
    data: SaveCashAdjustmentsRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CashSummaryReportResponse:
    return await caisse_calcul.save_cash_adjustments(db, organization_id, current_user.id, report_id, data)
