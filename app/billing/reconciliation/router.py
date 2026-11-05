"""Route de réconciliation des paiements (BE-095).

- `POST /api/v1/billing/reconciliations` : lance une réconciliation du tenant courant. Corps :
  `{"scope": "tenant", "periodKey": str | null}`. Réponse 201 avec le run (`id`, `scope`, `periodKey`,
  `status`, `differenceCount`, `startedAt`). Erreurs : 403 `FORBIDDEN` sans permission finance.

La décision est dans app/billing/reconciliation/service.py ; la route ne fait que relayer.
L'adaptateur est fourni par `obtenir_fournisseur_reconciliation`, remplaçable par
`app.dependency_overrides` en test.
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.payment_provider import FlutterwaveTestProvider, PaymentProvider
from app.billing.reconciliation.service import lancer_reconciliation
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.guards import get_current_organization_id

router = APIRouter()


def obtenir_fournisseur_reconciliation() -> PaymentProvider:
    """Adaptateur de réconciliation. Stub sandbox (BE-028 / QE-FAC-11) tant qu'aucun PSP n'est choisi."""
    return FlutterwaveTestProvider()


class DemandeReconciliation(BaseModel):
    """Corps de la demande. Seul le périmètre `tenant` est livré ; `periodKey` est indicatif."""

    scope: Literal["tenant"] = "tenant"
    periodKey: str | None = Field(default=None, max_length=20)


class ReconciliationReponse(BaseModel):
    """Représentation d'un run de réconciliation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scope: str
    periodKey: str | None
    status: str
    differenceCount: int
    startedAt: datetime


@router.post(
    "/reconciliations",
    response_model=ReconciliationReponse,
    status_code=status.HTTP_201_CREATED,
    summary="Lancer une réconciliation des paiements et résultats incertains (BE-095)",
)
async def reconcilier(
    data: DemandeReconciliation,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    fournisseur: PaymentProvider = Depends(obtenir_fournisseur_reconciliation),
):
    """Relaie la demande au service ; le run renvoyé porte le nombre d'écarts constatés."""
    return await lancer_reconciliation(
        db,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        scope=data.scope,
        period_key=data.periodKey,
        fournisseur=fournisseur,
    )
