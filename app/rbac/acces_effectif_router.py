"""Route de diagnostic d'accessibilité effective (BE-053).

Chemin imposé par la définition : `/api/v1/organizations/{orgId}/modules/{moduleId}/access-evaluation`.
Le routeur est séparé de `module_router` (préfixe `/rbac`) pour garder ce chemin exact.

La route réutilise la garde d'en-tête `X-Organization-Id` de rbac/module_router (le chemin doit
correspondre à l'en-tête), puis la permission d'administration `rbac.role.manage` (réservé aux
administrateurs de l'organisation). Une organisation hors périmètre renvoie 404 avant toute évaluation.
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.acces_effectif import evaluer_acces_effectif
from app.rbac.module_policy import is_valid_permission_code
from app.rbac.module_router import GUARD
from app.rbac.permissions import ROLE_MANAGE
from app.rbac.service import require_permission

router = APIRouter()


@router.get(
    "/organizations/{organization_id}/modules/{module_code}/access-evaluation",
    dependencies=[GUARD, Depends(require_permission(ROLE_MANAGE))],
)
async def evaluer_acces_module_endpoint(
    organization_id: uuid.UUID,
    module_code: str,
    action: str = Query(..., description="Code de permission visé, format domaine.entite.action."),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Diagnostic : `decision` (allow|deny) et `reason` (motif stable, None si accordé).

    Aucune ligne n'est écrite (CA-4) : la valeur est recalculée à chaque appel.
    """
    if not is_valid_permission_code(action):
        raise AppError(
            code="action_invalide",
            message="Code d'action au format domaine.entite.action attendu.",
            status_code=422,
        )
    evaluation = await evaluer_acces_effectif(
        db,
        user_id=current_user.id,
        organization_id=organization_id,
        module_code=module_code,
        action=action,
    )
    return {"decision": evaluation.decision, "reason": evaluation.motif}
