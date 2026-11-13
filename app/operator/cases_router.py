"""Routes des cas d'intervention (BE-123), montées sous `/api/v1/admin`.

Routes :
- `POST /api/v1/admin/cases` : ouvre un cas (rôle L1 ou L2 sur la portée du cas) ;
- `GET /api/v1/admin/cases/{case_id}` : lit un cas (lecture limitée, voir
  `app.operator.cases.exiger_lecture`) ;
- `POST /api/v1/admin/cases/{case_id}/assign` : affecte le cas à un compte
  (responsable de gestion seulement) ;
- `POST /api/v1/admin/cases/{case_id}/close` : clôt le cas (responsable de gestion
  seulement, et vérification enregistrée requise).

Chaque transition écrit une entrée d'audit (CA-5) dans la même transaction que la
transition ; sans identifiant de corrélation, rien n'est écrit (BE-122 CA-1).

Codes d'erreur : 422 pour un corps invalide (priorité hors enum, par exemple) ;
403 `admin_scope_denied` pour un refus de droit ; 404 `case_not_found` pour un cas
inconnu ; 409 pour une transition impossible (cas déjà clos, clôture sans
vérification enregistrée).
"""

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.admin_audit import ecrire_evenement_admin
from app.core.database import get_db
from app.core.errors import AppError
from app.core.logging import request_id_ctx
from app.core.security import get_current_user
from app.identity.models import User
from app.operator.cases import (
    ACTION_AFFECTATION,
    ACTION_CLOTURE,
    ACTION_OUVERTURE,
    TYPE_ENTITE_CAS,
    InterventionCase,
    charger_cas,
    exiger_gestion,
    exiger_lecture,
    exiger_ouverture,
    verification_enregistree,
)

router = APIRouter()


class CasCreate(BaseModel):
    """Corps d'ouverture. `tenantId` NULL désigne un cas de plateforme."""

    tenantId: uuid.UUID | None = None
    priority: Literal["basse", "normale", "haute"]
    qualification: str = Field(min_length=1, max_length=200)
    consentRef: str | None = Field(default=None, max_length=120)


class CasAffectation(BaseModel):
    """Corps d'affectation : le compte qui prend le cas en charge."""

    assigneeId: uuid.UUID


class CasCloture(BaseModel):
    """Corps de clôture : motif obligatoire."""

    closureReason: str = Field(min_length=1, max_length=500)


class CasResponse(BaseModel):
    """Représentation d'un cas d'intervention."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenantId: uuid.UUID | None
    status: str
    priority: str
    qualification: str
    openedBy: uuid.UUID
    assigneeId: uuid.UUID | None
    consentRef: str | None
    openedAtUtc: datetime
    closedAtUtc: datetime | None
    closureReason: str | None


def _correlation() -> str | None:
    return request_id_ctx.get()


@router.post(
    "/cases",
    response_model=CasResponse,
    status_code=201,
    summary="Ouvrir un cas d'intervention (BE-123)",
)
async def ouvrir_cas(
    data: CasCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InterventionCase:
    """Ouvre le cas, puis écrit son entrée d'audit, dans une seule transaction.

    Le droit s'évalue sur la portée du cas (plateforme ou tenant du corps) : un
    rôle L1 ou L2 sur une autre portée ne suffit pas (CA-3)."""
    await exiger_ouverture(db, current_user.id, data.tenantId)
    cas = InterventionCase(
        tenantId=data.tenantId,
        status="ouvert",
        priority=data.priority,
        qualification=data.qualification,
        openedBy=current_user.id,
        consentRef=data.consentRef,
        openedAtUtc=datetime.now(timezone.utc),
    )
    db.add(cas)
    await db.flush()
    await ecrire_evenement_admin(
        db,
        organization_id=data.tenantId,
        actor_user_id=current_user.id,
        action=ACTION_OUVERTURE,
        entity_type=TYPE_ENTITE_CAS,
        entity_id=cas.id,
        summary=f"Cas ouvert (priorité {data.priority})",
        correlation_id=_correlation(),
        changes={"status": "ouvert", "priority": data.priority},
    )
    await db.commit()
    return cas


@router.get(
    "/cases/{case_id}",
    response_model=CasResponse,
    summary="Lire un cas d'intervention (BE-123)",
)
async def lire_cas(
    case_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InterventionCase:
    """Lit le cas si le compte a un droit de lecture sur sa portée (404 si absent)."""
    cas = await charger_cas(db, case_id)
    await exiger_lecture(db, current_user.id, cas)
    return cas


@router.post(
    "/cases/{case_id}/assign",
    response_model=CasResponse,
    summary="Affecter un cas d'intervention (BE-123)",
)
async def affecter_cas(
    case_id: uuid.UUID,
    data: CasAffectation,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InterventionCase:
    """Affecte le cas à un compte existant ; passe le statut à `affecte`.

    Un cas clos ne s'affecte plus (409). Le compte cible doit exister (422)."""
    cas = await charger_cas(db, case_id)
    await exiger_gestion(db, current_user.id, cas)
    if cas.status == "cloture":
        raise AppError(code="case_closed", message="Cas déjà clos.", status_code=409)
    if await db.get(User, data.assigneeId) is None:
        raise AppError(code="case_assignee_unknown", message="Compte affecté inconnu.", status_code=422)
    cas.assigneeId = data.assigneeId
    cas.status = "affecte"
    await ecrire_evenement_admin(
        db,
        organization_id=cas.tenantId,
        actor_user_id=current_user.id,
        action=ACTION_AFFECTATION,
        entity_type=TYPE_ENTITE_CAS,
        entity_id=cas.id,
        summary="Cas affecté",
        correlation_id=_correlation(),
        changes={"status": "affecte", "assigneeId": str(data.assigneeId)},
    )
    await db.commit()
    return cas


@router.post(
    "/cases/{case_id}/close",
    response_model=CasResponse,
    summary="Clôturer un cas d'intervention (BE-123)",
)
async def cloturer_cas(
    case_id: uuid.UUID,
    data: CasCloture,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InterventionCase:
    """Clôt le cas : statut `cloture`, `closedAtUtc` et motif renseignés.

    409 si le cas est déjà clos, ou si aucune vérification n'est enregistrée pour
    ce cas (CA-4). La clôture ne se fait jamais sans cette trace."""
    cas = await charger_cas(db, case_id)
    await exiger_gestion(db, current_user.id, cas)
    if cas.status == "cloture":
        raise AppError(code="case_closed", message="Cas déjà clos.", status_code=409)
    if not await verification_enregistree(db, cas.id):
        raise AppError(
            code="case_verification_missing",
            message="Clôture refusée : aucune vérification enregistrée pour ce cas.",
            status_code=409,
        )
    cas.status = "cloture"
    cas.closedAtUtc = datetime.now(timezone.utc)
    cas.closureReason = data.closureReason
    await ecrire_evenement_admin(
        db,
        organization_id=cas.tenantId,
        actor_user_id=current_user.id,
        action=ACTION_CLOTURE,
        entity_type=TYPE_ENTITE_CAS,
        entity_id=cas.id,
        summary="Cas clos",
        correlation_id=_correlation(),
        changes={"status": "cloture", "closureReason": data.closureReason},
    )
    await db.commit()
    return cas
