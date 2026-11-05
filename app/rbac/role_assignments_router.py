"""Routes des affectations de rôle d'administration (BE-121), sous `/api/v1/admin`.

Routes :
- `POST /api/v1/admin/role-assignments` : attribue un rôle à un compte, pour une
  portée `platform` ou `tenant:<uuid>` ; crée une entrée d'audit (CA-4) ;
- `GET /api/v1/admin/role-assignments?actor_id=` : liste les affectations d'un
  compte (paramètre obligatoire).

Gardes :
- `require_admin_scope` (BE-120) : sans autorité plateforme, 403 (CA-1) ; portée
  tenant sans adhésion active au tenant, 403 (CA-3) ;
- une attribution de portée globale exige la portée de requête `platform` ;
  une attribution de portée tenant exige la portée de requête `platform` ou la
  même portée tenant (une portée tenant n'ouvre aucun autre tenant, CA-3).
  Le refus est un 403 `admin_scope_denied`, comme le reste de la portée admin.

Contrôles du corps (422) : portée mal formée (`admin_scope_invalid`), rôle
inconnu, rôle temporaire sans échéance ou échéance passée (CA-2), compte cible
inconnu. Voir `app/rbac/role_assignments.py` pour les règles de domaine.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.admin_audit import ecrire_evenement_admin
from app.core.database import get_db
from app.core.errors import AppError
from app.core.logging import request_id_ctx
from app.core.security import get_current_user
from app.identity.models import User
from app.operator.scope import AdminScope, parse_admin_scope, require_admin_scope
from app.rbac.role_assignments import AdminRoleAssignment, creer_affectation, lister_affectations

router = APIRouter()

ACTION_ATTRIBUTION = "admin.role_assignment.grant"
TYPE_ENTITE_AFFECTATION = "AdminRoleAssignment"


class AffectationCreate(BaseModel):
    """Corps d'une attribution. `scope` est `platform` ou `tenant:<uuid canonique>`."""

    actorId: uuid.UUID
    roleCode: str
    scope: str
    expiresAt: datetime | None = None


class AffectationResponse(BaseModel):
    """Représentation d'une affectation de rôle d'administration."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actorId: uuid.UUID
    roleCode: str
    scope: str
    grantedBy: uuid.UUID
    grantedAt: datetime
    expiresAt: datetime | None
    revokedAt: datetime | None


def _portee_canonique(portee: AdminScope) -> str:
    """Forme stockée d'une portée : `platform` ou `tenant:<uuid>` (canonique)."""
    return "platform" if portee.is_platform else f"tenant:{portee.organization_id}"


def _refus_portee() -> AppError:
    return AppError(
        code="admin_scope_denied",
        message="Accès d'administration refusé pour cette portée.",
        status_code=403,
    )


@router.post(
    "/role-assignments",
    response_model=AffectationResponse,
    status_code=201,
    summary="Attribuer un rôle d'administration global ou temporaire (BE-121)",
)
async def create_role_assignment(
    data: AffectationCreate,
    scope: AdminScope = Depends(require_admin_scope),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdminRoleAssignment:
    """Crée l'affectation, puis son entrée d'audit, dans une seule transaction.

    La portée de la cible est lue dans le corps et validée par `parse_admin_scope`.
    Si la cible est la plateforme, la requête doit elle-même porter la portée
    `platform` ; si la cible est un tenant, la requête doit porter la portée
    `platform` ou ce même tenant. Le compte cible doit exister (422 sinon).
    L'audit est écrit avec `correlation_id` issu de la requête : une requête
    sans identifiant de corrélation n'écrit rien (BE-122 CA-1, fail-closed).
    """
    cible = parse_admin_scope(data.scope)
    if cible.is_platform:
        if not scope.is_platform:
            raise _refus_portee()
    elif not scope.is_platform and scope.organization_id != cible.organization_id:
        raise _refus_portee()

    if await db.get(User, data.actorId) is None:
        raise AppError(code="admin_actor_unknown", message="Compte cible inconnu.", status_code=422)

    ligne = await creer_affectation(
        db,
        actor_id=data.actorId,
        role_code=data.roleCode,
        scope=_portee_canonique(cible),
        expires_at=data.expiresAt,
        granted_by=current_user.id,
    )
    await ecrire_evenement_admin(
        db,
        organization_id=None if cible.is_platform else cible.organization_id,
        actor_user_id=current_user.id,
        action=ACTION_ATTRIBUTION,
        entity_type=TYPE_ENTITE_AFFECTATION,
        entity_id=ligne.id,
        summary=f"Rôle {data.roleCode} attribué ({_portee_canonique(cible)})",
        correlation_id=request_id_ctx.get(),
        changes={
            "actorId": str(data.actorId),
            "roleCode": data.roleCode,
            "scope": _portee_canonique(cible),
            "expiresAt": data.expiresAt.isoformat() if data.expiresAt else None,
        },
    )
    await db.commit()
    return ligne


@router.get(
    "/role-assignments",
    response_model=list[AffectationResponse],
    summary="Lister les affectations de rôle d'administration d'un compte (BE-121)",
)
async def list_role_assignments(
    actor_id: uuid.UUID = Query(..., description="Compte dont on liste les affectations."),
    scope: AdminScope = Depends(require_admin_scope),
    db: AsyncSession = Depends(get_db),
) -> list[AdminRoleAssignment]:
    """Affectations du compte. Portée plateforme : toutes les portées du compte.
    Portée tenant : seulement les affectations de ce tenant, sans révéler les
    autres portées (CA-3)."""
    portee = None if scope.is_platform else _portee_canonique(scope)
    return await lister_affectations(db, actor_id, portee)
