"""Service du module Zylo Tanker — CRUD minimal de `Vessel`, même patron
que `create_truck`/`list_trucks` (`app/modules/zylo_liquid/service.py`) :
`_check_org_scope` local (même convention dupliquée dans chaque module
plutôt que partagée, voir zylo_liquid/location/alerts), `Page`/`PageMeta`
pour la liste paginée."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.zylo_tanker.models import Vessel
from app.modules.zylo_tanker.permissions import VESSEL_MANAGE, VESSEL_READ
from app.modules.zylo_tanker.schemas import CreateVesselRequest, SetVesselDestinationRequest, VesselResponse
from app.rbac.service import user_has_permission
from app.shared.pagination import PaginationParams
from app.shared.schemas import Page, PageMeta


async def _check_org_scope(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, permission_code: str) -> None:
    allowed = await user_has_permission(db, actor_user_id, organization_id, permission_code)
    if not allowed:
        raise AppError(code="permission_denied", message=f"Permission manquante : {permission_code}.", status_code=403)


async def _ensure_vessel_code_available(db: AsyncSession, organization_id: uuid.UUID, code: str) -> None:
    stmt = select(Vessel.id).where(Vessel.organizationId == organization_id, Vessel.code == code)
    if (await db.execute(stmt)).scalar_one_or_none() is not None:
        raise AppError(
            code="vessel_code_already_used",
            message=f"Un navire avec le code '{code}' existe déjà pour cette organisation.",
            status_code=409,
        )


async def create_vessel(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: CreateVesselRequest) -> VesselResponse:
    await _check_org_scope(db, organization_id, actor_user_id, VESSEL_MANAGE)
    await _ensure_vessel_code_available(db, organization_id, data.code)
    instance = Vessel(organizationId=organization_id, name=data.name, code=data.code)
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return VesselResponse.model_validate(instance)


async def get_vessel(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, vessel_id: uuid.UUID) -> VesselResponse:
    await _check_org_scope(db, organization_id, actor_user_id, VESSEL_READ)
    vessel = await db.get(Vessel, vessel_id)
    if vessel is None or vessel.organizationId != organization_id:
        raise AppError(code="vessel_not_found", message="Navire introuvable.", status_code=404)
    return VesselResponse.model_validate(vessel)


async def list_vessels(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: PaginationParams) -> Page:
    await _check_org_scope(db, organization_id, actor_user_id, VESSEL_READ)
    stmt = select(Vessel).where(Vessel.organizationId == organization_id).order_by(Vessel.name)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    rows = result.scalars().all()
    return Page(data=[VesselResponse.model_validate(r) for r in rows], meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset))


async def _get_vessel_or_404(db: AsyncSession, organization_id: uuid.UUID, vessel_id: uuid.UUID) -> Vessel:
    vessel = await db.get(Vessel, vessel_id)
    if vessel is None or vessel.organizationId != organization_id:
        raise AppError(code="vessel_not_found", message="Navire introuvable.", status_code=404)
    return vessel


async def set_vessel_destination(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, vessel_id: uuid.UUID, latitude: float, longitude: float, label: str | None = None,
) -> VesselResponse:
    """Fixe (ou remplace) la destination du navire — les quatre colonnes
    sont toujours écrites ensemble, `destinationSetAt` toujours horodaté
    par le serveur (jamais fourni par le client, voir
    `SetVesselDestinationRequest`). Consommée par
    `app.location.service.list_vessel_current_positions` pour le calcul
    d'ETA — jamais recalculée ailleurs."""
    await _check_org_scope(db, organization_id, actor_user_id, VESSEL_MANAGE)
    vessel = await _get_vessel_or_404(db, organization_id, vessel_id)
    vessel.destinationLatitude = latitude
    vessel.destinationLongitude = longitude
    vessel.destinationLabel = label
    vessel.destinationSetAt = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    await db.refresh(vessel)
    return VesselResponse.model_validate(vessel)


async def clear_vessel_destination(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, vessel_id: uuid.UUID) -> VesselResponse:
    """Efface la destination du navire — les quatre colonnes reviennent à
    `None` ensemble (jamais une valeur orpheline, ex. un label sans
    coordonnées)."""
    await _check_org_scope(db, organization_id, actor_user_id, VESSEL_MANAGE)
    vessel = await _get_vessel_or_404(db, organization_id, vessel_id)
    vessel.destinationLatitude = None
    vessel.destinationLongitude = None
    vessel.destinationLabel = None
    vessel.destinationSetAt = None
    await db.commit()
    await db.refresh(vessel)
    return VesselResponse.model_validate(vessel)
