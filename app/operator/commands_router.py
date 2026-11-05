"""Routes des commandes opérateur (BE-124), montées sous `/api/v1/admin`.

Routes :
- `POST /api/v1/admin/commands` : crée une intention de commande, ou renvoie celle
  qui existe déjà pour la même clé d'idempotence et le même corps (200) ;
- `GET /api/v1/admin/commands/{command_id}` : lit une commande (créateur, ou
  responsable de gestion de la portée de la cible) ;
- `POST /api/v1/admin/commands/{command_id}/approve` et `.../reject` : décision unique
  d'un approbateur indépendant (BE-128), corps `{"reasonTicket": ...}` obligatoire.
  Règles et codes dans `app.operator.approval` (403 pour un mauvais rôle, pour
  l'initiateur et pour un tenant étranger ; 409 si une décision existe déjà).

Codes : 201 à la création ; 200 au rejeu identique ; 409 `idempotency_conflict` si la
clé a servi à un autre corps ; 422 pour un corps invalide (motif absent, classe
inconnue) ; 403 `admin_scope_denied` si aucun rôle habilité sur la portée de la cible ;
404 `command_not_found`.

La garde de droit s'exécute avant la recherche d'idempotence : un compte qui a perdu
son droit ne peut pas rejouer une clé pour obtenir la commande d'origine.
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
from app.operator.cases import ROLES_GESTION, erreur_refus, portee_du_cas, roles_actifs_sur_portee
from app.operator.approval import ETAT_APPROUVEE, ETAT_REJETEE, decider_commande
from app.operator.commands import (
    AdminCommand,
    commande_existante,
    corps_identique,
    erreur_commande_introuvable,
    erreur_idempotence,
    exiger_classe_connue,
    nouvelle_commande,
    role_effectif,
)

router = APIRouter()


class CommandeCreate(BaseModel):
    """Corps d'intention. `reasonTicket` est obligatoire (CA-4)."""

    commandType: str = Field(min_length=1, max_length=80)
    commandVersion: int = Field(default=1, ge=1)
    tenantId: uuid.UUID | None = None
    targetObjectType: str = Field(min_length=1, max_length=60)
    targetObjectId: str = Field(min_length=1, max_length=120)
    targetVersionExpected: int | None = Field(default=None, ge=0)
    reasonTicket: str = Field(min_length=1, max_length=120)
    idempotencyKey: str = Field(min_length=8, max_length=120)


class CommandeResponse(BaseModel):
    """Représentation d'une commande opérateur."""

    model_config = ConfigDict(from_attributes=True)

    commandId: uuid.UUID
    commandType: str
    commandVersion: int
    actorId: uuid.UUID
    approverId: uuid.UUID | None
    effectiveRole: str
    effectiveScope: str
    tenantId: uuid.UUID | None
    targetObjectType: str
    targetObjectId: str
    targetVersionExpected: int | None
    reasonTicket: str
    idempotencyKey: str
    correlationId: str | None
    status: Literal["intention", "approuvee", "rejetee"]
    result: dict | None
    createdAtUtc: datetime
    expiresAtUtc: datetime | None


class DecisionCreate(BaseModel):
    """Corps d'une décision d'approbation. Le motif (ticket) est obligatoire (BE-128)."""

    reasonTicket: str = Field(min_length=1, max_length=120)


@router.post(
    "/commands",
    response_model=CommandeResponse,
    status_code=201,
    summary="Créer une intention de commande opérateur (BE-124)",
)
async def creer_commande(
    data: CommandeCreate,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdminCommand:
    """Crée l'intention ou renvoie la commande existante pour cette clé (CA-1, CA-2).

    La course entre deux envois simultanés est tranchée par la contrainte d'unicité
    (acteur, clé) : en cas de collision, la transaction est annulée et la commande
    gagnante est relue et comparée au corps.
    """
    exiger_classe_connue(data.commandType)
    corps = data.model_dump()
    role = await role_effectif(db, current_user.id, data.commandType, data.tenantId)

    existante = await commande_existante(db, current_user.id, data.idempotencyKey)
    if existante is not None:
        if not corps_identique(existante, corps):
            raise erreur_idempotence()
        response.status_code = 200
        return existante

    commande = nouvelle_commande(
        corps=corps,
        actor_id=current_user.id,
        effective_role=role,
        correlation_id=request_id_ctx.get(),
    )
    db.add(commande)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        gagnante = await commande_existante(db, current_user.id, data.idempotencyKey)
        if gagnante is None or not corps_identique(gagnante, corps):
            raise erreur_idempotence()
        response.status_code = 200
        return gagnante
    await db.refresh(commande)
    return commande


@router.post(
    "/commands/{command_id}/approve",
    response_model=CommandeResponse,
    summary="Approuver une commande opérateur par un approbateur indépendant (BE-128)",
)
async def approuver_commande(
    command_id: uuid.UUID,
    data: DecisionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdminCommand:
    """Enregistre l'approbation : la commande passe à `approuvee` (CA-4).

    Voir `app.operator.approval.decider_commande` pour l'ordre des contrôles.
    """
    return await decider_commande(
        db, command_id=command_id, approbateur_id=current_user.id,
        decision=ETAT_APPROUVEE, motif=data.reasonTicket,
    )


@router.post(
    "/commands/{command_id}/reject",
    response_model=CommandeResponse,
    summary="Rejeter une commande opérateur par un approbateur indépendant (BE-128)",
)
async def rejeter_commande(
    command_id: uuid.UUID,
    data: DecisionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdminCommand:
    """Enregistre le rejet : la commande passe à l'état terminal `rejetee` (CA-3)."""
    return await decider_commande(
        db, command_id=command_id, approbateur_id=current_user.id,
        decision=ETAT_REJETEE, motif=data.reasonTicket,
    )


@router.get(
    "/commands/{command_id}",
    response_model=CommandeResponse,
    summary="Lire une commande opérateur (BE-124)",
)
async def lire_commande(
    command_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdminCommand:
    """Lit la commande si l'on en est le créateur ou responsable de gestion de sa portée.

    Hypothèse consignée (QE-ADM-91) : la lecture par un tiers suit la règle de gestion
    de BE-123 ; un compte sans droit sur la portée reçoit 403, 404 si la commande
    n'existe pas.
    """
    commande = await db.get(AdminCommand, command_id)
    if commande is None:
        raise erreur_commande_introuvable()
    if commande.actorId == current_user.id:
        return commande
    roles = await roles_actifs_sur_portee(db, current_user.id, portee_du_cas(commande.tenantId))
    if roles & ROLES_GESTION:
        return commande
    raise erreur_refus()
