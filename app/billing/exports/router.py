"""Route de demande d'export des données de facturation (BE-098).

`POST /api/v1/billing/data-exports` (corps `DataExportCreate`) : demande l'export d'un compte
payeur dans l'organisation courante (en-tête `X-Organization-Id`, garde
`get_current_organization_id`). 201 avec la demande et le contenu ; 403 `FORBIDDEN` sans
permission ; 403 `SCOPE_MISMATCH` pour un compte hors tenant. La logique est dans
app/billing/exports/service.py.
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.exports import service
from app.billing.schemas import DataExportCreate, DataExportResponse
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.guards import get_current_organization_id

router = APIRouter()


@router.post(
    "/data-exports",
    response_model=DataExportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Demander un export des données de facturation (BE-098)",
)
async def demander_export(
    payload: DataExportCreate,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Crée la demande et renvoie son contenu ; aucune écriture en cas de refus."""
    demande, contenu = await service.demander_export(
        db,
        tenant_id=organization_id,
        demandeur_id=current_user.id,
        account_id=payload.accountId,
        scope=payload.scope,
    )
    return DataExportResponse(
        id=demande.id,
        scope=demande.scope,
        status=demande.status,
        requestedAt=demande.requestedAt,
        fileRef=demande.fileRef,
        content=contenu,
    )
