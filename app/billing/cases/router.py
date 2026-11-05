"""Routes des cas de facturation et d'assistance (BE-096).

Routes : `POST /api/v1/billing/cases` (ouverture, 201) et
`POST /api/v1/billing/cases/{case_id}/resolve` (résolution, 200), montées sous `/billing`
(app/api/v1/router.py).

Contrat :
- Le tenant vient de l'en-tête `X-Organization-Id` ; l'acteur vient du jeton. Aucun champ du corps
  ne désigne l'acteur ni le tenant : il n'existe aucune route d'impersonation.
- Permission contrôlée avant le périmètre : `billing.case.open` pour ouvrir,
  `billing.case.resolve` pour résoudre. Sans elle : 403 `FORBIDDEN`, rien n'est écrit.
- Motif vide ou blanc : 422 (validation du schéma).
- Cas absent ou d'un autre tenant : 404 `case_not_found`.
- Résolution d'un cas `action_pending` : approbateur distinct requis (`APPROVAL_REQUIRED`).
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.cases.service import ouvrir_cas, resoudre_cas
from app.billing.errors import BillingErrorCode, billing_error
from app.billing.permissions import BILLING_CASE_OPEN, BILLING_CASE_RESOLVE
from app.billing.models import BillingCase
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.guards import get_current_organization_id
from app.rbac.service import user_has_permission

router = APIRouter()


def _motif_non_vide(valeur: str) -> str:
    """Refuse un motif vide ou composé d'espaces ; renvoie la valeur nettoyée."""
    nettoye = valeur.strip()
    if not nettoye:
        raise ValueError("Le motif est obligatoire.")
    return nettoye


class OuvertureCasCorps(BaseModel):
    """Corps d'ouverture d'un cas. Les champs inconnus (acteur, assignation) sont ignorés."""

    scope: Literal["tenant", "payeur"]
    subjectRef: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def _valider_motif(cls, valeur: str) -> str:
        return _motif_non_vide(valeur)


class ResolutionCasCorps(BaseModel):
    """Corps de résolution : motif obligatoire, approbateur requis pour une action sensible."""

    reason: str = Field(min_length=1, max_length=2000)
    approverId: uuid.UUID | None = None

    @field_validator("reason")
    @classmethod
    def _valider_motif(cls, valeur: str) -> str:
        return _motif_non_vide(valeur)


class CasReponse(BaseModel):
    """Cas de facturation tel que renvoyé par les routes (BE-096)."""

    id: uuid.UUID
    scope: str
    subjectRef: str
    status: str
    assigneeId: uuid.UUID | None
    reason: str
    openedAt: datetime
    resolutionReason: str | None
    resolvedAt: datetime | None


def _vers_reponse(cas: BillingCase) -> CasReponse:
    return CasReponse(
        id=cas.id,
        scope=cas.scope,
        subjectRef=cas.subjectRef,
        status=cas.status,
        assigneeId=cas.assigneeId,
        reason=cas.reason,
        openedAt=cas.openedAt,
        resolutionReason=cas.resolutionReason,
        resolvedAt=cas.resolvedAt,
    )


@router.post(
    "/cases",
    response_model=CasReponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ouvrir un cas de facturation ou d'assistance (BE-096)",
)
async def ouvrir(
    corps: OuvertureCasCorps,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CasReponse:
    """Ouvre un cas `open` dans le tenant courant, avec son entrée d'audit."""
    if not await user_has_permission(db, current_user.id, organization_id, BILLING_CASE_OPEN):
        raise billing_error(BillingErrorCode.FORBIDDEN)
    cas = await ouvrir_cas(
        db,
        organization_id,
        current_user.id,
        scope=corps.scope,
        subject_ref=corps.subjectRef,
        reason=corps.reason,
    )
    return _vers_reponse(cas)


@router.post(
    "/cases/{case_id}/resolve",
    response_model=CasReponse,
    summary="Résoudre un cas de facturation ou d'assistance (BE-096)",
)
async def resoudre(
    case_id: uuid.UUID,
    corps: ResolutionCasCorps,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CasReponse:
    """Résout le cas avec motif et entrée d'audit. Permission `billing.case.resolve` requise."""
    if not await user_has_permission(db, current_user.id, organization_id, BILLING_CASE_RESOLVE):
        raise billing_error(BillingErrorCode.FORBIDDEN)
    cas = await resoudre_cas(
        db,
        case_id,
        organization_id,
        current_user.id,
        reason=corps.reason,
        approver_id=corps.approverId,
    )
    return _vers_reponse(cas)
