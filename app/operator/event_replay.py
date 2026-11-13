"""Rejeu d'un événement à effet métier (BE-139).

Un rejeu est une commande de classe `evenement.replay` (BE-127) : l'opérateur demande de
rejouer un événement déjà publié vers un consommateur nommé. Le rejeu peut dupliquer un
effet métier, donc il passe par tout le pipeline de commande : intention (BE-124),
approbation distincte (BE-128, 409 sans approbateur), garde d'exécution (BE-126).

Ce module contient :
- la construction du corps d'intention, sur le modèle de `app.operator.entitlement_commands` ;
- la lecture de l'événement source dans `outbox_evenement`, par son `eventId` ;
- l'exécuteur `executer_replay`, enregistré dans `app.operator.guard.EXECUTEURS`.

Idempotence (CA-1) : l'exécuteur passe par `consommer_evenement` (BE-166), qui consigne
le couple (consommateur, eventId) dans `consommation_evenement`. Un événement déjà consommé
renvoie `issue = doublon` sans appeler le consommateur : aucun second effet, même si la
commande de rejeu est rejouée avec une autre clé.

Résultat ambigu (CA-4) : si le consommateur lève `ResultatInconnu`, la trace de consommation
est conservée (le SAVEPOINT est relâché avant de relever l'exception). La garde transforme
cette exception en statut `resultat_inconnu` et committe. Un rejeu ultérieur voit la trace et
répond `doublon` : le consommateur n'est jamais rappelé pour un effet dont on ignore l'issue.
Une autre exception du consommateur annule le SAVEPOINT, donc la trace : un rejeu reste
possible, et la garde marque la commande `echec`.

Droits : la classe n'a pas d'entrée dans `ROLES_PAR_CLASSE`, elle retombe sur les rôles de
gestion (fermé par défaut). La portée est celle du tenant de l'événement, jamais celle de la
route : un gestionnaire du tenant A ne peut pas rejouer un événement du tenant B (CA-3).

Consommateur non branché : l'intention peut être créée sans que le consommateur soit connu
du registre `CONSOMMATEURS` (le registre est rempli au démarrage). L'exécuteur refuse alors
par 409 `consommateur_non_branche` ; la garde marque la commande `echec`.

Les routes sont dans `app.operator.event_replay_router`.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.evenements.consumer import CONSOMMATEURS
from app.evenements.enveloppe import EnveloppeEvenement
from app.evenements.models import OutboxEvenement
from app.evenements.outbox import consommer_evenement
from app.operator.guard import EXECUTEURS, ResultatInconnu

CLASSE_EVENEMENT_REPLAY = "evenement.replay"
TYPE_OBJET_EVENEMENT = "Evenement"
ISSUE_TRAITE = "traite"
ISSUE_DOUBLON = "doublon"


def erreur_evenement_introuvable() -> AppError:
    """404 : aucun événement publié n'a cet `eventId`."""
    return AppError(code="evenement_introuvable", message="Événement introuvable.", status_code=404)


def corps_commande_replay(
    *,
    event_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    consommateur: str,
    reason_ticket: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Corps d'intention au format de BE-124 pour un rejeu.

    La cible est l'événement lui-même (`Evenement`, son `eventId`). Le consommateur est porté
    par `payload`, donc comparé par `corps_identique` : une même clé ne peut pas désigner deux
    consommateurs différents.
    """
    return {
        "commandType": CLASSE_EVENEMENT_REPLAY,
        "commandVersion": 1,
        "tenantId": tenant_id,
        "targetObjectType": TYPE_OBJET_EVENEMENT,
        "targetObjectId": str(event_id),
        "targetVersionExpected": None,
        "reasonTicket": reason_ticket,
        "idempotencyKey": idempotency_key,
        "payload": {"consommateur": consommateur},
    }


async def evenement_source(db: AsyncSession, event_id: uuid.UUID) -> OutboxEvenement:
    """Renvoie la ligne d'outbox de l'événement, ou 404 si elle n'existe pas."""
    ligne = (await db.execute(select(OutboxEvenement).where(OutboxEvenement.eventId == event_id))).scalar_one_or_none()
    if ligne is None:
        raise erreur_evenement_introuvable()
    return ligne


async def executer_replay(db: AsyncSession, commande: Any) -> dict[str, Any]:
    """Domaine `evenement.replay` : rejoue l'événement vers le consommateur de la commande.

    Ne committe pas : la garde committe. Renvoie `{"issue": "traite"}` si le consommateur a
    appliqué l'événement, `{"issue": "doublon"}` si la trace existait déjà (aucun appel).

    Erreurs : 409 `consommateur_non_branche` si le consommateur n'est pas dans `CONSOMMATEURS` ;
    `ResultatInconnu` si le consommateur ne sait pas si son effet a eu lieu (CA-4, sans nouvel
    appel) ; toute autre exception du consommateur annule la tentative et remonte à la garde.
    """
    consommateur = (commande.payload or {}).get("consommateur")
    handler = CONSOMMATEURS.get(consommateur)
    if handler is None:
        raise AppError(
            code="consommateur_non_branche",
            message="Consommateur non branché : rejeu impossible.",
            status_code=409,
        )

    ligne = await evenement_source(db, uuid.UUID(commande.targetObjectId))
    evenement = EnveloppeEvenement.model_validate(ligne.payload)
    resultat_inconnu = False
    async with db.begin_nested():
        if not await consommer_evenement(db, consommateur, evenement, commande.tenantId):
            return {"issue": ISSUE_DOUBLON, "consommateur": consommateur, "eventId": str(evenement.eventId)}
        try:
            await handler(evenement)
        except ResultatInconnu:
            # Le SAVEPOINT est relâché avec la trace : l'effet est peut-être appliqué, il ne
            # doit pas être rejoué. L'exception est relevée hors du bloc, après ce relâchement.
            resultat_inconnu = True
    if resultat_inconnu:
        raise ResultatInconnu()
    return {"issue": ISSUE_TRAITE, "consommateur": consommateur, "eventId": str(evenement.eventId)}


EXECUTEURS[CLASSE_EVENEMENT_REPLAY] = executer_replay
