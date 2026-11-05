"""Console plateforme de réconciliation (BE-052), montée sous `/api/v1/admin/reconciliations`.

Routes :
- `GET /reconciliations?state=open` : liste les cas dans un état (droit `platform.reconciliation.resolve`), 200 ;
- `POST /reconciliations/{reconciliationId}/resolve` : résout un cas avec une décision et une preuve
  (même droit), 200 ; 422 sans `evidenceReference` (CA-4), 403 sans droit (CA-3), 404 inconnu, 409 déjà traité.

Le droit est vérifié avant toute lecture ou écriture (refus par défaut). Le routeur valide la transaction
après succès : `get_db` ne commit pas seul.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.modules_registry import reconciliation as service
from app.modules_registry.permissions import PLATFORM_RECONCILIATION_RESOLVE
from app.modules_registry.platform_rights import exiger_droit_plateforme
from app.modules_registry.models import ETATS_RECONCILIATION

router = APIRouter(prefix="/reconciliations", tags=["admin-reconciliation"])


class ResolutionReconciliationRequest(BaseModel):
    """Corps de la résolution. `evidenceReference` est vérifié par le service (422 si vide)."""

    resolution: str
    evidenceReference: str | None = None


class ReconciliationResponse(BaseModel):
    """Cas de réconciliation vu par la console plateforme."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    subjectType: str
    subjectId: uuid.UUID
    organizationId: uuid.UUID
    state: str
    sourceA: str
    sourceB: str
    openedAt: datetime
    resolution: str | None
    resolvedBy: uuid.UUID | None
    resolvedAt: datetime | None
    evidenceReference: str | None


@router.get("", response_model=list[ReconciliationResponse], summary="Liste les cas de réconciliation par état")
async def lister_reconciliations(
    state: str = Query("open", description=f"État demandé : {', '.join(ETATS_RECONCILIATION)}."),
    db: AsyncSession = Depends(get_db),
    utilisateur: User = Depends(get_current_user),
) -> list[ReconciliationResponse]:
    """Liste les cas de réconciliation filtrés par état (paramètre `state`, défaut `open`). Un état hors liste répond 422.
    """
    exiger_droit_plateforme(utilisateur.id, PLATFORM_RECONCILIATION_RESOLVE)
    cas = await service.lister_cas(db, state)
    return [ReconciliationResponse.model_validate(item) for item in cas]


@router.post(
    "/{reconciliation_id}/resolve",
    response_model=ReconciliationResponse,
    summary="Résout un cas de réconciliation avec une preuve",
)
async def resoudre_reconciliation(
    reconciliation_id: uuid.UUID,
    corps: ResolutionReconciliationRequest,
    db: AsyncSession = Depends(get_db),
    utilisateur: User = Depends(get_current_user),
) -> ReconciliationResponse:
    """Résout un cas de réconciliation avec une preuve. La preuve est obligatoire ; un cas déjà résolu répond 409.
    """
    exiger_droit_plateforme(utilisateur.id, PLATFORM_RECONCILIATION_RESOLVE)
    cas = await service.resoudre_cas(
        db,
        reconciliation_id=reconciliation_id,
        resolution=corps.resolution,
        evidence_reference=corps.evidenceReference,
        actor_user_id=utilisateur.id,
    )
    await db.commit()
    return ReconciliationResponse.model_validate(cas)
