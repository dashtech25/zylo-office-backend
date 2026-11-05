"""Routes des feature flags serveur (BE-251), domaine release.

- `GET /api/v1/internal/flags` : liste les flags, filtre optionnel par tenant.
- `PUT /api/v1/internal/flags/{flag_key}` : crée ou met à jour l'état d'un flag
  pour un tenant explicitement désigné, et trace le changement (`flag_changes`).

Les deux routes sont réservées à l'exploitation (`require_operator`) : un compte
hors de l'allowlist reçoit 403 et rien n'est écrit. La logique (canari, défaut sûr,
audit) vit dans `app.core.flags` ; ce module ne fait que transporter la requête.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.flags import FeatureFlag, modifier_flag
from app.identity.models import User
from app.operator.permissions import require_operator

router = APIRouter()


class ModifierFlagRequest(BaseModel):
    """Corps de PUT. Tous les champs sont requis : propriétaire et expiration obligatoires (CA-2)."""

    organizationId: uuid.UUID = Field(description="Tenant explicitement ciblé (portée du flag).")
    actif: bool
    proprietaireId: uuid.UUID
    expireLe: datetime


class FlagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cle: str
    organizationId: uuid.UUID = Field(validation_alias="organization_id")
    actif: bool
    defautActif: bool = Field(validation_alias="defaut_actif")
    proprietaireId: uuid.UUID = Field(validation_alias="proprietaire_id")
    expireLe: datetime = Field(validation_alias="expire_le")


@router.get("/flags", response_model=list[FlagOut])
async def lister_flags(
    organizationId: uuid.UUID | None = Query(default=None),
    _operateur: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> list[FeatureFlag]:
    """Liste les flags, éventuellement filtrés sur un tenant. Lecture seule."""
    stmt = select(FeatureFlag).order_by(FeatureFlag.cle)
    if organizationId is not None:
        stmt = stmt.where(FeatureFlag.organization_id == organizationId)
    return list((await db.execute(stmt)).scalars().all())


@router.put("/flags/{flag_key}", response_model=FlagOut)
async def modifier_flag_route(
    flag_key: str,
    body: ModifierFlagRequest,
    operateur: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> FeatureFlag:
    """Active ou désactive un flag pour un tenant ciblé ; écrit l'audit dans la même transaction."""
    flag = await modifier_flag(
        db,
        cle=flag_key,
        organization_id=body.organizationId,
        actif=body.actif,
        proprietaire_id=body.proprietaireId,
        expire_le=body.expireLe,
        acteur_id=operateur.id,
    )
    await db.commit()
    return flag
