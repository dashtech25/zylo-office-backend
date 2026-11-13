"""Routes des incidents d'exploitation (BE-247), montées sous `/api/v1/admin`.

- `GET /api/v1/admin/incidents` : file des incidents, paginée ;
- `GET /api/v1/admin/incidents/{incident_id}` : détail et chronologie.

Garde : `require_admin_scope` (BE-120). Sans autorité plateforme : 403 (CA-4). La file
et le détail sont des vues de plateforme : une portée `tenant:<uuid>` reçoit 403, car
l'accès à un tenant ne s'obtient pas par la file d'incidents (CA-3).

Redaction (CA-3) : les schémas de réponse ne contiennent que les colonnes
d'exploitation. Le nom, le slug ou tout autre champ d'un tenant ne sont jamais
renvoyés ici ; seul l'identifiant du tenant concerné apparaît.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.operator.incidents import lire_incident, lister_incidents
from app.operator.scope import AdminScope, require_admin_scope
from app.shared.pagination import PaginationParams
from app.shared.schemas import Page, PageMeta

router = APIRouter()


class IncidentLigne(BaseModel):
    """Ligne de la file : colonnes d'exploitation uniquement (CA-3)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    severity: str
    owner: str
    state: str
    occurredAt: datetime
    tenantId: uuid.UUID | None


class EvenementChronologie(BaseModel):
    """Entrée de chronologie, dans l'ordre de `sequence`."""

    model_config = ConfigDict(from_attributes=True)

    sequence: int
    eventType: str
    summary: str
    occurredAt: datetime
    actorUserId: uuid.UUID | None


class IncidentDetail(IncidentLigne):
    """Détail d'un incident avec sa chronologie complète."""

    chronologie: list[EvenementChronologie]


def _exiger_portee_plateforme(scope: AdminScope) -> None:
    """Refuse en 403 toute portée tenant : la file d'incidents n'est pas une vue tenant."""
    if not scope.is_platform:
        raise AppError(
            code="admin_scope_denied",
            message="Accès d'administration refusé pour cette portée.",
            status_code=403,
        )


@router.get("/incidents", response_model=Page[IncidentLigne], summary="File des incidents d'exploitation")
async def list_incidents(
    pagination: PaginationParams = Depends(),
    scope: AdminScope = Depends(require_admin_scope),
    db: AsyncSession = Depends(get_db),
) -> Page:
    """Incidents du plus récent au plus ancien, avec `limit`/`offset` et total."""
    _exiger_portee_plateforme(scope)
    lignes, total = await lister_incidents(db, limit=pagination.limit, offset=pagination.offset)
    return Page(
        data=[IncidentLigne.model_validate(ligne) for ligne in lignes],
        meta=PageMeta(total=total, limit=pagination.limit, offset=pagination.offset),
    )


@router.get(
    "/incidents/{incident_id}",
    response_model=IncidentDetail,
    summary="Détail d'un incident et sa chronologie",
)
async def get_incident(
    incident_id: uuid.UUID,
    scope: AdminScope = Depends(require_admin_scope),
    db: AsyncSession = Depends(get_db),
) -> IncidentDetail:
    """Incident, propriétaire, état, horodatage et chronologie ordonnée (CA-1, CA-2)."""
    _exiger_portee_plateforme(scope)
    incident, evenements = await lire_incident(db, incident_id)
    return IncidentDetail(
        **IncidentLigne.model_validate(incident).model_dump(),
        chronologie=[EvenementChronologie.model_validate(evenement) for evenement in evenements],
    )
