"""Journal des transitions de modules d'une organisation (BE-056).

Route : `GET /api/v1/organizations/{organization_id}/module-audit`, filtres `from`, `to`, `moduleId`
et pagination `limit`/`offset`.

Contrat :
- l'organisation du chemin doit être identique à l'en-tête `X-Organization-Id` ; un écart, une
  organisation étrangère ou sans appartenance active répond 404 `organization_not_found`
  (même erreur uniforme que le reste du socle, aucune énumération) ;
- permission : `organization.audit.read` (app/audit/permissions.py). Membre sans elle : 403 ;
- seules les lignes de cette organisation sont lues (partition tenant stricte) ;
- seuls les événements de module (`eventName` renseigné) sont renvoyés ;
- `moduleId` restreint aux événements dont le scope est ce module, dans cette organisation.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.audit.permissions import ORGANIZATION_AUDIT_READ
from app.core.database import get_db
from app.modules_registry.schemas import ModuleAuditEventResponse
from app.rbac.guards import get_current_organization_id, organisation_introuvable
from app.rbac.service import require_permission
from app.shared.pagination import PaginationParams
from app.shared.schemas import Page, PageMeta

router = APIRouter()


@router.get(
    "/{organization_id}/module-audit",
    response_model=Page[ModuleAuditEventResponse],
    dependencies=[Depends(require_permission(ORGANIZATION_AUDIT_READ))],
    summary="Journal des transitions de modules de l'organisation (BE-056)",
)
async def list_module_audit(
    organization_id: uuid.UUID,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    moduleId: uuid.UUID | None = None,
    pagination: PaginationParams = Depends(),
    header_organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    """Événements de transition de modules de l'organisation du chemin, les plus récents d'abord.

    `header_organization_id` valide l'appartenance active (404 sinon) avant la permission (403).
    Un chemin différent de l'en-tête est traité comme une organisation introuvable.
    """
    if organization_id != header_organization_id:
        raise organisation_introuvable()

    filtres = [AuditEvent.organizationId == organization_id, AuditEvent.eventName.is_not(None)]
    if from_ is not None:
        filtres.append(AuditEvent.createdAt >= from_)
    if to is not None:
        filtres.append(AuditEvent.createdAt <= to)
    if moduleId is not None:
        filtres.append(AuditEvent.scopeResourceType == "module")
        filtres.append(AuditEvent.scopeResourceId == moduleId)

    total = (await db.execute(select(func.count()).select_from(AuditEvent).where(*filtres))).scalar_one()
    lignes = (
        await db.execute(
            select(AuditEvent)
            .where(*filtres)
            .order_by(AuditEvent.createdAt.desc(), AuditEvent.id.desc())
            .limit(pagination.limit)
            .offset(pagination.offset)
        )
    ).scalars().all()
    return Page(
        data=[ModuleAuditEventResponse.from_evenement(ligne) for ligne in lignes],
        meta=PageMeta(total=total, limit=pagination.limit, offset=pagination.offset),
    )
