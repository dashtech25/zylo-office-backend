"""Route de demande de support, montée sous `/api/v1/organizations` (BE-118).

- `POST /{organization_id}/support-requests` : crée une demande `open` (201).

Ordre de contrôle : portée et permission (`exiger_action`, 401, 403 ou 404) ; validation du corps
(422) ; contexte secret (400) ; écriture et événement (`service.py`).
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.rbac.portee_organisation import OrgScope, exiger_action
from app.support.demandes.schemas import DemandeSupportCreate, DemandeSupportResponse
from app.support.demandes.service import create_support_request

router = APIRouter()

# Action du portail : sa permission (`support.request.create`) est dans POLITIQUE_PORTAIL (BE-118).
SUPPORT_PORTAIL_ACTION = "portail.support.demander"


@router.post(
    "/{organization_id}/support-requests",
    status_code=201,
    response_model=DemandeSupportResponse,
    summary="Ouvrir une demande de support client (BE-118)",
)
async def post_support_request(
    corps: DemandeSupportCreate,
    scope: OrgScope = Depends(exiger_action(SUPPORT_PORTAIL_ACTION)),
    db: AsyncSession = Depends(get_db),
) -> DemandeSupportResponse:
    """Crée la demande pour l'organisation du chemin ; l'auteur est l'utilisateur authentifié.

    Les pièces jointes ne sont pas acceptées par le schéma et ne sont jamais stockées.
    """
    ligne = await create_support_request(db, scope.organization_id, scope.user_id, corps.contexte)
    return DemandeSupportResponse.model_validate(ligne)
