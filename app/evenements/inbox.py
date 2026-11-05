"""Inbox consommateur : réception idempotente, ordre, quarantaine et tentatives bornées (BE-193).

Rôle : recevoir un événement pour un consommateur nommé (`subscriber`) et décider, dans un ordre
fixe, de son sort. Chaque couple (`subscriber`, `eventId`) a une ligne dans `event_inbox`.

Ordre des contrôles (le premier verdict gagne) :
1. doublon (CA-1) : une ligne `processed` ou `quarantine` existe déjà -> `doublon`, aucun effet ;
2. tenant inconnu (CA-2) : aucune organisation pour `tenantId` -> `quarantine`, sans appel du handler ;
3. schéma incompatible (CA-5) : `schemaVersion` absente de `versions_acceptees` -> `quarantine` ;
4. hors ordre (CA-3) : si `ordonne` est vrai et que `aggregateVersion` n'est pas la version suivante
   de l'agrégat (version attendue : une de plus que la plus haute version `processed`, 1 au départ)
   -> `retry`, le handler n'est pas appelé ;
5. sinon le handler est appelé dans un SAVEPOINT. Succès -> `processed`. Échec -> `retry`, ou
   `quarantine` quand le nombre de tentatives atteint `MAX_TENTATIVES` (CA-4).

Contrat transactionnel : la ligne d'inbox est écrite avant l'effet, et son état est mis à jour
dans la même transaction. Un échec du handler annule ses seuls effets (SAVEPOINT) ; la ligne
d'inbox, elle, reste et porte le compte de tentatives. L'appelant committe ou annule l'ensemble.

Garanties : une livraison répétée (au moins une fois, QE-API-22) ne produit pas de second effet,
parce que l'état `processed` est committé avec l'effet. Un passage qui tombe avant son commit
laisse la ligne absente : la prochaine distribution la rejoue.

Écart consigné : « tenant connu » signifie qu'une organisation existe pour ce `tenantId`, car
aucune table de scope par consommateur n'existe (voir `docs/`, outbox). Le statut `retry` sert aussi
à l'attente d'un hors-ordre, la table ne prévoyant que processed, retry et quarantine.
"""

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.evenements.models import EventInbox, OutboxEvenement
from app.identity.models import Organization

journal = logging.getLogger(__name__)

# Nombre maximal de tentatives avant quarantaine (QE-API-16 : 5 tentatives).
MAX_TENTATIVES = 5

STATUT_PROCESSED = "processed"
STATUT_RETRY = "retry"
STATUT_QUARANTINE = "quarantine"
ISSUE_DOUBLON = "doublon"

HandlerInbox = Callable[["EvenementRecu"], Awaitable[None]]


@dataclass(frozen=True)
class EvenementRecu:
    """Événement tel que reçu par un consommateur : champs d'enveloppe et d'agrégat, sans relecture.

    `aggregateType`, `aggregateId` et `aggregateVersion` sont nuls pour un événement sans agrégat
    (ou écrit avant BE-192) : l'ordre ne s'applique alors pas.
    """

    eventId: uuid.UUID
    eventType: str
    schemaVersion: int
    tenantId: uuid.UUID
    aggregateType: str | None = None
    aggregateId: str | None = None
    aggregateVersion: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def depuis_ligne(cls, ligne: OutboxEvenement) -> "EvenementRecu":
        """Construit l'événement reçu à partir d'une ligne de l'outbox (BE-166, BE-192)."""
        return cls(
            eventId=ligne.eventId,
            eventType=ligne.eventType,
            schemaVersion=ligne.schemaVersion,
            tenantId=ligne.tenantId,
            aggregateType=ligne.aggregateType,
            aggregateId=ligne.aggregateId,
            aggregateVersion=ligne.aggregateVersion,
            payload=ligne.payload,
        )


async def recevoir_evenement(
    db: AsyncSession,
    *,
    abonne: str,
    evenement: EvenementRecu,
    versions_acceptees: Iterable[int],
    ordonne: bool,
    handler: HandlerInbox,
) -> str:
    """Reçoit un événement pour un consommateur ; renvoie son statut (`processed`, `retry`,
    `quarantine`) ou `doublon` si le couple est déjà traité ou en quarantaine.

    `handler` porte l'effet métier, dans la session de l'appelant. Il n'est appelé qu'après les
    contrôles de tenant, de schéma et d'ordre. Une erreur du handler compte comme une tentative
    (CA-4) ; elle n'est pas remontée à l'appelant. Aucune charge utile n'est journalisée.
    """
    ligne = await _lire_ligne(db, abonne, evenement.eventId)
    if ligne is not None and ligne.status != STATUT_RETRY:
        return ISSUE_DOUBLON
    if ligne is None:
        ligne = await _consigner_reception(db, abonne, evenement)
        if ligne is None:
            return ISSUE_DOUBLON
    ligne_id = ligne.id
    tentatives = ligne.attempts

    if not await _tenant_connu(db, evenement.tenantId):
        return await _quarantaine(db, ligne_id, abonne, evenement, "tenant_inconnu")

    if evenement.schemaVersion not in set(versions_acceptees):
        return await _quarantaine(db, ligne_id, abonne, evenement, "schema_incompatible")

    if ordonne and evenement.aggregateVersion is not None:
        attendue = await _version_attendue(db, abonne, evenement)
        if evenement.aggregateVersion != attendue:
            return await _echec(db, ligne_id, abonne, evenement, tentatives, "hors_ordre")

    try:
        async with db.begin_nested():
            await handler(evenement)
    except Exception as exc:  # noqa: BLE001 : toute erreur de handler compte comme une tentative
        journal.warning(
            "échec de réception abonne=%s eventId=%s erreur=%s", abonne, evenement.eventId, type(exc).__name__
        )
        return await _echec(db, ligne_id, abonne, evenement, tentatives, "echec_handler")

    await _positionner(db, ligne_id, statut=STATUT_PROCESSED, tentatives=tentatives)
    return STATUT_PROCESSED


async def _lire_ligne(db: AsyncSession, abonne: str, event_id: uuid.UUID) -> EventInbox | None:
    """Renvoie la ligne d'inbox du couple (`abonne`, `event_id`), ou `None`."""
    resultat = await db.execute(
        select(EventInbox).where(EventInbox.subscriber == abonne, EventInbox.eventId == event_id)
    )
    return resultat.scalar_one_or_none()


async def _consigner_reception(db: AsyncSession, abonne: str, evenement: EvenementRecu) -> EventInbox | None:
    """Crée la ligne d'inbox en `retry` (0 tentative) ; renvoie `None` si un passage concurrent l'a créée.

    Dans un SAVEPOINT : la contrainte (`subscriber`, `eventId`) départage deux réceptions simultanées.
    Tous les attributs sont fixés à l'insertion pour ne pas relire une valeur serveur après coup.
    """
    ligne = EventInbox(
        subscriber=abonne,
        eventId=evenement.eventId,
        tenantId=evenement.tenantId,
        eventType=evenement.eventType,
        schemaVersion=evenement.schemaVersion,
        aggregateType=evenement.aggregateType,
        aggregateId=evenement.aggregateId,
        aggregateVersion=evenement.aggregateVersion,
        status=STATUT_RETRY,
        attempts=0,
    )
    try:
        async with db.begin_nested():
            db.add(ligne)
            await db.flush()
    except IntegrityError:
        return None
    return ligne


async def _tenant_connu(db: AsyncSession, tenant_id: uuid.UUID) -> bool:
    """Vrai si une organisation existe pour ce tenant (écart consigné : pas de scope consommateur)."""
    resultat = await db.execute(select(Organization.id).where(Organization.id == tenant_id))
    return resultat.first() is not None


async def _version_attendue(db: AsyncSession, abonne: str, evenement: EvenementRecu) -> int:
    """Version que l'agrégat doit porter pour que l'événement soit le suivant : plus haute `processed` + 1, 1 au départ."""
    plus_haute = await db.execute(
        select(func.max(EventInbox.aggregateVersion)).where(
            EventInbox.subscriber == abonne,
            EventInbox.aggregateType == evenement.aggregateType,
            EventInbox.aggregateId == evenement.aggregateId,
            EventInbox.status == STATUT_PROCESSED,
        )
    )
    maximum = plus_haute.scalar_one()
    return 1 if maximum is None else maximum + 1


async def _positionner(db: AsyncSession, ligne_id: uuid.UUID, *, statut: str, tentatives: int) -> None:
    """Écrit le statut et le compte de tentatives d'une ligne d'inbox, dans la transaction de l'appelant."""
    await db.execute(
        update(EventInbox)
        .where(EventInbox.id == ligne_id)
        .values(status=statut, attempts=tentatives)
        .execution_options(synchronize_session=False)
    )


async def _quarantaine(
    db: AsyncSession, ligne_id: uuid.UUID, abonne: str, evenement: EvenementRecu, motif: str
) -> str:
    """Met la ligne en quarantaine sans nouvelle tentative (tenant inconnu, schéma incompatible)."""
    journal.warning("quarantaine abonne=%s eventId=%s motif=%s", abonne, evenement.eventId, motif)
    await _positionner(db, ligne_id, statut=STATUT_QUARANTINE, tentatives=0)
    return STATUT_QUARANTINE


async def _echec(
    db: AsyncSession, ligne_id: uuid.UUID, abonne: str, evenement: EvenementRecu, tentatives: int, motif: str
) -> str:
    """Compte une tentative échouée ; renvoie `retry`, ou `quarantine` une fois `MAX_TENTATIVES` atteint (CA-4)."""
    nouvelles = tentatives + 1
    if nouvelles >= MAX_TENTATIVES:
        journal.warning(
            "quarantaine tentatives épuisées abonne=%s eventId=%s motif=%s", abonne, evenement.eventId, motif
        )
        statut = STATUT_QUARANTINE
    else:
        statut = STATUT_RETRY
    await _positionner(db, ligne_id, statut=statut, tentatives=nouvelles)
    return statut
