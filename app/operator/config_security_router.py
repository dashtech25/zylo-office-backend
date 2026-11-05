"""Routes de changement de configuration et de gel de credential (BE-141), sous `/api/v1/admin`.

Routes :
- `POST /api/v1/admin/organizations/{organization_id}/config-changes` : crée l'intention
  de changement de réglage (201), ou renvoie la même intention au rejeu identique (200) ;
  403 sans rôle de gestion sur le tenant (CA-3) ; 422 si le réglage est inconnu ; 409
  `idempotency_conflict` si la clé a servi à un autre corps.
- `POST /api/v1/admin/credentials/{credential_id}/freeze` : crée l'intention de gel (201)
  ou renvoie la même au rejeu (200) ; 403 pour tout rôle autre que sécurité (CA-1) ;
  404 si le credential est inconnu ; 409 si la clé a servi à un autre corps.

Les réponses ne contiennent jamais de valeur fournie ni de valeur de secret (CA-2) : seuls
l'identifiant, la classe, la cible, le motif et l'action sont renvoyés.

L'exécution (et donc l'approbation distincte, CA-4) passe par `app.operator.guard` ; ce
fichier ne fait que la mise en forme HTTP. Le droit est évalué avant l'idempotence, comme
dans BE-124 : un compte qui a perdu son droit ne peut pas rejouer une clé.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

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
from app.operator.config_security import (
    corps_changement_configuration,
    corps_gel_credential,
    credential_connu,
    exiger_reglage_connu,
    role_pour_configuration,
    role_pour_gel,
)

router = APIRouter()


class ChangementConfigurationCreate(BaseModel):
    """Corps d'une demande de changement de réglage pour une organisation (BE-141)."""

    settingKey: str = Field(min_length=1, max_length=150)
    valeur: str = Field(min_length=1, max_length=4000)
    reasonTicket: str = Field(min_length=1, max_length=120)
    idempotencyKey: str = Field(min_length=8, max_length=120)


class GelCredentialCreate(BaseModel):
    """Corps d'une demande de gel de credential (BE-141). Aucune valeur n'est acceptée."""

    reasonTicket: str = Field(min_length=1, max_length=120)
    idempotencyKey: str = Field(min_length=8, max_length=120)


class CommandeConfigurationResponse(BaseModel):
    """Intention de configuration ou de gel renvoyée au demandeur, sans valeur."""

    model_config = ConfigDict(from_attributes=True)

    commandId: uuid.UUID
    commandType: str
    status: Literal["intention", "approuvee", "rejetee"]
    action: str
    tenantId: uuid.UUID | None
    targetObjectType: str
    targetObjectId: str
    settingKey: str | None
    reasonTicket: str
    idempotencyKey: str
    createdAtUtc: datetime


def _reponse(commande: AdminCommand) -> CommandeConfigurationResponse:
    """Représentation d'une intention : action et réglage repris de sa charge utile, jamais la valeur."""
    charge: dict[str, Any] = commande.payload or {}
    return CommandeConfigurationResponse(
        commandId=commande.commandId,
        commandType=commande.commandType,
        status=commande.status,
        action=charge.get("action"),
        tenantId=commande.tenantId,
        targetObjectType=commande.targetObjectType,
        targetObjectId=commande.targetObjectId,
        settingKey=charge.get("settingKey"),
        reasonTicket=commande.reasonTicket,
        idempotencyKey=commande.idempotencyKey,
        createdAtUtc=commande.createdAtUtc,
    )


async def _enregistrer_ou_rejouer(
    db: AsyncSession,
    response: Response,
    *,
    actor_id: uuid.UUID,
    corps: dict[str, Any],
    effective_role: str,
    cle: str,
) -> CommandeConfigurationResponse:
    """Crée l'intention, ou renvoie l'existante (200) ; 409 si la clé a servi à un autre corps.

    Même schéma que BE-135 : la contrainte d'unicité (acteur, clé) tranche une course.
    """
    existante = await commande_existante(db, actor_id, cle)
    if existante is not None:
        if not corps_identique(existante, corps):
            raise erreur_idempotence()
        response.status_code = 200
        return _reponse(existante)

    commande = nouvelle_commande(
        corps=corps,
        actor_id=actor_id,
        effective_role=effective_role,
        correlation_id=request_id_ctx.get(),
    )
    db.add(commande)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        gagnante = await commande_existante(db, actor_id, cle)
        if gagnante is None or not corps_identique(gagnante, corps):
            raise erreur_idempotence()
        response.status_code = 200
        return _reponse(gagnante)
    await db.refresh(commande)
    return _reponse(commande)


@router.post(
    "/organizations/{organization_id}/config-changes",
    response_model=CommandeConfigurationResponse,
    status_code=201,
    summary="Demander un changement de configuration d'une organisation (BE-141)",
)
async def demander_changement_configuration(
    organization_id: uuid.UUID,
    data: ChangementConfigurationCreate,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CommandeConfigurationResponse:
    """Crée l'intention de changement de réglage. La valeur est empreintée, jamais conservée.

    Ordre : droit sur le tenant de la route (403), réglage connu (422), idempotence (200 ou
    409), puis intention. Aucun réglage n'est modifié ici : l'effet relève de BE-237.
    """
    role = await role_pour_configuration(db, current_user.id, organization_id)
    await exiger_reglage_connu(db, data.settingKey)
    corps = corps_changement_configuration(
        organization_id=organization_id,
        setting_key=data.settingKey,
        valeur=data.valeur,
        reason_ticket=data.reasonTicket,
        idempotency_key=data.idempotencyKey,
    )
    return await _enregistrer_ou_rejouer(
        db, response, actor_id=current_user.id, corps=corps, effective_role=role, cle=data.idempotencyKey,
    )


@router.post(
    "/credentials/{credential_id}/freeze",
    response_model=CommandeConfigurationResponse,
    status_code=201,
    summary="Demander le gel d'un credential (BE-141)",
)
async def demander_gel_credential(
    credential_id: uuid.UUID,
    data: GelCredentialCreate,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CommandeConfigurationResponse:
    """Crée l'intention de gel. Le gel n'a pas de tenant : la portée est la plateforme.

    Ordre : droit sécurité sur la plateforme (403), credential connu (404), idempotence
    (200 ou 409), puis intention. Le gel effectif relève du domaine propriétaire (BE-230).
    """
    role = await role_pour_gel(db, current_user.id)
    credential = await credential_connu(db, credential_id)
    corps = corps_gel_credential(
        credential=credential, reason_ticket=data.reasonTicket, idempotency_key=data.idempotencyKey,
    )
    return await _enregistrer_ou_rejouer(
        db, response, actor_id=current_user.id, corps=corps, effective_role=role, cle=data.idempotencyKey,
    )
