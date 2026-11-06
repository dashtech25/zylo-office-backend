"""Routes de la vérification d'organisation, montées sous `/api/v1/organizations` (BE-103).

- `GET /{organization_id}/verification` : statut du dernier cas, ou `null` (action
  `portail.verification.lire`, permission `organization.verification.read`).
- `POST /{organization_id}/verification` : dépôt d'une demande, 201 en `verification_pending`
  (action `portail.verification.deposer`, permission `organization.verification.submit`).

Ordre de contrôle : portée et permission (`exiger_action`, 401, 403 ou 404) ; validation du corps
(422) ; écriture (`service.py`). Refus : 404 hors appartenance, 403 sans permission.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.portail.verification.schemas import DepotVerificationRequest, VerificationCaseResponse
from app.portail.verification.service import dernier_cas, deposer_demande
from app.rbac.portee_organisation import OrgScope, exiger_action

router = APIRouter()

PORTAIL_VERIFICATION_LIRE = "portail.verification.lire"
PORTAIL_VERIFICATION_DEPOSER = "portail.verification.deposer"


@router.get(
    "/{organization_id}/verification",
    response_model=VerificationCaseResponse | None,
    summary="Statut de la vérification de l'organisation (BE-103)",
)
async def get_verification(
    scope: OrgScope = Depends(exiger_action(PORTAIL_VERIFICATION_LIRE)),
    db: AsyncSession = Depends(get_db),
) -> VerificationCaseResponse | None:
    """Dernier cas de l'organisation du chemin, sans motif interne ; `null` s'il n'y en a pas."""
    cas = await dernier_cas(db, scope.organization_id)
    return VerificationCaseResponse.model_validate(cas) if cas is not None else None


@router.post(
    "/{organization_id}/verification",
    status_code=201,
    response_model=VerificationCaseResponse,
    summary="Déposer une demande de vérification de l'organisation (BE-103)",
)
async def post_verification(
    corps: DepotVerificationRequest,
    scope: OrgScope = Depends(exiger_action(PORTAIL_VERIFICATION_DEPOSER)),
    db: AsyncSession = Depends(get_db),
) -> VerificationCaseResponse:
    """Crée le cas en `verification_pending` pour l'organisation du chemin."""
    cas = await deposer_demande(db, scope.organization_id)
    return VerificationCaseResponse.model_validate(cas)
