"""Liaison facturation vers entitlements : consommation des événements de service (BE-058).

Le service de facturation envoie à Zylo Office des événements qui modifient les droits
d'une organisation. Ce module est le seul endroit qui les traduit en écritures sur
`subscription_entitlement`. La route d'entrée (`app/billing/entitlement_events_router.py`)
ne fait que vérifier l'identité de service puis déléguer ici.

Types d'événements (QE-MOD-01, recommandation appliquée : route unique) :
- `granted` : crée l'entitlement identifié par (`subscriptionId`, `entitlementCode`), ou le met
  à jour s'il existe. La source (`sourceAttribution`) est celle reçue, sans valeur par défaut.
  Chaque écriture incrémente `stateVersion` (1 à la création, BE-045).
- `ended` : fin d'abonnement. Pour la cause `fin_abonnement`, l'entitlement passe à
  `expired` et `endsAt` prend la date de fin reçue. Pour la cause `impaye`, la règle n'est pas
  décidée (QE-MOD-06, défaut appliqué) : aucune écriture, issue `reconciliation_required`.

Ce qui n'est pas traité ici (signalé, non implémenté) :
- le changement d'offre, traduit en transitions de BE-041 dans la définition : la machine
  d'états de BE-041 porte les états d'installation des modules, pas les entitlements. Aucun
  type d'événement ne le couvre encore ;
- la suspension (`suspended`) : hors des valeurs de la contrainte `ck_subscription_entitlement_status`.

Idempotence : chaque `eventId` est écrit une fois dans `entitlement_source_events` (unique).
Un rejeu du même `eventId` renvoie `duplicate=True` et ne produit aucun effet, même si le
contenu a changé. La ligne de journal et l'effet sont écrits dans la même transaction : si
l'insertion concurrente du même `eventId` échoue, la transaction est annulée et le rejeu est
traité comme un doublon.

Journal des refus : une organisation ou un abonnement inconnu est journalisé (issue
`organisation_inconnue` ou `abonnement_inconnu`) avant la levée du 404. La ligne est
validée (commit) avant la levée, pour survivre à l'annulation de la requête.

L'identité de service est vérifiée par la route, jamais ici : ce module suppose un appelant
déjà authentifié comme service.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import EntitlementSourceEvent, Subscription, SubscriptionEntitlement
from app.core.errors import AppError
from app.identity.models import Organization

ISSUE_APPLIQUEE = "applied"
ISSUE_RECONCILIATION = "reconciliation_required"
ISSUE_ORGANISATION_INCONNUE = "organisation_inconnue"
ISSUE_ABONNEMENT_INCONNU = "abonnement_inconnu"
ISSUE_AUCUN_ENTITLEMENT = "aucun_entitlement"


class EvenementGranted(BaseModel):
    """Événement `granted` : attribution ou mise à jour d'un droit de l'organisation."""

    eventId: str = Field(min_length=1, max_length=160)
    type: Literal["granted"]
    organizationId: uuid.UUID
    subscriptionId: uuid.UUID
    moduleCode: str = Field(min_length=1, max_length=100)
    entitlementCode: str = Field(min_length=1, max_length=150)
    sourceAttribution: Literal["offre", "achat_additionnel", "essai", "allocation_admin", "usage_reel"]
    niveauApplication: Literal["organisation", "utilisateur"]
    startsAt: datetime
    endsAt: datetime | None = None
    quotaLimite: int | None = Field(default=None, gt=0)


class EvenementEnded(BaseModel):
    """Événement `ended` : fin d'abonnement, ou cause impayée (non décidée, QE-MOD-06)."""

    eventId: str = Field(min_length=1, max_length=160)
    type: Literal["ended"]
    organizationId: uuid.UUID
    subscriptionId: uuid.UUID
    moduleCode: str = Field(min_length=1, max_length=100)
    entitlementCode: str = Field(min_length=1, max_length=150)
    endedAt: datetime
    cause: Literal["fin_abonnement", "impaye"]


EvenementEntitlement = Annotated[Union[EvenementGranted, EvenementEnded], Field(discriminator="type")]


class ResultatEvenementEntitlement(BaseModel):
    """Réponse : `outcome` décrit l'effet (ou son absence), `duplicate` un rejeu d'`eventId`."""

    eventId: str
    outcome: str
    duplicate: bool


async def _doublon(db: AsyncSession, event_id: str) -> ResultatEvenementEntitlement | None:
    """Renvoie le résultat initial si `eventId` a déjà été reçu, sinon None."""
    ligne = await db.scalar(select(EntitlementSourceEvent).where(EntitlementSourceEvent.eventId == event_id))
    if ligne is None:
        return None
    return ResultatEvenementEntitlement(eventId=event_id, outcome=ligne.outcome, duplicate=True)


async def _journaliser_refus(db: AsyncSession, evenement, issue: str, subscription_id: uuid.UUID | None) -> None:
    """Journalise un refus et valide la ligne avant la levée d'erreur (CA-5)."""
    db.add(EntitlementSourceEvent(
        eventId=evenement.eventId, eventType=evenement.type, organizationId=evenement.organizationId,
        subscriptionId=subscription_id, entitlementId=None, outcome=issue,
    ))
    await db.commit()


async def traiter_evenement_entitlement(db: AsyncSession, evenement: EvenementEntitlement) -> ResultatEvenementEntitlement:
    """Traduit un événement de service en écriture d'entitlement, une seule fois par `eventId`.

    Ordre d'exécution :
    1. doublon : même `eventId` déjà journalisé -> résultat initial, `duplicate=True`, aucun effet ;
    2. organisation inconnue -> journal `organisation_inconnue`, puis AppError 404 `organization_not_found` ;
    3. abonnement absent de cette organisation -> journal `abonnement_inconnu`, puis 404
       `entitlement_subscription_unknown` (le message ne révèle pas l'existence d'un autre tenant) ;
    4. effet selon le type (`granted`, `ended`), puis ligne de journal, dans une seule transaction.

    Une `IntegrityError` levée au flush sans doublon retrouvé est relancée telle quelle : elle
    signale une violation d'une autre contrainte (par exemple une clé étrangère), pas un rejeu.
    """
    existant = await _doublon(db, evenement.eventId)
    if existant is not None:
        return existant

    organisation = await db.get(Organization, evenement.organizationId)
    if organisation is None:
        await _journaliser_refus(db, evenement, ISSUE_ORGANISATION_INCONNUE, evenement.subscriptionId)
        raise AppError(code="organization_not_found", message="Organisation introuvable.", status_code=404)

    abonnement = await db.scalar(select(Subscription).where(
        Subscription.id == evenement.subscriptionId, Subscription.organizationId == evenement.organizationId,
    ))
    if abonnement is None:
        await _journaliser_refus(db, evenement, ISSUE_ABONNEMENT_INCONNU, None)
        raise AppError(
            code="entitlement_subscription_unknown", message="Abonnement introuvable pour cette organisation.",
            status_code=404,
        )

    entitlement = await db.scalar(select(SubscriptionEntitlement).where(
        SubscriptionEntitlement.subscriptionId == evenement.subscriptionId,
        SubscriptionEntitlement.entitlementCode == evenement.entitlementCode,
    ))

    if isinstance(evenement, EvenementGranted):
        issue, entitlement = _appliquer_granted(db, evenement, entitlement)
    elif evenement.cause == "impaye":
        issue = ISSUE_RECONCILIATION
    else:
        issue = _appliquer_fin(evenement, entitlement)

    db.add(EntitlementSourceEvent(
        eventId=evenement.eventId, eventType=evenement.type, organizationId=evenement.organizationId,
        subscriptionId=evenement.subscriptionId,
        entitlementId=entitlement.id if entitlement is not None and issue == ISSUE_APPLIQUEE else None,
        outcome=issue,
    ))
    try:
        await db.flush()
    except IntegrityError:
        # Insertion concurrente du même eventId : l'autre transaction gagne, celle-ci est annulée.
        await db.rollback()
        existant = await _doublon(db, evenement.eventId)
        if existant is None:
            raise
        return existant
    await db.commit()
    return ResultatEvenementEntitlement(eventId=evenement.eventId, outcome=issue, duplicate=False)


def _appliquer_granted(
    db: AsyncSession, evenement: EvenementGranted, entitlement: SubscriptionEntitlement | None,
) -> tuple[str, SubscriptionEntitlement]:
    """Crée ou met à jour l'entitlement avec la source reçue ; incrémente `stateVersion`."""
    if entitlement is None:
        entitlement = SubscriptionEntitlement(
            organizationId=evenement.organizationId,
            subscriptionId=evenement.subscriptionId,
            moduleCode=evenement.moduleCode,
            entitlementCode=evenement.entitlementCode,
            status="active",
            startsAt=evenement.startsAt,
            endsAt=evenement.endsAt,
            quotaLimite=evenement.quotaLimite,
            niveauApplication=evenement.niveauApplication,
            sourceAttribution=evenement.sourceAttribution,
            stateVersion=1,
        )
        db.add(entitlement)
    else:
        entitlement.status = "active"
        entitlement.startsAt = evenement.startsAt
        entitlement.endsAt = evenement.endsAt
        entitlement.quotaLimite = evenement.quotaLimite
        entitlement.niveauApplication = evenement.niveauApplication
        entitlement.sourceAttribution = evenement.sourceAttribution
        entitlement.stateVersion = entitlement.stateVersion + 1
    return ISSUE_APPLIQUEE, entitlement


def _appliquer_fin(evenement: EvenementEnded, entitlement: SubscriptionEntitlement | None) -> str:
    """Fin d'abonnement : passe l'entitlement à `expired` à la date de fin reçue."""
    if entitlement is None:
        return ISSUE_AUCUN_ENTITLEMENT
    entitlement.status = "expired"
    entitlement.endsAt = evenement.endedAt
    entitlement.stateVersion = entitlement.stateVersion + 1
    return ISSUE_APPLIQUEE


