"""Lettres mortes : lecture par tenant et replay par un opérateur (BE-235, CA-3 et CA-4).

Rôle : exposer la file `dead_letters` (écrite par `app.evenements.consumer`) et rejouer une
entrée vers son consommateur. Les garanties d'isolation sont ici, pas dans la route :

- toute lecture et tout replay sont filtrés par `tenant_id` ; une entrée d'un autre tenant
  est traitée comme absente (404, CA-4), pour ne pas révéler son existence ;
- le replay repasse par la même tentative bornée que la consommation (`tenter_evenement`) : la trace de
  consommation empêche un second effet si l'événement a déjà été traité entre-temps ;
- un replay qui échoue encore laisse l'entrée `en_attente` et met à jour le nombre de tentatives.

Les droits (autorité d'opérateur, portée `X-Admin-Scope`) sont contrôlés en amont par la dépendance
`app.operator.scope.require_admin_scope` (CA-3, 403) : ce module suppose que l'appelant est
autorisé et ne reçoit que le `tenant_id` de sa portée.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.evenements.consumer import CONSOMMATEURS, maximum_tentatives, tenter_evenement, ISSUE_ECHEC
from app.evenements.enveloppe import EnveloppeEvenement
from app.evenements.models import DeadLetter, OutboxEvenement


async def lister_dead_letters(db: AsyncSession, tenant_id: uuid.UUID) -> list[DeadLetter]:
    """Renvoie les entrées DLQ du tenant, les plus anciennes d'abord. Filtre par tenant (CA-4)."""
    lignes = await db.execute(
        select(DeadLetter).where(DeadLetter.tenantId == tenant_id).order_by(DeadLetter.createdAt, DeadLetter.id)
    )
    return list(lignes.scalars())


async def rejouer_dead_letter(db: AsyncSession, dead_letter_id: uuid.UUID, tenant_id: uuid.UUID | None) -> DeadLetter:
    """Rejoue une entrée DLQ vers son consommateur et renvoie l'entrée mise à jour.

    Erreurs :
    - 404 `dead_letter_introuvable` si l'entrée n'existe pas, ou si son tenant n'est pas
      `tenant_id` (y compris `tenant_id=None`, portée plateforme) : CA-4 ;
    - 409 `dead_letter_deja_rejouee` si l'entrée est déjà `rejoue` ;
    - 409 `consommateur_non_branche` si le consommateur n'est pas dans `CONSOMMATEURS` ;
    - sinon, l'entrée passe à `rejoue` si le handler réussit, ou reste `en_attente` avec le
      nombre de tentatives mis à jour si toutes les tentatives échouent (pas d'exception levée).

    L'appelant committe. Le replay utilise la même limite de tentatives que la consommation.
    """
    ligne = await db.get(DeadLetter, dead_letter_id)
    if ligne is None or tenant_id is None or ligne.tenantId != tenant_id:
        raise AppError(code="dead_letter_introuvable", message="Entrée de lettre morte introuvable.", status_code=404)
    if ligne.statut != "en_attente":
        raise AppError(code="dead_letter_deja_rejouee", message="Cette entrée a déjà été rejouée.", status_code=409)

    handler = CONSOMMATEURS.get(ligne.consommateur)
    if handler is None:
        raise AppError(code="consommateur_non_branche", message="Consommateur non branché : replay impossible.", status_code=409)

    evenement = await _charger_evenement(db, ligne.eventId)
    maximum = maximum_tentatives()
    issue = await tenter_evenement(db, ligne.consommateur, evenement, ligne.tenantId, handler, maximum)
    if issue == ISSUE_ECHEC:
        ligne.tentatives = maximum
    else:
        ligne.statut = "rejoue"
        ligne.rejoueAt = datetime.now(timezone.utc)
    await db.flush()
    return ligne


async def _charger_evenement(db: AsyncSession, event_id: uuid.UUID) -> EnveloppeEvenement:
    """Relit l'enveloppe canonique d'un événement de l'outbox, à partir de son `eventId`."""
    ligne = (await db.execute(select(OutboxEvenement).where(OutboxEvenement.eventId == event_id))).scalar_one()
    return EnveloppeEvenement.model_validate(ligne.payload)
