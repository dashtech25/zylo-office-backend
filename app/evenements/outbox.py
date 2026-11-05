"""Publication par outbox et consommation idempotente (BE-166).

Rôle : rendre la publication d'un événement atomique avec la mutation métier qui le produit,
et garantir qu'un consommateur ne traite un événement qu'une fois, même si la livraison est
répétée. Le contrat d'enveloppe reste celui de BE-150 (`app.evenements.enveloppe`) ; la
publication synchrone en mémoire (`app.evenements.publication`) n'est pas modifiée.

Contrat de publication (`enregistrer_evenement`) :
- l'appelant ouvre la transaction métier, appelle `enregistrer_evenement` avec sa session,
  puis fait son `commit()`. L'événement n'existe pour les autres transactions qu'après ce
  commit (CA-1). Un rollback supprime l'événement avec la mutation. Ne jamais committer
  dans cette fonction : ce serait détacher l'événement de la mutation ;
- sans identité émetteur (`emetteur_tenant=None`), refus `PERMISSION_DENIED` 403 (CA-3) ;
- l'enveloppe est validée par `valider_enveloppe` : schéma, secret, tenant (CA-4) ;
- un `eventId` déjà présent renvoie l'enveloppe sans nouvelle ligne (déduplication).

Contrat de consommation (`consommer_evenement`, `distribuer_pour_consommateur`) :
- un événement n'est consommé que par des consommateurs du même tenant (CA-4) : un
  consommateur d'un autre tenant ne reçoit rien et rien n'est consigné ;
- la consommation est consignée dans `consommation_evenement` par un SAVEPOINT. Une
  seconde livraison échoue sur la contrainte d'unicité : elle est journalisée
  `REPLAY_DUPLICATE` et ne déclenche aucun effet (CA-2) ;
- le handler s'exécute dans la session de l'appelant : sa mutation et la trace de
  consommation sont donc validées par le même commit. Un rollback annule les deux.

Hors périmètre, décision en attente : le mécanisme de file qui pousse les événements vers
des consommateurs asynchrones, l'ordre par entité et la rétention (QE-PAR-10). Ce module
fournit la lecture par tenant et la consommation idempotente sur laquelle ce mécanisme
s'appuiera.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.erreurs.codes import CodeErreur, ErreurCatalogue
from app.evenements.enveloppe import EnveloppeEvenement, valider_enveloppe
from app.evenements.models import ConsommationEvenement, OutboxEvenement

journal = logging.getLogger(__name__)

HandlerEvenement = Callable[[EnveloppeEvenement], Awaitable[Any]]


async def enregistrer_evenement(
    db: AsyncSession,
    donnees: dict[str, Any],
    *,
    emetteur_tenant: uuid.UUID | None,
) -> EnveloppeEvenement:
    """Écrit un événement dans l'outbox, dans la transaction de l'appelant, sans commit.

    `emetteur_tenant` est le tenant de l'identité authentifiée de l'émetteur ; `None` signifie
    qu'aucun émetteur authentifié n'agit. Renvoie l'enveloppe canonique.

    Erreurs : `PERMISSION_DENIED` (403) sans émetteur ; `SCHEMA_INVALID` ou `TENANT_MISMATCH`
    selon `valider_enveloppe`. Aucune ligne n'est écrite en cas d'erreur.

    La vérification d'un doublon est une lecture sans verrou : deux écritures concurrentes du
    même `eventId` se départagent par la contrainte d'unicité, et la seconde lève
    `IntegrityError` côté appelant. Ce cas est volontairement non masqué.
    """
    if emetteur_tenant is None:
        raise ErreurCatalogue(CodeErreur.PERMISSION_DENIED, detail="émetteur d'événement non authentifié")

    enveloppe = valider_enveloppe(donnees, tenant_identite=emetteur_tenant)

    existant = await db.execute(select(OutboxEvenement.id).where(OutboxEvenement.eventId == enveloppe.eventId))
    if existant.scalar_one_or_none() is not None:
        journal.debug("événement déjà présent dans l'outbox (eventId=%s)", enveloppe.eventId)
        return enveloppe

    db.add(
        OutboxEvenement(
            eventId=enveloppe.eventId,
            eventType=enveloppe.eventType,
            schemaVersion=enveloppe.schemaVersion,
            tenantId=enveloppe.tenantId,
            payload=enveloppe.model_dump(mode="json"),
            statut="publie",
        )
    )
    await db.flush()
    return enveloppe


async def lire_evenements_pour_tenant(db: AsyncSession, tenant_id: uuid.UUID) -> list[EnveloppeEvenement]:
    """Renvoie les événements de l'outbox d'un tenant, dans l'ordre d'écriture.

    Ne lit que les lignes committées (visibilité par transaction PostgreSQL). Le filtre par
    `tenantId` est la frontière d'isolation (CA-4) : aucun événement d'un autre tenant n'est
    renvoyé.
    """
    lignes = await db.execute(
        select(OutboxEvenement).where(OutboxEvenement.tenantId == tenant_id).order_by(OutboxEvenement.createdAt, OutboxEvenement.eventId)
    )
    return [EnveloppeEvenement.model_validate(ligne.payload) for ligne in lignes.scalars()]


async def consommer_evenement(
    db: AsyncSession,
    consommateur: str,
    evenement: EnveloppeEvenement,
    tenant_consommateur: uuid.UUID,
) -> bool:
    """Consigne la consommation d'un événement par un consommateur ; renvoie `True` si elle est nouvelle.

    Renvoie `False` sans rien écrire si le tenant de l'événement n'est pas celui du consommateur
    (CA-4). Renvoie `False` et journalise `REPLAY_DUPLICATE` si le couple (consommateur,
    événement) est déjà consigné (CA-2). L'insertion est faite dans un SAVEPOINT pour qu'un
    doublon n'annule pas le reste de la transaction de l'appelant.
    """
    if evenement.tenantId != tenant_consommateur:
        journal.warning("événement hors tenant ignoré pour le consommateur %s", consommateur)
        return False

    try:
        async with db.begin_nested():
            db.add(ConsommationEvenement(consommateur=consommateur, eventId=evenement.eventId))
            await db.flush()
    except IntegrityError:
        journal.info("REPLAY_DUPLICATE consommateur=%s eventId=%s", consommateur, evenement.eventId)
        return False
    return True


async def distribuer_pour_consommateur(
    db: AsyncSession,
    consommateur: str,
    tenant_id: uuid.UUID,
    handler: HandlerEvenement,
) -> int:
    """Appelle `handler` une fois par événement non encore consommé du tenant ; renvoie leur nombre.

    Le handler reçoit la session de l'appelant et doit y écrire ses effets. L'appelant committe
    ensuite : effets et consommation sont alors atomiques. Si le handler lève une erreur, rien
    n'est committé et l'événement reste à consommer.
    """
    traites = 0
    for evenement in await lire_evenements_pour_tenant(db, tenant_id):
        if await consommer_evenement(db, consommateur, evenement, tenant_id):
            await handler(evenement)
            traites += 1
    return traites
