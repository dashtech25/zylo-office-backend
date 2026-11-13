"""Dispatcher : distribue les événements committés d'un tenant à un consommateur (BE-193).

Rôle : relire l'outbox du tenant (`outbox_evenement`, ordre d'écriture) et passer chaque
événement à `app.evenements.inbox.recevoir_evenement`. Le dispatcher ne garde aucun curseur : l'état
de chaque événement pour le consommateur est dans `event_inbox`. Un passage qui tombe avant son
commit n'a donc rien consigné, et le passage suivant redistribue (au moins une fois, QE-API-22).

Un événement déjà `processed` ou en quarantaine est compté en doublon et ignoré. Un événement
`retry` (hors ordre, ou échec sous le maximum) est tenté à nouveau. Un hors-ordre qui attend son
prédécesseur est donc repris au passage suivant, une fois le prédécesseur traité.

Contrat transactionnel : comme l'inbox, le dispatcher n'envoie pas de commit. L'appelant committe
après le lot ; une annulation supprime les états consignés du lot, pas les effets hors base.
"""

import uuid
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evenements.inbox import (
    ISSUE_DOUBLON,
    STATUT_PROCESSED,
    STATUT_QUARANTINE,
    STATUT_RETRY,
    EvenementRecu,
    HandlerInbox,
    recevoir_evenement,
)
from app.evenements.models import OutboxEvenement


@dataclass(frozen=True)
class BilanDistribution:
    """Bilan d'un passage : événements traités, en attente de reprise, en quarantaine, et ignorés."""

    traites: int
    en_attente: int
    quarantaine: int
    doublons: int


async def distribuer_lot(
    db: AsyncSession,
    *,
    abonne: str,
    tenant_id: uuid.UUID,
    versions_acceptees: Iterable[int],
    ordonne: bool,
    handler: HandlerInbox,
) -> BilanDistribution:
    """Distribue l'outbox du tenant au consommateur `abonne` ; renvoie le bilan du passage.

    Seules les lignes `portee = tenant` du tenant sont lues : l'isolation tient au filtre sur
    `tenantId` (un événement d'un autre tenant n'est jamais proposé à l'inbox).
    """
    resultat = await db.execute(
        select(OutboxEvenement)
        .where(OutboxEvenement.tenantId == tenant_id, OutboxEvenement.portee == "tenant")
        .order_by(OutboxEvenement.createdAt, OutboxEvenement.eventId)
    )
    evenements = [EvenementRecu.depuis_ligne(ligne) for ligne in resultat.scalars()]

    traites = en_attente = quarantaine = doublons = 0
    for evenement in evenements:
        issue = await recevoir_evenement(
            db,
            abonne=abonne,
            evenement=evenement,
            versions_acceptees=versions_acceptees,
            ordonne=ordonne,
            handler=handler,
        )
        if issue == STATUT_PROCESSED:
            traites += 1
        elif issue == STATUT_RETRY:
            en_attente += 1
        elif issue == STATUT_QUARANTINE:
            quarantaine += 1
        elif issue == ISSUE_DOUBLON:
            doublons += 1
    return BilanDistribution(traites=traites, en_attente=en_attente, quarantaine=quarantaine, doublons=doublons)
