"""Routes de la sortie de tenant (BE-246), montées sous `/api/v1/organizations`.

- `POST /{organization_id}/exit` : demande de sortie, 201 avec l'état et l'attestation ;
- `GET /{organization_id}/exit/attestation` : attestation de la dernière sortie.

Toutes les routes exigent une session. Les permissions sont évaluées dans le service, qui
journalise les refus avant de répondre 403 (app/sortie_tenant/service.py).
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.sortie_tenant import service
from app.sortie_tenant.schemas import DemandeSortie, SortieStatut

router = APIRouter()


@router.post("/{organization_id}/exit", status_code=201, response_model=SortieStatut, summary="Demander la sortie d'un tenant")
async def demander_sortie(
    organization_id: uuid.UUID,
    corps: DemandeSortie,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SortieStatut:
    """Efface le tenant (ou le déclare tenu si un hold est actif) ; 403 sans permission ou sans approbation distincte."""
    demande = await service.demander_sortie(db, organization_id, current_user.id, corps.approbateurId, corps.motif)
    return SortieStatut(id=demande.id, etat=demande.etat, attestation=demande.attestation)


@router.get("/{organization_id}/exit/attestation", response_model=dict, summary="Attestation de sortie d'un tenant")
async def attestation_sortie(
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Attestation de la dernière sortie : efface, différé, conservé ; 403 pour un tiers sans droit."""
    return await service.attestation_de(db, organization_id, current_user.id)
