"""Publication d'une enveloppe validée (BE-150).

Rôle : seule porte d'entrée pour publier un événement de domaine selon le contrat de BE-150.
Enchaîne, dans cet ordre : refus d'un émetteur non authentifié, validation de l'enveloppe
(`app.evenements.enveloppe.valider_enveloppe`), déduplication par `eventId`, puis distribution via
le registre intra-processus `app.shared.events`.

Déduplication (CA-3) : un `eventId` déjà distribué ne l'est plus. La mémoire est un registre
borné en process : elle suffit au transport actuel, mais un redémarrage la réinitialise. La
déduplication durable et l'outbox relèvent de BE-166.

Ordre « après commit » : le registre ne sait pas quelle transaction a produit l'événement. Tout
appelant doit donc publier après son propre commit, comme pour `app.shared.events.publish`.
"""

import logging
import uuid
from collections import OrderedDict
from typing import Any, Mapping

from app.core.errors import AppError
from app.evenements.enveloppe import EnveloppeEvenement, valider_enveloppe
from app.shared import events as bus

logger = logging.getLogger(__name__)

# Taille maximale du registre de déduplication. Au-delà, les plus anciens identifiants sont
# oubliés ; un rejeu plus ancien que cette fenêtre serait donc redistribué (limite connue, levée
# par BE-166).
TAILLE_REGISTRE_DEDUPLICATION = 10_000

_eventIds_distribues: "OrderedDict[uuid.UUID, None]" = OrderedDict()


async def publier_enveloppe(donnees: Mapping[str, Any], *, tenant_identite: uuid.UUID | None) -> EnveloppeEvenement:
    """Valide puis distribue un événement, et renvoie l'enveloppe canonique.

    `tenant_identite` est le tenant de l'émetteur authentifié ; `None` signifie qu'aucun émetteur
    authentifié n'agit. Recommandation QE-PAR-01 : seul un émetteur authentifié publie, sinon
    `PERMISSION_DENIED` (403). La permission fine de publication (BE-008) n'est pas encore
    contrôlée ici : NON DÉFINI, à brancher avec BE-159 ou BE-166.

    Erreurs : `PERMISSION_DENIED`, puis `SCHEMA_INVALID` et `TENANT_MISMATCH` (voir
    `valider_enveloppe`). Une enveloppe rejetée n'entre jamais dans le registre de déduplication :
    la même enveloppe corrigée peut donc être publiée ensuite.

    Un doublon (même `eventId`) n'est pas une erreur : il renvoie l'enveloppe sans nouvelle
    distribution. Une erreur d'un handler abonné est journalisée par `app.shared.events` et
    n'interrompt pas la publication.
    """
    if tenant_identite is None:
        raise AppError(code="PERMISSION_DENIED", message="Émetteur non authentifié : publication refusée.", status_code=403)

    enveloppe = valider_enveloppe(donnees, tenant_identite=tenant_identite)

    if enveloppe.eventId in _eventIds_distribues:
        logger.debug("événement déjà distribué ignoré (eventId=%s)", enveloppe.eventId)
        return enveloppe

    # Enregistrement avant l'appel aux handlers : aucune attente entre la vérification et
    # l'enregistrement, donc pas de double distribution entre deux tâches asyncio concurrentes.
    _eventIds_distribues[enveloppe.eventId] = None
    while len(_eventIds_distribues) > TAILLE_REGISTRE_DEDUPLICATION:
        _eventIds_distribues.popitem(last=False)

    await bus.publish(enveloppe.eventType, enveloppe=enveloppe)
    return enveloppe
