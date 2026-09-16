"""Routes du module Zylo Tanker (supervision de navires pétroliers) —
`GET /ping` (santé du module) + CRUD minimal de `Vessel` (2026-09-16,
premier vrai modèle métier). Le tracking GPS des navires (positions,
arrêts, réconciliation, commentaires) vit dans `app/location/router.py`,
monté une deuxième fois sous le préfixe `/zylo-tanker` (voir
`app/api/v1/router.py`) — jamais dupliqué ici. Même patron que
`app/modules/zylo_liquid/router.py` : un `APIRouter` gardé une seule fois
par `require_module_active`, jamais répété route par route (contrairement
à `app/location/router.py`, qui sert désormais deux modules et ne peut
plus se permettre une garde unique — voir sa docstring)."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.modules.zylo_tanker import service
from app.modules.zylo_tanker.schemas import CreateVesselRequest, VesselResponse
from app.modules_registry.service import require_module_active
from app.rbac.service import get_current_organization_id
from app.shared.pagination import PaginationParams
from app.shared.schemas import Page

router = APIRouter(dependencies=[Depends(require_module_active("zylo_tanker"))])


@router.get("/ping", summary="Vérifier que le module Zylo Tanker est actif et accessible")
async def ping(
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
) -> dict:
    """Route de vérification de santé du module — confirme que
    l'utilisateur est authentifié, rattaché à une organisation, et que
    cette organisation a bien activé `zylo_tanker` (sinon
    `require_module_active` répond 403 avant d'atteindre ce code)."""
    return {"module": "zylo_tanker", "status": "ok", "organizationId": str(organization_id)}


@router.post("/vessels", response_model=VesselResponse, status_code=201, summary="Créer un navire")
async def create_vessel(
    data: CreateVesselRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> VesselResponse:
    return await service.create_vessel(db, organization_id, current_user.id, data)


@router.get("/vessels", response_model=Page[VesselResponse], summary="Lister les navires de l'organisation")
async def list_vessels(
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Page:
    return await service.list_vessels(db, organization_id, current_user.id, pagination)


@router.get("/vessels/{vessel_id}", response_model=VesselResponse, summary="Détail d'un navire")
async def get_vessel(
    vessel_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> VesselResponse:
    return await service.get_vessel(db, organization_id, current_user.id, vessel_id)
