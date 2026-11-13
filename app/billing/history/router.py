"""Route de lecture de l'historique commercial (BE-099).

`GET /api/v1/billing/history` (montée sous `/billing`, app/api/v1/router.py) : page des entrées
`billing.*` du tenant courant (en-tête `X-Organization-Id`, garde `get_current_organization_id`).
Paramètres : `limit`, `offset` (pagination standard), `scope` (filtre optionnel).

Réponses :
- 200 : `Page[BillingHistoryEntryResponse]` ;
- 403 `FORBIDDEN` sans `billing.history.read` ;
- 404 `organization_not_found` si le demandeur n'appartient pas au tenant (garde, sans donnée).

Chaque entrée ne porte que des colonnes de résumé : identifiant, action, résumé pré-rendu,
type et identifiant de cible, périmètre, résultat, motif, acteur, date. Le détail `changes`
(états avant et après) et les métadonnées de requête (IP, user-agent) ne sont jamais renvoyés.
La logique est dans app/billing/history/service.py.
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.history import service
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.guards import get_current_organization_id
from app.shared.pagination import PaginationParams
from app.shared.schemas import Page, PageMeta

router = APIRouter()


class BillingHistoryEntryResponse(BaseModel):
    """Une entrée d'historique, sans le détail `changes` ni les métadonnées de requête (CA-4)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action: str
    summary: str
    entityType: str
    entityId: uuid.UUID | None
    scopeResourceType: str | None
    result: str
    reason: str | None
    actorUserId: uuid.UUID
    createdAt: datetime


@router.get(
    "/history",
    response_model=Page[BillingHistoryEntryResponse],
    summary="Lister l'historique commercial du tenant courant (BE-099)",
)
async def lister_historique(
    scope: Literal["payeur", "tenant", "beneficiaire"] | None = Query(None),
    pagination: PaginationParams = Depends(),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Entrées `billing.*` du tenant, les plus récentes d'abord. Le tenant ne vient jamais du client
    autre que l'en-tête validé par la garde ; un paramètre `organizationId` éventuel est ignoré."""
    lignes, total = await service.lister_historique(
        db,
        tenant_id=organization_id,
        demandeur_id=current_user.id,
        scope=scope,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    return Page(
        data=[BillingHistoryEntryResponse.model_validate(ligne) for ligne in lignes],
        meta=PageMeta(total=total, limit=pagination.limit, offset=pagination.offset),
    )
