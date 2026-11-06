"""Routes membership et sélection de contexte (BE-189).

Deux routeurs, montés sous `/api/v1/contexts` et `/api/v1/memberships` (app/api/v1/router.py) :
- `contexts_router` : `GET ""` liste les contextes ouverts par l'utilisateur ;
  `POST /select` ouvre un contexte (404 sans membership actif, audité).
- `memberships_router` : lecture ouverte à tout membre actif du tenant courant
  (`X-Organization-Id`) ; invitation, changement d'état et révocation exigent
  `membership.manage` (403 sans ce droit). La logique est dans app/identity/membership.py.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity import membership
from app.identity.models import User
from app.identity.permissions import MEMBERSHIP_MANAGE
from app.rbac.guards import get_current_organization_id
from app.rbac.service import require_permission


class SelectionContexteRequest(BaseModel):
    """Tenant à ouvrir. Le tenant est désigné dans le corps, jamais déduit d'un autre champ."""

    organizationId: uuid.UUID


class InvitationMembershipRequest(BaseModel):
    """Invitation d'un utilisateur existant, désigné par son e-mail."""

    email: str = Field(min_length=3, max_length=320)


class ModificationMembershipRequest(BaseModel):
    """Nouvel état du membership : `invited`, `active` ou `suspended` (la révocation passe par DELETE)."""

    state: Literal["invited", "active", "suspended"]


contexts_router = APIRouter()
memberships_router = APIRouter()


@contexts_router.get("", summary="Lister les contextes ouverts par l'utilisateur (BE-189)")
async def lister_contextes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Memberships `active` de l'utilisateur sur des organisations non supprimées. Liste vide si aucun."""
    return await membership.lister_contextes(db, current_user.id)


@contexts_router.post("/select", summary="Ouvrir le contexte d'un tenant (BE-189)")
async def selectionner_contexte(
    data: SelectionContexteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Refus 404 `organization_not_found` sans membership actif (opaque). Entrée d'audit `contexte.select`."""
    return await membership.selectionner_contexte(db, current_user, data.organizationId)


@memberships_router.get("", summary="Lister les memberships du tenant courant (BE-189)")
async def lister_memberships(
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Memberships du tenant désigné par `X-Organization-Id`, tous statuts. 404 si non membre actif."""
    return await membership.lister_memberships(db, organization_id)


@memberships_router.post(
    "",
    summary="Inviter un utilisateur dans le tenant courant (BE-189)",
    dependencies=[Depends(require_permission(MEMBERSHIP_MANAGE))],
)
async def inviter_membership(
    data: InvitationMembershipRequest,
    response: Response,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """201 à la création, 200 si le membership existe déjà (rejeu idempotent). 403 sans `membership.manage`."""
    resultat, cree = await membership.inviter(db, current_user, organization_id, data.email)
    response.status_code = 201 if cree else 200
    return resultat


@memberships_router.patch(
    "/{membership_id}",
    summary="Changer l'état d'un membership du tenant courant (BE-189)",
    dependencies=[Depends(require_permission(MEMBERSHIP_MANAGE))],
)
async def modifier_membership(
    membership_id: uuid.UUID,
    data: ModificationMembershipRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Passe le membership à `state` et incrémente `version`. 404 hors tenant, 409 si révoqué."""
    return await membership.modifier_etat(db, current_user, organization_id, membership_id, data.state)


@memberships_router.delete(
    "/{membership_id}",
    status_code=204,
    summary="Révoquer un membership du tenant courant (BE-189)",
    dependencies=[Depends(require_permission(MEMBERSHIP_MANAGE))],
)
async def revoquer_membership(
    membership_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Révocation : statut `revoked`, rôles retirés, historique conservé. Accès coupé dès la requête suivante."""
    await membership.revoquer(db, current_user, organization_id, membership_id)
