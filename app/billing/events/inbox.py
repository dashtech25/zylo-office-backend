"""Réception idempotente et ordonnée d'un événement fournisseur (BE-074, CA-2, CA-3, CA-4).

Rôle : consigner un événement reçu dans `inbox_event`, appliquer son effet une seule fois,
et ignorer ce qui est hors ordre.

Ordre des contrôles (le premier verdict gagne) :
1. garde anti-carte sur le payload (CA-4) : refus `SCHEMA_INVALID`, rien n'est écrit ;
2. doublon (CA-2) : une ligne existe déjà pour (fournisseur, identifiant) -> `doublon`,
   aucun effet ;
3. ordre (CA-3) : si `version_confirmee` est renseignée et `version_recue` lui est inférieure
   ou égale, l'événement est consigné `hors_ordre` et `appliquer` n'est pas appelé : un
   événement ancien ne fait pas régresser un état confirmé ;
4. sinon la ligne est consignée `applique`, puis `appliquer()` est appelé.

La ligne est insérée avant l'effet, dans un SAVEPOINT : deux réceptions concurrentes du même
événement se départagent sur la contrainte d'unicité, et la seconde renvoie `doublon` sans
effet. Pas de commit ici : l'appelant committe effet et consignation ensemble, ou annule
les deux. Un effet qui lève une erreur n'est donc pas consigné.

`version_recue` et `version_confirmee` sont fournies par l'appelant, qui lit son propre état
confirmé ; la réception ne connaît pas le modèle de l'agrégat.
"""

from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.events.garde import valider_sans_donnee_carte
from app.billing.events.models import InboxEvent

RESULTAT_APPLIQUE = "applique"
RESULTAT_HORS_ORDRE = "hors_ordre"
RESULTAT_DOUBLON = "doublon"


async def recevoir_evenement_entrant(
    db: AsyncSession,
    *,
    provider: str,
    providerEventId: str,
    payload: Any,
    version_recue: int,
    version_confirmee: int | None,
    appliquer: Callable[[], Awaitable[None]],
) -> str:
    """Reçoit un événement fournisseur ; renvoie `applique`, `hors_ordre` ou `doublon`.

    `appliquer` est une coroutine sans argument qui porte l'effet métier, dans la session de
    l'appelant. Elle n'est appelée que pour un événement nouveau et dans l'ordre.
    Erreurs : `SCHEMA_INVALID` si le payload contient une donnée de carte (CA-4).
    """
    valider_sans_donnee_carte(payload)

    existant = await db.execute(
        select(InboxEvent.id).where(InboxEvent.provider == provider, InboxEvent.providerEventId == providerEventId)
    )
    if existant.scalar_one_or_none() is not None:
        return RESULTAT_DOUBLON

    hors_ordre = version_confirmee is not None and version_recue <= version_confirmee
    statut = RESULTAT_HORS_ORDRE if hors_ordre else RESULTAT_APPLIQUE

    try:
        async with db.begin_nested():
            db.add(InboxEvent(provider=provider, providerEventId=providerEventId, status=statut, quarantineFlag=False))
            await db.flush()
    except IntegrityError:
        return RESULTAT_DOUBLON

    if not hors_ordre:
        await appliquer()
    return statut
