"""Recherche d'organisation pour la console de support (BE-129), sous `/api/v1/admin`.

Route : `GET /api/v1/admin/search?q=<terme>&type=organization`.

Garde : `require_admin_scope` (BE-120), déclarée sur la route et sur le montage
(BE-147 CA-3). Sans autorité plateforme : 403. Une portée tenant sans affectation
au tenant : 403 avant toute lecture.

Chaque recherche réussie est écrite dans le journal d'audit administratif
(BE-122) avant la réponse, avec l'empreinte du terme et jamais le terme. Les
règles de projection et de portée sont dans `app/operator/search.py`.
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.admin_audit import ecrire_evenement_admin
from app.core.database import get_db
from app.core.logging import request_id_ctx
from app.core.security import get_current_user
from app.identity.models import User
from app.operator.scope import AdminScope, require_admin_scope
from app.operator.search import (
    ACTION_RECHERCHE,
    empreinte_terme,
    projeter,
    rechercher_organisations,
    valider_terme,
)

router = APIRouter()


@router.get(
    "/search",
    summary="Rechercher une organisation (console de support, lecture)",
)
async def rechercher(
    q: str = Query(..., description="Terme cherché : nom, slug ou identifiant d'organisation."),
    type_recherche: Literal["organization"] = Query("organization", alias="type"),
    scope: AdminScope = Depends(require_admin_scope),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Organisations correspondant à `q`, selon la portée validée par `require_admin_scope`.

    Portée plateforme : toutes les organisations, champs complets. Portée tenant :
    l'organisation de la portée seule, champs normalisés. La recherche est
    journalisée (empreinte du terme) avant la réponse, dans la même transaction."""
    terme = valider_terme(q)
    organisations = await rechercher_organisations(db, scope, terme)
    complete = scope.is_platform
    donnees = [projeter(organisation, complete) for organisation in organisations]

    await ecrire_evenement_admin(
        db,
        organization_id=scope.organization_id,
        actor_user_id=current_user.id,
        action=ACTION_RECHERCHE,
        entity_type="Organization",
        entity_id=None,
        summary="Recherche d'organisations (terme masqué)",
        correlation_id=request_id_ctx.get(),
        changes={
            "termeEmpreinte": empreinte_terme(terme),
            "type": type_recherche,
            "projection": "complete" if complete else "normalisee",
            "nombreResultats": len(donnees),
        },
    )
    await db.commit()
    return {"data": donnees}
