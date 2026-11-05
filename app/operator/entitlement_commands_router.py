"""Routes des commandes d'entitlement et de module (BE-135), montées sous `/api/v1/admin`.

Routes :
- `POST /api/v1/admin/organizations/{organization_id}/entitlements/commands` : crée
  l'intention de changement de module (201), ou renvoie la même intention au rejeu
  identique (200) ; 409 `idempotency_conflict` si la clé a servi à un autre corps ;
  403 si le compte n'a pas le rôle de gestion sur ce tenant (CA-2, CA-3) ; 422 si le
  module est inconnu ou si l'opération n'est pas `activation` ou `desactivation`.
- `PATCH /api/v1/admin/organizations/{organization_id}/entitlements/{entitlement_id}` :
  toujours 405 (CA-1). Un entitlement dérivé se change par une commande, jamais par écriture.

La preview de l'intention reste `POST /api/v1/admin/commands/{id}/preview` (BE-125) ; ses
effets de classe `entitlement.module` sont ajoutés par `app.operator.entitlement_commands`.
La logique de droit, d'idempotence et d'événement vit dans ce module et dans
`app.operator.commands` ; ce fichier ne fait que la mise en forme HTTP.
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
from app.operator.entitlement_commands import (
    corps_commande,
    ecrire_evenement_invalidation,
    erreur_entitlement_derive,
    exiger_module_connu,
    role_pour_changement,
)

router = APIRouter()


class ChangementModuleCreate(BaseModel):
    """Corps d'une demande de changement de module pour une organisation (BE-135)."""

    moduleCode: str = Field(min_length=1, max_length=100)
    operation: Literal["activation", "desactivation"]
    reasonTicket: str = Field(min_length=1, max_length=120)
    idempotencyKey: str = Field(min_length=8, max_length=120)
    targetVersionExpected: int | None = Field(default=None, ge=0)


class CommandeEntitlementResponse(BaseModel):
    """Intention d'entitlement renvoyée au demandeur."""

    model_config = ConfigDict(from_attributes=True)

    commandId: uuid.UUID
    commandType: str
    status: Literal["intention", "approuvee", "rejetee"]
    tenantId: uuid.UUID
    moduleCode: str
    operation: str
    reasonTicket: str
    idempotencyKey: str
    createdAtUtc: datetime


def _reponse(commande: AdminCommand) -> CommandeEntitlementResponse:
    """Représentation d'une intention : module et opération repris de sa charge utile."""
    charge = commande.payload or {}
    return CommandeEntitlementResponse(
        commandId=commande.commandId,
        commandType=commande.commandType,
        status=commande.status,
        tenantId=commande.tenantId,
        moduleCode=charge.get("moduleCode"),
        operation=charge.get("operation"),
        reasonTicket=commande.reasonTicket,
        idempotencyKey=commande.idempotencyKey,
        createdAtUtc=commande.createdAtUtc,
    )


@router.post(
    "/organizations/{organization_id}/entitlements/commands",
    response_model=CommandeEntitlementResponse,
    status_code=201,
    summary="Demander un changement d'entitlement ou de module (BE-135)",
)
async def demander_changement_module(
    organization_id: uuid.UUID,
    data: ChangementModuleCreate,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CommandeEntitlementResponse:
    """Crée l'intention de changement de module, idempotente par acteur et clé.

    Ordre : droit sur le tenant de la route (403), module connu (422), idempotence (200 ou
    409), puis intention et événement d'invalidation écrits dans la même transaction (CA-5).
    Aucun droit n'est modifié ici : l'exécution relève du domaine propriétaire (QE-ADM-22).
    """
    role = await role_pour_changement(db, current_user.id, organization_id)
    await exiger_module_connu(db, data.moduleCode)
    corps = corps_commande(
        organization_id=organization_id,
        module_code=data.moduleCode,
        operation=data.operation,
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
    await ecrire_evenement_invalidation(db, commande, current_user.id)
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


@router.patch(
    "/organizations/{organization_id}/entitlements/{entitlement_id}",
    status_code=405,
    summary="Écriture directe d'un entitlement dérivé : refusée (BE-135, CA-1)",
)
async def ecrire_entitlement_directement(organization_id: uuid.UUID, entitlement_id: uuid.UUID) -> None:
    """Toujours 405 : un entitlement dérivé ne s'écrit que par une commande (voir `app.operator.entitlement_commands`).

    Cette route existe pour refuser explicitement l'écriture directe ; sans elle, FastAPI
    répondrait 404 sur ce chemin, ce qui ne dirait pas que l'entitlement existe.
    """
    raise erreur_entitlement_derive()
