"""Route de demande de rejeu d'événement (BE-139), montée sous `/api/v1/admin`.

Route :
- `POST /api/v1/admin/events/{event_id}/replay-commands` : crée l'intention de rejeu (201),
  ou renvoie la même intention au rejeu identique (200) ; 409 `idempotency_conflict` si la clé
  a servi à un autre corps ; 404 `evenement_introuvable` ; 403 si le compte n'a pas le rôle de
  gestion sur le tenant de l'événement (CA-2, CA-3).

L'approbation distincte passe par `POST /api/v1/admin/commands/{id}/approve` (BE-128) ; l'exécution
par la garde (BE-126). La route ne fait que la mise en forme HTTP : droit, idempotence et corps
sont dans `app.operator.event_replay` et `app.operator.commands`.
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
    role_effectif,
)
from app.operator.event_replay import CLASSE_EVENEMENT_REPLAY, corps_commande_replay, evenement_source

router = APIRouter()


class RejeuCreate(BaseModel):
    """Corps d'une demande de rejeu d'événement vers un consommateur (BE-139)."""

    consommateur: str = Field(min_length=1, max_length=150)
    reasonTicket: str = Field(min_length=1, max_length=120)
    idempotencyKey: str = Field(min_length=8, max_length=120)


class CommandeRejeuResponse(BaseModel):
    """Intention de rejeu renvoyée au demandeur."""

    model_config = ConfigDict(from_attributes=True)

    commandId: uuid.UUID
    commandType: str
    status: Literal["intention", "approuvee", "rejetee", "executee", "echec", "resultat_inconnu"]
    tenantId: uuid.UUID | None
    eventId: uuid.UUID
    consommateur: str
    reasonTicket: str
    idempotencyKey: str
    createdAtUtc: datetime


def _reponse(commande: AdminCommand) -> CommandeRejeuResponse:
    """Représentation d'une intention de rejeu : événement et consommateur repris du corps."""
    return CommandeRejeuResponse(
        commandId=commande.commandId,
        commandType=commande.commandType,
        status=commande.status,
        tenantId=commande.tenantId,
        eventId=uuid.UUID(commande.targetObjectId),
        consommateur=(commande.payload or {}).get("consommateur"),
        reasonTicket=commande.reasonTicket,
        idempotencyKey=commande.idempotencyKey,
        createdAtUtc=commande.createdAtUtc,
    )


@router.post(
    "/events/{event_id}/replay-commands",
    response_model=CommandeRejeuResponse,
    status_code=201,
    summary="Demander le rejeu d'un événement à effet métier (BE-139)",
)
async def demander_rejeu(
    event_id: uuid.UUID,
    data: RejeuCreate,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CommandeRejeuResponse:
    """Crée l'intention de rejeu, idempotente par acteur et clé.

    Ordre : événement existant (404), droit sur le tenant de l'événement (403), idempotence (200
    ou 409), puis intention écrite. Le tenant de la commande est celui de l'événement, jamais celui
    de la requête : c'est ce qui rend l'isolation (CA-3) indépendante du corps. Aucun effet n'est
    produit ici ; l'exécution relève de la garde, après approbation distincte.
    """
    evenement = await evenement_source(db, event_id)
    tenant_id = evenement.tenantId
    role = await role_effectif(db, current_user.id, CLASSE_EVENEMENT_REPLAY, tenant_id)
    corps = corps_commande_replay(
        event_id=event_id,
        tenant_id=tenant_id,
        consommateur=data.consommateur,
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
