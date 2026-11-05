"""Routes d'escalade et de clôture d'escalade (BE-142), montées sous `/api/v1/admin`.

Routes :
- `POST /api/v1/admin/cases/{case_id}/escalations` : ouvre une escalade sur un cas
  (rôle L1 ou L2 sur la portée du cas) et passe le cas à `escalade` ;
- `POST /api/v1/admin/escalations/{escalation_id}/close` : clôt une escalade
  (responsable de gestion de la portée du cas seulement).

Codes d'erreur : 422 pour un corps invalide (niveau hors 1 à 3, rôle cible inconnu) ;
403 `admin_scope_denied` pour un refus de droit ; 404 `case_not_found` ou
`escalation_not_found` ; 409 `case_closed` (ouverture sur cas clos) ou
`escalation_closed` (seconde clôture).

Chaque ouverture et chaque clôture écrit son entrée d'audit dans la même transaction
que la transition. La corrélation est celle de la requête (BE-122).
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import request_id_ctx
from app.core.security import get_current_user
from app.identity.models import User
from app.operator.cases import charger_cas
from app.operator.escalation import (
    NIVEAU_MAX,
    NIVEAU_MIN,
    Escalation,
    charger_escalade,
    cloturer_escalade,
    ouvrir_escalade,
)
from app.rbac.role_assignments import ROLES_CANDIDATS

router = APIRouter()


class EscaladeCreate(BaseModel):
    """Corps d'ouverture : niveau (1 à 3, QE-ADM-12) et rôle cible."""

    level: int = Field(ge=NIVEAU_MIN, le=NIVEAU_MAX)
    targetRole: str = Field(min_length=1, max_length=64)

    @field_validator("targetRole")
    @classmethod
    def _role_connu(cls, valeur: str) -> str:
        """Le rôle cible appartient au vocabulaire d'administration de BE-121."""
        if valeur not in ROLES_CANDIDATS:
            raise ValueError("rôle d'administration inconnu")
        return valeur


class EscaladeCloture(BaseModel):
    """Corps de clôture : motif obligatoire."""

    closureReason: str = Field(min_length=1, max_length=500)


class EscaladeResponse(BaseModel):
    """Représentation d'une escalade."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    caseId: uuid.UUID
    level: int
    targetRole: str
    openedAtUtc: datetime
    closedAtUtc: datetime | None
    closureReason: str | None


def _correlation() -> str | None:
    return request_id_ctx.get()


@router.post(
    "/cases/{case_id}/escalations",
    response_model=EscaladeResponse,
    status_code=201,
    summary="Ouvrir une escalade sur un cas d'intervention (BE-142)",
)
async def ouvrir_escalade_cas(
    case_id: uuid.UUID,
    data: EscaladeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Escalation:
    """Ouvre l'escalade, fait passer le cas à `escalade`, puis valide la transaction.

    Le droit s'évalue sur la portée du cas (CA-3) ; un agent L1 ou L2 de cette portée
    peut ouvrir (CA-2)."""
    cas = await charger_cas(db, case_id)
    escalade = await ouvrir_escalade(
        db,
        cas=cas,
        acteur_id=current_user.id,
        niveau=data.level,
        cible=data.targetRole,
        correlation_id=_correlation(),
    )
    await db.commit()
    return escalade


@router.post(
    "/escalations/{escalation_id}/close",
    response_model=EscaladeResponse,
    summary="Clôturer une escalade (BE-142)",
)
async def cloturer_escalade_admin(
    escalation_id: uuid.UUID,
    data: EscaladeCloture,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Escalation:
    """Clôt l'escalade ; réservé au responsable de gestion de la portée du cas (CA-1)."""
    escalade = await charger_escalade(db, escalation_id)
    await cloturer_escalade(
        db,
        escalade=escalade,
        acteur_id=current_user.id,
        motif=data.closureReason,
        correlation_id=_correlation(),
    )
    await db.commit()
    return escalade
