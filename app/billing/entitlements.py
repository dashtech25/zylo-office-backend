"""Entitlements d'abonnement : attribution, calcul de l'état et écriture gardée (BE-024).

Un entitlement (`SubscriptionEntitlement`, table `subscription_entitlement`) est un
droit accordé à une organisation : une capacité, une source, un niveau d'application,
un quota éventuel et un effet d'accès (`status`). Ce module est la seule porte d'entrée
pour le créer, le lire et calculer son état.

Règles :
- Source de vérité : l'état serveur. Un webhook de paiement ou un retour d'interface
  ne crée jamais d'entitlement : `app/billing/router.py` n'enregistre que l'événement.
- Les entitlements d'une offre sont dérivés de la version de plan que l'abonnement
  référence (`Subscription.planVersionId`, immuable), et `offreId` la mémorise.
- Écriture : permission `entitlement.manage` (app/billing/permissions.py), vérifiée par
  `rbac/service.py::user_has_permission`. Sans elle, 403 et aucune ligne écrite.
- Lecture : limitée à une organisation. Une ligne d'une autre organisation n'est jamais
  renvoyée. Une offre globale (`organizationId` nul) n'apparaît dans aucune lecture
  d'organisation.
- `expired` n'est pas une valeur stockée automatiquement : c'est un état calculé à partir
  de `endsAt` par `calculer_entitlements`. Les autres états (`active`, `inactive`,
  `blocked`) sont stockés dans `status`.

Les valeurs énumérées (`NIVEAUX_APPLICATION`, `SOURCES_ATTRIBUTION`, `ETATS_ENTITLEMENT`)
sont répétées par les contraintes CHECK de la table : toute évolution doit toucher les
deux, avec une migration.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import Capability, Plan, PlanVersion, Subscription, SubscriptionEntitlement
from app.billing.permissions import ENTITLEMENT_MANAGE
from app.core.errors import AppError
from app.rbac.service import user_has_permission

NIVEAUX_APPLICATION: tuple[str, ...] = ("organisation", "utilisateur")
SOURCES_ATTRIBUTION: tuple[str, ...] = ("offre", "achat_additionnel", "essai", "allocation_admin", "usage_reel")
# `expired` est calculé ; les trois autres sont stockés dans `status`.
ETATS_ENTITLEMENT: tuple[str, ...] = ("active", "inactive", "expired", "blocked")


@dataclass(frozen=True)
class EntitlementCalcule:
    """Vue d'un entitlement pour une lecture : l'état est calculé, pas stocké."""

    id: uuid.UUID
    organizationId: uuid.UUID | None
    subscriptionId: uuid.UUID
    moduleCode: str
    entitlementCode: str
    offreId: uuid.UUID | None
    capaciteId: uuid.UUID | None
    quotaLimite: int | None
    niveauApplication: str
    sourceAttribution: str
    etat: str


async def _capacite_pour_code(db: AsyncSession, module_code: str, code: str) -> uuid.UUID | None:
    """Rattache un code d'offre à une capacité du registre, si elle existe.

    Un code sans capacité correspondante reste un entitlement valide (`capaciteId` nul) :
    le registre de capacités est alimenté par les modules, pas par le calcul d'abonnement.
    """
    return await db.scalar(select(Capability.id).where(Capability.moduleCode == module_code, Capability.code == code))


async def attribuer_entitlements_offre(
    db: AsyncSession, subscription: Subscription, *, now: datetime | None = None
) -> list[SubscriptionEntitlement]:
    """Crée les entitlements d'un abonnement à partir de sa version de plan.

    Chaque code de `PlanVersion.entitlementCodes` devient une ligne `sourceAttribution`
    = `offre`, `niveauApplication` = `organisation`, rattachée à l'organisation de
    l'abonnement et à la version (`offreId`). La durée suit `subscription.endDate`.

    N'effectue pas de commit : l'appelant contrôle la transaction. Retourne les lignes
    ajoutées à la session (vide si la version ne porte aucun code).
    """
    version = await db.get(PlanVersion, subscription.planVersionId) if subscription.planVersionId else None
    if version is None:
        return []
    plan = await db.get(Plan, subscription.planId)
    module_code = plan.moduleCode if plan is not None else ""
    debut = now or datetime.now(timezone.utc)
    lignes: list[SubscriptionEntitlement] = []
    for code in version.entitlementCodes:
        ligne = SubscriptionEntitlement(
            organizationId=subscription.organizationId,
            subscriptionId=subscription.id,
            moduleCode=module_code,
            entitlementCode=code,
            status="active",
            startsAt=debut,
            endsAt=subscription.endDate,
            offreId=version.id,
            capaciteId=await _capacite_pour_code(db, module_code, code),
            quotaLimite=None,
            niveauApplication="organisation",
            sourceAttribution="offre",
        )
        db.add(ligne)
        lignes.append(ligne)
    await db.flush()
    return lignes


async def calculer_entitlements(
    db: AsyncSession, organization_id: uuid.UUID, *, now: datetime | None = None
) -> list[EntitlementCalcule]:
    """Renvoie les entitlements d'une organisation avec leur état calculé.

    Seules les lignes de `organization_id` sont lues (isolation, CA-4 et CA-10). L'état
    vaut `expired` quand la ligne est `active` mais que `endsAt` est dépassé ; sinon il
    reprend `status`. Une ligne `inactive` ou `blocked` reste telle quelle même si sa date
    de fin est passée : son état stocké prime.
    """
    maintenant = now or datetime.now(timezone.utc)
    lignes = (await db.scalars(
        select(SubscriptionEntitlement)
        .where(SubscriptionEntitlement.organizationId == organization_id)
        .order_by(SubscriptionEntitlement.entitlementCode)
    )).all()
    calcules: list[EntitlementCalcule] = []
    for ligne in lignes:
        etat = ligne.status
        if etat == "active" and ligne.endsAt is not None and ligne.endsAt <= maintenant:
            etat = "expired"
        calcules.append(EntitlementCalcule(
            id=ligne.id,
            organizationId=ligne.organizationId,
            subscriptionId=ligne.subscriptionId,
            moduleCode=ligne.moduleCode,
            entitlementCode=ligne.entitlementCode,
            offreId=ligne.offreId,
            capaciteId=ligne.capaciteId,
            quotaLimite=ligne.quotaLimite,
            niveauApplication=ligne.niveauApplication,
            sourceAttribution=ligne.sourceAttribution,
            etat=etat,
        ))
    return calcules


async def enregistrer_entitlement(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    organization_id: uuid.UUID | None,
    subscription_id: uuid.UUID,
    module_code: str,
    entitlement_code: str,
    starts_at: datetime,
    ends_at: datetime | None = None,
    offre_id: uuid.UUID | None = None,
    capacite_id: uuid.UUID | None = None,
    quota_limite: int | None = None,
    niveau_application: str = "organisation",
    source_attribution: str = "offre",
    status: str = "active",
) -> SubscriptionEntitlement:
    """Écrit un entitlement après contrôle de la permission `entitlement.manage`.

    Le contrôle a lieu avant toute écriture : sans la permission, `AppError` 403 est levé
    et rien n'est ajouté à la session. Les valeurs énumérées et la cohérence
    organisation/source sont ensuite garanties par les contraintes de la base (une
    valeur hors liste ou une capacité inconnue lève `IntegrityError` au commit).
    """
    autorise = await user_has_permission(db, actor_user_id, organization_id, ENTITLEMENT_MANAGE) if organization_id else False
    if not autorise:
        raise AppError(
            code="forbidden",
            message="Permission entitlement.manage requise pour écrire un entitlement.",
            status_code=403,
        )
    ligne = SubscriptionEntitlement(
        organizationId=organization_id,
        subscriptionId=subscription_id,
        moduleCode=module_code,
        entitlementCode=entitlement_code,
        status=status,
        startsAt=starts_at,
        endsAt=ends_at,
        offreId=offre_id,
        capaciteId=capacite_id,
        quotaLimite=quota_limite,
        niveauApplication=niveau_application,
        sourceAttribution=source_attribution,
    )
    db.add(ligne)
    await db.commit()
    await db.refresh(ligne)
    return ligne
