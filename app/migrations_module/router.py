"""Routes pour les migrations (BE-198)."""

import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.migrations_module import service
from app.migrations_module.schemas import MigrationRunRequest, MigrationRunResponse

router = APIRouter(prefix="/api/v1/admin/migrations", tags=["migrations"])


@router.post("/{migration_id}/dry-run", response_model=MigrationRunResponse)
async def dry_run(
    migration_id: uuid.UUID,
    request: MigrationRunRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> MigrationRunResponse:
    """Lance un dry-run d'une migration."""
    try:
        result = await service.dry_run_migration(migration_id, request.tenantId, user_id)
        return MigrationRunResponse(state=result["state"], checkpoint=result.get("checkpoint", 0))
    except ValueError as exc:
        error_msg = str(exc)
        if "Droit" in error_msg:
            raise HTTPException(status_code=403, detail=error_msg) from exc
        if "inactif" in error_msg:
            raise HTTPException(status_code=422, detail=error_msg) from exc
        raise HTTPException(status_code=500, detail=error_msg) from exc


@router.post("/{migration_id}/run", response_model=MigrationRunResponse)
async def run(
    migration_id: uuid.UUID,
    request: MigrationRunRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> MigrationRunResponse:
    """Lance une migration."""
    try:
        result = await service.run_migration(migration_id, request.tenantId, user_id)
        return MigrationRunResponse(state=result["state"], checkpoint=result.get("checkpoint", 0))
    except ValueError as exc:
        error_msg = str(exc)
        if "Droit" in error_msg:
            raise HTTPException(status_code=403, detail=error_msg) from exc
        if "inactif" in error_msg:
            raise HTTPException(status_code=422, detail=error_msg) from exc
        raise HTTPException(status_code=500, detail=error_msg) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{migration_id}/resume", response_model=MigrationRunResponse)
async def resume(
    migration_id: uuid.UUID,
    request: MigrationRunRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> MigrationRunResponse:
    """Reprend une migration."""
    try:
        result = await service.resume_migration(migration_id, request.tenantId, user_id)
        return MigrationRunResponse(state=result["state"], checkpoint=result.get("checkpoint", 0))
    except ValueError as exc:
        error_msg = str(exc)
        if "Droit" in error_msg:
            raise HTTPException(status_code=403, detail=error_msg) from exc
        if "inactif" in error_msg:
            raise HTTPException(status_code=422, detail=error_msg) from exc
        raise HTTPException(status_code=500, detail=error_msg) from exc


@router.post("/{migration_id}/rollback", response_model=MigrationRunResponse)
async def rollback(
    migration_id: uuid.UUID,
    request: MigrationRunRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> MigrationRunResponse:
    """Annule une migration."""
    try:
        result = await service.rollback_migration(migration_id, request.tenantId, user_id)
        return MigrationRunResponse(state=result["state"], checkpoint=result.get("checkpoint", 0))
    except ValueError as exc:
        error_msg = str(exc)
        if "Droit" in error_msg:
            raise HTTPException(status_code=403, detail=error_msg) from exc
        if "inactif" in error_msg:
            raise HTTPException(status_code=422, detail=error_msg) from exc
        if "Rollback refusé" in error_msg:
            raise HTTPException(status_code=409, detail=error_msg) from exc
        raise HTTPException(status_code=500, detail=error_msg) from exc
