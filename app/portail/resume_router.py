"""Route du résumé du portail (BE-109).

- `GET /organizations/{organization_id}/portal-summary` : résumé de l'organisation du chemin.
  Portée `OrgScope` (BE-101) et action `portail.resume.lire` (permission `portal.summary.read`) :
  404 hors appartenance, 401 sans session, 403 sans la permission du portail. Les sections
  (entitlements, usage, membres, facturation) sont filtrées par leur propre permission dans
  `build_portal_summary`. Montée sous `/api/v1/organizations` (app/api/v1/router.py).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.portail.resume import PortalSummaryResponse, build_portal_summary
from app.rbac.portee_organisation import OrgScope, exiger_action

router = APIRouter()

PORTAIL_RESUME_LIRE = "portail.resume.lire"


@router.get(
    "/{organization_id}/portal-summary",
    response_model=PortalSummaryResponse,
    response_model_exclude_unset=True,
    summary="Résumé du portail filtré par permission (BE-109)",
)
async def get_portal_summary(
    scope: OrgScope = Depends(exiger_action(PORTAIL_RESUME_LIRE)),
    db: AsyncSession = Depends(get_db),
) -> PortalSummaryResponse:
    """Sections accordées à l'utilisateur pour l'organisation du chemin ; les autres sont absentes."""
    return await build_portal_summary(db, scope)
