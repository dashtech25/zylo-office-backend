"""Allocation des sièges d'un entitlement aux membres d'une organisation (BE-046).

Un siège (`EntitlementAllocation`, table `entitlement_allocations`) rattache un membre à un
entitlement de l'organisation. Le nombre de sièges actifs est borné par `quotaLimite` de
l'entitlement ; sans quota (`quotaLimite` nul), aucune borne n'est appliquée.

Règles :
- Isolation : l'entitlement est toujours cherché avec `organizationId` = organisation courante.
  Un entitlement d'une autre organisation donne 404 `entitlement_not_found`, sans révéler
  son existence. La garde d'organisation (app/rbac/guards.py) refuse déjà un chemin ou un
  en-tête étranger ; ce service ne s'y fie pas seul.
- `organizationId` du siège est copié de l'entitlement verrouillé, jamais du client.
- Le `userId` doit être membre de l'organisation (`OrganizationUser`), sinon 422
  `allocation_user_not_member`.
- Concurrence : l'entitlement est verrouillé (`SELECT ... FOR UPDATE`) avant tout comptage.
  Deux attributions simultanées sur le dernier siège se succèdent : la seconde voit la
  version déjà incrémentée et le compte à jour. C'est ce verrou qui garantit CA-5 ; un
  comptage sans verrou laisserait passer deux lignes.
- Version d'état : le corps porte `stateVersion`, version lue par le client. Si elle ne
  correspond plus à `subscription_entitlement.stateVersion`, 409 `entitlement_state_conflict`.
  Chaque attribution ou révocation réussie incrémente `stateVersion` (BE-045 : compteur de
  version de l'état).
- Dépassement : 409 `ENTITLEMENT_SEAT_LIMIT_REACHED`, refus par défaut (QE-MOD-04), sans
  ligne créée.
- Révocation : `revokedAt` est renseigné, la ligne est conservée. Le siège redevient
  disponible (l'index unique partiel ne porte que sur les lignes actives).
- Événement : chaque attribution et chaque révocation écrivent une entrée d'audit
  `EntitlementAllocationChanged` (événement nommé dans BE-056). L'entrée est écrite dans la
  même transaction que le changement : pas d'écriture sans changement, ni l'inverse.

Les fonctions n'effectuent pas la vérification de permission : la route porte
`require_permission(ORGANIZATION_ENTITLEMENT_ALLOCATE | ORGANIZATION_ENTITLEMENT_REVOKE)`.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.billing.models import EntitlementAllocation, SubscriptionEntitlement
from app.core.errors import AppError
from app.identity.models import OrganizationUser

ACTION_EVENEMENT = "EntitlementAllocationChanged"


async def _verrouiller_entitlement(
    db: AsyncSession, organization_id: uuid.UUID, entitlement_id: uuid.UUID
) -> SubscriptionEntitlement:
    """Charge l'entitlement de l'organisation avec un verrou de ligne, ou lève 404.

    Le verrou sérialise les attributions et révocations concurrentes sur un même entitlement.
    """
    entitlement = await db.scalar(
        select(SubscriptionEntitlement)
        .where(
            SubscriptionEntitlement.id == entitlement_id,
            SubscriptionEntitlement.organizationId == organization_id,
        )
        .with_for_update()
    )
    if entitlement is None:
        raise AppError(code="entitlement_not_found", message="Entitlement introuvable.", status_code=404)
    return entitlement


async def _nombre_sieges_actifs(db: AsyncSession, entitlement_id: uuid.UUID) -> int:
    return await db.scalar(
        select(func.count(EntitlementAllocation.id)).where(
            EntitlementAllocation.entitlementId == entitlement_id,
            EntitlementAllocation.revokedAt.is_(None),
        )
    ) or 0


async def attribuer_siege(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    organization_id: uuid.UUID,
    entitlement_id: uuid.UUID,
    user_id: uuid.UUID,
    state_version: int,
) -> EntitlementAllocation:
    """Attribue un siège actif de l'entitlement à un membre, puis valide la transaction.

    Ordre des contrôles, tous avant toute écriture : entitlement de l'organisation (404),
    appartenance du membre (422), version d'état (409), siège déjà actif (409), quota (409).
    """
    entitlement = await _verrouiller_entitlement(db, organization_id, entitlement_id)

    membre = await db.scalar(select(OrganizationUser.id).where(
        OrganizationUser.organizationId == organization_id,
        OrganizationUser.userId == user_id,
    ))
    if membre is None:
        raise AppError(
            code="allocation_user_not_member",
            message="L'utilisateur n'est pas membre de cette organisation.",
            status_code=422,
        )
    if state_version != entitlement.stateVersion:
        raise AppError(
            code="entitlement_state_conflict",
            message="La version d'état de l'entitlement a changé. Relire avant de réessayer.",
            status_code=409,
        )
    deja_actif = await db.scalar(select(EntitlementAllocation.id).where(
        EntitlementAllocation.entitlementId == entitlement_id,
        EntitlementAllocation.userId == user_id,
        EntitlementAllocation.revokedAt.is_(None),
    ))
    if deja_actif is not None:
        raise AppError(
            code="allocation_already_active",
            message="Ce membre détient déjà un siège actif sur cet entitlement.",
            status_code=409,
        )
    if entitlement.quotaLimite is not None and await _nombre_sieges_actifs(db, entitlement_id) >= entitlement.quotaLimite:
        raise AppError(
            code="ENTITLEMENT_SEAT_LIMIT_REACHED",
            message="Le nombre de sièges de cet entitlement est atteint.",
            status_code=409,
        )

    allocation = EntitlementAllocation(
        entitlementId=entitlement_id,
        organizationId=entitlement.organizationId,
        userId=user_id,
        grantedBy=actor_user_id,
    )
    db.add(allocation)
    entitlement.stateVersion += 1
    await db.flush()
    await record_audit_event(
        db, organization_id, actor_user_id, ACTION_EVENEMENT, "EntitlementAllocation", allocation.id,
        "Siège d'entitlement attribué.", {"entitlementId": str(entitlement_id), "userId": str(user_id), "change": "granted"},
    )
    await db.commit()
    await db.refresh(allocation)
    return allocation


async def revoquer_siege(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    organization_id: uuid.UUID,
    entitlement_id: uuid.UUID,
    user_id: uuid.UUID,
) -> EntitlementAllocation:
    """Révoque le siège actif d'un membre : renseigne `revokedAt`, ne supprime rien.

    404 `allocation_not_found` si le membre n'a pas de siège actif sur cet entitlement.
    """
    entitlement = await _verrouiller_entitlement(db, organization_id, entitlement_id)
    allocation = await db.scalar(select(EntitlementAllocation).where(
        EntitlementAllocation.entitlementId == entitlement_id,
        EntitlementAllocation.userId == user_id,
        EntitlementAllocation.revokedAt.is_(None),
    ))
    if allocation is None:
        raise AppError(code="allocation_not_found", message="Siège actif introuvable.", status_code=404)

    allocation.revokedAt = datetime.now(timezone.utc)
    entitlement.stateVersion += 1
    await record_audit_event(
        db, organization_id, actor_user_id, ACTION_EVENEMENT, "EntitlementAllocation", allocation.id,
        "Siège d'entitlement révoqué.", {"entitlementId": str(entitlement_id), "userId": str(user_id), "change": "revoked"},
    )
    await db.commit()
    await db.refresh(allocation)
    return allocation
