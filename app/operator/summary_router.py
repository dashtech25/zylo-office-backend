"""Synthèse des états d'un compte client (BE-130), montée sous `/api/v1/admin`.

Route : `GET /api/v1/admin/organizations/{organization_id}/summary`.

Garde : `require_admin_scope` (BE-120), déclarée sur le montage. Sans autorité
plateforme : 403. La synthèse est un contenu tenant : elle exige une portée
`tenant:<organization_id>` (`assert_tenant_content_scope`). La portée plateforme
et une portée d'un autre tenant reçoivent 403. Les règles de projection et de
sections sont dans `app/operator/summary.py`.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.operator.scope import AdminScope, assert_tenant_content_scope, require_admin_scope
from app.operator.summary import construire_synthese, roles_actifs

router = APIRouter()


@router.get(
    "/organizations/{organization_id}/summary",
    summary="Synthèse des états d'un compte client (console de support, lecture)",
)
async def lire_synthese(
    organization_id: uuid.UUID,
    scope: AdminScope = Depends(require_admin_scope),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Sept sections (offre, abonnement, paiement, factures, droits, incidents, échéances).

    Les sections `paiement` et `factures` sont masquées pour les rôles sans
    lecture financière (BE-130 CA-2)."""
    assert_tenant_content_scope(scope, organization_id)
    roles = await roles_actifs(db, current_user.id, organization_id)
    return {"data": await construire_synthese(db, organization_id, roles)}
