"""Grants allow/deny par utilisateur, sur l'organisation courante (BE-017).

Routes publiques, montées sous `/api/v1/organizations` par `app/api/v1/router.py` :

- `POST /api/v1/organizations/current/members/{userId}/grants` : crée un grant
  (`allow` ou `deny`) pour ce membre dans l'organisation courante.
- `DELETE /api/v1/organizations/current/members/{userId}/grants/{grantId}` : révoque
  ce grant, avec la cascade de délégation (204).

Intention : ces routes ne font que de la mise en forme HTTP. La logique (résolution
allow/deny, non-élévation, cascade de révocation, audit) reste dans
`app/rbac/service.py` (`create_grant`, `revoke_grant`), réutilisée à l'identique par
l'ancienne route `/organizations/{organization_id}/grants` de `app/rbac/router.py`.
Aucun second chemin de décision n'est créé ici.

Organisation : résolue par l'en-tête `X-Organization-Id` via `get_current_organization_id`.
Le client n'envoie jamais d'identifiant d'organisation dans le corps.

Permission : `rbac.grant.manage` (GRANT_MANAGE), vérifiée avant toute écriture
(403 `permission_denied`). Le code exact est NON DÉFINI (QE-SOC-06) ; il reprend le
code existant. Règles appliquées par le service :
- cible non membre de l'organisation : 404 `user_not_found` (IAM-004) ;
- permission inconnue : 404 `permission_not_found` ;
- `allow` sur une permission que l'acteur ne possède pas à cette portée : 403
  `privilege_escalation_denied` ; `deny` n'est jamais soumis à cette règle ;
- grant d'un autre membre, ou d'une autre organisation : 404 `grant_not_found`.

Résultat allow puis deny sur la même permission : `deny` l'emporte (QE-SOC-07,
résolu par `user_has_permission`).

Audit : chaque création écrit `rbac.grant.create`, chaque révocation `rbac.grant.revoke`,
dans la même transaction que l'écriture (`app/audit/service.py`).
"""

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac import service
from app.rbac.guards import get_current_organization_id
from app.rbac.models import UserPermissionGrant
from app.rbac.permissions import GRANT_MANAGE
from app.rbac.schemas import CreateMemberGrantRequest, GrantResponse
from app.rbac.service import require_permission

router = APIRouter()


@router.post(
    "/current/members/{user_id}/grants",
    response_model=GrantResponse,
    status_code=201,
    summary="Accorder ou refuser une permission à un membre de l'organisation courante (BE-017)",
    dependencies=[Depends(require_permission(GRANT_MANAGE))],
)
async def create_member_grant(
    user_id: uuid.UUID,
    data: CreateMemberGrantRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserPermissionGrant:
    """Crée un grant `allow` ou `deny` pour `user_id` dans l'organisation courante.
    Refus : 403 sans `rbac.grant.manage`, 403 `privilege_escalation_denied` pour un
    `allow` que l'acteur ne possède pas, 404 si la cible n'est pas membre ou si la
    permission n'existe pas. En cas de refus, aucun grant n'est créé.
    Détail des règles : `app/rbac/grants_membres.py` (doc du module)."""
    return await service.create_grant(
        db,
        organization_id,
        current_user.id,
        user_id,
        data.permissionCode,
        data.effect,
        resource_type=data.resourceType,
        resource_id=data.resourceId,
        valid_until=data.validUntil,
        audit_note=data.auditNote,
        delegated_from_grant_id=data.delegatedFromGrantId,
    )


@router.delete(
    "/current/members/{user_id}/grants/{grant_id}",
    status_code=204,
    summary="Révoquer un grant d'un membre de l'organisation courante (BE-017)",
    dependencies=[Depends(require_permission(GRANT_MANAGE))],
)
async def revoke_member_grant(
    user_id: uuid.UUID,
    grant_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Révoque `grant_id`, à condition qu'il appartienne à `user_id` dans l'organisation
    courante ; sinon 404 `grant_not_found` et rien n'est modifié. La révocation cascade
    sur les délégations issues de ce grant (`service.revoke_grant`)."""
    grant = await db.get(UserPermissionGrant, grant_id)
    if grant is None or grant.organizationId != organization_id or grant.userId != user_id:
        raise AppError(code="grant_not_found", message="Grant introuvable.", status_code=404)
    await service.revoke_grant(db, organization_id, current_user.id, grant_id)
    return Response(status_code=204)
