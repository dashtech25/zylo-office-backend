"""Routes des lettres mortes d'intégration (BE-165), montées sous `/api/v1/integrations`.

- `GET  /integrations/lettres-mortes` : liste des échecs définitifs du tenant courant
  (permission `integrations.read`) ;
- `POST /integrations/lettres-mortes/{lettre_id}/reprises` : reprise manuelle avec motif
  (permission `integrations.manage`).

Le tenant vient toujours du contexte serveur (`get_current_organization_id`), jamais du corps.
La logique reste dans `app/integrations/lettres_mortes.py` ; ce module ne fait que traduire
les appels HTTP. La relance réelle n'a pas d'adaptateur en BE-165 : la route passe une relance
qui ne fait que marquer la reprise, le branchement sur le consommateur est à faire (QE-165-02).
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.ecriture import IdentiteEmettrice
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.integrations.lettres_mortes import lister_lettres_mortes, reprendre_lettre_morte
from app.integrations.models import LettreMorte
from app.rbac.guards import get_current_organization_id

router = APIRouter()


class LettreMorteResponse(BaseModel):
    """Vue d'une lettre morte : aucun contenu d'événement, seulement les métadonnées de reprise."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tentativeId: uuid.UUID
    originalId: uuid.UUID
    motif: str | None
    operateur: uuid.UUID | None
    reprisAt: datetime | None
    createdAt: datetime


class ReprendreLettreRequest(BaseModel):
    """Corps de la reprise : `motif` obligatoire. Vide ou absent, la reprise est refusée en 422."""

    motif: str | None = None


@router.get(
    "/lettres-mortes",
    response_model=list[LettreMorteResponse],
    summary="Lister les lettres mortes d'intégration du tenant courant (BE-165)",
)
async def lister(
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LettreMorte]:
    """Liste les lettres mortes ; exige `integrations.read` (403 sinon, rien n'est lu)."""
    identite = IdentiteEmettrice(user_id=current_user.id, organization_id=organization_id)
    return await lister_lettres_mortes(db, identite, organization_id)


@router.post(
    "/lettres-mortes/{lettre_id}/reprises",
    response_model=LettreMorteResponse,
    summary="Reprendre manuellement une lettre morte, avec motif (BE-165)",
)
async def reprendre(
    lettre_id: uuid.UUID,
    corps: ReprendreLettreRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LettreMorte:
    """Reprise avec motif (CA-2) ; 403 sans `integrations.manage` (CA-3), 404 hors tenant
    (CA-5), 409 `REPLAY_DUPLICATE` si la lettre a déjà été reprise (CA-4).

    La transaction est validée ici après la mutation et son audit, dans le même appel.
    """

    async def relance_sans_adaptateur(_lettre: LettreMorte) -> None:
        """Pas d'adaptateur d'intégration en BE-165 : la reprise est tracée, la relance est à brancher."""
        return None

    identite = IdentiteEmettrice(user_id=current_user.id, organization_id=organization_id)
    lettre = await reprendre_lettre_morte(
        db,
        identite=identite,
        organization_id=organization_id,
        lettre_id=lettre_id,
        motif=corps.motif,
        relance=relance_sans_adaptateur,
    )
    await db.commit()
    return lettre
