"""Routes des commandes de changement de rôle ou d'adhésion (BE-140), montées sous `/api/v1/admin`.

Route :
- `POST /api/v1/admin/organizations/{organization_id}/memberships/{user_id}/role-changes` :
  crée l'intention de changement de rôles du membre `user_id` (201), ou renvoie la même
  intention au rejeu identique (200) ; 409 `idempotency_conflict` si la clé a servi à un
  autre corps ; 403 si le compte n'a pas le rôle de gestion sur ce tenant (CA-1, CA-2) ;
  404 `user_not_found` si l'utilisateur n'est pas membre ; 404 `role_not_found` si un rôle
  n'appartient pas à l'organisation ; 422 si un rôle est un rôle de module.

La prévisualisation (`/commands/{id}/preview`), la confirmation, l'approbation distincte
(`/approve`, BE-128) et l'exécution (garde BE-126) passent par les routes communes ; ce
fichier ne fait que la mise en forme HTTP. La logique vit dans `app.operator.membership_commands`
et `app.operator.commands`.
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import request_id_ctx
from app.core.security import get_current_user
from app.identity.models import User
from app.operator.commands import (
    AdminCommand,
    commande_existante,
    corps_identique,
    erreur_idempotence,
    nouvelle_commande,
)
from app.operator.membership_commands import (
    corps_commande,
    exiger_membre_et_roles,
    role_pour_changement,
)

router = APIRouter()


class ChangementRoleCreate(BaseModel):
    """Corps d'une demande de changement de rôles d'un membre (BE-140)."""

    roleIds: list[uuid.UUID] = Field(max_length=100)
    reasonTicket: str = Field(min_length=1, max_length=120)
    idempotencyKey: str = Field(min_length=8, max_length=120)
    targetVersionExpected: int | None = Field(default=None, ge=0)


class CommandeRoleAdhesionResponse(BaseModel):
    """Intention de changement de rôle renvoyée au demandeur."""

    model_config = ConfigDict(from_attributes=True)

    commandId: uuid.UUID
    commandType: str
    status: Literal["intention", "approuvee", "rejetee"]
    tenantId: uuid.UUID
    userId: uuid.UUID
    roleIds: list[uuid.UUID]
    reasonTicket: str
    idempotencyKey: str
    createdAtUtc: datetime


def _reponse(commande: AdminCommand) -> CommandeRoleAdhesionResponse:
    """Représentation d'une intention : membre et rôles cibles repris de sa charge utile."""
    charge = commande.payload or {}
    return CommandeRoleAdhesionResponse(
        commandId=commande.commandId,
        commandType=commande.commandType,
        status=commande.status,
        tenantId=commande.tenantId,
        userId=uuid.UUID(charge["userId"]),
        roleIds=[uuid.UUID(role_id) for role_id in charge.get("roleIds", [])],
        reasonTicket=commande.reasonTicket,
        idempotencyKey=commande.idempotencyKey,
        createdAtUtc=commande.createdAtUtc,
    )


@router.post(
    "/organizations/{organization_id}/memberships/{user_id}/role-changes",
    response_model=CommandeRoleAdhesionResponse,
    status_code=201,
    summary="Demander un changement de rôle ou d'adhésion d'un membre (BE-140)",
)
async def demander_changement_role(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    data: ChangementRoleCreate,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CommandeRoleAdhesionResponse:
    """Crée l'intention de changement de rôles, idempotente par acteur et clé.

    Ordre : droit sur le tenant de la route (403), membre et rôles (404, 422), idempotence
    (200 ou 409), puis intention écrite. Aucun rôle n'est modifié ici : le changement relève
    de la chaîne prévisualisation, approbation distincte et exécution (BE-125, BE-128, BE-126).
    """
    role = await role_pour_changement(db, current_user.id, organization_id)
    await exiger_membre_et_roles(db, organization_id, user_id, data.roleIds)
    corps = corps_commande(
        organization_id=organization_id,
        user_id=user_id,
        role_ids=data.roleIds,
        reason_ticket=data.reasonTicket,
        idempotency_key=data.idempotencyKey,
        target_version_expected=data.targetVersionExpected,
    )

    existante = await commande_existante(db, current_user.id, data.idempotencyKey)
    if existante is not None:
        if not corps_identique(existante, corps):
            raise erreur_idempotence()
        response.status_code = 200
        return _reponse(existante)

    commande = nouvelle_commande(
        corps=corps,
        actor_id=current_user.id,
        effective_role=role,
        correlation_id=request_id_ctx.get(),
    )
    commande.commandId = uuid.uuid4()
    db.add(commande)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        gagnante = await commande_existante(db, current_user.id, data.idempotencyKey)
        if gagnante is None or not corps_identique(gagnante, corps):
            raise erreur_idempotence()
        response.status_code = 200
        return _reponse(gagnante)
    await db.refresh(commande)
    return _reponse(commande)
