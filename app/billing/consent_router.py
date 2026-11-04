"""Route des consentements versionnés (BE-076).

`POST /api/v1/billing/consents` (corps `ConsentCreate`) : enregistre un consentement ou
sa correction pour le compte désigné, dans l'organisation courante (en-tête
`X-Organization-Id`, garde `get_current_organization_id`). 201 avec la ligne créée ;
403 `FORBIDDEN` sans permission d'acheteur, 403 `SCOPE_MISMATCH` pour un compte hors
tenant. La logique est dans app/billing/consents.py.
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import consents
from app.billing.schemas import ConsentCreate, ConsentResponse
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.rbac.guards import get_current_organization_id

router = APIRouter()


@router.post(
    "/consents",
    response_model=ConsentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enregistrer un consentement versionné (BE-076)",
)
async def enregistrer_consentement(
    payload: ConsentCreate,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Enregistre un consentement ou une correction ; aucune écriture en cas de refus."""
    return await consents.enregistrer_consentement(
        db,
        tenant_id=organization_id,
        personne_id=current_user.id,
        account_id=payload.accountId,
        consent_text_version=payload.consentTextVersion,
        scope=payload.scope,
        correction_of_id=payload.correctionOfId,
    )
