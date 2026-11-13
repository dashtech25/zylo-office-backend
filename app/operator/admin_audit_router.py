"""Journal d'audit administratif en lecture seule (BE-122), monté sous `/api/v1/admin`.

Route : `GET /api/v1/admin/audit-events`.

Garde : `require_admin_scope` (BE-120). Sans autorité plateforme : 403 ; portée
tenant sans affectation au tenant : 403 (jamais de liste partielle).

Portée : sans en-tête `X-Admin-Scope` (ou `platform`), seules les entrées sans
organisation sont renvoyées : la portée plateforme ne donne jamais accès au contenu
d'un tenant (BE-120 CA-2). Avec `tenant:<uuid>`, seules les entrées de ce tenant.

Lecture seule : PUT, PATCH et DELETE sur cette route reçoivent 405 (CA-3). Une
correction passe par une nouvelle entrée (`app.audit.admin_audit.enregistrer_correction`).
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.audit.schemas import AuditLogResponse
from app.core.database import get_db
from app.operator.scope import AdminScope, require_admin_scope
from app.shared.pagination import PaginationParams
from app.shared.schemas import Page, PageMeta

router = APIRouter()


@router.get(
    "/audit-events",
    response_model=Page[AuditLogResponse],
    summary="Consulter le journal d'audit administratif (lecture seule)",
)
async def list_admin_audit_events(
    pagination: PaginationParams = Depends(),
    scope: AdminScope = Depends(require_admin_scope),
    db: AsyncSession = Depends(get_db),
) -> Page:
    """Entrées de `audit_event` selon la portée validée par `require_admin_scope`.

    Plateforme : `organizationId` nul. Tenant : `organizationId` égal au tenant
    de la portée. Tri par date décroissante, pagination `limit`/`offset`."""
    if scope.is_platform:
        stmt = select(AuditEvent).where(AuditEvent.organizationId.is_(None))
    else:
        stmt = select(AuditEvent).where(AuditEvent.organizationId == scope.organization_id)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.order_by(AuditEvent.createdAt.desc()).limit(pagination.limit).offset(pagination.offset))
    rows = result.scalars().all()
    return Page(
        data=[AuditLogResponse.model_validate(row) for row in rows],
        meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset),
    )
