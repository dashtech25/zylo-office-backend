"""Consommation d'un lot d'événements : retry borné, lettre morte et isolation (BE-235).

Rôle : faire passer les événements committés d'un tenant à un consommateur nommé, avec trois
garanties au-dessus de `app.evenements.outbox` (BE-166) :

1. Déduplication (CA-1) : la trace `consommation_evenement` (couple consommateur, eventId)
   empêche tout second effet. La consommation réutilise `consommer_evenement` tel quel.
2. Retry borné (CA-2) : une tentative échouée est annulée dans un SAVEPOINT, puis réessayée.
   Le nombre maximal vient de `settings.EVENTS_CONSUMER_MAX_TENTATIVES` (QE-EXP-08), lu à
   chaque appel. Après la dernière tentative, l'événement part en DLQ (`app.evenements.models.DeadLetter`).
3. Poison (CA-5) : l'échec d'un événement ne stoppe pas le lot ; les suivants sont traités.

Contrat transactionnel : chaque tentative vit dans son SAVEPOINT. Le handler écrit dans la session
de l'appelant ; si une tentative échoue, ses effets et sa trace de consommation sont annulés
ensemble. L'appelant committe ensuite le lot (effets, traces et lignes DLQ atomiques).

Consommateurs : `CONSOMMATEURS` associe un nom de consommateur à son handler. Il sert aussi au
replay (`app.evenements.dlq`) : un consommateur absent du registre ne peut pas être rejoué.
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.evenements.enveloppe import EnveloppeEvenement
from app.evenements.models import DeadLetter
from app.evenements.outbox import HandlerEvenement, consommer_evenement, lire_evenements_pour_tenant

journal = logging.getLogger(__name__)

# Registre des consommateurs connus, rempli par les modules au démarrage. Vide par défaut : un
# événement ne peut être rejoué que vers un consommateur explicitement branché.
CONSOMMATEURS: dict[str, HandlerEvenement] = {}

ISSUE_TRAITE = "traite"
ISSUE_DOUBLON = "doublon"
ISSUE_ECHEC = "echec"


@dataclass(frozen=True)
class ResultatLot:
    """Bilan d'un lot : événements traités, déjà consommés, et envoyés en DLQ pendant ce passage."""

    traites: int
    doublons: int
    dlq: int


def maximum_tentatives() -> int:
    """Renvoie le nombre maximal de tentatives lu de la configuration (QE-EXP-08).

    Refuse (503 `consommation_non_configuree`) si la valeur est absente : la définition ne fixe
    aucun défaut, et un défaut codé rendrait la DLQ silencieusement différente selon l'environnement.
    """
    valeur = settings.EVENTS_CONSUMER_MAX_TENTATIVES
    if valeur is None or valeur < 1:
        raise AppError(
            code="consommation_non_configuree",
            message="Nombre maximal de tentatives de consommation non configuré.",
            status_code=503,
        )
    return valeur


async def tenter_evenement(
    db: AsyncSession,
    consommateur: str,
    evenement: EnveloppeEvenement,
    tenant_id: uuid.UUID,
    handler: HandlerEvenement,
    maximum: int,
) -> str:
    """Essaie de consommer un événement jusqu'à `maximum` fois ; renvoie l'issue.

    Renvoie `ISSUE_TRAITE` si le handler a réussi, `ISSUE_DOUBLON` si la trace existe déjà
    (le handler n'est pas appelé), et `ISSUE_ECHEC` si toutes les tentatives ont échoué. Chaque
    tentative est dans un SAVEPOINT : une exception annule la trace et les effets partiels du
    handler avant la tentative suivante. Le message d'erreur n'est journalisé qu'au niveau
    warning, sans payload.
    """
    for numero in range(1, maximum + 1):
        try:
            async with db.begin_nested():
                if not await consommer_evenement(db, consommateur, evenement, tenant_id):
                    return ISSUE_DOUBLON
                await handler(evenement)
            return ISSUE_TRAITE
        except Exception as exc:  # noqa: BLE001 : toute erreur de handler compte comme une tentative
            journal.warning(
                "échec de consommation consommateur=%s eventId=%s tentative=%d/%d erreur=%s",
                consommateur, evenement.eventId, numero, maximum, type(exc).__name__,
            )
    return ISSUE_ECHEC


async def consommer_lot(
    db: AsyncSession,
    consommateur: str,
    tenant_id: uuid.UUID,
    handler: HandlerEvenement,
) -> ResultatLot:
    """Consomme les événements committés du tenant pour `consommateur` ; renvoie le bilan.

    Un événement déjà présent en DLQ pour ce consommateur est ignoré sans nouvelle tentative :
    il attend un replay explicite (BE-235, `app.evenements.dlq.rejouer_dead_letter`). L'appelant
    committe après le lot.
    """
    maximum = maximum_tentatives()
    traites = doublons = dlq = 0
    for evenement in await lire_evenements_pour_tenant(db, tenant_id):
        if await _deja_en_dlq(db, consommateur, evenement.eventId):
            continue
        issue = await tenter_evenement(db, consommateur, evenement, tenant_id, handler, maximum)
        if issue == ISSUE_TRAITE:
            traites += 1
        elif issue == ISSUE_DOUBLON:
            doublons += 1
        else:
            await _envoyer_en_dlq(db, consommateur, evenement, tenant_id, maximum)
            dlq += 1
    return ResultatLot(traites=traites, doublons=doublons, dlq=dlq)


async def _deja_en_dlq(db: AsyncSession, consommateur: str, event_id: uuid.UUID) -> bool:
    """Vrai si une entrée DLQ existe déjà pour ce couple (consommateur, événement)."""
    existant = await db.execute(
        select(DeadLetter.id).where(DeadLetter.consommateur == consommateur, DeadLetter.eventId == event_id)
    )
    return existant.first() is not None


async def _envoyer_en_dlq(
    db: AsyncSession,
    consommateur: str,
    evenement: EnveloppeEvenement,
    tenant_id: uuid.UUID,
    tentatives: int,
) -> None:
    """Ajoute l'entrée de lettre morte d'un événement en échec définitif (CA-2)."""
    db.add(
        DeadLetter(
            eventId=evenement.eventId,
            consommateur=consommateur,
            motif="echec_consommation_epuisee",
            tentatives=tentatives,
            tenantId=tenant_id,
            statut="en_attente",
        )
    )
    await db.flush()
