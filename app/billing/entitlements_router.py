"""Routeur des entitlements et décisions d'accès (BE-201).

Routes :
- POST /api/v1/entitlements : octroi d'un entitlement
- POST /api/v1/entitlements/{entitlementId}/revoke : révocation d'un entitlement
- GET /api/v1/access/decisions : décision d'accès pour une capacité donnée
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.audit.service import record_audit_event
from app.billing.models import SubscriptionEntitlement
from app.billing.permissions import ENTITLEMENT_MANAGE
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.identity.service import require_organization_member
from app.rbac.guards import get_current_organization_id
from app.rbac.service import require_permission

router = APIRouter()


class CreateEntitlementRequest(BaseModel):
    """Modèle de requête pour créer un entitlement."""
    subscriptionId: uuid.UUID
    moduleCode: str
    entitlementCode: str
    sourceAttribution: str
    niveauApplication: str
    startsAt: datetime
    endsAt: Optional[datetime] = None


class CreateEntitlementResponse(BaseModel):
    """Modèle de réponse pour la création d'un entitlement."""
    entitlementId: str


class AccessDecision(BaseModel):
    """Modèle de décision d'accès."""
    decision: str  # "granted" or "denied"
    provenance: Optional[dict] = None


@router.post(
    "/entitlements",
    response_model=CreateEntitlementResponse,
    status_code=201,
    dependencies=[Depends(require_permission(ENTITLEMENT_MANAGE))],
)
async def create_entitlement(
    data: CreateEntitlementRequest,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> CreateEntitlementResponse:
    """Octroie un entitlement à un abonnement.

    CA-1 : une action dont seul l'entitlement est présent renvoie 403 (non-substitution)
           -> un entitlement n'est pas une permission d'action

    CA-5 : un double octroi identique ne crée pas de second entitlement (idempotence)
    """
    # Chercher l'entitlement existant avec la même clé (subscriptionId + entitlementCode)
    existing = await db.scalar(
        select(SubscriptionEntitlement).where(
            and_(
                SubscriptionEntitlement.subscriptionId == data.subscriptionId,
                SubscriptionEntitlement.entitlementCode == data.entitlementCode,
            )
        )
    )

    if existing:
        # CA-5 : idempotence - retourner l'entitlement existant
        return CreateEntitlementResponse(entitlementId=str(existing.id))

    # Créer le nouvel entitlement
    entitlement = SubscriptionEntitlement(
        subscriptionId=data.subscriptionId,
        moduleCode=data.moduleCode,
        entitlementCode=data.entitlementCode,
        status="active",
        startsAt=data.startsAt,
        endsAt=data.endsAt,
        niveauApplication=data.niveauApplication,
        sourceAttribution=data.sourceAttribution,
        organizationId=organization_id,
    )

    db.add(entitlement)
    await db.flush()

    # CA-6 : enregistrer dans l'audit
    await record_audit_event(
        db=db,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        action="entitlement.granted",
        entity_type="entitlement",
        entity_id=entitlement.id,
    )

    await db.commit()
    return CreateEntitlementResponse(entitlementId=str(entitlement.id))


@router.post(
    "/entitlements/{entitlement_id}/revoke",
    dependencies=[Depends(require_permission(ENTITLEMENT_MANAGE))],
)
async def revoke_entitlement(
    entitlement_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Révoque un entitlement.

    CA-3 : après révocation, un cache obsolète n'accorde plus l'accès
    CA-6 : chaque révocation écrit une entrée d'audit
    """
    entitlement = await db.scalar(
        select(SubscriptionEntitlement).where(
            SubscriptionEntitlement.id == entitlement_id
        )
    )

    if not entitlement:
        return {"status": "error", "message": "Entitlement not found"}

    # Mettre à jour le statut à "revoked"
    entitlement.status = "revoked"
    await db.flush()

    # CA-6 : enregistrer dans l'audit
    await record_audit_event(
        db=db,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        action="entitlement.revoked",
        entity_type="entitlement",
        entity_id=entitlement_id,
    )

    await db.commit()
    return {"status": "success"}


@router.get(
    "/access/decisions",
    response_model=AccessDecision,
    dependencies=[Depends(require_organization_member)],
)
async def get_access_decision(
    capability: str = Query(..., description="Capability code to check access for"),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> AccessDecision:
    """Retourne la décision d'accès et sa provenance pour une capacité donnée.

    CA-2 : la décision renvoie la décision et sa provenance
    CA-3 : après révocation, le cache obsolète n'accorde plus l'accès
    CA-4 : isolation : une décision pour le tenant B ne reflète pas un entitlement du tenant A
    """
    # Chercher un entitlement actif et valide pour cette capacité dans l'organisation courante
    entitlement = await db.scalar(
        select(SubscriptionEntitlement).where(
            and_(
                SubscriptionEntitlement.organizationId == organization_id,
                SubscriptionEntitlement.entitlementCode == capability,
                SubscriptionEntitlement.status == "active",
                # Vérifier les dates de validité
                SubscriptionEntitlement.startsAt <= datetime.now(timezone.utc),
            )
        )
    )

    # Vérifier que l'entitlement n'a pas expiré
    if entitlement and entitlement.endsAt and entitlement.endsAt < datetime.now(timezone.utc):
        entitlement = None

    if entitlement:
        # CA-2 : retourner la décision et la provenance
        return AccessDecision(
            decision="granted",
            provenance={
                "entitlementId": str(entitlement.id),
                "source": entitlement.sourceAttribution,
            }
        )
    else:
        # CA-4 : isolation implicitée (on cherche dans l'organisation courante)
        return AccessDecision(
            decision="denied",
            provenance=None,
        )
