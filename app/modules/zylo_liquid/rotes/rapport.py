"""Routes des rubriques 2 à 7 du rapport de tour (D4)."""

import uuid

from fastapi import APIRouter, Depends
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.modules.zylo_liquid.permissions import REPORT_SECTIONS_MANAGE, REPORT_SECTIONS_READ
from app.modules.zylo_liquid.exploitation.schemas_rapport import ReportSectionsResponse, SaveReportSectionsRequest
from app.rbac.service import get_current_organization_id, require_permission_scoped_via
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.zylo_liquid.exploitation import rapport_rubriques as rapport_rubriques
from app.modules.zylo_liquid.scopes import _pump_assignment_report_scope

router = APIRouter()


@router.get(
    "/shift-reports/{report_id}/report-sections",
    response_model=ReportSectionsResponse,
    dependencies=[Depends(require_permission_scoped_via(REPORT_SECTIONS_READ, _pump_assignment_report_scope))],
    summary="Rubriques 2 à 7 du rapport de tour : statuts, lignes, totaux calculés, contexte de saisie",
    description=(
        "Six rubriques (2 lubrifiants, 3 gaz, 4 boutique, 5 crédits clients, 6 bons valeur, 7 paiements électroniques) avec statut "
        "(`not_started` | `saved` | `ras`), `version` à renvoyer à l'enregistrement, lignes, cumuls calculés par le serveur, `warnings` non bloquants, "
        "`totals` (contrat D5/D6) et `context` (catalogue lubrifiants et prix, ouvertures reportées, pompes du tour, comptes/plaques/chauffeurs/reste de "
        "crédit, suggestion indicative des tickets boutique). Noms seulement, jamais d'e-mail."
    ),
)
async def get_report_sections(
    report_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReportSectionsResponse:
    return await rapport_rubriques.get_report_sections(db, organization_id, current_user.id, report_id)



@router.put(
    "/shift-reports/{report_id}/report-sections",
    response_model=ReportSectionsResponse,
    dependencies=[Depends(require_permission_scoped_via(REPORT_SECTIONS_MANAGE, _pump_assignment_report_scope))],
    summary="Enregistrer tout = une ou plusieurs rubriques 2 à 7 (état final, tout-ou-rien, brouillon jusqu'à la signature)",
    description=(
        "Corps `{sections:{\"2\":{version, status (saved|ras|not_started), detailMode?, rasNote?, lines:[…], orangeBalance?, mtnBalance?, rature?:{reasonCode, "
        "reasonNote?, initialedByUserId}}, …}}`. Une cellule invalide : 422 `shift_report_sections_invalid` avec `details=[{cell:\"r<rubrique>:<ligne>:<champ>\", "
        "section, rowNumber, field, code, message}]`, rien n'est écrit (aucune rubrique du lot). 409 `report_not_open`, `shift_report_sections_version_changed`. "
        "Aucune vente ni créance n'est créée (E7)."
    ),
)
async def save_report_sections(
    report_id: uuid.UUID,
    data: SaveReportSectionsRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReportSectionsResponse:
    return await rapport_rubriques.save_report_sections(db, organization_id, current_user.id, report_id, data)
