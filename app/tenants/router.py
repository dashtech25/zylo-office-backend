"""Routes du cycle de vie du tenant (BE-185), montées sous `/api/v1/tenants`.

Routes :
- `POST /api/v1/tenants` : demande de création, 201 (droit `platform.tenant.manage`) ;
- `GET /api/v1/tenants/{tenant_id}` : lecture, 200 (plateforme, ou membre d'un tenant non fermé) ;
- `POST /api/v1/tenants/{tenant_id}/transitions` : transition, 200 (droit `platform.tenant.manage`).

Erreurs : 401 sans session ; 403 sans droit plateforme ; 404 tenant introuvable
(ou non visible) ; 409 `version_conflict` ou slug déjà pris ; 422 transition hors
graphe. La transaction est validée ici, après succès ; `get_db` ne commit pas seul.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.tenants import service
from app.tenants.schemas import CreerTenantRequest, TenantResponse, TransitionTenantRequest

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post("", response_model=TenantResponse, status_code=201, summary="Demande la création d'un tenant")
async def creer_tenant(
    corps: CreerTenantRequest,
    db: AsyncSession = Depends(get_db),
    utilisateur: User = Depends(get_current_user),
) -> TenantResponse:
    """Crée un tenant en `requested`. Droit : `platform.tenant.manage`."""
    tenant = await service.creer_tenant(db, utilisateur.id, corps.slug)
    await db.commit()
    return TenantResponse.model_validate(tenant)


@router.get("/{tenant_id}", response_model=TenantResponse, summary="Lit un tenant")
async def lire_tenant(
    tenant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    utilisateur: User = Depends(get_current_user),
) -> TenantResponse:
    """Lit un tenant. Un membre ne voit pas un tenant fermé ; un autre utilisateur reçoit 404."""
    tenant = await service.lire_tenant(db, utilisateur.id, tenant_id)
    return TenantResponse.model_validate(tenant)


@router.post(
    "/{tenant_id}/transitions",
    response_model=TenantResponse,
    summary="Fait passer un tenant à un nouvel état du cycle de vie",
)
async def transitionner_tenant(
    tenant_id: uuid.UUID,
    corps: TransitionTenantRequest,
    db: AsyncSession = Depends(get_db),
    utilisateur: User = Depends(get_current_user),
) -> TenantResponse:
    """Applique une transition si `expectedVersion` est la version courante et si le graphe la permet."""
    tenant = await service.transitionner(db, utilisateur.id, tenant_id, corps.targetState, corps.expectedVersion)
    await db.commit()
    return TenantResponse.model_validate(tenant)
