"""Routes de suspension et de rétablissement d'un tenant (BE-134), montées sous `/api/v1/admin`.

Routes :
- `POST /api/v1/admin/organizations/{organization_id}/suspension` : crée l'intention de
  suspension (201), ou renvoie la même intention au rejeu identique (200) ; 409
  `idempotency_conflict` si la clé a servi à un autre corps ; 403 si le compte n'a pas le
  rôle de gestion sur ce tenant (CA-1, CA-3).
- `POST /api/v1/admin/organizations/{organization_id}/reinstatement` : même réponses, plus
  409 `reinstatement_preconditions_non_remplies` si le tenant n'est pas suspendu.

La preview de l'intention reste `POST /api/v1/admin/commands/{id}/preview` (BE-125) ; ses
effets sont ajoutés par `app.operator.tenant_status`. La logique de droit, d'idempotence et
de préconditions vit dans ce module ; ce fichier ne fait que la mise en forme HTTP.
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
from app.operator.tenant_status import (
    corps_commande,
    exiger_tenant_suspendu,
    role_pour_operation,
)

router = APIRouter()


class SuspensionCreate(BaseModel):
    """Corps d'une demande de suspension ou de rétablissement d'un tenant (BE-134)."""

    reasonTicket: str = Field(min_length=1, max_length=120)
    idempotencyKey: str = Field(min_length=8, max_length=120)


class CommandeSuspensionResponse(BaseModel):
    """Intention de suspension ou de rétablissement renvoyée au demandeur."""

    model_config = ConfigDict(from_attributes=True)

    commandId: uuid.UUID
    commandType: str
    status: Literal["intention", "approuvee", "rejetee"]
    tenantId: uuid.UUID
    operation: str
    reasonTicket: str
    idempotencyKey: str
    createdAtUtc: datetime


def _reponse(commande: AdminCommand) -> CommandeSuspensionResponse:
    """Représentation d'une intention : l'opération est reprise de sa charge utile."""
    charge = commande.payload or {}
    return CommandeSuspensionResponse(
        commandId=commande.commandId,
        commandType=commande.commandType,
        status=commande.status,
        tenantId=commande.tenantId,
        operation=charge.get("operation"),
        reasonTicket=commande.reasonTicket,
        idempotencyKey=commande.idempotencyKey,
        createdAtUtc=commande.createdAtUtc,
    )


async def _creer_intention(
    *,
    db: AsyncSession,
    current_user: User,
    organization_id: uuid.UUID,
    data: SuspensionCreate,
    response: Response,
    operation: str,
    exiger_suspendu: bool,
) -> CommandeSuspensionResponse:
    """Crée l'intention, idempotente par acteur et clé (CA-5).

    Ordre : droit sur le tenant (403), préconditions du rétablissement (409), idempotence
    (200 ou 409), puis intention écrite. Aucun statut de tenant n'est modifié ici.
    """
    role = await role_pour_operation(db, current_user.id, organization_id)
    if exiger_suspendu:
        await exiger_tenant_suspendu(db, organization_id)
    corps = corps_commande(
        organization_id=organization_id,
        operation=operation,
        reason_ticket=data.reasonTicket,
        idempotency_key=data.idempotencyKey,
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


@router.post(
    "/organizations/{organization_id}/suspension",
    response_model=CommandeSuspensionResponse,
    status_code=201,
    summary="Demander la suspension d'un tenant (BE-134)",
)
async def demander_suspension(
    organization_id: uuid.UUID,
    data: SuspensionCreate,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CommandeSuspensionResponse:
    """Intention de suspension : approbation distincte exigée à l'exécution (CA-2, BE-126)."""
    return await _creer_intention(
        db=db,
        current_user=current_user,
        organization_id=organization_id,
        data=data,
        response=response,
        operation="suspension",
        exiger_suspendu=False,
    )


@router.post(
    "/organizations/{organization_id}/reinstatement",
    response_model=CommandeSuspensionResponse,
    status_code=201,
    summary="Demander le rétablissement d'un tenant suspendu (BE-134)",
)
async def demander_retablissement(
    organization_id: uuid.UUID,
    data: SuspensionCreate,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CommandeSuspensionResponse:
    """Intention de rétablissement : 409 si le tenant n'est pas à l'état `suspended`."""
    return await _creer_intention(
        db=db,
        current_user=current_user,
        organization_id=organization_id,
        data=data,
        response=response,
        operation="reinstatement",
        exiger_suspendu=True,
    )
