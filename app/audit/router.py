import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service
from app.audit.schemas import AuditLogResponse
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.identity.service import require_organization_member
from app.shared.pagination import PaginationParams
from app.shared.schemas import Page, PageMeta

router = APIRouter()


@router.get(
    "/organizations/{organization_id}",
    response_model=Page[AuditLogResponse],
    dependencies=[Depends(require_organization_member)],
)
async def list_audit_logs(
    organization_id: uuid.UUID,
    actionPrefix: str | None = None,
    scopeResourceType: str | None = None,
    scopeResourceId: uuid.UUID | None = None,
    actorUserId: uuid.UUID | None = None,
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page:
    """Filtré automatiquement selon la portée que possède l'utilisateur sur
    `audit.log.view` (§17) — un propriétaire voit tout, un gérant de station
    ne voit que les évènements de ses stations autorisées, un utilisateur
    sans la permission reçoit un 403 explicite plutôt qu'une liste vide
    silencieuse. `scopeResourceType`/`scopeResourceId` (Centre administratif
    et opérationnel de la station, domaine « Historique ») filtrent en plus
    sur une entité précise, ex. `station`/<stationId>. `actorUserId` (module
    Personnel, activité récente d'une fiche membre) filtre sur l'auteur —
    jamais un contournement de la restriction de portée ci-dessus."""
    rows, total = await service.list_audit_logs(
        db, organization_id, current_user.id, actionPrefix, pagination.limit, pagination.offset,
        scope_resource_type=scopeResourceType, scope_resource_id=scopeResourceId, actor_user_id=actorUserId,
    )
    return Page(
        data=[AuditLogResponse.model_validate(row) for row in rows],
        meta=PageMeta(total=total, limit=pagination.limit, offset=pagination.offset),
    )
